#!/usr/bin/env python3
"""Build deterministic source-code and Wikimedia development corpus items."""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import struct
import tarfile
import tempfile
from typing import Any, BinaryIO, Iterable, Optional
import xml.etree.ElementTree as ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_RULES = REPOSITORY / "config" / "text-source-path-rules-v1.json"
SOURCE_MAGIC = b"AXSCB1\n"
WIKIMEDIA_MAGIC = b"AXWKT1\n"
U64 = struct.Struct("<Q")
SHA256_BYTES = 32
CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def repository_reference(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY).as_posix()
    except ValueError:
        return resolved.name


def _validated_member_path(member: tarfile.TarInfo) -> tuple[str, ...]:
    raw_name = member.name.rstrip("/") if member.isdir() else member.name
    if not raw_name or raw_name.startswith("/") or "\\" in raw_name:
        raise ValueError(f"unsafe archive path: {member.name!r}")
    raw_parts = raw_name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"unsafe archive path: {member.name!r}")
    try:
        encoded = raw_name.encode("utf-8", errors="strict")
        if encoded.decode("utf-8", errors="strict") != raw_name:
            raise UnicodeError("path does not round-trip")
    except UnicodeError as error:
        raise ValueError(f"archive path is not strict UTF-8: {member.name!r}") from error
    normalized = PurePosixPath(*raw_parts).as_posix()
    if normalized != raw_name:
        raise ValueError(f"archive path normalization changed bytes: {member.name!r}")
    return tuple(raw_parts)


def _safe_tar_members(archive: tarfile.TarFile) -> list[tuple[tarfile.TarInfo, tuple[str, ...]]]:
    members: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    exact_paths: set[str] = set()
    casefold_paths: dict[str, str] = {}
    roots: set[str] = set()
    for member in archive.getmembers():
        parts = _validated_member_path(member)
        normalized = "/".join(parts)
        if normalized in exact_paths:
            raise ValueError(f"duplicate archive path: {normalized}")
        exact_paths.add(normalized)
        folded = normalized.casefold()
        previous = casefold_paths.get(folded)
        if previous is not None and previous != normalized:
            raise ValueError(f"case-fold archive collision: {previous} vs {normalized}")
        casefold_paths[folded] = normalized
        roots.add(parts[0])
        if member.issym() or member.islnk():
            raise ValueError(f"archive links are forbidden: {normalized}")
        if not member.isdir() and not member.isreg():
            raise ValueError(f"non-regular archive member is forbidden: {normalized}")
        members.append((member, parts))
    if len(roots) != 1:
        raise ValueError("source archive must contain exactly one top-level directory")
    root = next(iter(roots))
    if any(member.isreg() and len(parts) < 2 for member, parts in members):
        raise ValueError(f"regular file appears at archive root instead of under {root}")
    return members


def _is_selected_source(
    relative: str,
    source_id: str,
    rules: dict[str, Any],
) -> bool:
    if not any(relative.endswith(extension) for extension in rules["selected_extensions"]):
        return False
    parts = relative.split("/")
    excluded_segments = set(rules["excluded_segments"])
    if any(part in excluded_segments for part in parts):
        return False
    for prefix in rules["project_excluded_prefixes"].get(source_id, []):
        if relative == prefix or relative.startswith(prefix + "/"):
            return False
    return True


def _manifest_source_entry(path_bytes: bytes, size: int, digest: bytes) -> bytes:
    return U64.pack(len(path_bytes)) + path_bytes + U64.pack(size) + digest


