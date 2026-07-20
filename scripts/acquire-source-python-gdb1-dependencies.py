#!/usr/bin/env python3
"""Acquire only the exact official-PyPI wheels frozen for GDB1."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import ssl
from types import ModuleType
from typing import Any
from urllib.request import Request, urlopen


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPOSITORY / "config" / "source-python-gdb1-dependency-lock-v1.json"
DEFAULT_CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
USER_AGENT = "compression-lab-gdb1-dependency-lock/1"
MAX_METADATA_BYTES = 16 * 1024 * 1024


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


VERIFIER = load_script(
    "gdb1_dependency_lock_verifier_for_acquisition",
    REPOSITORY / "scripts" / "verify-source-python-gdb1-dependency-lock.py",
)


def fetch_bytes(url: str, *, host: str, maximum_bytes: int) -> bytes:
    if not VERIFIER.safe_https_host(url, host):
        raise ValueError(f"refusing non-official URL: {url}")
    request = Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urlopen(request, timeout=60, context=ssl.create_default_context()) as response:
        final_url = response.geturl()
        if not VERIFIER.safe_https_host(final_url, host):
            raise ValueError(f"redirect escaped official host: {final_url}")
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > maximum_bytes:
            raise ValueError("official response exceeds frozen size bound")
        value = response.read(maximum_bytes + 1)
    if len(value) > maximum_bytes:
        raise ValueError("official response exceeds frozen size bound")
    return value


def verify_pypi_metadata(package: dict[str, Any]) -> None:
    raw = fetch_bytes(
        package["pypi_json_url"],
        host="pypi.org",
        maximum_bytes=MAX_METADATA_BYTES,
    )
    value = json.loads(raw)
    info = value.get("info", {})
    if (
        info.get("name") != package["name"]
        or info.get("version") != package["version"]
        or info.get("requires_python") != package["requires_python"]
        or (info.get("requires_dist") or []) != package["requires_dist"]
        or package["source_url"] not in (info.get("project_urls") or {}).values()
    ):
        raise ValueError(f"official PyPI metadata differs for {package['name']}")
    by_filename = {
        row.get("filename"): row
        for row in value.get("urls", [])
        if isinstance(row, dict)
    }
    for artifact in package["artifacts"]:
        row = by_filename.get(artifact["filename"], {})
        if (
            row.get("packagetype") != "bdist_wheel"
            or row.get("url") != artifact["url"]
            or row.get("size") != artifact["size_bytes"]
            or row.get("digests", {}).get("sha256") != artifact["sha256"]
            or row.get("upload_time_iso_8601") != artifact["upload_time_iso_8601"]
        ):
            raise ValueError(
                f"official PyPI artifact metadata differs for {artifact['filename']}"
            )


def download_artifact(artifact: dict[str, Any], destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(f"refusing substituted artifact path: {destination.name}")
        raw = destination.read_bytes()
        if (
            len(raw) != artifact["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != artifact["sha256"]
        ):
            raise ValueError(f"existing artifact differs: {destination.name}")
        return
    url = artifact["url"]
    if not VERIFIER.safe_https_host(url, "files.pythonhosted.org"):
        raise ValueError(f"refusing non-official artifact URL: {url}")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    temporary = destination.with_name(f".{destination.name}.part-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("refusing stale dependency partial")
    size = 0
    digest = hashlib.sha256()
    try:
        with urlopen(
            request, timeout=120, context=ssl.create_default_context()
        ) as response:
            if not VERIFIER.safe_https_host(
                response.geturl(), "files.pythonhosted.org"
            ):
                raise ValueError("artifact redirect escaped files.pythonhosted.org")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != artifact["size_bytes"]:
                raise ValueError("artifact Content-Length differs from lock")
            with temporary.open("xb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > artifact["size_bytes"]:
                        raise ValueError("artifact exceeds locked byte size")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if size != artifact["size_bytes"] or digest.hexdigest() != artifact["sha256"]:
            raise ValueError("downloaded artifact size or SHA-256 differs")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def acquire(lock_path: Path, config_path: Path, destination: Path) -> dict[str, Any]:
    config_raw, _config = VERIFIER.read_canonical(config_path)
    lock_raw, lock = VERIFIER.read_canonical(lock_path)
    if VERIFIER.sha256_bytes(lock_raw) != VERIFIER.EXPECTED_LOCK_SHA256:
        raise ValueError("dependency lock differs from the frozen trust anchor")
    VERIFIER.validate_lock(lock, config_raw)
    if destination.is_symlink():
        raise ValueError("dependency destination may not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ValueError("dependency destination is not a directory")
    expected = {
        artifact["filename"] for _package, artifact in VERIFIER.artifact_rows(lock)
    }
    observed = {path.name for path in destination.iterdir()}
    if not observed <= expected:
        raise ValueError("dependency destination contains unlisted files")
    for package in lock["packages"]:
        verify_pypi_metadata(package)
    for _package, artifact in VERIFIER.artifact_rows(lock):
        download_artifact(artifact, destination / artifact["filename"])
    return VERIFIER.verify(lock_path, config_path, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        result = acquire(args.lock, args.config, args.destination)
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"GDB1 dependency acquisition failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
