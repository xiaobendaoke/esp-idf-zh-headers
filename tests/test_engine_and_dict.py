"""Unit tests for the localization engine, C-code invariance, and dictionary integrity."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from idf_zh.engine import (  # noqa: E402
    TranslationCatalog,
    apply_translations,
    inspect_status,
    restore_headers,
    safe_resolve_header,
)
from idf_zh.validator import (  # noqa: E402
    mask_comments,
    validate_dictionary_dir,
    validate_pair,
)


SAMPLE_EN_HEADER = """/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#define DEMO_MAGIC_STR "/**< string literal must NOT be touched */ // nor this"
#define DEMO_MULTI_MACRO(x) \\
    do { /* macro inline comment with trailing slash */ \\
        (x)++; \\
    } while (0)

/**
 * @brief Initialize demo peripheral bus
 *
 * @param[in] config Bus configuration pointer
 * @param[out] ret_handle Returned bus handle
 * @return ESP_OK on success
 */
int demo_bus_init(const void *config, void **ret_handle);

typedef struct {
    int scl_num; /*!< SCL GPIO number */
    int sda_num; ///< SDA GPIO number
} demo_cfg_t;

#ifdef __cplusplus
}
#endif /* DEMO_HEADER_H */
"""


class EngineAndValidatorTests(unittest.TestCase):
    def _make_mock_catalog(self, rel_path: str) -> TranslationCatalog:
        entries = {
            "/**\n * @brief Initialize demo peripheral bus\n *\n * @param[in] config Bus configuration pointer\n * @param[out] ret_handle Returned bus handle\n * @return ESP_OK on success\n */": (
                "/**\n * @brief 初始化演示外设总线\n *\n * @param[in] config 总线配置指针\n * @param[out] ret_handle 返回的总线句柄\n * @return 成功返回 ESP_OK\n */"
            ),
            "/*!< SCL GPIO number */": "/*!< SCL GPIO 引脚编号 */",
            "///< SDA GPIO number": "///< SDA GPIO 引脚编号",
        }
        return TranslationCatalog(
            manifest={"headers": [rel_path]},
            by_component={"demo_comp": entries},
            global_map=dict(entries),
            known_zh=set(entries.values()),
        )

    def test_validate_pair_rules(self) -> None:
        orig = "/**\n * @param[in] bus_handle Bus handle\n */"
        good_zh = "/**\n * @param[in] bus_handle 总线句柄\n */"
        self.assertEqual(validate_pair(orig, good_zh), [])

        bad_opener = "/*\n * @param[in] bus_handle 总线句柄\n */"
        self.assertTrue(any("opener" in e for e in validate_pair(orig, bad_opener)))

        bad_premature = "/**\n * 提前闭合 */ 危险 @param[in] bus_handle 总线句柄\n */"
        self.assertTrue(any("Premature" in e for e in validate_pair(orig, bad_premature)))

        bad_param = "/**\n * @param[in] wrong_name 总线句柄\n */"
        self.assertTrue(any("bus_handle" in e for e in validate_pair(orig, bad_param)))

        no_cjk = "/**\n * @param[in] bus_handle Pure English\n */"
        self.assertTrue(any("Chinese" in e for e in validate_pair(orig, no_cjk)))

    def test_apply_idempotency_crlf_and_restore(self) -> None:
        rel = "components/demo_comp/include/demo.h"
        catalog = self._make_mock_catalog(rel)

        with tempfile.TemporaryDirectory() as tmp:
            idf_root = pathlib.Path(tmp) / "esp-idf"
            bkp_root = pathlib.Path(tmp) / "backups"
            hdr_path = idf_root / rel
            hdr_path.parent.mkdir(parents=True, exist_ok=True)

            # Write CRLF input to test Windows core.autocrlf=true compatibility
            crlf_bytes = SAMPLE_EN_HEADER.replace("\n", "\r\n").encode("utf-8")
            hdr_path.write_bytes(crlf_bytes)

            # 1st apply
            res1 = apply_translations(idf_root, catalog, bkp_root)
            self.assertEqual(res1.modified_headers, 1)
            self.assertEqual(res1.translated_comments, 3)
            self.assertEqual(res1.unmatched_en_comments, 0)

            patched_bytes = hdr_path.read_bytes()
            patched_text = patched_bytes.decode("utf-8")
            self.assertIn("\r\n", patched_text)
            self.assertIn("初始化演示外设总线", patched_text)
            self.assertIn('DEMO_MAGIC_STR "/**< string literal must NOT be touched */ // nor this"', patched_text)
            self.assertIn("SPDX-License-Identifier: Apache-2.0", patched_text)
            self.assertIn("#endif /* DEMO_HEADER_H */", patched_text)
            self.assertEqual(mask_comments(SAMPLE_EN_HEADER), mask_comments(patched_text))

            # 2nd apply (idempotency check)
            res2 = apply_translations(idf_root, catalog, bkp_root)
            self.assertEqual(res2.modified_headers, 0)
            self.assertEqual(res2.already_localized_headers, 1)
            self.assertEqual(res2.already_zh_comments, 3)
            self.assertEqual(hdr_path.read_bytes(), patched_bytes)

            # Status check
            st = inspect_status(idf_root, catalog, bkp_root)
            self.assertEqual(st.localized_headers, 1)
            self.assertEqual(st.already_zh_comments, 3)
            self.assertEqual(st.matchable_en_comments, 0)
            self.assertTrue(st.has_local_backup)

            # Simulate user editing C code -> restore without --force must protect it
            edited_c = patched_text + "\nint user_added_api(void);\r\n"
            hdr_path.write_bytes(edited_c.encode("utf-8"))
            res_protected = restore_headers(idf_root, catalog, bkp_root, force=False)
            self.assertEqual(res_protected.restored_headers, 0)
            self.assertEqual(res_protected.skipped_code_edited, [rel])

            # Revert user edit and restore cleanly -> must match original CRLF bytes 100%
            hdr_path.write_bytes(patched_bytes)
            res_restore = restore_headers(idf_root, catalog, bkp_root, force=False)
            self.assertEqual(res_restore.restored_headers, 1)
            self.assertEqual(hdr_path.read_bytes(), crlf_bytes)

    def test_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            idf_root = pathlib.Path(tmp) / "esp-idf"
            idf_root.mkdir()
            with self.assertRaises(ValueError):
                safe_resolve_header(idf_root, "../escape.h")
            with self.assertRaises(ValueError):
                safe_resolve_header(idf_root, "components/foo/bar.c")

    def test_production_dictionary_integrity(self) -> None:
        translations_dir = REPO_ROOT / "translations"
        summary = validate_dictionary_dir(translations_dir)
        self.assertTrue(
            summary.ok,
            f"Dictionary validation failed with {len(summary.errors)} errors: {summary.errors[:5]}",
        )
        self.assertGreaterEqual(summary.component_files, 90)
        self.assertGreaterEqual(summary.total_entries, 19000)


if __name__ == "__main__":
    unittest.main()