def build_source_bundle(
    *,
    archive_path: Path,
    destination: Path,
    source: dict[str, Any],
    rules_path: Path = DEFAULT_RULES,
) -> dict[str, Any]:
    if destination.exists():
        raise ValueError(f"refusing to replace source bundle: {destination}")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    maximum_bytes = int(rules["maximum_bundle_bytes"])
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, mode="r:*") as archive:
        members = _safe_tar_members(archive)
        selected: list[tuple[bytes, str, tarfile.TarInfo]] = []
        for member, parts in members:
            if not member.isreg():
                continue
            relative = "/".join(parts[1:])
            if _is_selected_source(relative, source["id"], rules):
                selected.append((relative.encode("utf-8"), relative, member))
        selected.sort(key=lambda row: row[0])
        if not selected:
            raise ValueError("source selection produced no files")

        fixed_bytes = len(SOURCE_MAGIC) + U64.size + SHA256_BYTES
        retained: list[tuple[bytes, str, tarfile.TarInfo]] = []
        framed_bytes = fixed_bytes
        for path_bytes, relative, member in selected:
            record_bytes = U64.size + len(path_bytes) + U64.size + member.size
            if framed_bytes + record_bytes > maximum_bytes:
                break
            retained.append((path_bytes, relative, member))
            framed_bytes += record_bytes
        if not retained:
            raise ValueError("first selected source file exceeds the bundle byte cap")

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
        )
        temporary = Path(temporary_name)
        items: list[dict[str, Any]] = []
        manifest_digest = hashlib.sha256()
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(SOURCE_MAGIC)
                output.write(U64.pack(len(retained)))
                for path_bytes, relative, member in retained:
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError(f"unable to read selected member: {relative}")
                    output.write(U64.pack(len(path_bytes)))
                    output.write(path_bytes)
                    output.write(U64.pack(member.size))
                    content_digest = hashlib.sha256()
                    observed_size = 0
                    with extracted:
                        while chunk := extracted.read(CHUNK_SIZE):
                            output.write(chunk)
                            content_digest.update(chunk)
                            observed_size += len(chunk)
                    if observed_size != member.size:
                        raise ValueError(f"archive member size changed while reading: {relative}")
                    digest_bytes = content_digest.digest()
                    manifest_digest.update(
                        _manifest_source_entry(path_bytes, member.size, digest_bytes)
                    )
                    items.append(
                        {
                            "path": relative,
                            "size_bytes": member.size,
                            "sha256": content_digest.hexdigest(),
                        }
                    )
                output.write(manifest_digest.digest())
                output.flush()
            if temporary.stat().st_size != framed_bytes:
                raise ValueError("source bundle framing byte count mismatch")
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    return {
        "schema_version": 1,
        "format": "source-bundle-v1",
        "magic_hex": SOURCE_MAGIC.hex(),
        "source_id": source["id"],
        "archive_path": archive_path.name,
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": file_digest(archive_path),
        "rules_path": repository_reference(rules_path),
        "rules_sha256": file_digest(rules_path),
        "selected_file_count": len(selected),
        "retained_file_count": len(items),
        "truncated_at_byte_cap": len(items) != len(selected),
        "bundle_path": destination.name,
        "bundle_size_bytes": destination.stat().st_size,
        "bundle_sha256": file_digest(destination),
        "ordered_manifest_sha256": manifest_digest.hexdigest(),
        "items": items,
    }


class _RejectingXMLReader:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.tail = b""

    def read(self, size: int = -1) -> bytes:
        chunk = self.source.read(size)
        lowered = (self.tail + chunk).lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ValueError("XML document type and entity declarations are forbidden")
        self.tail = lowered[-16:]
        return chunk


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _required_text(element: ElementTree.Element, name: str) -> str:
    children = _direct_children(element, name)
    if len(children) != 1 or children[0].text is None:
        raise ValueError(f"Wikimedia page lacks exactly one {name}")
    return children[0].text


def _manifest_wikimedia_entry(
    page_id: int,
    revision_id: int,
    title_bytes: bytes,
    text_bytes: bytes,
) -> bytes:
    return (
        U64.pack(page_id)
        + U64.pack(revision_id)
        + U64.pack(len(title_bytes))
        + title_bytes
        + U64.pack(len(text_bytes))
        + hashlib.sha256(text_bytes).digest()
    )


def _page_record(
    page: ElementTree.Element,
) -> Optional[tuple[int, int, bytes, bytes]]:
    if _required_text(page, "ns") != "0" or _direct_children(page, "redirect"):
        return None
    page_id = int(_required_text(page, "id"))
    title_bytes = _required_text(page, "title").encode("utf-8", errors="strict")
    revisions = _direct_children(page, "revision")
    if not revisions:
        return None
    revision = revisions[-1]
    revision_id = int(_required_text(revision, "id"))
    texts = _direct_children(revision, "text")
    if len(texts) != 1 or texts[0].text is None or texts[0].text == "":
        return None
    text_bytes = texts[0].text.encode("utf-8", errors="strict")
    return page_id, revision_id, title_bytes, text_bytes


