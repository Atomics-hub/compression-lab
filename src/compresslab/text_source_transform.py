"""Reversible structural transforms for text/source development experiments."""

from __future__ import annotations

import hashlib
import struct
from typing import Final


SOURCE_MAGIC: Final = b"AXSCB1\n"
WIKIMEDIA_MAGIC: Final = b"AXWKT1\n"
TRANSFORM_MAGIC: Final = b"AXTS1"
HEADER: Final = struct.Struct("<5sBQQ32s")
U64: Final = struct.Struct("<Q")
SOURCE_DEMUX: Final = 1
SOURCE_EXTENSION_LANES: Final = 2
WIKIMEDIA_DEMUX: Final = 3
MAX_RECORDS: Final = 1_000_000
MAX_PATH_BYTES: Final = 1024 * 1024
MAX_LANES: Final = 4096
MAX_U64: Final = (1 << 64) - 1


def _put_varint(output: bytearray, value: int) -> None:
    if value < 0 or value > MAX_U64:
        raise ValueError("text/source varint is outside uint64")
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)


def _get_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("text/source varint is truncated")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            if shift > 0 and byte == 0:
                raise ValueError("text/source varint is overlong")
            if value > MAX_U64:
                raise ValueError("text/source varint overflows uint64")
            return value, offset
    raise ValueError("text/source varint is overlong")


def _zigzag_encode(value: int) -> int:
    if value < -(1 << 63) or value > (1 << 63) - 1:
        raise ValueError("text/source signed delta is outside int64")
    return (value << 1) ^ (value >> 63)


def _zigzag_decode(value: int) -> int:
    decoded = (value >> 1) ^ -(value & 1)
    if decoded < -(1 << 63) or decoded > (1 << 63) - 1:
        raise ValueError("text/source signed delta is outside int64")
    return decoded


def _take(data: bytes, offset: int, size: int, label: str) -> tuple[bytes, int]:
    if size < 0 or offset < 0 or size > len(data) - offset:
        raise ValueError(f"text/source {label} is truncated")
    return data[offset : offset + size], offset + size


def _common_prefix(left: bytes, right: bytes) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def _extension(path: bytes) -> bytes:
    name = path.rsplit(b"/", 1)[-1]
    dot = name.rfind(b".")
    if dot <= 0 or dot == len(name) - 1:
        return b""
    return name[dot:].lower()


def _header(kind: int, original: bytes, records: int) -> bytearray:
    return bytearray(
        HEADER.pack(
            TRANSFORM_MAGIC,
            kind,
            len(original),
            records,
            hashlib.sha256(original).digest(),
        )
    )


def _parse_source(data: bytes) -> tuple[list[tuple[bytes, bytes]], bytes]:
    if not data.startswith(SOURCE_MAGIC) or len(data) < len(SOURCE_MAGIC) + 8 + 32:
        raise ValueError("source bundle header is invalid")
    offset = len(SOURCE_MAGIC)
    count = U64.unpack_from(data, offset)[0]
    offset += U64.size
    if count > MAX_RECORDS:
        raise ValueError("source bundle record count exceeds limit")
    records = []
    previous_path = b""
    for _ in range(count):
        if offset + U64.size > len(data):
            raise ValueError("source bundle path length is truncated")
        path_size = U64.unpack_from(data, offset)[0]
        offset += U64.size
        if path_size == 0 or path_size > MAX_PATH_BYTES:
            raise ValueError("source bundle path length is invalid")
        path, offset = _take(data, offset, path_size, "path")
        try:
            path.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("source bundle path is not UTF-8") from error
        if path <= previous_path:
            raise ValueError("source bundle paths are not strictly sorted")
        previous_path = path
        if offset + U64.size > len(data):
            raise ValueError("source bundle content length is truncated")
        content_size = U64.unpack_from(data, offset)[0]
        offset += U64.size
        content, offset = _take(data, offset, content_size, "content")
        records.append((path, content))
    manifest, offset = _take(data, offset, 32, "manifest digest")
    if offset != len(data):
        raise ValueError("source bundle has trailing bytes")
    return records, manifest


