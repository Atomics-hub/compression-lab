#!/usr/bin/env python3
"""Recompute and verify the frozen TS-P1/WK-P1 entropy-ceiling result."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY / "scripts" / "benchmark-text-source-predictor-ceiling.py"
SPEC = importlib.util.spec_from_file_location("predictor_ceiling_verifier", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load predictor ceiling runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=RUNNER.DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=RUNNER.DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=RUNNER.DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=RUNNER.DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = RUNNER.verify(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            output=args.output,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"predictor entropy-ceiling verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
