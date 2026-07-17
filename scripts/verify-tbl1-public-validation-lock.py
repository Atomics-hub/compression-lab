#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPOSITORY / "config" / "tbl1-public-validation-lock.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY,
        check=check,
        capture_output=True,
    )


def verify_historical_lock(lock_path: Path) -> dict[str, Any]:
    """Audit a completed lock against the exact commit it originally froze."""
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    readiness = str(lock["readiness_commit"])
    head = git("rev-parse", "HEAD").stdout.decode().strip()
    ancestor = git("merge-base", "--is-ancestor", readiness, "HEAD", check=False)
    if ancestor.returncode != 0:
        raise ValueError("readiness commit is not an ancestor of HEAD")

    verified: dict[str, str] = {}
    for relative, expected in lock["locked_paths"].items():
        committed = sha256_bytes(git("show", f"{readiness}:{relative}").stdout)
        if committed != expected:
            raise ValueError(f"readiness commit digest mismatch: {relative}")
        verified[relative] = expected

    return {
        "schema_version": 1,
        "passed": True,
        "head_commit": head,
        "readiness_commit": readiness,
        "lock_path": str(lock_path.resolve()),
        "lock_sha256": sha256_bytes(lock_path.read_bytes()),
        "verified_paths": verified,
        "claim_ceiling": lock["claim_ceiling"],
    }


def verify_lock(
    lock_path: Path,
    *,
    require_clean: bool = True,
) -> dict[str, Any]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    historical = verify_historical_lock(lock_path)
    status = git("status", "--porcelain", "--untracked-files=no").stdout.decode().strip()
    if require_clean and status:
        raise ValueError("public validation requires a clean tracked tree")

    for relative, expected in lock["locked_paths"].items():
        working = sha256_bytes((REPOSITORY / relative).read_bytes())
        if working != expected:
            raise ValueError(f"locked working path drifted: {relative}")

    return {
        **historical,
        "tracked_status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the exact TBL1 public-validation readiness lock"
    )
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
