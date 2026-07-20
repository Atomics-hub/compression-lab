#!/usr/bin/env python3
"""Assemble the exact E1 training roster after the tool barrier has passed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
E1_CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary training file: {path}")


def normalized_relative(path: Path, base: Path) -> str:
    relative = path.resolve().relative_to(base.resolve()).as_posix()
    parsed = PurePosixPath(relative)
    if any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError("training path is not normalized")
    return relative


def rows_from_manifest(kind: str, path: Path, base: Path) -> dict[str, dict[str, Any]]:
    ordinary(path)
    document = json.loads(path.read_bytes())
    if (
        kind != "text"
        and document.get("split", document.get("benchmark_split")) != "development"
    ):
        raise ValueError(f"non-development split in {kind} manifest")
    if kind == "text" and document.get("public_validation_accessed") is not False:
        raise ValueError("text/source manifest touched public validation")
    rows = {}
    for item in document["items"]:
        if kind == "text":
            item_id = item["source_id"]
            relative = item["bundle_path"]
            size = item["bundle_size_bytes"]
            digest = item["bundle_sha256"]
        else:
            item_id = item["id"]
            relative = item.get("path", item.get("item_path"))
            size = item.get("size_bytes", item.get("item_bytes"))
            digest = item.get("sha256", item.get("item_sha256"))
        source = path.parent / relative
        ordinary(source)
        if source.stat().st_size != size or sha256_file(source) != digest:
            raise ValueError(f"training item identity differs: {item_id}")
        if item_id in rows:
            raise ValueError(f"duplicate training item: {item_id}")
        rows[item_id] = {
            "path": normalized_relative(source, base),
            "bytes": size,
            "sha256": digest,
            "source_manifest_path": normalized_relative(path, base),
            "source_manifest_sha256": sha256_file(path),
        }
    return rows


def assemble(base: Path, manifests: dict[str, Path]) -> dict[str, Any]:
    e1 = json.loads(E1_CONFIG.read_bytes())
    available: dict[str, dict[str, Any]] = {}
    for kind in ("clue", "text", "tabular", "successor"):
        for item_id, row in rows_from_manifest(kind, manifests[kind], base).items():
            if item_id in available:
                raise ValueError(f"duplicate item across training manifests: {item_id}")
            available[item_id] = row
    items = []
    for declared in e1["items"]:
        selected = available.get(declared["id"])
        if selected is None:
            raise ValueError(f"declared E1 training item is absent: {declared['id']}")
        if (selected["bytes"], selected["sha256"]) != (
            declared["bytes"],
            declared["sha256"],
        ):
            raise ValueError(f"E1 training declaration differs: {declared['id']}")
        items.append(
            {
                "id": declared["id"],
                "category": declared["category"],
                "license": declared["license"],
                **selected,
            }
        )
    if len(items) != 17 or {row["id"] for row in items} != {
        row["id"] for row in e1["items"]
    }:
        raise ValueError("E1 training roster is incomplete")
    return {
        "schema_version": 1,
        "name": "frontier-headroom-e1-training-manifest-v1",
        "completed": True,
        "e1_config_sha256": sha256_file(E1_CONFIG),
        "base": ".",
        "items": items,
        "public_validation_accessed": False,
        "private_holdout_accessed": False,
        "claim_ceiling": "Exact licensed E1 training bytes only; no validation, holdout, candidate win, or state-of-the-art evidence.",
    }


def write_immutable(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError("refusing to replace differing E1 training manifest")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--clue", type=Path, required=True)
    parser.add_argument("--text", type=Path, required=True)
    parser.add_argument("--tabular", type=Path, required=True)
    parser.add_argument("--successor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = assemble(
            args.base,
            {
                "clue": args.clue,
                "text": args.text,
                "tabular": args.tabular,
                "successor": args.successor,
            },
        )
        write_immutable(args.output, payload)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"E1 training-manifest assembly failed: {error}") from error
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