def encode_source(data: bytes, *, extension_lanes: bool) -> bytes:
    records, manifest = _parse_source(data)
    kind = SOURCE_EXTENSION_LANES if extension_lanes else SOURCE_DEMUX
    lane_names = (
        sorted({_extension(path) for path, _ in records})
        if extension_lanes and records
        else [b""]
    )
    if len(lane_names) > MAX_LANES:
        raise ValueError("source extension lane count exceeds limit")
    lane_index = {name: index for index, name in enumerate(lane_names)}
    metadata = bytearray()
    lane_payloads = [bytearray() for _ in lane_names]
    previous_path = b""
    for path, content in records:
        prefix = _common_prefix(previous_path, path)
        suffix = path[prefix:]
        lane = lane_index[_extension(path)] if extension_lanes else 0
        _put_varint(metadata, prefix)
        _put_varint(metadata, len(suffix))
        metadata.extend(suffix)
        _put_varint(metadata, len(content))
        _put_varint(metadata, lane)
        lane_payloads[lane].extend(content)
        previous_path = path

    output = _header(kind, data, len(records))
    output.extend(manifest)
    _put_varint(output, len(lane_names))
    for name in lane_names:
        _put_varint(output, len(name))
        output.extend(name)
    _put_varint(output, len(metadata))
    output.extend(metadata)
    for payload in lane_payloads:
        _put_varint(output, len(payload))
        output.extend(payload)
    return bytes(output)


def _decode_source(data: bytes, kind: int, count: int, original_size: int) -> bytes:
    offset = HEADER.size
    manifest, offset = _take(data, offset, 32, "source manifest digest")
    lane_count, offset = _get_varint(data, offset)
    if lane_count == 0 or lane_count > MAX_LANES:
        raise ValueError("text/source lane count is invalid")
    lane_names = []
    for _ in range(lane_count):
        size, offset = _get_varint(data, offset)
        if size > MAX_PATH_BYTES:
            raise ValueError("text/source lane name is too large")
        name, offset = _take(data, offset, size, "lane name")
        lane_names.append(name)
    if lane_names != sorted(set(lane_names)):
        raise ValueError("text/source lane names are not unique and sorted")
    if kind == SOURCE_DEMUX and lane_names != [b""]:
        raise ValueError("source demux must contain exactly one unnamed lane")

    metadata_size, offset = _get_varint(data, offset)
    metadata, offset = _take(data, offset, metadata_size, "source metadata")
    metadata_offset = 0
    records: list[tuple[bytes, int, int]] = []
    previous_path = b""
    lane_totals = [0] * lane_count
    projected_size = len(SOURCE_MAGIC) + U64.size + 32
    for _ in range(count):
        prefix, metadata_offset = _get_varint(metadata, metadata_offset)
        suffix_size, metadata_offset = _get_varint(metadata, metadata_offset)
        if prefix > len(previous_path) or suffix_size > MAX_PATH_BYTES:
            raise ValueError("text/source front-coded path is invalid")
        suffix, metadata_offset = _take(
            metadata, metadata_offset, suffix_size, "path suffix"
        )
        path = previous_path[:prefix] + suffix
        if not path or len(path) > MAX_PATH_BYTES or path <= previous_path:
            raise ValueError("text/source reconstructed path order is invalid")
        if prefix != _common_prefix(previous_path, path):
            raise ValueError("text/source front-coded path is noncanonical")
        try:
            path.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("text/source reconstructed path is not UTF-8") from error
        content_size, metadata_offset = _get_varint(metadata, metadata_offset)
        lane, metadata_offset = _get_varint(metadata, metadata_offset)
        if lane >= lane_count:
            raise ValueError("text/source lane index is invalid")
        if kind == SOURCE_EXTENSION_LANES and lane_names[lane] != _extension(path):
            raise ValueError("text/source lane does not match path extension")
        if content_size > MAX_U64 - lane_totals[lane]:
            raise ValueError("text/source lane size overflows uint64")
        projected_size += 2 * U64.size + len(path) + content_size
        if projected_size > original_size:
            raise ValueError("text/source metadata exceeds declared output size")
        lane_totals[lane] += content_size
        records.append((path, content_size, lane))
        previous_path = path
    if kind == SOURCE_EXTENSION_LANES:
        expected_lane_names = (
            sorted({_extension(path) for path, _content_size, _lane in records})
            if records
            else [b""]
        )
        if lane_names != expected_lane_names:
            raise ValueError("source extension lane roster differs from records")
    if metadata_offset != len(metadata):
        raise ValueError("text/source metadata has trailing bytes")
    if projected_size != original_size:
        raise ValueError("text/source metadata differs from declared output size")

    lanes = []
    for expected_size in lane_totals:
        observed_size, offset = _get_varint(data, offset)
        if observed_size != expected_size:
            raise ValueError("text/source lane size differs from metadata")
        payload, offset = _take(data, offset, observed_size, "lane payload")
        lanes.append(payload)
    if offset != len(data):
        raise ValueError("text/source transform has trailing bytes")

    lane_offsets = [0] * lane_count
    output = bytearray(SOURCE_MAGIC)
    output.extend(U64.pack(count))
    for path, content_size, lane in records:
        lane_offset = lane_offsets[lane]
        content = lanes[lane][lane_offset : lane_offset + content_size]
        if len(content) != content_size:
            raise ValueError("text/source lane content is truncated")
        lane_offsets[lane] += content_size
        output.extend(U64.pack(len(path)))
        output.extend(path)
        output.extend(U64.pack(content_size))
        output.extend(content)
    output.extend(manifest)
    return bytes(output)


