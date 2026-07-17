#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPOSITORY / "config" / "dms2-public-validation-lock.json"
DEFAULT_GATES = REPOSITORY / "config" / "dms2-public-validation-gates.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json_atomic_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to replace existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        if path.exists():
            raise ValueError(f"refusing to replace existing output: {path}")
        os.rename(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def project(
    *,
    source_manifest_path: Path,
    lock_path: Path,
    gates_path: Path,
    output_path: Path,
    receipt_path: Path,
) -> tuple[Path, Path]:
    if output_path.parent.resolve() != source_manifest_path.parent.resolve():
        raise ValueError("projected manifest must remain beside its acquired item files")
    if output_path.exists() or receipt_path.exists():
        raise ValueError("refusing to replace an existing projection or receipt")

    source_bytes = source_manifest_path.read_bytes()
    source = json.loads(source_bytes)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    gates = json.loads(gates_path.read_text(encoding="utf-8"))
    expected_ids = list(lock["authorization"]["expected_item_ids"])
    expected_items = gates["validation"]["expected_items"]
    if [item["id"] for item in expected_items] != expected_ids:
        raise ValueError("lock and gate item order differ")

    source_items = source.get("items", [])
    source_by_id: dict[str, dict[str, Any]] = {}
    for item in source_items:
        item_id = str(item.get("id"))
        if item_id in source_by_id:
            raise ValueError(f"duplicate acquired item: {item_id}")
        source_by_id[item_id] = item
    missing = [item_id for item_id in expected_ids if item_id not in source_by_id]
    if missing:
        raise ValueError(f"locked items missing from first acquisition: {missing}")

    selected = [copy.deepcopy(source_by_id[item_id]) for item_id in expected_ids]
    observed = [
        {"id": item.get("id"), "family": item.get("family"), "track": item.get("track")}
        for item in selected
    ]
    if observed != expected_items:
        raise ValueError("acquired item identity, family, or track differs from gates")

    excluded = [item for item in source_items if item.get("id") not in expected_ids]
    projected = copy.deepcopy(source)
    projected["items"] = selected
    projected["evaluation_tracks"] = sorted({str(item["track"]) for item in selected})
    projected["pre_score_projection"] = {
        "source_manifest": source_manifest_path.name,
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "selection_rule": "exact ordered lock.authorization.expected_item_ids",
        "selected_item_ids": expected_ids,
        "excluded_item_ids": [str(item["id"]) for item in excluded],
        "content_or_performance_consulted": False,
        "candidate_surface_changed": False,
        "gates_changed": False,
        "reason": (
            "The frozen acquisition wrapper acquired the complete successor "
            "public-validation split instead of only the two IDs already frozen "
            "for DMS2. Projection occurred before any compression score."
        ),
    }
    encoded = (json.dumps(projected, indent=2, sort_keys=True) + "\n").encode()
    receipt = {
        "schema_version": 1,
        "name": "dms2-public-validation-first-acquisition-deviation-v1",
        "status": "acquired_with_pre_score_manifest_projection",
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "projected_manifest_sha256": sha256_bytes(encoded),
        "selection_rule": "exact ordered lock.authorization.expected_item_ids",
        "selected_items": [
            {
                key: item[key]
                for key in ("id", "family", "track", "size_bytes", "sha256", "archive_sha256")
            }
            for item in selected
        ],
        "unexpectedly_acquired_but_unscored_items": [
            {
                key: item[key]
                for key in ("id", "family", "track", "size_bytes", "sha256", "archive_sha256")
            }
            for item in excluded
        ],
        "scored_attempts_started_before_projection": 0,
        "candidate_surface_changed": False,
        "gates_changed": False,
        "claim_ceiling": (
            "This receipt records an acquisition-scope deviation and a deterministic "
            "pre-score projection. It is not compression-performance evidence."
        ),
    }

    write_json_atomic_exclusive(output_path, projected)
    try:
        write_json_atomic_exclusive(receipt_path, receipt)
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise
    return output_path, receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project the first DMS2 acquisition to its predeclared locked item IDs"
    )
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        output, receipt = project(
            source_manifest_path=args.source_manifest,
            lock_path=args.lock,
            gates_path=args.gates,
            output_path=args.output,
            receipt_path=args.receipt,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise SystemExit(f"DMS2 manifest projection refused: {error}") from error
    print(output)
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
