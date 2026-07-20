#!/usr/bin/env python3
"""Verify the text/source research-ceiling aggregate against every raw host run."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType


REPOSITORY = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGGREGATE = load_script(
    "research_ceiling_aggregate_for_verifier",
    REPOSITORY / "scripts" / "aggregate-text-source-research-ceiling.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("--plan", type=Path, default=AGGREGATE.DEFAULT_PLAN)
    parser.add_argument(
        "--host-run",
        action="append",
        nargs=3,
        metavar=("TOOLCHAIN_RECEIPT", "TOOLS_ROOT", "OUTPUT"),
        required=True,
    )
    parser.add_argument(
        "--second-host-run",
        nargs=3,
        metavar=("TOOLCHAIN_RECEIPT", "TOOLS_ROOT", "OUTPUT"),
    )
    args = parser.parse_args()
    host_runs = AGGREGATE.parse_host_runs(args.host_run)
    second_host_run = (
        AGGREGATE.SecondHostRun(*(Path(value) for value in args.second_host_run))
        if args.second_host_run
        else None
    )
    try:
        result = AGGREGATE.validate_aggregate(
            aggregate_path=args.aggregate,
            plan_path=args.plan,
            host_runs=host_runs,
            second_host_run=second_host_run,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"research-ceiling aggregate verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