def _parse_wikimedia(data: bytes) -> tuple[list[tuple[int, int, bytes, bytes]], bytes]:
    if (
        not data.startswith(WIKIMEDIA_MAGIC)
        or len(data) < len(WIKIMEDIA_MAGIC) + 8 + 32
    ):
        raise ValueError("Wikimedia bundle header is invalid")
    offset = len(WIKIMEDIA_MAGIC)
    count = U64.unpack_from(data, offset)[0]
    offset += U64.size
    if count > MAX_RECORDS:
        raise ValueError("Wikimedia record count exceeds limit")
    records = []
    for _ in range(count):
        if offset + 3 * U64.size > len(data):
            raise ValueError("Wikimedia record metadata is truncated")
        page_id = U64.unpack_from(data, offset)[0]
        revision_id = U64.unpack_from(data, offset + U64.size)[0]
        title_size = U64.unpack_from(data, offset + 2 * U64.size)[0]
        offset += 3 * U64.size
        if title_size > MAX_PATH_BYTES:
            raise ValueError("Wikimedia title is too large")
        title, offset = _take(data, offset, title_size, "title")
        try:
            title.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("Wikimedia title is not UTF-8") from error
        if offset + U64.size > len(data):
            raise ValueError("Wikimedia text length is truncated")
        text_size = U64.unpack_from(data, offset)[0]
        offset += U64.size
        text, offset = _take(data, offset, text_size, "text")
        records.append((page_id, revision_id, title, text))
    manifest, offset = _take(data, offset, 32, "manifest digest")
    if offset != len(data):
        raise ValueError("Wikimedia bundle has trailing bytes")
    return records, manifest


def encode_wikimedia(data: bytes) -> bytes:
    records, manifest = _parse_wikimedia(data)
    metadata = bytearray()
    titles = bytearray()
    texts = bytearray()
    previous_page = 0
    previous_revision = 0
    previous_title = b""
    for page_id, revision_id, title, text in records:
        _put_varint(metadata, _zigzag_encode(page_id - previous_page))
        _put_varint(metadata, _zigzag_encode(revision_id - previous_revision))
        prefix = _common_prefix(previous_title, title)
        suffix = title[prefix:]
        _put_varint(metadata, prefix)
        _put_varint(metadata, len(suffix))
        _put_varint(metadata, len(text))
        titles.extend(suffix)
        texts.extend(text)
        previous_page = page_id
        previous_revision = revision_id
        previous_title = title

    output = _header(WIKIMEDIA_DEMUX, data, len(records))
    output.extend(manifest)
    _put_varint(output, len(metadata))
    _put_varint(output, len(titles))
    _put_varint(output, len(texts))
    output.extend(metadata)
    output.extend(titles)
    output.extend(texts)
    return bytes(output)


