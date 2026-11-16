"""Core header localization engine with atomic writes and idempotent backups."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import os
import pathlib
import re
import subprocess
import tempfile

from .validator import (
    CJK_RE,
    TOKEN_RE,
    is_translatable_comment,
    mask_comments,
    verify_utf8_no_bom,
)

LOGGER = logging.getLogger("idf_zh")

DOXY_HEADER_RE = re.compile(r"\$\(PROJECT_PATH\)/([^\s\\]+\.h)")


@dataclasses.dataclass
class TranslationCatalog:
    """In-memory lookup catalog loaded from `translations/`."""

    manifest: dict[str, object]
    by_component: dict[str, dict[str, str]]
    global_map: dict[str, str]
    known_zh: set[str]


@dataclasses.dataclass
class ApplyResult:
    """Summary returned by `apply_translations`."""

    scanned_headers: int
    modified_headers: int
    already_localized_headers: int
    translated_comments: int
    already_zh_comments: int
    unmatched_en_comments: int
    dry_run: bool


@dataclasses.dataclass
class RestoreResult:
    """Summary returned by `restore_headers`."""

    restored_headers: int
    skipped_unmodified: int
    skipped_code_edited: list[str]
    dry_run: bool


@dataclasses.dataclass
class StatusResult:
    """Live inspection summary returned by `inspect_status`."""

    target_headers: int
    existing_headers: int
    localized_headers: int
    already_zh_comments: int
    matchable_en_comments: int
    unmatched_en_comments: int
    has_local_backup: bool


def header_component_name(rel_path: str) -> str:
    """Extract the ESP-IDF component name from a relative header path."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "components":
        return parts[1]
    return parts[0]


def load_catalog(translations_dir: pathlib.Path) -> TranslationCatalog:
    """Load `manifest.json` and all `components/*.json` dictionaries."""
    manifest_path = translations_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Translation manifest not found: {manifest_path}")

    manifest = json.loads(
        verify_utf8_no_bom(manifest_path.read_bytes(), "manifest.json")
    )
    comp_dir = translations_dir / "components"
    by_component: dict[str, dict[str, str]] = {}
    global_map: dict[str, str] = {}
    known_zh: set[str] = set()

    for cf in sorted(comp_dir.glob("*.json")):
        obj = json.loads(verify_utf8_no_bom(cf.read_bytes(), cf.name))
        comp_name = str(obj.get("component") or cf.stem)
        entries: dict[str, str] = obj["entries"]
        by_component[comp_name] = entries
        for en_txt, zh_txt in entries.items():
            global_map.setdefault(en_txt, zh_txt)
            known_zh.add(zh_txt)

    return TranslationCatalog(
        manifest=manifest,
        by_component=by_component,
        global_map=global_map,
        known_zh=known_zh,
    )


def safe_resolve_header(idf_root: pathlib.Path, rel_path: str) -> pathlib.Path:
    """Resolve `rel_path` inside `idf_root` while preventing path traversal."""
    norm_rel = rel_path.replace("\\", "/").lstrip("/")
    if not norm_rel.endswith(".h") or ".." in norm_rel.split("/"):
        raise ValueError(f"Unsafe or non-header relative path rejected: {rel_path!r}")
    root_resolved = idf_root.resolve()
    candidate = (root_resolved / norm_rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Path traversal outside IDF_PATH rejected: {rel_path!r}"
        ) from exc
    return candidate


def resolve_target_headers(
    idf_root: pathlib.Path,
    catalog: TranslationCatalog,
    target: str = "esp32s3",
    component_filter: str | None = None,
) -> list[str]:
    """Discover public API headers from ESP-IDF Doxyfiles or fallback manifest."""
    doxy_dir = idf_root / "docs" / "doxygen"
    doxy_main = doxy_dir / "Doxyfile"
    rels: list[str] = []
    seen: set[str] = set()

    def _add(rel: str) -> None:
        norm = rel.replace("\\", "/")
        if norm not in seen:
            seen.add(norm)
            rels.append(norm)

    if doxy_main.is_file():
        main_txt = doxy_main.read_text("utf-8", errors="replace")
        if target == "all":
            doxy_targets = sorted(doxy_dir.glob("Doxyfile_*"))
            targets = [p.name.removeprefix("Doxyfile_") for p in doxy_targets]
        else:
            targets = [target]

        for tgt in targets:
            combined = main_txt
            tgt_file = doxy_dir / f"Doxyfile_{tgt}"
            if tgt_file.is_file():
                combined = combined + "\n" + tgt_file.read_text("utf-8", errors="replace")
            for raw_match in DOXY_HEADER_RE.findall(combined):
                resolved_rel = raw_match.replace("$(IDF_TARGET)", tgt)
                if (idf_root / resolved_rel).is_file():
                    _add(resolved_rel)

        psram_rel = "components/esp_psram/include/esp_psram.h"
        if (idf_root / psram_rel).is_file():
            _add(psram_rel)
    else:
        for item in catalog.manifest.get("headers", []):  # type: ignore[union-attr]
            rel_str = str(item)
            if (idf_root / rel_str).is_file():
                _add(rel_str)

    if component_filter:
        rels = [r for r in rels if header_component_name(r) == component_filter]
    return rels


