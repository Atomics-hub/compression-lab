#!/usr/bin/env python3
"""Verify live GitHub metadata against the pinned E1 recovery receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"expected ordinary JSON file: {path}")
    return json.loads(path.read_bytes())


def normalize_artifact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "size_in_bytes": row["size_in_bytes"],
        "digest": row["digest"],
        "expired": row["expired"],
    }


def verify(pinned_path: Path, run_path: Path, artifacts_path: Path) -> dict[str, Any]:
    pinned = read(pinned_path)
    run = read(run_path)
    artifacts = read(artifacts_path)
    live_identity = {
        "source_run_id": run["id"],
        "source_run_attempt": run["run_attempt"],
        "source_head_sha": run["head_sha"],
        "source_event": run["event"],
        "source_conclusion": run["conclusion"],
        "source_url": run["html_url"],
    }
    for key, value in live_identity.items():
        if pinned.get(key) != value:
            raise ValueError(f"live E1 recovery run identity differs: {key}")
    live_artifacts = sorted(
        (normalize_artifact(row) for row in artifacts["artifacts"]),
        key=lambda row: row["name"],
    )
    if live_artifacts != pinned["artifacts"]:
        raise ValueError("live E1 recovery artifact roster or digest differs")
    return pinned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pinned", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = verify(args.pinned, args.run, args.artifacts)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"E1 GitHub recovery verification failed: {error}") from error
    print(json.dumps({"verified": True, "source_run_id": receipt["source_run_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