def _decode_wikimedia(data: bytes, count: int, original_size: int) -> bytes:
    offset = HEADER.size
    manifest, offset = _take(data, offset, 32, "Wikimedia manifest digest")
    metadata_size, offset = _get_varint(data, offset)
    titles_size, offset = _get_varint(data, offset)
    texts_size, offset = _get_varint(data, offset)
    metadata, offset = _take(data, offset, metadata_size, "Wikimedia metadata")
    titles, offset = _take(data, offset, titles_size, "Wikimedia titles")
    texts, offset = _take(data, offset, texts_size, "Wikimedia texts")
    if offset != len(data):
        raise ValueError("Wikimedia transform has trailing bytes")

    metadata_offset = 0
    title_offset = 0
    text_offset = 0
    page_id = 0
    revision_id = 0
    previous_title = b""
    projected_size = len(WIKIMEDIA_MAGIC) + U64.size + 32
    output = bytearray(WIKIMEDIA_MAGIC)
    output.extend(U64.pack(count))
    for _ in range(count):
        page_delta, metadata_offset = _get_varint(metadata, metadata_offset)
        revision_delta, metadata_offset = _get_varint(metadata, metadata_offset)
        prefix, metadata_offset = _get_varint(metadata, metadata_offset)
        suffix_size, metadata_offset = _get_varint(metadata, metadata_offset)
        text_size, metadata_offset = _get_varint(metadata, metadata_offset)
        page_id += _zigzag_decode(page_delta)
        revision_id += _zigzag_decode(revision_delta)
        if not 0 <= page_id <= MAX_U64 or not 0 <= revision_id <= MAX_U64:
            raise ValueError("Wikimedia reconstructed ID is outside uint64")
        if prefix > len(previous_title) or suffix_size > MAX_PATH_BYTES:
            raise ValueError("Wikimedia front-coded title is invalid")
        suffix, title_offset = _take(titles, title_offset, suffix_size, "title suffix")
        title = previous_title[:prefix] + suffix
        if prefix != _common_prefix(previous_title, title):
            raise ValueError("Wikimedia front-coded title is noncanonical")
        try:
            title.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("Wikimedia reconstructed title is not UTF-8") from error
        text, text_offset = _take(texts, text_offset, text_size, "text payload")
        projected_size += 4 * U64.size + len(title) + len(text)
        if projected_size > original_size:
            raise ValueError("Wikimedia metadata exceeds declared output size")
        output.extend(U64.pack(page_id))
        output.extend(U64.pack(revision_id))
        output.extend(U64.pack(len(title)))
        output.extend(title)
        output.extend(U64.pack(len(text)))
        output.extend(text)
        previous_title = title
    if (
        metadata_offset != len(metadata)
        or title_offset != len(titles)
        or text_offset != len(texts)
    ):
        raise ValueError("Wikimedia transformed sections have trailing bytes")
    if projected_size != original_size:
        raise ValueError("Wikimedia metadata differs from declared output size")
    output.extend(manifest)
    return bytes(output)


def encode(data: bytes, *, source_extension_lanes: bool = True) -> bytes:
    if data.startswith(SOURCE_MAGIC):
        return encode_source(data, extension_lanes=source_extension_lanes)
    if data.startswith(WIKIMEDIA_MAGIC):
        return encode_wikimedia(data)
    raise ValueError("unsupported text/source development framing")


def decode(data: bytes, *, max_output_size: int | None = None) -> bytes:
    if len(data) < HEADER.size:
        raise ValueError("text/source transform header is truncated")
    magic, kind, original_size, count, expected_sha256 = HEADER.unpack_from(data)
    if magic != TRANSFORM_MAGIC:
        raise ValueError("text/source transform magic is invalid")
    if kind not in {SOURCE_DEMUX, SOURCE_EXTENSION_LANES, WIKIMEDIA_DEMUX}:
        raise ValueError("text/source transform kind is unsupported")
    if count > MAX_RECORDS:
        raise ValueError("text/source transform record count exceeds limit")
    if max_output_size is not None:
        if (
            isinstance(max_output_size, bool)
            or not isinstance(max_output_size, int)
            or max_output_size < 0
        ):
            raise ValueError("text/source maximum output size is invalid")
        if original_size > max_output_size:
            raise ValueError("text/source declared output exceeds limit")
    if kind in {SOURCE_DEMUX, SOURCE_EXTENSION_LANES}:
        restored = _decode_source(data, kind, count, original_size)
    else:
        restored = _decode_wikimedia(data, count, original_size)
    if len(restored) != original_size:
        raise ValueError("text/source restored size differs from header")
    if hashlib.sha256(restored).digest() != expected_sha256:
        raise ValueError("text/source restored digest differs from header")
    return restored
