from __future__ import annotations

import struct
from typing import Dict, Tuple


MAGIC = b"LWS1"
HEADER = struct.Struct(">4sI")
MODE_RAW = 0
MODE_SPLICE = 1
MAX_REFERENCE_SIZE = 1024 * 1024


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint value cannot be negative")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _decode_varint(data: bytes, offset: int) -> Tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(data):
            raise ValueError("splice transform varint is truncated")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("splice transform varint is too long")


def _records(data: bytes) -> list[bytes]:
    if not data:
        return []
    records = data.splitlines(keepends=True)
    if b"".join(records) != data:
        raise AssertionError("line splitting changed input bytes")
    return records


def _common_edges(previous: bytes, current: bytes) -> Tuple[int, int]:
    shared = min(len(previous), len(current))
    prefix = 0
    while prefix < shared and previous[prefix] == current[prefix]:
        prefix += 1
    suffix_limit = shared - prefix
    suffix = 0
    while (
        suffix < suffix_limit
        and previous[len(previous) - 1 - suffix]
        == current[len(current) - 1 - suffix]
    ):
        suffix += 1
    return prefix, suffix


def encode(data: bytes) -> Tuple[bytes, Dict[str, int]]:
    records = _records(data)
    output = bytearray(HEADER.pack(MAGIC, len(records)))
    previous: bytes | None = None
    raw_records = 0
    spliced_records = 0
    for record in records:
        raw = bytes((MODE_RAW,)) + _encode_varint(len(record)) + record
        selected = raw
        if (
            previous is not None
            and len(previous) <= MAX_REFERENCE_SIZE
            and len(record) <= MAX_REFERENCE_SIZE
        ):
            prefix, suffix = _common_edges(previous, record)
            middle_end = len(record) - suffix
            middle = record[prefix:middle_end]
            splice = (
                bytes((MODE_SPLICE,))
                + _encode_varint(prefix)
                + _encode_varint(suffix)
                + _encode_varint(len(middle))
                + middle
            )
            if len(splice) < len(raw):
                selected = splice
        output.extend(selected)
        if selected[0] == MODE_SPLICE:
            spliced_records += 1
        else:
            raw_records += 1
        previous = record
    return bytes(output), {
        "record_count": len(records),
        "raw_records": raw_records,
        "spliced_records": spliced_records,
        "transformed_bytes": len(output),
    }


def decode(data: bytes, *, expected_size: int) -> bytes:
    if expected_size < 0:
        raise ValueError("expected size cannot be negative")
    if len(data) < HEADER.size:
        raise ValueError("splice transform is truncated")
    magic, record_count = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError("splice transform magic mismatch")
    offset = HEADER.size
    output = bytearray()
    previous: bytes | None = None
    for _ in range(record_count):
        if offset >= len(data):
            raise ValueError("splice transform record is truncated")
        mode = data[offset]
        offset += 1
        if mode == MODE_RAW:
            size, offset = _decode_varint(data, offset)
            end = offset + size
            if end > len(data):
                raise ValueError("splice transform raw record is truncated")
            record = data[offset:end]
            offset = end
        elif mode == MODE_SPLICE:
            if previous is None:
                raise ValueError("splice transform references no prior record")
            if len(previous) > MAX_REFERENCE_SIZE:
                raise ValueError("splice transform reference exceeds its bound")
            prefix, offset = _decode_varint(data, offset)
            suffix, offset = _decode_varint(data, offset)
            middle_size, offset = _decode_varint(data, offset)
            if prefix + suffix > len(previous):
                raise ValueError("splice transform reference bounds are invalid")
            end = offset + middle_size
            if end > len(data):
                raise ValueError("splice transform middle is truncated")
            middle = data[offset:end]
            offset = end
            suffix_bytes = previous[len(previous) - suffix :] if suffix else b""
            record = previous[:prefix] + middle + suffix_bytes
            if len(record) > MAX_REFERENCE_SIZE:
                raise ValueError("splice transform record exceeds its bound")
        else:
            raise ValueError(f"unsupported splice transform mode: {mode}")
        if len(output) + len(record) > expected_size:
            raise ValueError("splice transform output exceeds expected size")
        output.extend(record)
        previous = record
    if offset != len(data):
        raise ValueError("splice transform has trailing data")
    if len(output) != expected_size:
        raise ValueError(
            f"splice transform size mismatch: expected {expected_size}, "
            f"got {len(output)}"
        )
    return bytes(output)
