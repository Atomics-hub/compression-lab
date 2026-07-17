#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
FETCHER = REPOSITORY / "scripts" / "fetch_tabular_successor_corpus.py"
VERIFIER = REPOSITORY / "scripts" / "verify-dms2-public-validation-lock.py"
DEFAULT_CONFIG = REPOSITORY / "config" / "tabular-successor-corpus-v1.json"
DEFAULT_LOCK = REPOSITORY / "config" / "dms2-public-validation-lock.json"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def acquire(
    *,
    config: Path,
    lock: Path,
    output: Path,
    cache: Path,
    allow_public_validation: bool,
) -> Path:
    if not allow_public_validation:
        raise ValueError(
            "refusing to acquire DMS2 public validation without "
            "--allow-public-validation"
        )
    verifier = load_module("verify_dms2_public_validation_lock", VERIFIER)
    verifier.verify_lock(lock)
    fetcher = load_module("fetch_dms2_successor_corpus", FETCHER)
    return fetcher.build(
        config,
        "public-validation",
        output,
        cache,
        allow_public_validation=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire the locked DMS2 public-validation matrices once"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--allow-public-validation", action="store_true")
    args = parser.parse_args()
    try:
        manifest = acquire(
            config=args.config,
            lock=args.lock,
            output=args.output,
            cache=args.cache,
            allow_public_validation=args.allow_public_validation,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f"DMS2 acquisition refused: {error}") from error
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
