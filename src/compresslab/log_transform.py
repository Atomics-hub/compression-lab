from __future__ import annotations

from collections import deque
import struct
from typing import Deque, Dict, Iterable, Tuple


MAGIC = b"LWX1"
RECENT_MAGIC = b"LWX2"
HEADER = struct.Struct(">4sI")
MODE_RAW = 0
MODE_REFERENCE = 1
MAX_WINDOW = 16
MAX_RUN = 128
MAX_RECORDS = (1 << 32) - 1
RECENT_SLOT_COUNT = 1024
RECENT_MAX_RECORD_SIZE = 32 * 1024


def _records(data: bytes) -> Iterable[bytes]:
    offset = 0
    while offset < len(data):
        end = data.find(b"\n", offset)
        if end < 0:
            yield data[offset:]
            return
        end += 1
        yield data[offset:end]
        offset = end


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint value must be non-negative")
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
            raise ValueError("log transform varint is truncated")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ValueError("log transform varint is too large")


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _zero_run(data: bytes, offset: int) -> int:
    end = offset
    limit = min(len(data), offset + MAX_RUN)
    while end < limit and data[end] == 0:
        end += 1
    return end - offset


def _encode_residual(residual: bytes) -> bytes:
    output = bytearray()
    offset = 0
    while offset < len(residual):
        zero_count = _zero_run(residual, offset)
        if zero_count >= 2:
            output.append(0x80 | (zero_count - 1))
            offset += zero_count
            continue

        literal_start = offset
        offset += max(1, zero_count)
        while offset < len(residual) and offset - literal_start < MAX_RUN:
            zero_count = _zero_run(residual, offset)
            if zero_count >= 2:
                break
            offset += max(1, zero_count)
        literal = residual[literal_start:offset]
        output.append(len(literal) - 1)
        output.extend(literal)
    return bytes(output)


def _decode_residual(
    data: bytes,
    offset: int,
    expected_size: int,
) -> Tuple[bytes, int]:
    output = bytearray()
    while len(output) < expected_size:
        if offset >= len(data):
            raise ValueError("log transform residual is truncated")
        command = data[offset]
        offset += 1
        size = (command & 0x7F) + 1
        if size > expected_size - len(output):
            raise ValueError("log transform residual exceeds record size")
        if command & 0x80:
            output.extend(b"\0" * size)
            continue
        if size > len(data) - offset:
            raise ValueError("log transform literal is truncated")
        output.extend(data[offset:offset + size])
        offset += size
    return bytes(output), offset


def encode(
    data: bytes,
    *,
    window_size: int = 8,
) -> Tuple[bytes, dict[str, int]]:
    if not 1 <= window_size <= MAX_WINDOW:
        raise ValueError(f"window_size must be between 1 and {MAX_WINDOW}")
    records = list(_records(data))
    if len(records) > MAX_RECORDS:
        raise ValueError("log transform contains too many records")

    output = bytearray(HEADER.pack(MAGIC, len(records)))
    history: Dict[int, Deque[bytes]] = {}
    referenced_records = 0
    raw_records = 0
    zero_bytes = 0
    residual_bytes = 0

    for record in records:
        output.extend(_encode_varint(len(record)))
        bucket = history.setdefault(len(record), deque(maxlen=window_size))
        best_index = -1
        best_payload = b""
        best_zero_bytes = 0
        for index, reference in enumerate(bucket):
            residual = _xor(record, reference)
            payload = _encode_residual(residual)
            if best_index < 0 or len(payload) < len(best_payload):
                best_index = index
                best_payload = payload
                best_zero_bytes = residual.count(0)

        if best_index >= 0 and len(best_payload) + 1 < len(record):
            output.extend((MODE_REFERENCE, best_index))
            output.extend(best_payload)
            referenced_records += 1
            residual_bytes += len(best_payload)
            zero_bytes += best_zero_bytes
        else:
            output.append(MODE_RAW)
            output.extend(record)
            raw_records += 1
        bucket.appendleft(record)

    return bytes(output), {
        "record_count": len(records),
        "referenced_records": referenced_records,
        "raw_records": raw_records,
        "residual_bytes": residual_bytes,
        "zero_bytes": zero_bytes,
        "window_size": window_size,
    }


