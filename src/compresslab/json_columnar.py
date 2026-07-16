from __future__ import annotations

import hashlib
import re
import struct
from typing import Dict, List, Optional, Tuple, Union

from .native import zstd_compress, zstd_decompress


MAGIC = b"JLC1"
VERSION = 1
MARKER = 0xFF
MARKER_CHANNEL = 0x00
MARKER_LITERAL = 0xFE
MAX_CHANNELS = 256
MAX_RAW_EXPANSION = 4
MAX_RAW_OVERHEAD = 4096
HEADER = struct.Struct(">4sB3xQ32sIQQ")
CHANNEL_HEADER = struct.Struct(">QQ")
NUMBER = re.compile(
    rb"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z"
)

TelemetryValue = Union[str, int, float, bool]


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
            raise ValueError("JSON-column varint is truncated")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("JSON-column varint is too long")


def _string_end(data: bytes, offset: int, limit: int) -> Optional[int]:
    if offset >= limit or data[offset] != 0x22:
        return None
    offset += 1
    while offset < limit:
        value = data[offset]
        offset += 1
        if value == 0x22:
            return offset
        if value == 0x5C:
            if offset >= limit:
                return None
            offset += 1
    return None


def _skip_whitespace(data: bytes, offset: int, limit: int) -> int:
    while offset < limit and data[offset] in b" \t\r\n":
        offset += 1
    return offset


def _compound_end(data: bytes, offset: int, limit: int) -> Optional[int]:
    opening = data[offset]
    closing = 0x7D if opening == 0x7B else 0x5D
    stack = [closing]
    offset += 1
    while offset < limit:
        value = data[offset]
        if value == 0x22:
            end = _string_end(data, offset, limit)
            if end is None:
                return None
            offset = end
            continue
        if value == 0x7B:
            stack.append(0x7D)
        elif value == 0x5B:
            stack.append(0x5D)
        elif value in (0x7D, 0x5D):
            if not stack or value != stack.pop():
                return None
            if not stack:
                return offset + 1
        offset += 1
    return None


def _value_end(data: bytes, offset: int, limit: int) -> Optional[int]:
    if offset >= limit:
        return None
    value = data[offset]
    if value == 0x22:
        return _string_end(data, offset, limit)
    if value in (0x7B, 0x5B):
        return _compound_end(data, offset, limit)
    end = offset
    while end < limit and data[end] not in b",} \t\r\n":
        end += 1
    if end == offset:
        return None
    token = data[offset:end]
    if token in (b"true", b"false", b"null"):
        return end
    return end if NUMBER.fullmatch(token) else None


def _top_level_fields(
    record: bytes,
) -> Optional[List[Tuple[bytes, int, int]]]:
    content_limit = len(record)
    if record.endswith(b"\r\n"):
        content_limit -= 2
    elif record.endswith(b"\n"):
        content_limit -= 1
    offset = _skip_whitespace(record, 0, content_limit)
    if offset >= content_limit or record[offset] != 0x7B:
        return None
    offset += 1
    fields: List[Tuple[bytes, int, int]] = []
    offset = _skip_whitespace(record, offset, content_limit)
    if offset < content_limit and record[offset] == 0x7D:
        offset += 1
    else:
        while True:
            offset = _skip_whitespace(record, offset, content_limit)
            key_start = offset
            key_end = _string_end(record, offset, content_limit)
            if key_end is None:
                return None
            key = record[key_start:key_end]
            offset = _skip_whitespace(record, key_end, content_limit)
            if offset >= content_limit or record[offset] != 0x3A:
                return None
            offset = _skip_whitespace(record, offset + 1, content_limit)
            value_start = offset
            value_end = _value_end(record, value_start, content_limit)
            if value_end is None:
                return None
            fields.append((key, value_start, value_end))
            offset = _skip_whitespace(record, value_end, content_limit)
            if offset >= content_limit:
                return None
            if record[offset] == 0x2C:
                offset += 1
                continue
            if record[offset] == 0x7D:
                offset += 1
                break
            return None
    offset = _skip_whitespace(record, offset, content_limit)
    if offset != content_limit:
        return None
    return fields


