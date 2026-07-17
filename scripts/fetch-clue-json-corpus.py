#!/usr/bin/env python3
"""Acquire byte-exact frozen CLUE-LDS NDJSON ranges."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from typing import Any, BinaryIO, IO


REPOSITORY = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024
DEFAULT_VALIDATION_LOCK = (
    REPOSITORY / "config" / "clue-jls2-public-validation-lock.json"
)
LOCK_VERIFIER = (
    REPOSITORY / "scripts" / "verify-clue-jls2-public-validation-lock.py"
)


def verify_validation_lock(lock_path: Path) -> dict[str, Any]:
    specification = importlib.util.spec_from_file_location(
        "verify_clue_jls2_public_validation_lock",
        LOCK_VERIFIER,
    )
    if specification is None or specification.loader is None:
        raise ValueError("unable to load the CLUE JLS2 readiness-lock verifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.verify_lock(lock_path)


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "compression-lab-corpus-fetch/1"},
    )
    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output, CHUNK_SIZE)
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def validated_member(archive: zipfile.ZipFile, expected: str) -> zipfile.ZipInfo:
    path = PurePosixPath(expected)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"unsafe member path: {expected}")
    files = [item for item in archive.infolist() if not item.is_dir()]
    if len(files) != 1 or files[0].filename != expected:
        raise ValueError("archive member roster differs from frozen source")
    return files[0]


def verify_archive(path: Path, archive: dict[str, Any]) -> dict[str, str]:
    if path.stat().st_size != archive["size_bytes"]:
        raise ValueError("CLUE archive byte count mismatch")
    algorithm = archive["publisher_digest_algorithm"]
    publisher_digest = file_digest(path, algorithm)
    if publisher_digest != archive["publisher_digest"]:
        raise ValueError(f"CLUE archive {algorithm} mismatch")
    sha256 = file_digest(path, "sha256")
    if archive.get("sha256") is not None and sha256 != archive["sha256"]:
        raise ValueError("CLUE archive SHA-256 mismatch")
    return {algorithm: publisher_digest, "sha256": sha256}


def _open_temporary(directory: Path, name: str) -> tuple[Path, BinaryIO]:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{name}.", suffix=".partial", dir=directory
    )
    return Path(temporary_name), os.fdopen(descriptor, "wb")


def select_ranges(
    source: IO[bytes],
    selections: list[dict[str, Any]],
    output: Path,
) -> list[dict[str, Any]]:
    ordered = sorted(selections, key=lambda row: row["first_record_id"])
    for previous, current in zip(ordered, ordered[1:]):
        if previous["last_record_id"] >= current["first_record_id"]:
            raise ValueError("selected record ranges overlap")

    temporary_paths: dict[str, Path] = {}
    outputs: dict[str, BinaryIO] = {}
    hashes = {row["id"]: hashlib.sha256() for row in ordered}
    sizes = {row["id"]: 0 for row in ordered}
    counts = {row["id"]: 0 for row in ordered}
    try:
        for selection in ordered:
            name = f"{selection['id']}.jsonl"
            temporary, stream = _open_temporary(output, name)
            temporary_paths[selection["id"]] = temporary
            outputs[selection["id"]] = stream

        selection_index = 0
        for line_number, line in enumerate(source, start=1):
            while (
                selection_index < len(ordered)
                and line_number > ordered[selection_index]["last_record_id"]
            ):
                selection_index += 1
            if selection_index == len(ordered):
                break
            selection = ordered[selection_index]
            if line_number < selection["first_record_id"]:
                continue
            if not line.endswith(b"\n"):
                raise ValueError(f"record {line_number} lacks a newline boundary")
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"record {line_number} is invalid JSON") from error
            if not isinstance(record, dict) or record.get("id") != line_number:
                raise ValueError(f"record ID/line mismatch at {line_number}")
            destination = outputs[selection["id"]]
            destination.write(line)
            hashes[selection["id"]].update(line)
            sizes[selection["id"]] += len(line)
            counts[selection["id"]] += 1
        for selection in ordered:
            identifier = selection["id"]
            expected_count = (
                selection["last_record_id"] - selection["first_record_id"] + 1
            )
            if counts[identifier] != expected_count:
                raise ValueError(f"selected range is incomplete: {identifier}")
            if (
                selection.get("size_bytes") is not None
                and sizes[identifier] != selection["size_bytes"]
            ):
                raise ValueError(f"selected range byte count mismatch: {identifier}")
            selected_sha256 = hashes[identifier].hexdigest()
            if (
                selection.get("sha256") is not None
                and selected_sha256 != selection["sha256"]
            ):
                raise ValueError(f"selected range SHA-256 mismatch: {identifier}")
    except BaseException:
        for stream in outputs.values():
            stream.close()
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)
        raise
    else:
        for stream in outputs.values():
            stream.close()

    items = []
    for selection in ordered:
        identifier = selection["id"]
        destination_path = output / f"{identifier}.jsonl"
        os.replace(temporary_paths[identifier], destination_path)
        items.append(
            {
                **selection,
                "path": destination_path.name,
                "record_count": counts[identifier],
                "size_bytes": sizes[identifier],
                "sha256": hashes[identifier].hexdigest(),
                "split": "development",
                "category": "structured_cloud_event_logs",
                "license_spdx": "CC-BY-4.0",
            }
        )
    return items


def build(
    config_path: Path,
    split: str,
    output: Path,
    cache: Path,
    *,
    allow_public_validation: bool = False,
    validation_lock: Path = DEFAULT_VALIDATION_LOCK,
) -> Path:
    normalized_split = split.replace("-", "_")
    if normalized_split not in {"development", "public_validation"}:
        raise ValueError(f"unsupported split: {split}")
    if normalized_split == "public_validation" and not allow_public_validation:
        raise ValueError(
            "refusing to acquire CLUE public validation without "
            "--allow-public-validation"
        )
    if normalized_split == "public_validation":
        try:
            verify_validation_lock(validation_lock)
        except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
            raise ValueError(
                f"refusing CLUE public validation without a valid final readiness lock: {error}"
            ) from error

    config = json.loads(config_path.read_text(encoding="utf-8"))
    selections = config["selection"][normalized_split]
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    archive_config = config["archive"]
    archive_path = cache / archive_config["filename"]
    if not archive_path.is_file():
        print(f"download {archive_config['url']}", flush=True)
        download(archive_config["url"], archive_path)
    digests = verify_archive(archive_path, archive_config)

    with zipfile.ZipFile(archive_path) as archive:
        member = validated_member(archive, archive_config["member"])
        with archive.open(member) as source:
            items = select_ranges(source, selections, output)
    for item in items:
        item["split"] = normalized_split
        item["dataset"] = config["name"]
        item["source_url"] = config["provider"]["record_url"]
        item["provenance"] = {
            "doi": config["provider"]["doi"],
            "archive_sha256": digests["sha256"],
            "selection_rule": config["selection"]["rule"],
        }

    resolved_config = config_path.resolve()
    try:
        config_reference = str(resolved_config.relative_to(REPOSITORY))
    except ValueError:
        config_reference = str(resolved_config)

    manifest = {
        "schema_version": 1,
        "name": config["name"],
        "category": config["category"],
        "split": normalized_split,
        "claim_ceiling": config["claim_ceiling"],
        "provider": config["provider"],
        "config_path": config_reference,
        "config_sha256": file_digest(config_path, "sha256"),
        "archive": {
            "filename": archive_config["filename"],
            "size_bytes": archive_path.stat().st_size,
            "publisher_digest_algorithm": archive_config["publisher_digest_algorithm"],
            "publisher_digest": digests[archive_config["publisher_digest_algorithm"]],
            "sha256": digests["sha256"],
            "member": member.filename,
            "member_size_bytes": member.file_size,
        },
        "selection_rule": config["selection"]["rule"],
        "items": items,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "config" / "clue-json-log-corpus-v1.json",
    )
    parser.add_argument(
        "--split",
        choices=("development", "public-validation"),
        default="development",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "corpora" / "clue-json-log-development-v1",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPOSITORY / "corpora" / "_download-cache" / "clue-v1",
    )
    parser.add_argument("--allow-public-validation", action="store_true")
    parser.add_argument("--validation-lock", type=Path, default=DEFAULT_VALIDATION_LOCK)
    args = parser.parse_args()
    manifest = build(
        args.config,
        args.split,
        args.output,
        args.cache,
        allow_public_validation=args.allow_public_validation,
        validation_lock=args.validation_lock,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
