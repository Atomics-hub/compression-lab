from __future__ import annotations

import hashlib
import struct
import time
from typing import Tuple

from .native import (
    tabular_native_available,
    tabular_reassemble,
    tabular_transform,
    zstd_compress,
    zstd_compress_multithread,
    zstd_decompress,
    zstd_frame_content_size,
)


MAGIC = b"TBL1"
VERSION = 1
BACKEND_DIRECT = 0
BACKEND_COLUMN = 1
HEADER = struct.Struct(">4sBBBQ32s")
DEFAULT_MAX_OUTPUT_SIZE = 2 * 1024 * 1024 * 1024
TRANSFORM_SLACK = 1024 * 1024
AUTO_DELIMITERS = (ord(","), ord(";"), ord("\t"), ord("|"))
DETECTION_SAMPLE_BYTES = 1024 * 1024
SAMPLE_COLUMN_MARGIN = 0.98
DENSE_SAMPLE_LEVEL = 3
DENSE_DEFAULT_LEVEL = 9
DENSE_EXTREME_LEVEL = 16
DENSE_EXTREME_THREADS = 2
DENSE_EXTREME_COLUMN_RATIO = 0.05


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint cannot encode a negative value")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _decode_varint(data: bytes | memoryview, offset: int) -> Tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated TBL1 varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise ValueError("TBL1 varint is too large")


def reference_transform(data: bytes, delimiter: int) -> bytes:
    if not 0 <= delimiter <= 255:
        raise ValueError("delimiter must be one byte")
    delimiter_bytes = bytes((delimiter,))
    columns: list[bytearray] = []
    row_metadata = bytearray()
    row_count = 0
    start = 0

    while start < len(data):
        newline = data.find(b"\n", start)
        if newline < 0:
            end = len(data)
            terminated = False
        else:
            end = newline
            terminated = True
        fields = data[start:end].split(delimiter_bytes)
        arity = len(fields)
        row_metadata.extend(_encode_varint((arity << 1) | int(terminated)))
        if arity > len(columns):
            columns.extend(bytearray() for _ in range(arity - len(columns)))
        for index, field in enumerate(fields):
            columns[index].extend(_encode_varint(len(field)))
            columns[index].extend(field)
        row_count += 1
        if not terminated:
            break
        start = newline + 1

    output = bytearray()
    output.extend(_encode_varint(row_count))
    output.extend(_encode_varint(len(columns)))
    output.extend(_encode_varint(len(row_metadata)))
    output.extend(row_metadata)
    for column in columns:
        output.extend(_encode_varint(len(column)))
        output.extend(column)
    return bytes(output)


def reference_inverse_transform(
    data: bytes, delimiter: int, expected_size: int
) -> bytes:
    if not 0 <= delimiter <= 255:
        raise ValueError("delimiter must be one byte")
    if expected_size < 0:
        raise ValueError("expected size cannot be negative")
    offset = 0
    row_count, offset = _decode_varint(data, offset)
    column_count, offset = _decode_varint(data, offset)
    metadata_size, offset = _decode_varint(data, offset)
    if row_count > expected_size + 1 or column_count > expected_size + 1:
        raise ValueError("TBL1 row or column count exceeds output bound")
    metadata_end = offset + metadata_size
    if metadata_end > len(data):
        raise ValueError("truncated TBL1 row metadata")

    arities: list[int] = []
    terminators = bytearray()
    metadata_offset = offset
    total_fields = 0
    for _ in range(row_count):
        packed, metadata_offset = _decode_varint(data, metadata_offset)
        arity = packed >> 1
        if arity == 0 or arity > column_count:
            raise ValueError("invalid TBL1 row arity")
        total_fields += arity
        if total_fields > expected_size + row_count + 1:
            raise ValueError("TBL1 field count exceeds output bound")
        arities.append(arity)
        terminators.append(packed & 1)
    if metadata_offset != metadata_end:
        raise ValueError("trailing or incomplete TBL1 row metadata")
    offset = metadata_end

    column_views: list[memoryview] = []
    for _ in range(column_count):
        column_size, offset = _decode_varint(data, offset)
        column_end = offset + column_size
        if column_end > len(data):
            raise ValueError("truncated TBL1 column stream")
        column_views.append(memoryview(data)[offset:column_end])
        offset = column_end
    if offset != len(data):
        raise ValueError("trailing TBL1 transformed bytes")

    column_offsets = [0] * column_count
    delimiter_bytes = bytes((delimiter,))
    output = bytearray()
    for row_index, arity in enumerate(arities):
        for column_index in range(arity):
            column = column_views[column_index]
            field_size, field_offset = _decode_varint(
                column, column_offsets[column_index]
            )
            field_end = field_offset + field_size
            if field_end > len(column):
                raise ValueError("truncated TBL1 field")
            if column_index:
                output.extend(delimiter_bytes)
            output.extend(column[field_offset:field_end])
            column_offsets[column_index] = field_end
            if len(output) > expected_size:
                raise ValueError("TBL1 output exceeds declared size")
        if terminators[row_index]:
            output.append(0x0A)
            if len(output) > expected_size:
                raise ValueError("TBL1 output exceeds declared size")

    if any(
        column_offsets[index] != len(column)
        for index, column in enumerate(column_views)
    ):
        raise ValueError("unused or incomplete TBL1 column data")
    if len(output) != expected_size:
        raise ValueError(
            f"TBL1 output size mismatch: expected {expected_size}, got {len(output)}"
        )
    return bytes(output)


