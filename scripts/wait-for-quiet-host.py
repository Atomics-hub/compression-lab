#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for a sustained benchmark-eligible host-load window"
    )
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--consecutive", type=int, default=3)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.consecutive < 1 or args.interval <= 0 or args.timeout < 0:
        raise SystemExit("consecutive and interval must be positive; timeout cannot be negative")
    config = json.loads(args.gates.read_text(encoding="utf-8"))
    threshold = float(
        config["requirements"]["max_normalized_preflight_load_1m"]
    )
    cpu_count = os.cpu_count() or 0
    if cpu_count <= 0:
        print("logical CPU count unavailable", file=sys.stderr)
        return 2

    deadline = time.monotonic() + args.timeout
    qualifying = 0
    while True:
        load_1m = os.getloadavg()[0]
        normalized = load_1m / cpu_count
        qualifying = qualifying + 1 if normalized <= threshold else 0
        print(
            f"preflight load1={load_1m:.3f} load/core={normalized:.3f} "
            f"eligible={qualifying}/{args.consecutive}",
            flush=True,
        )
        if qualifying >= args.consecutive:
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"quiet-host preflight timed out above {threshold:.3f} load/core",
                file=sys.stderr,
            )
            return 2
        time.sleep(min(args.interval, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
