#!/usr/bin/env python3
"""Verify the built incompressible/precompressed corpus without source payloads."""

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


BUILDER = load_script(
    "incompressible_precompressed_builder_for_verifier",
    REPOSITORY / "scripts" / "build-incompressible-precompressed-development.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "corpus", nargs="?", type=Path, default=BUILDER.DEFAULT_OUTPUT
    )
    parser.add_argument("--plan", type=Path, default=BUILDER.DEFAULT_PLAN)
    args = parser.parse_args()
    try:
        BUILDER.PLAN_VERIFY.verify(
            config_path=BUILDER.PLANNER.DEFAULT_CONFIG,
            acquisition_path=BUILDER.PLANNER.DEFAULT_ACQUISITION,
            plan_path=args.plan,
        )
        result = BUILDER.validate_corpus(args.corpus, args.plan)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"development corpus verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