def _append_literal(output: bytearray, data: bytes) -> None:
    output.extend(data.replace(b"\xff", b"\xff\xfe"))


def _split_records(data: bytes) -> List[bytes]:
    if not data:
        return []
    records = data.splitlines(keepends=True)
    if b"".join(records) != data:
        raise AssertionError("line splitting changed JSON-log bytes")
    return records


def transform(data: bytes) -> Tuple[bytes, List[bytes], Dict[str, TelemetryValue]]:
    skeleton = bytearray()
    channels: List[bytearray] = []
    channel_by_key: Dict[bytes, int] = {}
    extracted_records = 0
    literal_records = 0
    extracted_values = 0
    records = _split_records(data)
    for record in records:
        fields = _top_level_fields(record)
        pending_keys = []
        if fields is not None:
            for key, _, _ in fields:
                if key not in channel_by_key and key not in pending_keys:
                    pending_keys.append(key)
            if len(channel_by_key) + len(pending_keys) > MAX_CHANNELS:
                fields = None
        if fields is None:
            _append_literal(skeleton, record)
            literal_records += 1
            continue
        for key in pending_keys:
            channel_by_key[key] = len(channels)
            channels.append(bytearray())
        offset = 0
        for key, value_start, value_end in fields:
            _append_literal(skeleton, record[offset:value_start])
            channel_id = channel_by_key[key]
            skeleton.extend((MARKER, MARKER_CHANNEL))
            skeleton.extend(_encode_varint(channel_id))
            value = record[value_start:value_end]
            channels[channel_id].extend(_encode_varint(len(value)))
            channels[channel_id].extend(value)
            extracted_values += 1
            offset = value_end
        _append_literal(skeleton, record[offset:])
        extracted_records += 1
    raw_channels = [bytes(channel) for channel in channels]
    return bytes(skeleton), raw_channels, {
        "record_count": len(records),
        "extracted_records": extracted_records,
        "literal_records": literal_records,
        "extracted_values": extracted_values,
        "channel_count": len(raw_channels),
        "skeleton_bytes": len(skeleton),
        "channel_bytes": sum(len(channel) for channel in raw_channels),
    }


def compress(
    data: bytes,
    *,
    level: int = 3,
) -> Tuple[bytes, Dict[str, TelemetryValue]]:
    skeleton, channels, telemetry = transform(data)
    skeleton_payload = zstd_compress(skeleton, level=level)
    channel_payloads = [
        zstd_compress(channel, level=level) for channel in channels
    ]
    output = bytearray(
        HEADER.pack(
            MAGIC,
            VERSION,
            len(data),
            hashlib.sha256(data).digest(),
            len(channels),
            len(skeleton),
            len(skeleton_payload),
        )
    )
    for channel, payload in zip(channels, channel_payloads):
        output.extend(CHANNEL_HEADER.pack(len(channel), len(payload)))
    output.extend(skeleton_payload)
    for payload in channel_payloads:
        output.extend(payload)
    return bytes(output), {
        **telemetry,
        "encoded_bytes": len(output),
        "skeleton_payload_bytes": len(skeleton_payload),
        "channel_payload_bytes": sum(len(payload) for payload in channel_payloads),
        "zstd_level": level,
    }