def decode(
    transformed: bytes,
    *,
    expected_size: int,
    window_size: int = 8,
) -> bytes:
    if not 1 <= window_size <= MAX_WINDOW:
        raise ValueError(f"window_size must be between 1 and {MAX_WINDOW}")
    if len(transformed) < HEADER.size:
        raise ValueError("log transform is truncated")
    magic, record_count = HEADER.unpack(transformed[:HEADER.size])
    if magic != MAGIC:
        raise ValueError("log transform magic mismatch")

    offset = HEADER.size
    output = bytearray()
    history: Dict[int, Deque[bytes]] = {}
    for _ in range(record_count):
        size, offset = _decode_varint(transformed, offset)
        if size > expected_size - len(output):
            raise ValueError("log transform output exceeds expected size")
        if offset >= len(transformed):
            raise ValueError("log transform record mode is truncated")
        mode = transformed[offset]
        offset += 1
        bucket = history.setdefault(size, deque(maxlen=window_size))
        if mode == MODE_RAW:
            if size > len(transformed) - offset:
                raise ValueError("log transform raw record is truncated")
            record = transformed[offset:offset + size]
            offset += size
        elif mode == MODE_REFERENCE:
            if offset >= len(transformed):
                raise ValueError("log transform reference is truncated")
            reference_index = transformed[offset]
            offset += 1
            if reference_index >= len(bucket):
                raise ValueError("log transform reference is invalid")
            residual, offset = _decode_residual(transformed, offset, size)
            record = _xor(residual, bucket[reference_index])
        else:
            raise ValueError("log transform record mode is invalid")
        output.extend(record)
        bucket.appendleft(record)

    if offset != len(transformed):
        raise ValueError("log transform contains trailing data")
    if len(output) != expected_size:
        raise ValueError("log transform output size mismatch")
    return bytes(output)


def _recent_slot(size: int) -> int:
    return size % RECENT_SLOT_COUNT


def encode_recent(data: bytes) -> Tuple[bytes, dict[str, int]]:
    records = list(_records(data))
    if len(records) > MAX_RECORDS:
        raise ValueError("log transform contains too many records")

    output = bytearray(HEADER.pack(RECENT_MAGIC, len(records)))
    history: list[Tuple[int, bytes] | None] = [None] * RECENT_SLOT_COUNT
    referenced_records = 0
    raw_records = 0
    residual_bytes = 0
    zero_bytes = 0

    for record in records:
        size = len(record)
        output.extend(_encode_varint(size))
        slot = _recent_slot(size)
        entry = history[slot]
        payload = b""
        payload_zero_bytes = 0
        if (
            size <= RECENT_MAX_RECORD_SIZE
            and entry is not None
            and entry[0] == size
        ):
            residual = _xor(record, entry[1])
            payload = _encode_residual(residual)
            payload_zero_bytes = residual.count(0)

        if payload and len(payload) < len(record):
            output.append(MODE_REFERENCE)
            output.extend(payload)
            referenced_records += 1
            residual_bytes += len(payload)
            zero_bytes += payload_zero_bytes
        else:
            output.append(MODE_RAW)
            output.extend(record)
            raw_records += 1

        if size <= RECENT_MAX_RECORD_SIZE:
            history[slot] = (size, record)

    return bytes(output), {
        "record_count": len(records),
        "referenced_records": referenced_records,
        "raw_records": raw_records,
        "residual_bytes": residual_bytes,
        "zero_bytes": zero_bytes,
        "slot_count": RECENT_SLOT_COUNT,
        "maximum_reference_record_size": RECENT_MAX_RECORD_SIZE,
    }


def decode_recent(transformed: bytes, *, expected_size: int) -> bytes:
    if len(transformed) < HEADER.size:
        raise ValueError("log transform is truncated")
    magic, record_count = HEADER.unpack(transformed[:HEADER.size])
    if magic != RECENT_MAGIC:
        raise ValueError("log transform magic mismatch")

    offset = HEADER.size
    output = bytearray()
    history: list[Tuple[int, bytes] | None] = [None] * RECENT_SLOT_COUNT
    for _ in range(record_count):
        size, offset = _decode_varint(transformed, offset)
        if size > expected_size - len(output):
            raise ValueError("log transform output exceeds expected size")
        if offset >= len(transformed):
            raise ValueError("log transform record mode is truncated")
        mode = transformed[offset]
        offset += 1
        slot = _recent_slot(size)
        if mode == MODE_RAW:
            if size > len(transformed) - offset:
                raise ValueError("log transform raw record is truncated")
            record = transformed[offset:offset + size]
            offset += size
        elif mode == MODE_REFERENCE:
            entry = history[slot]
            if (
                size > RECENT_MAX_RECORD_SIZE
                or entry is None
                or entry[0] != size
            ):
                raise ValueError("log transform reference is invalid")
            residual, offset = _decode_residual(transformed, offset, size)
            record = _xor(residual, entry[1])
        else:
            raise ValueError("log transform record mode is invalid")
        output.extend(record)
        if size <= RECENT_MAX_RECORD_SIZE:
            history[slot] = (size, record)

    if offset != len(transformed):
        raise ValueError("log transform contains trailing data")
    if len(output) != expected_size:
        raise ValueError("log transform output size mismatch")
    return bytes(output)
