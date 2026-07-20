#!/usr/bin/env python3
"""Verify a routed text/source successor decision from public probe evidence."""

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


ROUTER = load_script(
    "structural_successor_router_for_verifier",
    REPOSITORY / "scripts" / "route-text-source-structural-successor.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "decision", nargs="?", type=Path, default=ROUTER.DEFAULT_OUTPUT
    )
    parser.add_argument("--config", type=Path, default=ROUTER.DEFAULT_CONFIG)
    parser.add_argument(
        "--publication", type=Path, default=ROUTER.DEFAULT_PUBLICATION
    )
    args = parser.parse_args()
    try:
        result = ROUTER.validate_decision(
            args.config, args.publication, args.decision
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"successor decision verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
