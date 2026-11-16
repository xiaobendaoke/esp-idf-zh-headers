#!/usr/bin/env python3
"""Zero-install root entry point: `python idf_zh.py <apply|restore|status|validate>`."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from idf_zh.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
