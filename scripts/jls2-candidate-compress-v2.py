#!/usr/bin/env python3
"""Cold-process single-file JLS2 candidate compression driver.

A deliberately minimal entry point: it imports the frozen candidate encoder and
compresses exactly one source file to one destination. It exists so the v2
benchmark can measure candidate compression peak RSS through the clean-child
instrument (scripts/measure-clean-rss.py) instead of an in-benchmark
wait4 reaped from the large parent. It performs no measurement itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.json_log_codec import compress_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    compress_file(args.source, args.destination, overwrite=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