def transform(data: bytes, delimiter: int) -> bytes:
    if tabular_native_available():
        return tabular_transform(data, delimiter)
    return reference_transform(data, delimiter)


def inverse_transform(data: bytes, delimiter: int, expected_size: int) -> bytes:
    if tabular_native_available():
        return tabular_reassemble(data, delimiter, expected_size)
    return reference_inverse_transform(data, delimiter, expected_size)


def _pack_frame(data: bytes, delimiter: int, backend: int, payload: bytes) -> bytes:
    return HEADER.pack(
        MAGIC,
        VERSION,
        delimiter,
        backend,
        len(data),
        hashlib.sha256(data).digest(),
    ) + payload


def compress(data: bytes, delimiter: int, level: int = 9) -> bytes:
    transformed = transform(data, delimiter)
    direct_payload = zstd_compress(data, level=level)
    column_payload = zstd_compress(transformed, level=level)
    if len(column_payload) < len(direct_payload):
        return _pack_frame(data, delimiter, BACKEND_COLUMN, column_payload)
    return _pack_frame(data, delimiter, BACKEND_DIRECT, direct_payload)


def _representative_sample(data: bytes) -> bytes:
    if len(data) <= DETECTION_SAMPLE_BYTES:
        return data
    block = DETECTION_SAMPLE_BYTES // 3
    middle = len(data) // 2 - block // 2
    return data[:block] + data[middle : middle + block] + data[-block:]


def _detect_delimiter_from_sample(sample: bytes) -> int:
    counts = [sample.count(bytes((delimiter,))) for delimiter in AUTO_DELIMITERS]
    return AUTO_DELIMITERS[max(range(len(counts)), key=counts.__getitem__)]


def detect_delimiter(data: bytes) -> int:
    return _detect_delimiter_from_sample(_representative_sample(data))


def _sample_backend(
    sample: bytes, delimiter: int, level: int
) -> tuple[int, bytes, bytes]:
    direct_sample = zstd_compress(sample, level=level)
    column_sample = zstd_compress(transform(sample, delimiter), level=level)
    if len(column_sample) < len(direct_sample) * SAMPLE_COLUMN_MARGIN:
        return BACKEND_COLUMN, direct_sample, column_sample
    return BACKEND_DIRECT, direct_sample, column_sample


def compress_auto_with_metadata(data: bytes, level: int = 9) -> tuple[bytes, dict]:
    selector_start = time.perf_counter_ns()
    sample = _representative_sample(data)
    delimiter = _detect_delimiter_from_sample(sample)
    backend, direct_sample, column_sample = _sample_backend(
        sample, delimiter, level
    )
    if backend == BACKEND_COLUMN:
        reason = "sample-column-clear-win"
    else:
        reason = "sample-direct-or-ambiguous"
    selector_ns = time.perf_counter_ns() - selector_start

    if backend == BACKEND_COLUMN:
        payload = zstd_compress(transform(data, delimiter), level=level)
    else:
        payload = zstd_compress(data, level=level)
    frame = _pack_frame(data, delimiter, backend, payload)
    sample_size = max(1, len(sample))
    return frame, {
        "selector_ns": selector_ns,
        "selector_stages": 1,
        "selector_sample_bytes": len(sample),
        "sample_ratio": len(direct_sample) / sample_size,
        "transformed_sample_ratio": len(column_sample) / sample_size,
        "selector_reason": reason,
        "compression_level": level,
        "compression_threads": 1,
    }