def build_wikimedia_bundle(
    *,
    archive_path: Path,
    destination: Path,
    source: dict[str, Any],
    maximum_bytes: int = 67_108_864,
) -> dict[str, Any]:
    if destination.exists():
        raise ValueError(f"refusing to replace Wikimedia bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    temporary = Path(temporary_name)
    items: list[dict[str, Any]] = []
    manifest_digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "w+b") as output:
            output.write(WIKIMEDIA_MAGIC)
            output.write(U64.pack(0))
            with bz2.BZ2File(archive_path, "rb") as compressed:
                reader = _RejectingXMLReader(compressed)
                context: Iterable[tuple[str, ElementTree.Element]] = ElementTree.iterparse(
                    reader, events=("end",)
                )
                for _, element in context:
                    if _local_name(element.tag) != "page":
                        continue
                    record = _page_record(element)
                    if record is not None:
                        page_id, revision_id, title_bytes, text_bytes = record
                        encoded = (
                            U64.pack(page_id)
                            + U64.pack(revision_id)
                            + U64.pack(len(title_bytes))
                            + title_bytes
                            + U64.pack(len(text_bytes))
                            + text_bytes
                        )
                        if output.tell() + len(encoded) + SHA256_BYTES > maximum_bytes:
                            element.clear()
                            break
                        output.write(encoded)
                        text_sha256 = hashlib.sha256(text_bytes).hexdigest()
                        manifest_digest.update(
                            _manifest_wikimedia_entry(
                                page_id, revision_id, title_bytes, text_bytes
                            )
                        )
                        items.append(
                            {
                                "page_id": page_id,
                                "revision_id": revision_id,
                                "title": title_bytes.decode("utf-8"),
                                "title_sha256": hashlib.sha256(title_bytes).hexdigest(),
                                "text_size_bytes": len(text_bytes),
                                "text_sha256": text_sha256,
                            }
                        )
                    element.clear()
            if not items:
                raise ValueError("Wikimedia selection produced no pages")
            output.write(manifest_digest.digest())
            output.seek(len(WIKIMEDIA_MAGIC))
            output.write(U64.pack(len(items)))
            output.flush()
        if temporary.stat().st_size > maximum_bytes:
            raise ValueError("Wikimedia bundle exceeded its byte cap")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "schema_version": 1,
        "format": "wikimedia-revision-text-v1",
        "magic_hex": WIKIMEDIA_MAGIC.hex(),
        "source_id": source["id"],
        "dump_date": source["dump_date"],
        "archive_path": archive_path.name,
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": file_digest(archive_path),
        "retained_page_count": len(items),
        "bundle_path": destination.name,
        "bundle_size_bytes": destination.stat().st_size,
        "bundle_sha256": file_digest(destination),
        "ordered_manifest_sha256": manifest_digest.hexdigest(),
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="kind", required=True)

    source_parser = subparsers.add_parser("source")
    source_parser.add_argument("--archive", type=Path, required=True)
    source_parser.add_argument("--source-id", required=True)
    source_parser.add_argument("--output", type=Path, required=True)
    source_parser.add_argument("--manifest", type=Path, required=True)
    source_parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)

    wiki_parser = subparsers.add_parser("wikimedia")
    wiki_parser.add_argument("--archive", type=Path, required=True)
    wiki_parser.add_argument("--source-id", required=True)
    wiki_parser.add_argument("--dump-date", required=True)
    wiki_parser.add_argument("--output", type=Path, required=True)
    wiki_parser.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if args.kind == "source":
        manifest = build_source_bundle(
            archive_path=args.archive,
            destination=args.output,
            source={"id": args.source_id},
            rules_path=args.rules,
        )
    else:
        manifest = build_wikimedia_bundle(
            archive_path=args.archive,
            destination=args.output,
            source={"id": args.source_id, "dump_date": args.dump_date},
        )
    write_json_atomic(args.manifest, manifest)
    print(args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
