# esp-idf-zh-headers

[![CI](https://github.com/xiaobendaoke/esp-idf-zh-headers/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaobendaoke/esp-idf-zh-headers/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![ESP-IDF](https://img.shields.io/badge/ESP--IDF-v6.1_(100%25_API_Headers)-red.svg)](https://github.com/espressif/esp-idf)
[![Python](https://img.shields.io/badge/Python-3.9%2B_(Zero_Deps)-3776AB.svg)](./pyproject.toml)

**[简体中文主文档](./README.md)**

An offline Simplified Chinese Doxygen localization dictionary and non-destructive patching toolkit for **ESP-IDF** public API headers, enabling native offline Chinese hover/autocomplete documentation in `clangd` and VS Code IntelliSense without modifying a single token of C code.

## Highlights

- **100% Public API Header Coverage (ESP-IDF v6.1 baseline)**: Covers all **375** official public API headers (`101` components, `19,807` unique English Doxygen comment strings, `22,431` total occurrences, `0` untranslated prose comments remaining).
- **Mathematically Verified C-Code Invariance**: A single-pass C lexical tokenizer masks string/char literals and comments, asserting `mask_comments(before) == mask_comments(after)` prior to every atomic write. Verified against `xtensa-esp32s3-elf-gcc` (`-Wall -Werror`) with zero warnings and zero errors.
- **Idempotent Local Backups & Safe Restore**: Automatically backs up untouched headers before patching (even on non-Git `.zip` SDK installations) and protects user C-code edits during `restore`.
- **Cross-Platform & Zero Dependencies**: Preserves LF / CRLF (`core.autocrlf=true`) line endings, writes UTF-8 without BOM, and uses only the Python 3.9+ standard library.

## Quick Usage

```bash
git clone https://github.com/xiaobendaoke/esp-idf-zh-headers.git
cd esp-idf-zh-headers

# Validate built-in component dictionaries
python idf_zh.py validate

# Inspect current ESP-IDF installation status
python idf_zh.py status --idf-path /path/to/esp-idf

# Apply Chinese Doxygen comments (idempotent)
python idf_zh.py apply --idf-path /path/to/esp-idf --target all

# Restore pristine English headers anytime
python idf_zh.py restore --idf-path /path/to/esp-idf --target all
```

After running `apply` on an existing project, **delete any stale project-local `clangd` index cache** (`rm -rf build/.cache/clangd .cache/clangd` — otherwise old `.c.*.idx` definition shards cached before patching will override the newly translated `.h` comments), then restart `clangd` (`Ctrl+Shift+P` -> **`clangd: Restart language server`**).

## License & Attribution

Licensed under the [Apache License 2.0](./LICENSE). Upstream copyright and third-party attribution notices are documented in [NOTICE](./NOTICE). This is an independent community project and is not affiliated with Espressif Systems.
