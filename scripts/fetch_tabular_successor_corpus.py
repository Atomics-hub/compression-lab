#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
BASE_SCRIPT = REPOSITORY / "scripts" / "fetch_tabular_corpus.py"
SPECIFICATION = importlib.util.spec_from_file_location(
    "frozen_fetch_tabular_corpus",
    BASE_SCRIPT,
)
if SPECIFICATION is None or SPECIFICATION.loader is None:
    raise RuntimeError("unable to load frozen tabular corpus fetcher")
BASE = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(BASE)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build(
    config_path: Path,
    split: str,
    output: Path,
    cache: Path,
    allow_public_validation: bool = False,
) -> Path:
    manifest_path = BASE.build(
        config_path,
        split,
        output,
        cache,
        allow_public_validation,
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_key = split.replace("-", "_")
    sources = {source["id"]: source for source in config[config_key]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["items"]:
        source = sources[item["id"]]
        for key in ("track", "delimiter", "structure"):
            item[key] = source[key]
    manifest["evaluation_tracks"] = sorted(
        {item["track"] for item in manifest["items"]}
    )
    manifest["routing_policy"] = config["contamination_policy"][
        "production_routing"
    ]
    write_json_atomic(manifest_path, manifest)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "config" / "tabular-successor-corpus-v1.json",
    )
    parser.add_argument(
        "--split",
        choices=("development", "public-validation"),
        default="development",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "corpora" / "tabular-successor-development-v1",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=(
            REPOSITORY / "corpora" / "_download-cache" / "uci-tabular-successor-v1"
        ),
    )
    parser.add_argument("--allow-public-validation", action="store_true")
    args = parser.parse_args()
    print(
        build(
            args.config,
            args.split,
            args.output,
            args.cache,
            args.allow_public_validation,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
