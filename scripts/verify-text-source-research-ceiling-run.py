#!/usr/bin/env python3
"""Verify one raw host-scoped text/source research-ceiling run."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY / "scripts" / "benchmark-text-source-research-ceiling.py"
SPEC = importlib.util.spec_from_file_location("research_ceiling_runner_verifier", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load research-ceiling runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=RUNNER.DEFAULT_PLAN)
    parser.add_argument("--toolchain-receipt", type=Path, required=True)
    parser.add_argument("--tools-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=RUNNER.DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = RUNNER.validate_output(
            plan_path=args.plan,
            toolchain_receipt_path=args.toolchain_receipt,
            tools_root=args.tools_root,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"research-ceiling run verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
