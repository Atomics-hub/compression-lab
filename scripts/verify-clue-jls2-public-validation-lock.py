#!/usr/bin/env python3
"""Verify the exact final CLUE JLS2 public-validation readiness lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPOSITORY / "config" / "clue-jls2-public-validation-lock.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY,
        check=check,
        capture_output=True,
    )


def verify_lock(
    lock_path: Path,
    *,
    require_clean: bool = True,
) -> dict[str, Any]:
    if not lock_path.is_file():
        raise ValueError("final CLUE JLS2 readiness lock is missing")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("name") != "clue-jls2-public-validation-readiness-lock-v1":
        raise ValueError("unexpected CLUE JLS2 readiness lock identity")
    readiness = str(lock["readiness_commit"])
    head = git("rev-parse", "HEAD").stdout.decode().strip()
    status = git("status", "--porcelain", "--untracked-files=no").stdout.decode().strip()
    if require_clean and status:
        raise ValueError("public validation requires a clean tracked tree")
    ancestor = git("merge-base", "--is-ancestor", readiness, "HEAD", check=False)
    if ancestor.returncode != 0:
        raise ValueError("readiness commit is not an ancestor of HEAD")

    authorization = lock["authorization"]
    if authorization["maximum_acquisitions"] != 1:
        raise ValueError("readiness lock must authorize exactly one acquisition")
    if authorization["maximum_scored_attempts"] != 1:
        raise ValueError("readiness lock must authorize exactly one scored attempt")
    if authorization["expected_item_ids"] != [
        "clue-validation-a",
        "clue-validation-b",
    ]:
        raise ValueError("readiness lock item roster differs from the sealed split")

    verified: dict[str, str] = {}
    for relative, expected in lock["locked_paths"].items():
        working_path = REPOSITORY / relative
        if not working_path.is_file():
            raise ValueError(f"locked path is missing: {relative}")
        working = sha256_bytes(working_path.read_bytes())
        committed = sha256_bytes(git("show", f"{readiness}:{relative}").stdout)
        if committed != expected:
            raise ValueError(f"readiness commit digest mismatch: {relative}")
        if working != expected:
            raise ValueError(f"locked working path drifted: {relative}")
        verified[relative] = expected

    return {
        "schema_version": 1,
        "passed": True,
        "head_commit": head,
        "readiness_commit": readiness,
        "tracked_status": status,
        "lock_path": str(lock_path.resolve()),
        "lock_sha256": sha256_bytes(lock_path.read_bytes()),
        "verified_paths": verified,
        "claim_ceiling": lock["claim_ceiling"],
        "authorization": authorization,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify_lock(args.lock)
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"lock verification failed: {error}") from error
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            raise SystemExit("refusing to replace an existing lock receipt")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
