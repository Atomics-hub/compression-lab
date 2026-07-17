#!/usr/bin/env python3
"""Verify and receipt the completed text/source development acquisition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from typing import Any, BinaryIO


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_ACQUISITION = (
    REPOSITORY / "config" / "text-source-development-acquisition-v1.json"
)
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_RECEIPT = REPOSITORY / "runs" / "text-source-development-acquisition-v1.json"
SOURCE_MAGIC = b"AXSCB1\n"
WIKIMEDIA_MAGIC = b"AXWKT1\n"
U64 = struct.Struct("<Q")
CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def read_exact(source: BinaryIO, size: int, label: str) -> bytes:
    data = source.read(size)
    if len(data) != size:
        raise ValueError(f"truncated {label}")
    return data


def read_u64(source: BinaryIO, label: str) -> int:
    return U64.unpack(read_exact(source, U64.size, label))[0]


def hash_exact(source: BinaryIO, size: int, label: str) -> bytes:
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = source.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError(f"truncated {label}")
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.digest()


def verify_source_bundle(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_items = manifest["items"]
    manifest_digest = hashlib.sha256()
    previous_path: bytes = b""
    with path.open("rb") as source:
        if read_exact(source, len(SOURCE_MAGIC), "source magic") != SOURCE_MAGIC:
            raise ValueError(f"source magic mismatch: {path.name}")
        count = read_u64(source, "source record count")
        if count != len(expected_items):
            raise ValueError(f"source record count mismatch: {path.name}")
        for index, expected in enumerate(expected_items):
            path_size = read_u64(source, "source path size")
            if path_size > 1024 * 1024:
                raise ValueError("source path exceeds the verifier bound")
            path_bytes = read_exact(source, path_size, "source path")
            relative = path_bytes.decode("utf-8", errors="strict")
            if index and path_bytes <= previous_path:
                raise ValueError(f"source paths are not strictly bytewise ordered: {relative}")
            previous_path = path_bytes
            content_size = read_u64(source, "source content size")
            content_digest = hash_exact(source, content_size, "source content")
            if relative != expected["path"]:
                raise ValueError(f"source manifest path mismatch: {relative}")
            if content_size != expected["size_bytes"]:
                raise ValueError(f"source manifest size mismatch: {relative}")
            if content_digest.hex() != expected["sha256"]:
                raise ValueError(f"source manifest digest mismatch: {relative}")
            manifest_digest.update(
                U64.pack(len(path_bytes))
                + path_bytes
                + U64.pack(content_size)
                + content_digest
            )
        terminal = read_exact(source, 32, "source terminal manifest digest")
        if source.read(1):
            raise ValueError(f"trailing source bundle bytes: {path.name}")
    if terminal != manifest_digest.digest():
        raise ValueError(f"source terminal manifest digest mismatch: {path.name}")
    if terminal.hex() != manifest["ordered_manifest_sha256"]:
        raise ValueError(f"source ordered-manifest binding mismatch: {path.name}")
    return {"record_count": count, "ordered_manifest_sha256": terminal.hex()}


def verify_wikimedia_bundle(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_items = manifest["items"]
    manifest_digest = hashlib.sha256()
    with path.open("rb") as source:
        if read_exact(source, len(WIKIMEDIA_MAGIC), "Wikimedia magic") != WIKIMEDIA_MAGIC:
            raise ValueError(f"Wikimedia magic mismatch: {path.name}")
        count = read_u64(source, "Wikimedia record count")
        if count != len(expected_items):
            raise ValueError(f"Wikimedia record count mismatch: {path.name}")
        for expected in expected_items:
            page_id = read_u64(source, "page ID")
            revision_id = read_u64(source, "revision ID")
            title_size = read_u64(source, "title size")
            if title_size > 1024 * 1024:
                raise ValueError("Wikimedia title exceeds the verifier bound")
            title_bytes = read_exact(source, title_size, "title")
            title = title_bytes.decode("utf-8", errors="strict")
            text_size = read_u64(source, "revision text size")
            text_digest = hash_exact(source, text_size, "revision text")
            if page_id != expected["page_id"] or revision_id != expected["revision_id"]:
                raise ValueError(f"Wikimedia revision identity mismatch: {title}")
            if title != expected["title"]:
                raise ValueError(f"Wikimedia title mismatch: {title}")
            if hashlib.sha256(title_bytes).hexdigest() != expected["title_sha256"]:
                raise ValueError(f"Wikimedia title digest mismatch: {title}")
            if text_size != expected["text_size_bytes"]:
                raise ValueError(f"Wikimedia text size mismatch: {title}")
            if text_digest.hex() != expected["text_sha256"]:
                raise ValueError(f"Wikimedia text digest mismatch: {title}")
            manifest_digest.update(
                U64.pack(page_id)
                + U64.pack(revision_id)
                + U64.pack(len(title_bytes))
                + title_bytes
                + U64.pack(text_size)
                + text_digest
            )
        terminal = read_exact(source, 32, "Wikimedia terminal manifest digest")
        if source.read(1):
            raise ValueError(f"trailing Wikimedia bundle bytes: {path.name}")
    if terminal != manifest_digest.digest():
        raise ValueError(f"Wikimedia terminal manifest digest mismatch: {path.name}")
    if terminal.hex() != manifest["ordered_manifest_sha256"]:
        raise ValueError(f"Wikimedia ordered-manifest binding mismatch: {path.name}")
    return {"record_count": count, "ordered_manifest_sha256": terminal.hex()}


def git_blob_digest(commit: str, relative: str) -> str:
    content = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def verify(
    *,
    acquisition_path: Path,
    corpus: Path,
) -> dict[str, Any]:
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    aggregate_path = corpus / "manifest.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    if file_digest(aggregate_path) != acquisition["aggregate_manifest_sha256"]:
        raise ValueError("aggregate acquisition manifest digest mismatch")
    if aggregate["public_validation_accessed"] or acquisition["public_validation_accessed"]:
        raise ValueError("development receipt reports public-validation access")
    if aggregate["protocol_sha256"] != acquisition["protocol_sha256"]:
        raise ValueError("aggregate protocol digest mismatch")
    if aggregate["rules_sha256"] != acquisition["rules_sha256"]:
        raise ValueError("aggregate rule digest mismatch")
    commit = acquisition["acquisition_commit"]
    if git_blob_digest(commit, "config/text-source-category-protocol-v1.json") != acquisition[
        "protocol_sha256"
    ]:
        raise ValueError("historical acquisition protocol digest mismatch")
    if git_blob_digest(commit, "config/text-source-path-rules-v1.json") != acquisition[
        "rules_sha256"
    ]:
        raise ValueError("historical acquisition rule digest mismatch")
    toolchain = aggregate["toolchain"]
    if git_blob_digest(commit, "scripts/build-text-source-corpora.py") != toolchain[
        "builder_sha256"
    ]:
        raise ValueError("historical builder digest mismatch")
    if git_blob_digest(commit, "scripts/fetch-text-source-development.py") != toolchain[
        "fetcher_sha256"
    ]:
        raise ValueError("historical fetcher digest mismatch")

    expected_ids = {
        "cpython-3.14.6-source",
        "typescript-6.0.3-source",
        "rust-1.97.1-source",
        "llvm-22.1.8-source",
        "enwikibooks-20260701",
        "enwikinews-20260701",
        "enwikiversity-20260701",
    }
    if {row["source_id"] for row in aggregate["items"]} != expected_ids:
        raise ValueError("aggregate development source roster mismatch")

    receipt_items = []
    total_bytes = 0
    for aggregate_item in aggregate["items"]:
        manifest_path = corpus / aggregate_item["manifest_path"]
        bundle_path = corpus / aggregate_item["bundle_path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["source_id"] != aggregate_item["source_id"]:
            raise ValueError("item manifest source identity mismatch")
        if bundle_path.stat().st_size != aggregate_item["bundle_size_bytes"]:
            raise ValueError(f"bundle size mismatch: {bundle_path.name}")
        if file_digest(bundle_path) != aggregate_item["bundle_sha256"]:
            raise ValueError(f"bundle SHA-256 mismatch: {bundle_path.name}")
        if manifest["bundle_size_bytes"] != aggregate_item["bundle_size_bytes"]:
            raise ValueError(f"item/aggregate bundle size mismatch: {bundle_path.name}")
        if manifest["bundle_sha256"] != aggregate_item["bundle_sha256"]:
            raise ValueError(f"item/aggregate bundle digest mismatch: {bundle_path.name}")
        if manifest["archive_sha256"] != aggregate_item["archive_sha256"]:
            raise ValueError(f"item/aggregate archive digest mismatch: {bundle_path.name}")
        if aggregate_item["format"] == "source-bundle-v1":
            framing = verify_source_bundle(bundle_path, manifest)
            selected_count = manifest["selected_file_count"]
            truncated = manifest["truncated_at_byte_cap"]
        elif aggregate_item["format"] == "wikimedia-revision-text-v1":
            framing = verify_wikimedia_bundle(bundle_path, manifest)
            selected_count = manifest["retained_page_count"]
            truncated = None
        else:
            raise ValueError(f"unsupported development format: {aggregate_item['format']}")
        total_bytes += aggregate_item["bundle_size_bytes"]
        receipt_items.append(
            {
                **aggregate_item,
                "archive_size_bytes": manifest["archive_size_bytes"],
                "manifest_sha256": file_digest(manifest_path),
                "ordered_manifest_sha256": framing["ordered_manifest_sha256"],
                "record_count": framing["record_count"],
                "selected_record_count": selected_count,
                "truncated_at_byte_cap": truncated,
                "provenance": manifest["provenance"],
            }
        )

    return {
        "schema_version": 1,
        "name": acquisition["name"],
        "passed": True,
        "acquisition_commit": commit,
        "aggregate_manifest_sha256": acquisition["aggregate_manifest_sha256"],
        "protocol_sha256": acquisition["protocol_sha256"],
        "rules_sha256": acquisition["rules_sha256"],
        "public_validation_accessed": False,
        "attempts": acquisition["attempts"],
        "toolchain": toolchain,
        "item_count": len(receipt_items),
        "total_derived_bytes": total_bytes,
        "items": receipt_items,
        "claim_ceiling": acquisition["claim_ceiling"],
    }


def write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to replace acquisition receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(receipt, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition", type=Path, default=DEFAULT_ACQUISITION)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    try:
        receipt = verify(acquisition_path=args.acquisition, corpus=args.corpus)
        write_receipt(args.receipt, receipt)
    except (KeyError, OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"development verification failed: {error}") from error
    print(args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
