"""Lexical scanner, C-code mask invariance checker, and dictionary validator."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re

# Single-pass C lexical tokenizer matching string literals, char literals,
# block comments, and single-line comments in exact source order.
TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*[\s\S]*?\*/|//[^\r\n]*'
)

OPENERS: tuple[str, ...] = (
    "/**<",
    "/*!<",
    "/**",
    "/*!",
    "/*",
    "///<",
    "//!<",
    "///",
    "//!",
    "//",
)

LICENSE_KEYWORDS: tuple[str, ...] = (
    "SPDX-FileCopyrightText",
    "SPDX-License-Identifier",
    "Copyright",
    "Permission is hereby granted",
    "Licensed under",
    "All rights reserved",
    "Redistribution and use",
)

LINT_KEYWORDS: tuple[str, ...] = ("NOLINT", "fallthrough", "FALLTHROUGH")

DOXY_STRUCT_RE = re.compile(
    r"[@\\](?:cond|endcond|defgroup|addtogroup|ingroup|name|file|weakgroup)\b[^\r\n]*"
)
URL_RE = re.compile(r"https?://\S+")
HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:Hz|kHz|MHz|GHz|ms|us|ns|s|B|KB|MB|bit|bits|V|mV|mA|uA|%)\b"
)
DELIM_STRIP_RE = re.compile(r"^/\*+<?|^/\*!<?|^//+[!\/]?<?|\*+/$")
ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PARAM_RE = re.compile(
    r"[@\\]param(?:\s*\[[^\]]*\])?\s+([A-Za-z_][A-Za-z0-9_]*)"
)


@dataclasses.dataclass(frozen=True)
class ValidationSummary:
    """Result summary of validating the component translation dictionaries."""

    component_files: int
    total_entries: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def verify_utf8_no_bom(raw: bytes, label: str) -> str:
    """Decode raw bytes as UTF-8 while rejecting UTF-8 BOM headers.

    Args:
        raw: Raw file bytes.
        label: Human-readable file identifier for error messages.

    Returns:
        Decoded UTF-8 string.

    Raises:
        ValueError: If UTF-8 BOM is present or bytes are invalid UTF-8.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label}: UTF-8 BOM is not allowed")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label}: Invalid UTF-8 encoding ({exc})") from exc


