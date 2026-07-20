#!/usr/bin/env python3
"""Exact bounded record-neighborhood transform for text/source experiments."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from pathlib import Path
import struct
from typing import Any, Final


SOURCE_MAGIC: Final = b"AXSCB1\n"
WIKIMEDIA_MAGIC: Final = b"AXWKT1\n"
TRANSFORM_MAGIC: Final = b"AXRN1\0"
HEADER: Final = struct.Struct("<6sBQQ32s")
U64: Final = struct.Struct("<Q")
SOURCE_KIND: Final = 1
WIKIMEDIA_KIND: Final = 2
MAX_RECORDS: Final = 1_000_000
MAX_NAME_BYTES: Final = 1024 * 1024
MAX_U64: Final = (1 << 64) - 1
WINDOW_BYTES: Final = 48
MAX_SAMPLE_WINDOWS: Final = 64
HASH_PERSON: Final = b"AXRN-W1"
MINHASH_SEEDS: Final = (
    0x243F6A8885A308D3,
    0x13198A2E03707344,
    0xA4093822299F31D0,
    0x082EFA98EC4E6C89,
)


def put_varint(output: bytearray, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_U64:
        raise ValueError("record-neighborhood varint is outside uint64")
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)


def get_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("record-neighborhood varint is truncated")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            if shift > 0 and byte == 0:
                raise ValueError("record-neighborhood varint is overlong")
            if value > MAX_U64:
                raise ValueError("record-neighborhood varint overflows uint64")
            return value, offset
    raise ValueError("record-neighborhood varint is overlong")


def zigzag_encode(value: int) -> int:
    if not -(1 << 63) <= value <= (1 << 63) - 1:
        raise ValueError("record-neighborhood signed delta is outside int64")
    return (value << 1) ^ (value >> 63)


def zigzag_decode(value: int) -> int:
    decoded = (value >> 1) ^ -(value & 1)
    if not -(1 << 63) <= decoded <= (1 << 63) - 1:
        raise ValueError("record-neighborhood signed delta is outside int64")
    return decoded


def take(data: bytes, offset: int, size: int, label: str) -> tuple[bytes, int]:
    if size < 0 or offset < 0 or size > len(data) - offset:
        raise ValueError(f"record-neighborhood {label} is truncated")
    return data[offset : offset + size], offset + size


def common_prefix(left: bytes, right: bytes) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def extension(path: bytes) -> bytes:
    name = path.rsplit(b"/", 1)[-1]
    dot = name.rfind(b".")
    if dot <= 0 or dot == len(name) - 1:
        return b""
    return name[dot:].lower()


def namespace(title: bytes) -> bytes:
    marker = title.find(b":")
    return title[:marker].lower() if 0 < marker <= 64 else b""


def sample_offsets(size: int) -> list[int]:
    if size < 0:
        raise ValueError("record-neighborhood content size is invalid")
    if size <= WINDOW_BYTES:
        return [0]
    maximum = size - WINDOW_BYTES
    count = min(MAX_SAMPLE_WINDOWS, maximum // WINDOW_BYTES + 2)
    if count == 1:
        return [0]
    return [index * maximum // (count - 1) for index in range(count)]


def window_hashes(content: bytes) -> tuple[int, ...]:
    values = {
        int.from_bytes(
            hashlib.blake2b(
                content[offset : offset + WINDOW_BYTES],
                digest_size=8,
                person=HASH_PERSON,
            ).digest(),
            "little",
        )
        for offset in sample_offsets(len(content))
    }
    return tuple(sorted(values))


def mix64(value: int) -> int:
    value = (value ^ (value >> 30)) * 0xBF58476D1CE4E5B9 & MAX_U64
    value = (value ^ (value >> 27)) * 0x94D049BB133111EB & MAX_U64
    return value ^ (value >> 31)


def record_order(records: list[tuple[bytes, bytes]]) -> list[int]:
    fingerprints = [window_hashes(content) for _record_class, content in records]
    frequencies: Counter[int] = Counter(
        fingerprint for row in fingerprints for fingerprint in row
    )
    maximum_frequency = max(2, (len(records) + 99) // 100)

    def key(index: int) -> tuple[Any, ...]:
        record_class, content = records[index]
        candidates = tuple(
            fingerprint
            for fingerprint in fingerprints[index]
            if 2 <= frequencies[fingerprint] <= maximum_frequency
        )
        if not candidates:
            candidates = fingerprints[index]
        signature = tuple(
            min((mix64(value ^ seed) for value in candidates), default=MAX_U64)
            for seed in MINHASH_SEEDS
        )
        return (record_class, *signature, len(content).bit_length(), index)

    return sorted(range(len(records)), key=key)


def parse_source(data: bytes) -> tuple[list[tuple[bytes, bytes]], bytes]:
    if not data.startswith(SOURCE_MAGIC) or len(data) < len(SOURCE_MAGIC) + 40:
        raise ValueError("record-neighborhood source bundle header is invalid")
    offset = len(SOURCE_MAGIC)
    count = U64.unpack_from(data, offset)[0]
    offset += U64.size
    if count > MAX_RECORDS:
        raise ValueError("record-neighborhood source record count exceeds limit")
    records = []
    previous = b""
    for _ in range(count):
        if offset + U64.size > len(data):
            raise ValueError("record-neighborhood source path size is truncated")
        path_size = U64.unpack_from(data, offset)[0]
        offset += U64.size
        if path_size == 0 or path_size > MAX_NAME_BYTES:
            raise ValueError("record-neighborhood source path size is invalid")
        path, offset = take(data, offset, path_size, "source path")
        try:
            path.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("record-neighborhood source path is not UTF-8") from error
        if path <= previous:
            raise ValueError("record-neighborhood source paths are not sorted")
        previous = path
        if offset + U64.size > len(data):
            raise ValueError("record-neighborhood source content size is truncated")
        content_size = U64.unpack_from(data, offset)[0]
        offset += U64.size
        content, offset = take(data, offset, content_size, "source content")
        records.append((path, content))
    manifest, offset = take(data, offset, 32, "source manifest")
    if offset != len(data):
        raise ValueError("record-neighborhood source bundle has trailing bytes")
    return records, manifest


def parse_wikimedia(
    data: bytes,
) -> tuple[list[tuple[int, int, bytes, bytes]], bytes]:
    if not data.startswith(WIKIMEDIA_MAGIC) or len(data) < len(WIKIMEDIA_MAGIC) + 40:
        raise ValueError("record-neighborhood Wikimedia bundle header is invalid")
    offset = len(WIKIMEDIA_MAGIC)
    count = U64.unpack_from(data, offset)[0]
    offset += U64.size
    if count > MAX_RECORDS:
        raise ValueError("record-neighborhood Wikimedia record count exceeds limit")
    records = []
    for _ in range(count):
        if offset + 3 * U64.size > len(data):
            raise ValueError("record-neighborhood Wikimedia metadata is truncated")
        page_id, revision_id, title_size = struct.unpack_from("<QQQ", data, offset)
        offset += 3 * U64.size
        if title_size > MAX_NAME_BYTES:
            raise ValueError("record-neighborhood Wikimedia title is too large")
        title, offset = take(data, offset, title_size, "Wikimedia title")
        try:
            title.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("record-neighborhood Wikimedia title is not UTF-8") from error
        if offset + U64.size > len(data):
            raise ValueError("record-neighborhood Wikimedia text size is truncated")
        text_size = U64.unpack_from(data, offset)[0]
        offset += U64.size
        text, offset = take(data, offset, text_size, "Wikimedia text")
        records.append((page_id, revision_id, title, text))
    manifest, offset = take(data, offset, 32, "Wikimedia manifest")
    if offset != len(data):
        raise ValueError("record-neighborhood Wikimedia bundle has trailing bytes")
    return records, manifest


def encode_order(order: list[int]) -> bytes:
    output = bytearray()
    previous = 0
    for index in order:
        put_varint(output, zigzag_encode(index - previous))
        previous = index
    return bytes(output)


def decode_order(data: bytes, count: int) -> list[int]:
    order = []
    offset = 0
    previous = 0
    for _ in range(count):
        delta, offset = get_varint(data, offset)
        index = previous + zigzag_decode(delta)
        if not 0 <= index < count:
            raise ValueError("record-neighborhood permutation index is invalid")
        order.append(index)
        previous = index
    if offset != len(data) or len(set(order)) != count:
        raise ValueError("record-neighborhood permutation is not canonical")
    return order


def assemble(
    *,
    kind: int,
    original: bytes,
    count: int,
    manifest: bytes,
    metadata: bytes,
    order: list[int],
    payload: bytes,
) -> bytes:
    order_bytes = encode_order(order)
    output = bytearray(
        HEADER.pack(
            TRANSFORM_MAGIC,
            kind,
            len(original),
            count,
            hashlib.sha256(original).digest(),
        )
    )
    output.extend(manifest)
    put_varint(output, len(metadata))
    put_varint(output, len(order_bytes))
    put_varint(output, len(payload))
    output.extend(metadata)
    output.extend(order_bytes)
    output.extend(payload)
    return bytes(output)


def encode_source(data: bytes) -> bytes:
    records, manifest = parse_source(data)
    metadata = bytearray()
    previous = b""
    ordering_records = []
    for path, content in records:
        prefix = common_prefix(previous, path)
        suffix = path[prefix:]
        put_varint(metadata, prefix)
        put_varint(metadata, len(suffix))
        metadata.extend(suffix)
        put_varint(metadata, len(content))
        ordering_records.append((extension(path), content))
        previous = path
    order = record_order(ordering_records)
    payload = b"".join(records[index][1] for index in order)
    return assemble(
        kind=SOURCE_KIND,
        original=data,
        count=len(records),
        manifest=manifest,
        metadata=bytes(metadata),
        order=order,
        payload=payload,
    )


def encode_wikimedia(data: bytes) -> bytes:
    records, manifest = parse_wikimedia(data)
    metadata = bytearray()
    previous_page = 0
    previous_revision = 0
    previous_title = b""
    ordering_records = []
    for page_id, revision_id, title, text in records:
        put_varint(metadata, zigzag_encode(page_id - previous_page))
        put_varint(metadata, zigzag_encode(revision_id - previous_revision))
        prefix = common_prefix(previous_title, title)
        suffix = title[prefix:]
        put_varint(metadata, prefix)
        put_varint(metadata, len(suffix))
        metadata.extend(suffix)
        put_varint(metadata, len(text))
        ordering_records.append((namespace(title), text))
        previous_page = page_id
        previous_revision = revision_id
        previous_title = title
    order = record_order(ordering_records)
    payload = b"".join(records[index][3] for index in order)
    return assemble(
        kind=WIKIMEDIA_KIND,
        original=data,
        count=len(records),
        manifest=manifest,
        metadata=bytes(metadata),
        order=order,
        payload=payload,
    )


def encode(data: bytes) -> bytes:
    if data.startswith(SOURCE_MAGIC):
        return encode_source(data)
    if data.startswith(WIKIMEDIA_MAGIC):
        return encode_wikimedia(data)
    raise ValueError("record-neighborhood input framing is unsupported")


def decode(data: bytes, *, max_output_size: int | None = None) -> bytes:
    if len(data) < HEADER.size + 32:
        raise ValueError("record-neighborhood transform header is truncated")
    magic, kind, original_size, count, expected_digest = HEADER.unpack_from(data)
    if magic != TRANSFORM_MAGIC or kind not in {SOURCE_KIND, WIKIMEDIA_KIND}:
        raise ValueError("record-neighborhood transform identity is invalid")
    if count > MAX_RECORDS:
        raise ValueError("record-neighborhood transformed record count exceeds limit")
    if max_output_size is not None:
        if isinstance(max_output_size, bool) or not isinstance(max_output_size, int) or max_output_size < 0:
            raise ValueError("record-neighborhood maximum output size is invalid")
        if original_size > max_output_size:
            raise ValueError("record-neighborhood declared output exceeds limit")
    offset = HEADER.size
    manifest, offset = take(data, offset, 32, "manifest")
    metadata_size, offset = get_varint(data, offset)
    order_size, offset = get_varint(data, offset)
    payload_size, offset = get_varint(data, offset)
    metadata, offset = take(data, offset, metadata_size, "metadata")
    order_bytes, offset = take(data, offset, order_size, "permutation")
    payload, offset = take(data, offset, payload_size, "payload")
    if offset != len(data):
        raise ValueError("record-neighborhood transform has trailing bytes")
    order = decode_order(order_bytes, count)
    metadata_offset = 0
    projected_size = (
        len(SOURCE_MAGIC) if kind == SOURCE_KIND else len(WIKIMEDIA_MAGIC)
    ) + U64.size + 32
    source_meta: list[tuple[bytes, int]] = []
    wiki_meta: list[tuple[int, int, bytes, int]] = []
    if kind == SOURCE_KIND:
        previous = b""
        for _ in range(count):
            prefix, metadata_offset = get_varint(metadata, metadata_offset)
            suffix_size, metadata_offset = get_varint(metadata, metadata_offset)
            if prefix > len(previous) or suffix_size > MAX_NAME_BYTES:
                raise ValueError("record-neighborhood source path metadata is invalid")
            suffix, metadata_offset = take(metadata, metadata_offset, suffix_size, "path suffix")
            path = previous[:prefix] + suffix
            if not path or path <= previous or prefix != common_prefix(previous, path):
                raise ValueError("record-neighborhood source path is noncanonical")
            try:
                path.decode("utf-8", errors="strict")
            except UnicodeError as error:
                raise ValueError("record-neighborhood source path is not UTF-8") from error
            content_size, metadata_offset = get_varint(metadata, metadata_offset)
            projected_size += 2 * U64.size + len(path) + content_size
            if projected_size > original_size:
                raise ValueError("record-neighborhood source output exceeds declaration")
            source_meta.append((path, content_size))
            previous = path
        record_classes = [extension(path) for path, _size in source_meta]
    else:
        page_id = 0
        revision_id = 0
        previous_title = b""
        for _ in range(count):
            page_delta, metadata_offset = get_varint(metadata, metadata_offset)
            revision_delta, metadata_offset = get_varint(metadata, metadata_offset)
            page_id += zigzag_decode(page_delta)
            revision_id += zigzag_decode(revision_delta)
            if not 0 <= page_id <= MAX_U64 or not 0 <= revision_id <= MAX_U64:
                raise ValueError("record-neighborhood Wikimedia ID is invalid")
            prefix, metadata_offset = get_varint(metadata, metadata_offset)
            suffix_size, metadata_offset = get_varint(metadata, metadata_offset)
            if prefix > len(previous_title) or suffix_size > MAX_NAME_BYTES:
                raise ValueError("record-neighborhood Wikimedia title metadata is invalid")
            suffix, metadata_offset = take(metadata, metadata_offset, suffix_size, "title suffix")
            title = previous_title[:prefix] + suffix
            if prefix != common_prefix(previous_title, title):
                raise ValueError("record-neighborhood Wikimedia title is noncanonical")
            try:
                title.decode("utf-8", errors="strict")
            except UnicodeError as error:
                raise ValueError("record-neighborhood Wikimedia title is not UTF-8") from error
            text_size, metadata_offset = get_varint(metadata, metadata_offset)
            projected_size += 4 * U64.size + len(title) + text_size
            if projected_size > original_size:
                raise ValueError("record-neighborhood Wikimedia output exceeds declaration")
            wiki_meta.append((page_id, revision_id, title, text_size))
            previous_title = title
        record_classes = [namespace(title) for _page, _revision, title, _size in wiki_meta]
    if metadata_offset != len(metadata) or projected_size != original_size:
        raise ValueError("record-neighborhood metadata differs from declaration")
    contents: list[bytes | None] = [None] * count
    payload_offset = 0
    sizes = [row[1] for row in source_meta] if kind == SOURCE_KIND else [row[3] for row in wiki_meta]
    for index in order:
        content, payload_offset = take(payload, payload_offset, sizes[index], "record payload")
        contents[index] = content
    if payload_offset != len(payload) or any(content is None for content in contents):
        raise ValueError("record-neighborhood payload differs from permutation")
    complete_contents: list[bytes] = []
    for restored_content in contents:
        if restored_content is None:
            raise ValueError("record-neighborhood payload differs from permutation")
        complete_contents.append(restored_content)
    ordering_records = [
        (record_classes[index], complete_contents[index]) for index in range(count)
    ]
    if order != record_order(ordering_records):
        raise ValueError("record-neighborhood permutation is noncanonical")
    output = bytearray(SOURCE_MAGIC if kind == SOURCE_KIND else WIKIMEDIA_MAGIC)
    output.extend(U64.pack(count))
    if kind == SOURCE_KIND:
        for index, (path, content_size) in enumerate(source_meta):
            content = complete_contents[index]
            if len(content) != content_size:
                raise ValueError("record-neighborhood source content differs")
            output.extend(U64.pack(len(path)))
            output.extend(path)
            output.extend(U64.pack(content_size))
            output.extend(content)
    else:
        for index, (page_id, revision_id, title, text_size) in enumerate(wiki_meta):
            text = complete_contents[index]
            if len(text) != text_size:
                raise ValueError("record-neighborhood Wikimedia text differs")
            output.extend(struct.pack("<QQQ", page_id, revision_id, len(title)))
            output.extend(title)
            output.extend(U64.pack(text_size))
            output.extend(text)
    output.extend(manifest)
    restored = bytes(output)
    if len(restored) != original_size or hashlib.sha256(restored).digest() != expected_digest:
        raise ValueError("record-neighborhood restored identity differs")
    return restored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    encode_parser = subparsers.add_parser("encode")
    encode_parser.add_argument("source", type=Path)
    encode_parser.add_argument("output", type=Path)
    decode_parser = subparsers.add_parser("decode")
    decode_parser.add_argument("source", type=Path)
    decode_parser.add_argument("output", type=Path)
    decode_parser.add_argument("--max-output-size", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "encode":
            args.output.write_bytes(encode(args.source.read_bytes()))
        else:
            args.output.write_bytes(
                decode(args.source.read_bytes(), max_output_size=args.max_output_size)
            )
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"record-neighborhood transform failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
