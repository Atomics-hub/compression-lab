#!/usr/bin/env python3
"""Acquire or verify pinned numeric baseline sources without building/running them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "config" / "numeric-ar5-numr-toolchain-lock-v1.json"
EXPECTED_CANONICAL_LOCK_SHA256 = (
    "f47540d8e32bd190811a95341959f800f8f46ad59d7fdb0cc55cf5a9932e7931"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def output(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip()


def acquire_source(destination: Path, source: dict[str, Any], allow_download: bool) -> None:
    if destination.exists():
        return
    if not allow_download:
        raise ValueError(f"pinned source is absent: {source['id']}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        subprocess.run(["git", "init", str(temporary)], check=True, timeout=60)
        subprocess.run(
            ["git", "-C", str(temporary), "remote", "add", "origin", source["repository"]],
            check=True,
            timeout=60,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(temporary),
                "fetch",
                "--depth",
                "1",
                "origin",
                source["revision"],
            ],
            check=True,
            timeout=600,
        )
        subprocess.run(
            ["git", "-C", str(temporary), "checkout", "--detach", "FETCH_HEAD"],
            check=True,
            timeout=60,
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_source(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    destination = root / source["directory"]
    if not destination.is_dir():
        raise ValueError(f"pinned source directory is absent: {source['id']}")
    head = output(["git", "-C", str(destination), "rev-parse", "HEAD"])
    tree = output(["git", "-C", str(destination), "rev-parse", "HEAD^{tree}"])
    status = output(["git", "-C", str(destination), "status", "--porcelain"])
    remote = output(["git", "-C", str(destination), "remote", "get-url", "origin"])
    if head != source["revision"] or tree != source["tree"] or status:
        raise ValueError(f"source identity or cleanliness differs: {source['id']}")
    if remote != source["repository"]:
        raise ValueError(f"source remote differs: {source['id']}")
    license_path = destination / source["license_file"]
    if (
        license_path.is_symlink()
        or not license_path.is_file()
        or license_path.stat().st_size != source["license_bytes"]
        or sha256_file(license_path) != source["license_sha256"]
    ):
        raise ValueError(f"license identity differs: {source['id']}")
    return {
        "id": source["id"],
        "revision": head,
        "tree": tree,
        "license_sha256": source["license_sha256"],
        "clean": True,
    }


def verify_runtime(lock: dict[str, Any]) -> dict[str, Any]:
    import platform
    import sys

    import zstandard

    expected = lock["candidate_runtime"]
    extension = Path(getattr(zstandard, "backend_c").__file__).resolve()
    executable = Path(sys.executable).resolve()
    observed = {
        "host": platform.platform(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable_sha256": sha256_file(executable),
        "python_zstandard_version": zstandard.__version__,
        "python_zstandard_backend": zstandard.backend,
        "python_zstandard_extension_bytes": extension.stat().st_size,
        "python_zstandard_extension_sha256": sha256_file(extension),
        "bundled_libzstd_version": ".".join(map(str, zstandard.ZSTD_VERSION)),
        "zstd_parameters": expected["zstd_parameters"],
    }
    if observed != expected:
        raise ValueError("candidate runtime differs from the frozen host lock")
    return observed


def verify_lock(lock: dict[str, Any]) -> None:
    if set(lock) != {
        "schema_version",
        "name",
        "status",
        "measurement_authorized",
        "corpus_access_authorized",
        "claim_ceiling",
        "source_root",
        "sources",
        "candidate_runtime",
        "baseline_binary_status",
        "authorization_blockers",
        "allowed_execution",
        "forbidden_execution",
        "results",
    }:
        raise ValueError("toolchain lock keys drifted")
    if (
        lock["schema_version"] != 1
        or lock["measurement_authorized"] is not False
        or lock["corpus_access_authorized"] is not False
        or lock["results"] is not None
        or lock["baseline_binary_status"] != "unbuilt_and_unauthorized"
    ):
        raise ValueError("toolchain lock must remain fail-closed")
    sources = lock["sources"]
    if len(sources) != 8 or len({source["id"] for source in sources}) != 8:
        raise ValueError("exactly eight unique official sources are required")
    for source in sources:
        if (
            not source["repository"].startswith("https://github.com/")
            or len(source["revision"]) != 40
            or len(source["tree"]) != 40
            or len(source["license_sha256"]) != 64
        ):
            raise ValueError(f"source lock is incomplete: {source['id']}")
    if len(lock["authorization_blockers"]) != 4:
        raise ValueError("all four authorization blockers are required")
    canonical = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != EXPECTED_CANONICAL_LOCK_SHA256:
        raise ValueError("frozen toolchain lock identity drifted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    verify_lock(lock)
    source_root = ROOT / lock["source_root"]
    receipts = []
    for source in lock["sources"]:
        destination = source_root / source["directory"]
        acquire_source(destination, source, args.allow_download)
        receipts.append(verify_source(source_root, source))
    result = {
        "schema_version": 1,
        "name": "numeric-ar5-numr-toolchain-receipt-v1",
        "lock_sha256": sha256_file(args.lock),
        "sources": receipts,
        "candidate_runtime": verify_runtime(lock),
        "measurement_authorized": False,
        "corpus_access_authorized": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