def decompress(
    frame: bytes,
    *,
    max_output_size: Optional[int] = None,
) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("JSON-column frame is truncated")
    (
        magic,
        version,
        original_size,
        expected_sha256,
        channel_count,
        skeleton_size,
        skeleton_payload_size,
    ) = HEADER.unpack_from(frame)
    if magic != MAGIC:
        raise ValueError("JSON-column frame magic mismatch")
    if version != VERSION:
        raise ValueError(f"unsupported JSON-column version: {version}")
    if channel_count > MAX_CHANNELS:
        raise ValueError("JSON-column frame has too many channels")
    if max_output_size is not None and original_size > max_output_size:
        raise ValueError("JSON-column output exceeds safety limit")
    maximum_raw_size = (
        original_size * MAX_RAW_EXPANSION + MAX_RAW_OVERHEAD
    )
    if skeleton_size > maximum_raw_size:
        raise ValueError("JSON-column skeleton size exceeds its bound")
    header_end = HEADER.size + channel_count * CHANNEL_HEADER.size
    if header_end > len(frame):
        raise ValueError("JSON-column channel table is truncated")
    channel_sizes = []
    total_raw_size = skeleton_size
    offset = HEADER.size
    for _ in range(channel_count):
        raw_size, payload_size = CHANNEL_HEADER.unpack_from(frame, offset)
        offset += CHANNEL_HEADER.size
        total_raw_size += raw_size
        if raw_size > maximum_raw_size or total_raw_size > maximum_raw_size:
            raise ValueError("JSON-column channel sizes exceed their bound")
        channel_sizes.append((raw_size, payload_size))
    skeleton_end = header_end + skeleton_payload_size
    if skeleton_end > len(frame):
        raise ValueError("JSON-column skeleton payload is truncated")
    try:
        skeleton = zstd_decompress(
            frame[header_end:skeleton_end],
            skeleton_size,
        )
        channels = []
        offset = skeleton_end
        for raw_size, payload_size in channel_sizes:
            end = offset + payload_size
            if end > len(frame):
                raise ValueError("JSON-column channel payload is truncated")
            channels.append(zstd_decompress(frame[offset:end], raw_size))
            offset = end
    except RuntimeError as error:
        raise ValueError(f"invalid JSON-column payload: {error}") from error
    if offset != len(frame):
        raise ValueError("JSON-column frame has trailing data")

    channel_offsets = [0] * channel_count
    output = bytearray()
    offset = 0
    while offset < len(skeleton):
        marker = skeleton.find(bytes((MARKER,)), offset)
        if marker < 0:
            literal = skeleton[offset:]
            if len(literal) > original_size - len(output):
                raise ValueError("JSON-column output exceeds declared size")
            output.extend(literal)
            break
        literal = skeleton[offset:marker]
        if len(literal) > original_size - len(output):
            raise ValueError("JSON-column output exceeds declared size")
        output.extend(literal)
        offset = marker + 1
        if offset >= len(skeleton):
            raise ValueError("JSON-column marker is truncated")
        tag = skeleton[offset]
        offset += 1
        if tag == MARKER_LITERAL:
            if len(output) >= original_size:
                raise ValueError("JSON-column output exceeds declared size")
            output.append(MARKER)
            continue
        if tag != MARKER_CHANNEL:
            raise ValueError("JSON-column marker tag is invalid")
        channel_id, offset = _decode_varint(skeleton, offset)
        if channel_id >= channel_count:
            raise ValueError("JSON-column channel reference is invalid")
        channel = channels[channel_id]
        channel_offset = channel_offsets[channel_id]
        value_size, value_offset = _decode_varint(channel, channel_offset)
        value_end = value_offset + value_size
        if value_end > len(channel):
            raise ValueError("JSON-column value is truncated")
        value = channel[value_offset:value_end]
        if len(value) > original_size - len(output):
            raise ValueError("JSON-column output exceeds declared size")
        output.extend(value)
        channel_offsets[channel_id] = value_end
    if any(
        channel_offsets[index] != len(channel)
        for index, channel in enumerate(channels)
    ):
        raise ValueError("JSON-column channel has unconsumed values")
    if len(output) != original_size:
        raise ValueError("JSON-column output size mismatch")
    restored = bytes(output)
    if hashlib.sha256(restored).digest() != expected_sha256:
        raise ValueError("JSON-column frame SHA-256 mismatch")
    return restored
