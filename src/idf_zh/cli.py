"""Command-line interface for ESP-IDF Chinese API Header Localization."""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys
import uuid

from . import __version__
from .engine import apply_translations, inspect_status, load_catalog, restore_headers
from .validator import validate_dictionary_dir


def _default_repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _setup_logging(verbose: bool, trace_id: str) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    fmt = logging.Formatter(
        f"%(asctime)s [%(levelname)s] [trace_id={trace_id}] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger = logging.getLogger("idf_zh")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def _resolve_idf_path(arg_idf_path: str | None) -> pathlib.Path:
    raw = arg_idf_path or os.environ.get("IDF_PATH")
    if not raw:
        raise ValueError(
            "未指定 ESP-IDF 路径：请传入 `--idf-path <路径>` 或预先设置 `IDF_PATH` 环境变量。"
        )
    idf_root = pathlib.Path(raw).expanduser().resolve()
    if not (idf_root / "components").is_dir():
        raise ValueError(
            f"无效的 ESP-IDF 目录（未找到 components/ 子目录）：{idf_root}"
        )
    return idf_root


def build_parser() -> argparse.ArgumentParser:
    repo_root = _default_repo_root()
    parser = argparse.ArgumentParser(
        prog="idf-zh",
        description="ESP-IDF 公开 API 头文件 Doxygen 简体中文离线汉化与无损还原工具",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--translations-dir",
        type=pathlib.Path,
        default=repo_root / "translations",
        help="翻译字典目录路径（默认使用仓库内置 translations/）",
    )
    parser.add_argument(
        "--backup-dir",
        type=pathlib.Path,
        default=repo_root / ".local_backups",
        help="原始英文头文件本地备份目录（默认保存在仓库 .local_backups/）",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="输出详细结构化调试日志"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--idf-path",
        type=str,
        default=None,
        help="本地 ESP-IDF 根目录路径（未指定时自动读取 IDF_PATH 环境变量）",
    )
    common.add_argument(
        "--target",
        type=str,
        default="esp32s3",
        help="目标芯片名称，如 esp32s3 / esp32 / esp32c3 / esp32c6 / esp32p4 / all（默认：esp32s3）",
    )
    common.add_argument(
        "--component",
        type=str,
        default=None,
        help="仅处理指定组件（例如 esp_driver_i2c、freertos、esp_wifi）",
    )

    p_apply = sub.add_parser(
        "apply", parents=[common], help="将简体中文 Doxygen 注释无损注入 ESP-IDF 头文件"
    )
    p_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览可匹配的头文件与注释数量，不修改磁盘文件",
    )

    p_restore = sub.add_parser(
        "restore", parents=[common], help="将头文件无损还原为原始英文注释版本"
    )
    p_restore.add_argument(
        "--dry-run", action="store_true", help="仅预览将还原的文件数量，不修改磁盘文件"
    )
    p_restore.add_argument(
        "--no-git-fallback",
        action="store_true",
        help="仅使用本地备份还原，不使用 ESP-IDF 仓库自身的 git HEAD 作为兜底",
    )
    p_restore.add_argument(
        "--force",
        action="store_true",
        help="即使检测到头文件非注释 C 代码被用户手工改动过，也强制还原",
    )

    sub.add_parser("status", parents=[common], help="扫描并查看当前 ESP-IDF 头文件的汉化覆盖率")
    sub.add_parser("validate", help="校验内置 translations/ 翻译字典格式与语法安全性")

    return parser


def main(argv: list[str] | None = None) -> int:
    trace_id = uuid.uuid4().hex[:8]
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = _setup_logging(args.verbose, trace_id)

    translations_dir = args.translations_dir.resolve()
    backup_dir = args.backup_dir.resolve()

    try:
        if args.command == "validate":
            summary = validate_dictionary_dir(translations_dir)
            print(f"Component files checked : {summary.component_files}")
            print(f"Total dictionary entries: {summary.total_entries}")
            if not summary.ok:
                print(f"Validation FAILED with {len(summary.errors)} error(s):")
                for err in summary.errors[:20]:
                    print(f"  - {err}")
                return 1
            print("Validation result       : OK (0 errors)")
            return 0

        idf_root = _resolve_idf_path(args.idf_path)
        logger.debug(
            "command=%s idf_root=%s target=%s component=%s",
            args.command,
            idf_root,
            args.target,
            args.component,
        )
        catalog = load_catalog(translations_dir)

        if args.command == "status":
            st = inspect_status(
                idf_root=idf_root,
                catalog=catalog,
                backup_root=backup_dir,
                target=args.target,
                component_filter=args.component,
            )
            print(f"ESP-IDF Path             : {idf_root}")
            print(f"Target                   : {args.target}")
            print(f"Target API headers       : {st.existing_headers} / {st.target_headers}")
            print(f"Localized headers        : {st.localized_headers}")
            print(f"Localized comments (ZH)  : {st.already_zh_comments}")
            print(f"Matchable comments (EN)  : {st.matchable_en_comments}")
            print(f"Unmatched comments (EN)  : {st.unmatched_en_comments}")
            print(f"Local backup present     : {'Yes' if st.has_local_backup else 'No'}")
            return 0

        if args.command == "apply":
            res = apply_translations(
                idf_root=idf_root,
                catalog=catalog,
                backup_root=backup_dir,
                target=args.target,
                component_filter=args.component,
                dry_run=args.dry_run,
            )
            mode_tag = " [DRY-RUN]" if res.dry_run else ""
            print(f"Apply completed{mode_tag}:")
            print(f"  Scanned headers          : {res.scanned_headers}")
            print(f"  Newly modified headers   : {res.modified_headers}")
            print(f"  Already localized headers: {res.already_localized_headers}")
            print(f"  Newly translated comments: {res.translated_comments}")
            print(f"  Already Chinese comments : {res.already_zh_comments}")
            print(f"  Unmatched English items  : {res.unmatched_en_comments}")
            if not res.dry_run and res.modified_headers > 0:
                print(
                    "\n提示：\n"
                    "  1. 若你的工程此前已被 clangd 索引过，请先删除工程下的 `build/.cache/clangd`（或 `.cache/clangd`）旧索引缓存\n"
                    "     （防止旧 `.c.*.idx` 定义分片中残留的英文注释覆盖新头文件注释）；\n"
                    "  2. 在 VS Code / Cursor 中按 Ctrl+Shift+P 执行 `clangd: Restart language server` 即可看到全中文提示。"
                )
            return 0

        if args.command == "restore":
            res_r = restore_headers(
                idf_root=idf_root,
                catalog=catalog,
                backup_root=backup_dir,
                target=args.target,
                component_filter=args.component,
                use_git_fallback=not args.no_git_fallback,
                force=args.force,
                dry_run=args.dry_run,
            )
            mode_tag = " [DRY-RUN]" if res_r.dry_run else ""
            print(f"Restore completed{mode_tag}:")
            print(f"  Restored headers         : {res_r.restored_headers}")
            print(f"  Unchanged / skipped      : {res_r.skipped_unmodified}")
            if res_r.skipped_code_edited:
                print(
                    f"  Protected (C code edited): {len(res_r.skipped_code_edited)} "
                    "(use --force to overwrite)"
                )
                for p in res_r.skipped_code_edited[:10]:
                    print(f"    * {p}")
            return 0

    except Exception as exc:
        logger.error("Execution failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
