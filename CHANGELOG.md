# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-11-16

### Added
- **100% ESP-IDF v6.1 Public API Header Dictionary** (`translations/components/*.json`):
  - `101` component JSON dictionaries covering all `375` official public API headers (`Doxyfile` + `Doxyfile_esp32s3` + `esp_psram.h`).
  - `19,807` unique English Doxygen comment keys (`19,892` component entries, `22,431` total matched header comment occurrences).
- **Zero-Dependency CLI & Engine** (`idf_zh` / `idf_zh.py`):
  - `apply`: Idempotent local backup + atomic UTF-8 (no BOM) patching with CRLF/LF preservation and pre-write C-code mask invariance checks.
  - `restore`: Lossless header restoration from local snapshots (or Git `HEAD` fallback) with automatic user C-code edit protection.
  - `status`: Live inspection of localized vs. remaining English comments per target/component.
  - `validate`: Offline Doxygen delimiter, `@param`, encoding, and CJK coverage validator.
- **CI & Test Suite**:
  - Cross-platform GitHub Actions workflow (`ubuntu-latest`, `windows-latest`, Python 3.10–3.12) and `unittest` suite.
