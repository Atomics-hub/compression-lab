from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO, Iterator
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
BACKEND_STORE = 2
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
DENSE_FALLBACK_THREADS = 2
DENSE_FALLBACK_MULTITHREAD_MIN = 8 * 1024 * 1024
DENSE_COLUMN_SAFETY_LEVEL = 3
STREAM_MAGIC = b"TBS1"
STREAM_VERSION = 1
STREAM_FLAGS = 0
STREAM_HEADER = struct.Struct(">4sBBHQQQQ32s32sI")
STREAM_SEGMENT_HEADER = struct.Struct(">QQ")
DEFAULT_STREAM_SEGMENT_SIZE = 16 * 1024 * 1024
DEFAULT_STREAM_RECORD_SLACK = 1024 * 1024
DEFAULT_STREAM_CONCURRENCY = 2
MAX_STREAM_SEGMENT_SIZE = 256 * 1024 * 1024
MAX_STREAM_RECORD_SLACK = 16 * 1024 * 1024
MAX_STREAM_CONCURRENCY = 4
STREAM_FRAME_SLACK = 256 * 1024
STREAM_SOURCE_MANIFEST_DOMAIN = b"TBS1-source-manifest-v1\0"


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


def _compress_dense_column(
    data: bytes,
    delimiter: int,
    level: int,
    threads: int,
) -> bytes:
    transformed = transform(data, delimiter)
    if threads > 1:
        return zstd_compress_multithread(
            transformed,
            level=level,
            threads=threads,
        )
    return zstd_compress(transformed, level=level)


def _compress_dense_direct(
    data: bytes,
    level: int,
    threads: int,
) -> tuple[bytes, int, int]:
    actual_threads = 1
    if threads > 1 and len(data) >= DENSE_FALLBACK_MULTITHREAD_MIN:
        payload = (
            zstd_compress_multithread(
                data,
                level=level,
                threads=threads,
            )
        )
        actual_threads = threads
    else:
        payload = zstd_compress(data, level=level)
    if len(payload) < len(data):
        return payload, BACKEND_DIRECT, actual_threads
    return data, BACKEND_STORE, 0


def compress_dense_auto_with_metadata(
    data: bytes,
    enforce_direct_fallback: bool = False,
) -> tuple[bytes, dict]:
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

    direct_fallback_compared = False
    direct_fallback_selected = False
    if backend == BACKEND_COLUMN and enforce_direct_fallback:
        direct_fallback_compared = True
        with ThreadPoolExecutor(max_workers=2) as executor:
            direct_future = executor.submit(
                _compress_dense_direct,
                data,
                DENSE_COLUMN_SAFETY_LEVEL,
                1,
            )
            column_future = executor.submit(
                _compress_dense_column,
                data,
                delimiter,
                level,
                threads,
            )
            (
                direct_payload,
                direct_backend,
                direct_threads,
            ) = direct_future.result()
            column_payload = column_future.result()
        if len(column_payload) < len(direct_payload):
            payload = column_payload
        else:
            payload = direct_payload
            backend = direct_backend
            level = (
                DENSE_COLUMN_SAFETY_LEVEL
                if backend == BACKEND_DIRECT
                else 0
            )
            threads = direct_threads
            reason = (
                "full-direct-fallback"
                if backend == BACKEND_DIRECT
                else "full-store-fallback"
            )
            direct_fallback_selected = True
    elif backend == BACKEND_COLUMN:
        payload = _compress_dense_column(data, delimiter, level, threads)
    else:
        if enforce_direct_fallback:
            payload, backend, threads = _compress_dense_direct(
                data,
                DENSE_DEFAULT_LEVEL,
                DENSE_FALLBACK_THREADS,
            )
            if backend == BACKEND_STORE:
                level = 0
        else:
            payload = zstd_compress(data, level=level)
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
        "direct_fallback_compared": direct_fallback_compared,
        "direct_fallback_selected": direct_fallback_selected,
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
    if backend == BACKEND_STORE:
        return "store"
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
    elif backend == BACKEND_STORE:
        output = payload
        if len(output) != original_size:
            raise ValueError("TBL1 stored payload size mismatch")
    else:
        raise ValueError("unsupported TBL1 backend")
    if hashlib.sha256(output).digest() != expected_hash:
        raise ValueError("TBL1 SHA-256 mismatch")
    return output


def _validate_stream_configuration(segment_size: int, record_slack: int) -> None:
    if not 1 <= segment_size <= MAX_STREAM_SEGMENT_SIZE:
        raise ValueError("TBL1 stream segment size is outside the supported bound")
    if not 0 <= record_slack <= MAX_STREAM_RECORD_SLACK:
        raise ValueError("TBL1 stream record slack is outside the supported bound")