def mask_comments(src: str) -> str:
    """Replace all C comments with fixed placeholders while keeping C code intact.

    Comparing ``mask_comments(before) == mask_comments(after)`` guarantees that
    not a single preprocessor directive, string literal, identifier, or C token
    outside comments was altered.
    """
    normalized = src.replace("\r\n", "\n")

    def _repl(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok.startswith("/*"):
            return "/*COMMENT*/"
        if tok.startswith("//"):
            return "//COMMENT"
        return tok

    return TOKEN_RE.sub(_repl, normalized)


def get_opener(comment: str) -> str:
    """Return the exact comment opening delimiter (longest match first)."""
    for opener in OPENERS:
        if comment.startswith(opener):
            return opener
    return ""


def is_translatable_comment(full_src: str, match: re.Match[str]) -> bool:
    """Determine whether a matched C comment token contains translatable English prose.

    Intentionally excludes SPDX/copyright headers, preprocessor `#endif` guards,
    macro backslash-continuation lines, static-analyzer annotations, comments
    that already contain Chinese characters, and pure symbolic/ALL_CAPS tokens.
    """
    tok = match.group(0)
    if not (tok.startswith("/*") or tok.startswith("//")):
        return False
    if tok in ("/**/", "/*!*/"):
        return False
    if CJK_RE.search(tok):
        return False
    if any(kw in tok for kw in LICENSE_KEYWORDS):
        return False
    if tok.startswith(("/*lint", "//lint")) or any(kw in tok for kw in LINT_KEYWORDS):
        return False

    line_start = full_src.rfind("\n", 0, match.start()) + 1
    before = full_src[line_start : match.start()].strip()
    line_end = full_src.find("\n", match.end())
    after = full_src[match.end() : (line_end if line_end != -1 else len(full_src))]

    if before.startswith(("#endif", "#else", "#elif")):
        return False
    if "\\" in after or (tok.startswith("//") and tok.rstrip().endswith("\\")):
        return False
    if tok.startswith("////"):
        return False

    cleaned = DELIM_STRIP_RE.sub("", tok)
    cleaned = DOXY_STRUCT_RE.sub("", cleaned)
    cleaned = URL_RE.sub("", cleaned)
    cleaned = HEX_RE.sub("", cleaned)
    cleaned = UNIT_RE.sub("", cleaned)
    cleaned_stripped = cleaned.strip()

    if ALL_CAPS_RE.match(cleaned_stripped):
        return False
    if not re.search(r"[A-Za-z]{2,}", cleaned_stripped):
        return False
    return True


def validate_pair(orig: str, zh: str, label: str = "") -> list[str]:
    """Validate a single `(english_comment, chinese_comment)` translation pair.

    Checks delimiter preservation, absence of premature block-comment closure,
    single-line newline/continuation safety, `@param` identifier preservation,
    and presence of Simplified Chinese characters.
    """
    prefix = f"{label}: " if label else ""
    errors: list[str] = []

    if not isinstance(orig, str) or not orig.strip():
        return [f"{prefix}Original comment key must be a non-empty string"]
    if not isinstance(zh, str) or not zh.strip():
        return [f"{prefix}Translated comment value must be a non-empty string"]

    opener = get_opener(orig)
    if not opener or not zh.startswith(opener):
        errors.append(
            f"{prefix}Must preserve exact opener {opener!r}, got {zh[:12]!r}"
        )

    if orig.startswith("/*"):
        if not zh.endswith("*/"):
            errors.append(f"{prefix}Block comment must end with '*/'")
        elif "*/" in zh[:-2]:
            errors.append(f"{prefix}Premature '*/' found inside block comment body")
    elif orig.startswith("//"):
        if "\n" in zh or "\r" in zh:
            errors.append(f"{prefix}Single-line comment must not contain newlines")
        if zh.rstrip().endswith("\\"):
            errors.append(f"{prefix}Single-line comment must not end with '\\'")

    for param_name in PARAM_RE.findall(orig):
        if param_name in ("in", "out", "inout"):
            continue
        if not re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(param_name)}(?![A-Za-z0-9_])", zh
        ):
            errors.append(f"{prefix}Missing @param identifier {param_name!r}")

    if not CJK_RE.search(zh):
        errors.append(f"{prefix}Translation must contain Chinese characters")

    return errors


def validate_dictionary_dir(translations_dir: pathlib.Path) -> ValidationSummary:
    """Validate `manifest.json` and all `components/*.json` translation files."""
    errors: list[str] = []
    manifest_path = translations_dir / "manifest.json"
    comp_dir = translations_dir / "components"

    if not manifest_path.is_file():
        return ValidationSummary(0, 0, [f"Missing manifest file: {manifest_path}"])
    if not comp_dir.is_dir():
        return ValidationSummary(0, 0, [f"Missing components directory: {comp_dir}"])

    try:
        manifest_text = verify_utf8_no_bom(manifest_path.read_bytes(), "manifest.json")
        manifest = json.loads(manifest_text)
        if not isinstance(manifest, dict) or "headers" not in manifest:
            errors.append("manifest.json: Missing required 'headers' list")
    except Exception as exc:
        errors.append(f"manifest.json: {exc}")

    comp_files = sorted(comp_dir.glob("*.json"))
    if not comp_files:
        errors.append("components/: No component JSON files found")

    total_entries = 0
    for cf in comp_files:
        try:
            txt = verify_utf8_no_bom(cf.read_bytes(), cf.name)
            data = json.loads(txt)
        except Exception as exc:
            errors.append(f"{cf.name}: {exc}")
            continue

        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            errors.append(f"{cf.name}: Root object must contain an 'entries' dict")
            continue

        entries: dict[str, str] = data["entries"]
        for idx, (orig, zh) in enumerate(entries.items(), start=1):
            total_entries += 1
            pair_errs = validate_pair(orig, zh, label=f"{cf.name}#{idx}")
            errors.extend(pair_errs)

    return ValidationSummary(
        component_files=len(comp_files),
        total_entries=total_entries,
        errors=errors,
    )
