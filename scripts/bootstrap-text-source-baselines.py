#!/usr/bin/env python3
"""Build the exact source-based tools required by the text/source census."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any
import urllib.request


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-baseline-toolchain-v1.json"
DEFAULT_ROOT = REPOSITORY / ".baseline-tools" / "text-source-v1"
CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "compression-lab-text-source-baseline-v1"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output, CHUNK_SIZE)


def acquire_archive(entry: dict[str, Any], cache: Path) -> Path:
    destination = cache / f"{entry['name']}-{entry['commit']}.tar.gz"
    if destination.exists():
        if destination.stat().st_size != entry["archive_size_bytes"]:
            raise ValueError(f"cached archive size mismatch: {destination.name}")
        if file_digest(destination) != entry["archive_sha256"]:
            raise ValueError(f"cached archive digest mismatch: {destination.name}")
        return destination
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=cache
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        download(entry["archive_url"], temporary)
        if temporary.stat().st_size != entry["archive_size_bytes"]:
            raise ValueError(f"downloaded archive size mismatch: {destination.name}")
        if file_digest(temporary) != entry["archive_sha256"]:
            raise ValueError(f"downloaded archive digest mismatch: {destination.name}")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination.mkdir()
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if not members:
                raise ValueError(f"empty source archive: {archive_path.name}")
            roots: set[str] = set()
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise ValueError(f"unsafe source archive path: {member.name}")
                roots.add(path.parts[0])
                if not (member.isdir() or member.isfile()):
                    raise ValueError(f"unsupported source archive member: {member.name}")
            if len(roots) != 1:
                raise ValueError(f"source archive has multiple roots: {archive_path.name}")
            root = next(iter(roots))
            for member in members:
                path = PurePosixPath(member.name)
                relative = PurePosixPath(*path.parts[1:])
                if not relative.parts:
                    continue
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"missing archive content: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, CHUNK_SIZE)
                target.chmod(member.mode & 0o777)
            if not root:
                raise ValueError("source archive root is empty")
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def run_checked(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command exited {completed.returncode}: {command}")


def build_entry(entry: dict[str, Any], root: Path, archive_path: Path) -> dict[str, Any]:
    sources = root / "src"
    builds = root / "build"
    source = sources / f"{entry['name']}-{entry['commit']}"
    build = builds / f"{entry['name']}-{entry['commit']}"
    if not source.exists():
        staged = sources / f".{source.name}.staging"
        if staged.exists():
            shutil.rmtree(staged)
        safe_extract(archive_path, staged)
        os.replace(staged, source)
    if build.exists():
        shutil.rmtree(build)
    build.mkdir()
    configure = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build),
        *entry["cmake_arguments"],
    ]
    run_checked(configure, root)
    run_checked(
        [
            "cmake",
            "--build",
            str(build),
            "--config",
            "Release",
            "--target",
            entry["target"],
            "-j",
            str(max(1, min(os.cpu_count() or 1, 16))),
        ],
        root,
    )
    relative = Path(entry["built_relative_path"])
    if relative.parts[0] == "build":
        binary = build.joinpath(*relative.parts[1:])
    else:
        binary = source / relative
    if not binary.is_file():
        raise ValueError(f"built binary is missing: {binary}")
    installed = root / "bin" / entry["installed_name"]
    temporary = installed.with_name(f".{installed.name}.partial")
    shutil.copyfile(binary, temporary)
    temporary.chmod(0o755)
    os.replace(temporary, installed)
    return {
        "name": entry["name"],
        "version": entry["version"],
        "tag": entry["tag"],
        "commit": entry["commit"],
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": file_digest(archive_path),
        "binary_path": str(installed.resolve()),
        "binary_size_bytes": installed.stat().st_size,
        "binary_sha256": file_digest(installed),
        "cmake_arguments": entry["cmake_arguments"],
        "target": entry["target"],
    }


def bootstrap(config_path: Path, root: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    for child in ("bin", "cache", "src", "build"):
        (root / child).mkdir(exist_ok=True)
    rows = []
    for entry in config["source_builds"]:
        archive_path = acquire_archive(entry, root / "cache")
        rows.append(build_entry(entry, root, archive_path))
    receipt = {
        "schema_version": 1,
        "name": config["name"],
        "config_path": str(config_path.resolve()),
        "config_sha256": file_digest(config_path),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cmake": subprocess.run(
            ["cmake", "--version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0],
        "builds": rows,
    }
    receipt_path = root / "receipt.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".receipt.", suffix=".partial", dir=root
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(receipt, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary_name, receipt_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    try:
        receipt = bootstrap(args.config, args.root)
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"baseline bootstrap failed: {error}") from error
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