def _record_aligned_chunks(
    source: BinaryIO,
    segment_size: int,
    record_slack: int,
) -> Iterator[bytes]:
    while True:
        head = source.read(segment_size)
        if not head:
            return
        if (
            len(head) == segment_size
            and record_slack
            and not head.endswith(b"\n")
        ):
            tail = source.readline(record_slack)
            if tail:
                head += tail
        yield head


def _temporary_destination(destination: Path) -> tuple[Path, BinaryIO]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    return Path(temporary_name), os.fdopen(descriptor, "w+b")


def _compress_stream_chunk(chunk: bytes) -> tuple[int, bytes, dict]:
    frame, metadata = compress_dense_auto_with_metadata(
        chunk,
        enforce_direct_fallback=True,
    )
    return len(chunk), frame, metadata


def _compressed_stream_chunks(
    source: BinaryIO,
    segment_size: int,
    record_slack: int,
    concurrency: int,
) -> Iterator[tuple[int, bytes, dict]]:
    pending: deque[Future[tuple[int, bytes, dict]]] = deque()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for chunk in _record_aligned_chunks(source, segment_size, record_slack):
            pending.append(executor.submit(_compress_stream_chunk, chunk))
            if len(pending) >= concurrency:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()


def compress_stream(
    source: Path | str,
    destination: Path | str,
    segment_size: int = DEFAULT_STREAM_SEGMENT_SIZE,
    record_slack: int = DEFAULT_STREAM_RECORD_SLACK,
    concurrency: int = DEFAULT_STREAM_CONCURRENCY,
) -> dict:
    """Compress a delimited file with memory bounded by one TBL1 segment."""

    _validate_stream_configuration(segment_size, record_slack)
    if not 1 <= concurrency <= MAX_STREAM_CONCURRENCY:
        raise ValueError("TBL1 stream concurrency is outside the supported bound")
    source_path = Path(source)
    destination_path = Path(destination)
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("TBL1 stream source and destination must differ")
    declared_source_size = source_path.stat().st_size
    temporary_path, output = _temporary_destination(destination_path)
    source_manifest_digest = hashlib.sha256(STREAM_SOURCE_MANIFEST_DOMAIN)
    payload_digest = hashlib.sha256()
    source_bytes = 0
    payload_bytes = 0
    segment_count = 0
    transformed_segments = 0
    direct_segments = 0
    raw_stored_segments = 0
    direct_fallback_compared_segments = 0
    direct_fallback_selected_segments = 0
    selector_ns = 0
    maximum_sample_bytes = 0
    weighted_direct_sample = 0.0
    weighted_column_sample = 0.0
    sample_weight = 0
    delimiters: set[int] = set()
    levels: set[int] = set()
    maximum_threads = 0
    try:
        with output, source_path.open("rb") as input_file:
            output.write(b"\0" * STREAM_HEADER.size)
            for chunk_size, frame, metadata in _compressed_stream_chunks(
                input_file,
                segment_size,
                record_slack,
                concurrency,
            ):
                segment_header = STREAM_SEGMENT_HEADER.pack(
                    chunk_size,
                    len(frame),
                )
                output.write(segment_header)
                output.write(frame)
                payload_digest.update(segment_header)
                payload_digest.update(frame)
                inner_source_hash = frame[HEADER.size - 32 : HEADER.size]
                source_manifest_digest.update(struct.pack(">Q", chunk_size))
                source_manifest_digest.update(inner_source_hash)
                source_bytes += chunk_size
                payload_bytes += len(segment_header) + len(frame)
                segment_count += 1
                backend = frame_backend(frame)
                transformed_segments += int(backend == "column-transpose+zstd")
                direct_segments += int(backend == "direct-zstd")
                raw_stored_segments += int(backend == "store")
                direct_fallback_compared_segments += int(
                    metadata["direct_fallback_compared"]
                )
                direct_fallback_selected_segments += int(
                    metadata["direct_fallback_selected"]
                )
                selector_ns += int(metadata["selector_ns"])
                sample_bytes = int(metadata["selector_sample_bytes"])
                maximum_sample_bytes = max(maximum_sample_bytes, sample_bytes)
                weighted_direct_sample += float(metadata["sample_ratio"]) * sample_bytes
                weighted_column_sample += (
                    float(metadata["transformed_sample_ratio"]) * sample_bytes
                )
                sample_weight += sample_bytes
                delimiters.add(frame_delimiter(frame))
                levels.add(int(metadata["compression_level"]))
                maximum_threads = max(
                    maximum_threads,
                    int(metadata["compression_threads"]),
                )

            if source_bytes != declared_source_size:
                raise RuntimeError("TBL1 stream source changed while being compressed")
            header = STREAM_HEADER.pack(
                STREAM_MAGIC,
                STREAM_VERSION,
                STREAM_FLAGS,
                0,
                segment_size,
                record_slack,
                source_bytes,
                payload_bytes,
                source_manifest_digest.digest(),
                payload_digest.digest(),
                segment_count,
            )
            output.seek(0)
            output.write(header)
            output.flush()
        os.replace(temporary_path, destination_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    if transformed_segments == segment_count and segment_count:
        selected_backend = "tbl1-stream-column"
    elif direct_segments == segment_count and segment_count:
        selected_backend = "tbl1-stream-direct"
    elif raw_stored_segments == segment_count and segment_count:
        selected_backend = "tbl1-stream-store"
    elif segment_count:
        selected_backend = "tbl1-stream-mixed"
    else:
        selected_backend = "tbl1-stream-empty"
    return {
        "selected_backend": selected_backend,
        "selector_ns": selector_ns,
        "selector_stages": int(segment_count > 0),
        "selector_sample_bytes": maximum_sample_bytes,
        "sample_ratio": (
            weighted_direct_sample / sample_weight if sample_weight else 0.0
        ),
        "transformed_sample_ratio": (
            weighted_column_sample / sample_weight if sample_weight else 0.0
        ),
        "selector_reason": "bounded-per-segment-dense",
        "delimiter": next(iter(delimiters)) if len(delimiters) == 1 else 0,
        "compression_level": next(iter(levels)) if len(levels) == 1 else 0,
        "compression_threads": maximum_threads,
        "segment_count": segment_count,
        "candidate_segment_count": segment_count,
        "transformed_segments": transformed_segments,
        "direct_segments": direct_segments,
        "stored_segments": raw_stored_segments,
        "direct_fallback_compared_segments": (
            direct_fallback_compared_segments
        ),
        "direct_fallback_selected_segments": (
            direct_fallback_selected_segments
        ),
        "stream_segment_size": segment_size,
        "stream_record_slack": record_slack,
        "stream_concurrency": concurrency,
    }


def _read_exact(source: BinaryIO, size: int, label: str) -> bytes:
    data = source.read(size)
    if len(data) != size:
        raise ValueError(f"truncated TBL1 stream {label}")
    return data


def inspect_stream(source: Path | str) -> dict:
    source_path = Path(source)
    with source_path.open("rb") as input_file:
        header = _read_exact(input_file, STREAM_HEADER.size, "header")
    (
        magic,
        version,
        flags,
        reserved,
        segment_size,
        record_slack,
        original_size,
        payload_size,
        source_manifest_hash,
        payload_hash,
        segment_count,
    ) = STREAM_HEADER.unpack(header)
    if magic != STREAM_MAGIC or version != STREAM_VERSION:
        raise ValueError("unsupported TBL1 stream")
    if flags != STREAM_FLAGS or reserved != 0:
        raise ValueError("unsupported TBL1 stream flags")
    _validate_stream_configuration(segment_size, record_slack)
    if payload_size != source_path.stat().st_size - STREAM_HEADER.size:
        raise ValueError("TBL1 stream payload size mismatch")
    if (original_size == 0) != (segment_count == 0):
        raise ValueError("invalid TBL1 stream segment count")
    maximum_segment_count = (
        (original_size + segment_size - 1) // segment_size
        if original_size
        else 0
    )
    if segment_count > maximum_segment_count:
        raise ValueError("TBL1 stream segment count exceeds output bound")
    return {
        "segment_size": segment_size,
        "record_slack": record_slack,
        "original_size": original_size,
        "payload_size": payload_size,
        "source_manifest_sha256": source_manifest_hash.hex(),
        "payload_sha256": payload_hash.hex(),
        "segment_count": segment_count,
    }


def decompress_stream(
    source: Path | str,
    destination: Path | str,
    max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
    concurrency: int = DEFAULT_STREAM_CONCURRENCY,
) -> dict:
    """Restore a TBL1 stream while holding at most one segment in memory."""

    source_path = Path(source)
    destination_path = Path(destination)
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("TBL1 stream source and destination must differ")
    if not 1 <= concurrency <= MAX_STREAM_CONCURRENCY:
        raise ValueError("TBL1 stream concurrency is outside the supported bound")
    info = inspect_stream(source_path)
    original_size = int(info["original_size"])
    if original_size > max_output_size:
        raise ValueError("TBL1 stream declared output exceeds configured limit")
    segment_size = int(info["segment_size"])
    record_slack = int(info["record_slack"])
    payload_size = int(info["payload_size"])
    segment_count = int(info["segment_count"])
    expected_source_manifest_hash = bytes.fromhex(
        str(info["source_manifest_sha256"])
    )
    expected_payload_hash = bytes.fromhex(str(info["payload_sha256"]))
    temporary_path, output = _temporary_destination(destination_path)
    source_manifest_digest = hashlib.sha256(STREAM_SOURCE_MANIFEST_DOMAIN)
    payload_digest = hashlib.sha256()
    restored_bytes = 0
    consumed_payload = 0
    transformed_segments = 0
    direct_segments = 0
    raw_stored_segments = 0
    pending: deque[tuple[Future[bytes], int]] = deque()

    def flush_restored_segment(output_file: BinaryIO) -> int:
        future, declared_size = pending.popleft()
        restored = future.result()
        if len(restored) != declared_size:
            raise ValueError("TBL1 stream segment size mismatch")
        output_file.write(restored)
        return len(restored)

    try:
        with output, source_path.open("rb") as input_file:
            _read_exact(input_file, STREAM_HEADER.size, "header")
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                declared_segment_bytes = 0
                for segment_index in range(segment_count):
                    segment_header = _read_exact(
                        input_file,
                        STREAM_SEGMENT_HEADER.size,
                        "segment header",
                    )
                    consumed_payload += len(segment_header)
                    payload_digest.update(segment_header)
                    segment_original_size, frame_size = (
                        STREAM_SEGMENT_HEADER.unpack(segment_header)
                    )
                    if not 1 <= segment_original_size <= segment_size + record_slack:
                        raise ValueError("TBL1 stream segment exceeds configured bound")
                    if (
                        segment_index + 1 < segment_count
                        and segment_original_size < segment_size
                    ):
                        raise ValueError(
                            "TBL1 stream has an undersized interior segment"
                        )
                    declared_segment_bytes += segment_original_size
                    if declared_segment_bytes > original_size:
                        raise ValueError("TBL1 stream segments exceed declared output")
                    maximum_frame_size = (
                        segment_original_size
                        + segment_original_size // 64
                        + STREAM_FRAME_SLACK
                        + HEADER.size
                    )
                    if not HEADER.size <= frame_size <= maximum_frame_size:
                        raise ValueError(
                            "TBL1 stream frame size exceeds configured bound"
                        )
                    if consumed_payload + frame_size > payload_size:
                        raise ValueError("TBL1 stream frame exceeds declared payload")
                    frame = _read_exact(input_file, frame_size, "segment frame")
                    consumed_payload += frame_size
                    payload_digest.update(frame)
                    inner_source_hash = frame[HEADER.size - 32 : HEADER.size]
                    source_manifest_digest.update(
                        struct.pack(">Q", segment_original_size)
                    )
                    source_manifest_digest.update(inner_source_hash)
                    backend = frame_backend(frame)
                    pending.append(
                        (
                            executor.submit(
                                decompress,
                                frame,
                                segment_original_size,
                            ),
                            segment_original_size,
                        )
                    )
                    transformed_segments += int(
                        backend == "column-transpose+zstd"
                    )
                    direct_segments += int(backend == "direct-zstd")
                    raw_stored_segments += int(backend == "store")
                    if len(pending) >= concurrency:
                        restored_bytes += flush_restored_segment(output)
                while pending:
                    restored_bytes += flush_restored_segment(output)

            if consumed_payload != payload_size:
                raise ValueError("TBL1 stream payload accounting mismatch")
            if input_file.read(1):
                raise ValueError("trailing TBL1 stream data")
            if restored_bytes != original_size:
                raise ValueError("TBL1 stream output size mismatch")
            if payload_digest.digest() != expected_payload_hash:
                raise ValueError("TBL1 stream payload SHA-256 mismatch")
            if (
                source_manifest_digest.digest()
                != expected_source_manifest_hash
            ):
                raise ValueError("TBL1 stream source manifest SHA-256 mismatch")
            output.flush()
        os.replace(temporary_path, destination_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return {
        "selected_backend": "tbl1-stream-decode",
        "selector_ns": 0,
        "segment_count": segment_count,
        "candidate_segment_count": segment_count,
        "transformed_segments": transformed_segments,
        "direct_segments": direct_segments,
        "stored_segments": raw_stored_segments,
        "stream_segment_size": segment_size,
        "stream_record_slack": record_slack,
        "stream_concurrency": concurrency,
    }