def compress_auto(data: bytes, level: int = 9) -> bytes:
    frame, _metadata = compress_auto_with_metadata(data, level=level)
    return frame


def compress_dense_auto_with_metadata(data: bytes) -> tuple[bytes, dict]:
    selector_start = time.perf_counter_ns()
    sample = _representative_sample(data)
    delimiter = _detect_delimiter_from_sample(sample)
    backend, direct_sample, column_sample = _sample_backend(
        sample, delimiter, DENSE_SAMPLE_LEVEL
    )
    sample_size = max(1, len(sample))
    column_ratio = len(column_sample) / sample_size
    if backend == BACKEND_COLUMN and column_ratio < DENSE_EXTREME_COLUMN_RATIO:
        level = DENSE_EXTREME_LEVEL
        threads = DENSE_EXTREME_THREADS
        reason = "extreme-column-ratio"
    elif backend == BACKEND_COLUMN:
        level = DENSE_DEFAULT_LEVEL
        threads = 1
        reason = "ordinary-column-ratio"
    else:
        level = DENSE_DEFAULT_LEVEL
        threads = 1
        reason = "direct-or-ambiguous"
    selector_ns = time.perf_counter_ns() - selector_start

    source = transform(data, delimiter) if backend == BACKEND_COLUMN else data
    if threads > 1:
        payload = zstd_compress_multithread(source, level=level, threads=threads)
    else:
        payload = zstd_compress(source, level=level)
    frame = _pack_frame(data, delimiter, backend, payload)
    return frame, {
        "selector_ns": selector_ns,
        "selector_stages": 1,
        "selector_sample_bytes": len(sample),
        "sample_ratio": len(direct_sample) / sample_size,
        "transformed_sample_ratio": column_ratio,
        "selector_reason": reason,
        "compression_level": level,
        "compression_threads": threads,
    }


def frame_backend(frame: bytes) -> str:
    if len(frame) < HEADER.size:
        raise ValueError("truncated TBL1 frame")
    magic, version, _delimiter, backend, _size, _digest = HEADER.unpack_from(frame)
    if magic != MAGIC or version != VERSION:
        raise ValueError("unsupported TBL1 frame")
    if backend == BACKEND_DIRECT:
        return "direct-zstd"
    if backend == BACKEND_COLUMN:
        return "column-transpose+zstd"
    raise ValueError("unsupported TBL1 backend")


def frame_delimiter(frame: bytes) -> int:
    if len(frame) < HEADER.size:
        raise ValueError("truncated TBL1 frame")
    magic, version, delimiter, _backend, _size, _digest = HEADER.unpack_from(frame)
    if magic != MAGIC or version != VERSION:
        raise ValueError("unsupported TBL1 frame")
    return delimiter


def decompress(
    frame: bytes,
    max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated TBL1 frame")
    magic, version, delimiter, backend, original_size, expected_hash = HEADER.unpack_from(
        frame
    )
    if magic != MAGIC or version != VERSION:
        raise ValueError("unsupported TBL1 frame")
    if original_size > max_output_size:
        raise ValueError("TBL1 declared output exceeds configured limit")
    payload = frame[HEADER.size:]
    if backend == BACKEND_DIRECT:
        output = zstd_decompress(payload, original_size)
    elif backend == BACKEND_COLUMN:
        transformed_size = zstd_frame_content_size(payload)
        maximum_transformed = original_size * 5 + TRANSFORM_SLACK
        if transformed_size > maximum_transformed:
            raise ValueError("TBL1 transformed size exceeds configured bound")
        transformed = zstd_decompress(payload, transformed_size)
        output = inverse_transform(transformed, delimiter, original_size)
    else:
        raise ValueError("unsupported TBL1 backend")
    if hashlib.sha256(output).digest() != expected_hash:
        raise ValueError("TBL1 SHA-256 mismatch")
    return output
