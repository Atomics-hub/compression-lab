#!/usr/bin/env python3
"""Extract a frozen E1 source archive while rejecting unsafe archive entries."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile


MAX_EXTRACTED_BYTES = 256 * 1024 * 1024


def target(root: Path, name: str, strip_components: int) -> Path | None:
    if "\\" in name:
        raise ValueError("archive member contains a backslash")
    parsed = PurePosixPath(name)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError("archive member path is unsafe")
    parts = parsed.parts[strip_components:]
    if not parts:
        return None
    destination = root.joinpath(*parts)
    destination.resolve().relative_to(root.resolve())
    return destination


def write_member(source, destination: Path, size: int, seen: set[Path]) -> None:
    if destination in seen or destination.exists():
        raise ValueError("archive member path is duplicated")
    seen.add(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        shutil.copyfileobj(source, output, 1024 * 1024)
    if destination.stat().st_size != size:
        raise ValueError("archive member size differs")


def extract(archive: Path, root: Path, strip_components: int) -> None:
    if archive.is_symlink() or not archive.is_file() or root.exists():
        raise ValueError("archive or destination state is unsafe")
    root.mkdir(parents=True)
    seen: set[Path] = set()
    total = 0
    try:
        if tarfile.is_tarfile(archive):
            with tarfile.open(archive, "r:*") as bundle:
                for member in bundle:
                    destination = target(root, member.name, strip_components)
                    if destination is None or member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("archive contains a link or special entry")
                    total += member.size
                    if total > MAX_EXTRACTED_BYTES:
                        raise ValueError("archive exceeds the extraction byte limit")
                    source = bundle.extractfile(member)
                    if source is None:
                        raise ValueError("archive regular member is unreadable")
                    with source:
                        write_member(source, destination, member.size, seen)
        else:
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    destination = target(root, member.filename, strip_components)
                    if destination is None or member.is_dir():
                        continue
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if kind not in {0, stat.S_IFREG}:
                        raise ValueError("archive contains a link or special entry")
                    total += member.file_size
                    if total > MAX_EXTRACTED_BYTES:
                        raise ValueError("archive exceeds the extraction byte limit")
                    with bundle.open(member) as source:
                        write_member(source, destination, member.file_size, seen)
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strip-components", type=int, default=0)
    args = parser.parse_args()
    if args.strip_components < 0:
        raise SystemExit("strip-components must be nonnegative")
    try:
        extract(args.archive, args.output, args.strip_components)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SystemExit(f"safe E1 extraction failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
