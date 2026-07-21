#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import urllib.request
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "compression-lab-tabular-corpus/1"},
    )
    partial = destination.with_suffix(destination.suffix + ".partial")
    with urllib.request.urlopen(request, timeout=180) as response:
        with partial.open("wb") as output:
            shutil.copyfileobj(response, output, CHUNK_SIZE)
    partial.replace(destination)


def _validated_member(archive: zipfile.ZipFile, member: str) -> zipfile.ZipInfo:
    path = PurePosixPath(member)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe member path: {member}")
    matches = [info for info in archive.infolist() if info.filename == member]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one archive member {member!r}")
    info = matches[0]
    mode = info.external_attr >> 16
    if info.is_dir() or stat.S_ISLNK(mode):
        raise ValueError(f"archive member is not a regular file: {member}")
    return info


def _record_aligned_prefix(source, maximum: int) -> tuple[bytes, bool]:
    if maximum <= 0:
        raise ValueError("maximum item size must be positive")
    data = bytearray()
    while len(data) <= maximum:
        chunk = source.read(min(CHUNK_SIZE, maximum + 1 - len(data)))
        if not chunk:
            return bytes(data), True
        data.extend(chunk)
    prefix = bytes(data[:maximum])
    end = prefix.rfind(b"\n") + 1
    if end == 0:
        raise ValueError("no complete LF-terminated record within item size cap")
    return prefix[:end], False


def extract_item(
    archive_path: Path,
    member: str,
    member_compression: str,
    maximum: int,
) -> tuple[bytes, bool]:
    with zipfile.ZipFile(archive_path) as archive:
        info = _validated_member(archive, member)
        with archive.open(info) as member_stream:
            if member_compression == "none":
                return _record_aligned_prefix(member_stream, maximum)
            if member_compression == "gzip":
                with gzip.GzipFile(fileobj=member_stream) as decompressed:
                    return _record_aligned_prefix(decompressed, maximum)
    raise ValueError(f"unsupported member compression: {member_compression}")


def build(
    config_path: Path,
    split: str,
    output: Path,
    cache: Path,
    allow_public_validation: bool = False,
) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_key = split.replace("-", "_")
    if config_key not in {"development", "public_validation"}:
        raise ValueError(f"unsupported split: {split}")
    if config_key == "public_validation" and not allow_public_validation:
        raise ValueError(
            "refusing to acquire public validation without "
            "--allow-public-validation"
        )

    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    maximum = int(config["selection"]["max_item_bytes"])
    benchmark_split = "train" if config_key == "development" else "validation"
    manifest_items = []
    for source in config[config_key]:
        archive_path = cache / f"{source['id']}.zip"
        if not archive_path.is_file():
            print(f"download {source['archive_url']}", flush=True)
            download(source["archive_url"], archive_path)
        archive_sha256 = file_sha256(archive_path)
        expected_archive_sha256 = source["archive_sha256"]
        if (
            expected_archive_sha256 is not None
            and archive_sha256 != expected_archive_sha256
        ):
            raise ValueError(
                f"{source['id']} archive SHA-256 mismatch: expected "
                f"{expected_archive_sha256}, got {archive_sha256}"
            )

        item, source_complete = extract_item(
            archive_path,
            source["member"],
            source["member_compression"],
            maximum,
        )
        item_path = output / f"{source['id']}.table"
        item_sha256 = hashlib.sha256(item).hexdigest()
        expected_item_bytes = source.get("selected_item_bytes")
        if expected_item_bytes is not None and len(item) != expected_item_bytes:
            raise ValueError(
                f"{source['id']} item size mismatch: expected "
                f"{expected_item_bytes}, got {len(item)}"
            )
        expected_item_sha256 = source.get("selected_item_sha256")
        if expected_item_sha256 is not None and item_sha256 != expected_item_sha256:
            raise ValueError(
                f"{source['id']} item SHA-256 mismatch: expected "
                f"{expected_item_sha256}, got {item_sha256}"
            )
        expected_source_complete = source.get("source_complete")
        if (
            expected_source_complete is not None
            and source_complete is not expected_source_complete
        ):
            raise ValueError(
                f"{source['id']} completeness mismatch: expected "
                f"{expected_source_complete}, got {source_complete}"
            )
        item_path.write_bytes(item)
        manifest_items.append(
            {
                "id": source["id"],
                "family": source["family"],
                "path": item_path.name,
                "category": config["category"],
                "split": benchmark_split,
                "size_bytes": len(item),
                "sha256": item_sha256,
                "dataset": source["title"],
                "license_spdx": config["provider"]["license_spdx"],
                "doi": source["doi"],
                "source_url": source["page_url"],
                "page_url": source["page_url"],
                "archive_url": source["archive_url"],
                "archive_path": str(archive_path),
                "archive_sha256": archive_sha256,
                "publisher_digest_pinned": expected_archive_sha256 is not None,
                "member": source["member"],
                "member_compression": source["member_compression"],
                "item_path": item_path.name,
                "item_bytes": len(item),
                "item_sha256": item_sha256,
                "item_digest_pinned": expected_item_sha256 is not None,
                "source_complete": source_complete,
                "provenance": {
                    "provider": config["provider"]["name"],
                    "archive_url": source["archive_url"],
                    "archive_sha256": archive_sha256,
                    "member": source["member"],
                    "member_compression": source["member_compression"],
                    "selection_rule": config["selection"]["slice_rule"],
                    "source_split": config_key,
                },
            }
        )
        print(
            f"verified {source['family']} {len(item):,} bytes "
            f"sha256={item_sha256}",
            flush=True,
        )

    manifest = {
        "schema_version": 2,
        "generator": "compression-lab-tabular-corpus",
        "name": config["name"],
        "category": config["category"],
        "claim_ceiling": config["claim_ceiling"],
        "split": config_key,
        "source_split": config_key,
        "benchmark_split": benchmark_split,
        "config_path": str(config_path),
        "config_sha256": file_sha256(config_path),
        "selection": config["selection"],
        "items": manifest_items,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "config" / "tabular-corpus-v1.json",
    )
    parser.add_argument(
        "--split",
        choices=("development", "public-validation"),
        default="development",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "corpora" / "tabular-development-v1",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPOSITORY / "corpora" / "_download-cache" / "uci-tabular-v1",
    )
    parser.add_argument("--allow-public-validation", action="store_true")
    args = parser.parse_args()
    print(
        build(
            args.config,
            args.split,
            args.output,
            args.cache,
            args.allow_public_validation,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