def atomic_write_bytes(target_path: pathlib.Path, data: bytes) -> None:
    """Atomically write `data` to `target_path` via a same-directory temp file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    tmp_path = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(str(tmp_path), str(target_path))
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _idf_backup_slot(backup_root: pathlib.Path, idf_root: pathlib.Path) -> pathlib.Path:
    digest = hashlib.sha256(
        str(idf_root.resolve()).lower().encode("utf-8")
    ).hexdigest()[:12]
    return backup_root / f"idf_{digest}"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_translations(
    idf_root: pathlib.Path,
    catalog: TranslationCatalog,
    backup_root: pathlib.Path,
    target: str = "esp32s3",
    component_filter: str | None = None,
    dry_run: bool = False,
) -> ApplyResult:
    """Apply Chinese Doxygen comment translations to `<idf_root>` headers.

    Idempotent & C-code safe:
    - Normalizes CRLF/LF during lookup and preserves the file's original EOL style.
    - Verifies `mask_comments(original) == mask_comments(translated)` before writing.
    - Saves original unmodified files once into `backup_root` (never overwritten by
      subsequent `apply` runs).
    """
    rels = resolve_target_headers(
        idf_root, catalog, target=target, component_filter=component_filter
    )
    slot_dir = _idf_backup_slot(backup_root, idf_root)
    files_backup_dir = slot_dir / "files"
    meta_file = slot_dir / "backup_meta.json"

    backup_meta: dict[str, object] = {
        "idf_root": str(idf_root.resolve()),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "files": {},
    }
    if meta_file.is_file():
        try:
            backup_meta = json.loads(meta_file.read_text("utf-8"))
        except Exception as exc:
            LOGGER.warning("Ignoring unreadable backup metadata (%s)", exc)
    recorded_files: dict[str, dict[str, str]] = backup_meta.setdefault("files", {})  # type: ignore[assignment]

    modified_headers = 0
    already_localized_headers = 0
    translated_comments = 0
    already_zh_comments = 0
    unmatched_en_comments = 0

    for rel in rels:
        target_path = safe_resolve_header(idf_root, rel)
        if not target_path.is_file():
            continue

        raw_bytes = target_path.read_bytes()
        has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
        raw_no_bom = raw_bytes[3:] if has_bom else raw_bytes
        raw_text = raw_no_bom.decode("utf-8")
        uses_crlf = "\r\n" in raw_text
        src_lf = raw_text.replace("\r\n", "\n")

        comp = header_component_name(rel)
        comp_map = catalog.by_component.get(comp, {})

        out_parts: list[str] = []
        last_pos = 0
        file_changed = False
        file_has_zh = False

        for match in TOKEN_RE.finditer(src_lf):
            tok = match.group(0)
            if not (tok.startswith("/*") or tok.startswith("//")):
                continue

            if tok in catalog.known_zh or CJK_RE.search(tok):
                already_zh_comments += 1
                file_has_zh = True
                continue

            zh_rep = comp_map.get(tok) or catalog.global_map.get(tok)
            if zh_rep is not None and zh_rep != tok:
                out_parts.append(src_lf[last_pos : match.start()])
                out_parts.append(zh_rep)
                last_pos = match.end()
                file_changed = True
                translated_comments += 1
            elif is_translatable_comment(src_lf, match):
                unmatched_en_comments += 1

        if not file_changed:
            if file_has_zh:
                already_localized_headers += 1
            continue

        out_parts.append(src_lf[last_pos:])
        new_src_lf = "".join(out_parts)

        if mask_comments(src_lf) != mask_comments(new_src_lf):
            raise RuntimeError(
                f"C-code invariance check failed for {rel}; aborting without writing."
            )

        final_text = new_src_lf.replace("\n", "\r\n") if uses_crlf else new_src_lf
        new_bytes = final_text.encode("utf-8")

        if not dry_run:
            bkp_file = files_backup_dir / rel
            if not bkp_file.exists():
                atomic_write_bytes(bkp_file, raw_bytes)
                recorded_files[rel] = {
                    "orig_sha256": _sha256_hex(raw_bytes),
                    "patched_sha256": _sha256_hex(new_bytes),
                }
            else:
                recorded_files.setdefault(rel, {})["patched_sha256"] = _sha256_hex(
                    new_bytes
                )
            atomic_write_bytes(target_path, new_bytes)

        modified_headers += 1

    if not dry_run and modified_headers > 0:
        backup_meta["updated_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        atomic_write_bytes(
            meta_file,
            (json.dumps(backup_meta, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            ),
        )

    return ApplyResult(
        scanned_headers=len(rels),
        modified_headers=modified_headers,
        already_localized_headers=already_localized_headers,
        translated_comments=translated_comments,
        already_zh_comments=already_zh_comments,
        unmatched_en_comments=unmatched_en_comments,
        dry_run=dry_run,
    )


def _fetch_git_head_blob(idf_root: pathlib.Path, rel: str) -> bytes | None:
    """Fetch `HEAD:<rel>` bytes from Git if `idf_root` is a Git repository."""
    if not (idf_root / ".git").exists():
        return None
    res = subprocess.run(
        ["git", "-C", str(idf_root), "show", f"HEAD:{rel}"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if res.returncode != 0:
        return None
    return res.stdout


def restore_headers(
    idf_root: pathlib.Path,
    catalog: TranslationCatalog,
    backup_root: pathlib.Path,
    target: str = "esp32s3",
    component_filter: str | None = None,
    use_git_fallback: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> RestoreResult:
    """Restore translated headers back to their original English versions.

    Uses local backup snapshots first, falling back to `git show HEAD:<rel>` when
    `use_git_fallback=True`. Protects user C-code edits by checking
    `mask_comments(disk) == mask_comments(original)` unless `force=True`.
    """
    rels = resolve_target_headers(
        idf_root, catalog, target=target, component_filter=component_filter
    )
    slot_dir = _idf_backup_slot(backup_root, idf_root)
    files_backup_dir = slot_dir / "files"

    restored = 0
    skipped_unmodified = 0
    skipped_code_edited: list[str] = []

    for rel in rels:
        target_path = safe_resolve_header(idf_root, rel)
        if not target_path.is_file():
            continue

        disk_bytes = target_path.read_bytes()
        bkp_file = files_backup_dir / rel
        orig_bytes: bytes | None = None
        if bkp_file.is_file():
            orig_bytes = bkp_file.read_bytes()
        elif use_git_fallback:
            orig_bytes = _fetch_git_head_blob(idf_root, rel)

        if orig_bytes is None or orig_bytes == disk_bytes:
            skipped_unmodified += 1
            continue

        disk_text = disk_bytes.decode("utf-8", errors="replace")
        orig_text = orig_bytes.decode("utf-8", errors="replace")
        if not force and mask_comments(disk_text) != mask_comments(orig_text):
            skipped_code_edited.append(rel)
            continue

        if not dry_run:
            atomic_write_bytes(target_path, orig_bytes)
            if bkp_file.is_file():
                bkp_file.unlink(missing_ok=True)
        restored += 1

    return RestoreResult(
        restored_headers=restored,
        skipped_unmodified=skipped_unmodified,
        skipped_code_edited=skipped_code_edited,
        dry_run=dry_run,
    )


def inspect_status(
    idf_root: pathlib.Path,
    catalog: TranslationCatalog,
    backup_root: pathlib.Path,
    target: str = "esp32s3",
    component_filter: str | None = None,
) -> StatusResult:
    """Inspect current Chinese localization status of `<idf_root>` without modifying files."""
    rels = resolve_target_headers(
        idf_root, catalog, target=target, component_filter=component_filter
    )
    slot_dir = _idf_backup_slot(backup_root, idf_root)
    has_backup = (slot_dir / "files").is_dir() and any(
        (slot_dir / "files").rglob("*.h")
    )

    existing_headers = 0
    localized_headers = 0
    already_zh = 0
    matchable_en = 0
    unmatched_en = 0

    for rel in rels:
        target_path = safe_resolve_header(idf_root, rel)
        if not target_path.is_file():
            continue
        existing_headers += 1
        src_lf = (
            target_path.read_bytes()
            .decode("utf-8", errors="replace")
            .replace("\r\n", "\n")
        )
        comp = header_component_name(rel)
        comp_map = catalog.by_component.get(comp, {})
        file_has_zh = False

        for match in TOKEN_RE.finditer(src_lf):
            tok = match.group(0)
            if not (tok.startswith("/*") or tok.startswith("//")):
                continue
            if tok in catalog.known_zh or CJK_RE.search(tok):
                already_zh += 1
                file_has_zh = True
            elif tok in comp_map or tok in catalog.global_map:
                matchable_en += 1
            elif is_translatable_comment(src_lf, match):
                unmatched_en += 1

        if file_has_zh:
            localized_headers += 1

    return StatusResult(
        target_headers=len(rels),
        existing_headers=existing_headers,
        localized_headers=localized_headers,
        already_zh_comments=already_zh,
        matchable_en_comments=matchable_en,
        unmatched_en_comments=unmatched_en,
        has_local_backup=has_backup,
    )
