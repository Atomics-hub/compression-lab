from __future__ import annotations

from collections import Counter
import hashlib
import struct
import time
from typing import Callable, Dict, List, Tuple
import zlib


MAGIC = b"CLAB"
VERSION = 3
BACKEND_SEGMENTED = 6
FRAME_HEADER = struct.Struct(">4sBBQ32s")
SEGMENT_COUNT = struct.Struct(">I")
SEGMENT_HEADER = struct.Struct(">BIII")
SEGMENT_SIZE = 1024 * 1024
SAMPLE_SIZE = 32 * 1024
TRANSFORM_SAMPLE_THRESHOLD = 0.97

RECIPE_STORE = 0
RECIPE_ZSTD_3 = 1
RECIPE_DELTA_TRANSPOSE_ZSTD_3 = 2

_RECIPE_NAMES = {
    RECIPE_STORE: "store",
    RECIPE_ZSTD_3: "zstd-3",
    RECIPE_DELTA_TRANSPOSE_ZSTD_3: "delta-transpose+zstd-3",
}

Encoder = Callable[[bytes], bytes]
Decoder = Callable[[bytes, int], bytes]
Transform = Callable[[bytes], bytes]
InverseTransform = Callable[[bytes, int], bytes]
EncodedSegment = Tuple[int, bytes, bytes]


def _representative_sample(data: bytes, total_size: int = SAMPLE_SIZE) -> bytes:
    if len(data) <= total_size:
        return data
    block_size = max(1, total_size // 3)
    middle = max(0, len(data) // 2 - block_size // 2)
    tail_size = total_size - 2 * block_size
    return data[:block_size] + data[middle:middle + block_size] + data[-tail_size:]


def _encode_segment(
    data: bytes,
    zstd_encode: Encoder,
    delta_transpose: Transform,
) -> Tuple[EncodedSegment, Dict[str, float]]:
    selector_start = time.perf_counter_ns()
    sample = _representative_sample(data)
    raw_sample = zstd_encode(sample)
    transformed_sample = delta_transpose(sample)
    transformed_sample_encoded = zstd_encode(transformed_sample)
    raw_sample_ratio = len(raw_sample) / len(sample) if sample else 1.0
    transformed_sample_ratio = (
        len(transformed_sample_encoded) / len(sample) if sample else 1.0
    )
    use_transform = (
        bool(sample)
        and len(transformed_sample_encoded)
        < len(raw_sample) * TRANSFORM_SAMPLE_THRESHOLD
    )
    selector_ns = time.perf_counter_ns() - selector_start

    if use_transform:
        recipe = RECIPE_DELTA_TRANSPOSE_ZSTD_3
        payload = zstd_encode(delta_transpose(data))
    else:
        recipe = RECIPE_ZSTD_3
        payload = zstd_encode(data)
    if len(payload) >= len(data):
        recipe = RECIPE_STORE
        payload = data

    return (recipe, data, payload), {
        "selector_ns": float(selector_ns),
        "sample_bytes": float(len(sample)),
        "raw_sample_bytes": float(len(raw_sample)),
        "transformed_sample_bytes": float(len(transformed_sample_encoded)),
        "raw_sample_ratio": raw_sample_ratio,
        "transformed_sample_ratio": transformed_sample_ratio,
    }


def _pack_frame(data: bytes, segments: List[EncodedSegment]) -> bytes:
    output = bytearray(
        FRAME_HEADER.pack(
            MAGIC,
            VERSION,
            BACKEND_SEGMENTED,
            len(data),
            hashlib.sha256(data).digest(),
        )
    )
    output.extend(SEGMENT_COUNT.pack(len(segments)))
    for recipe, original, payload in segments:
        output.extend(
            SEGMENT_HEADER.pack(
                recipe,
                len(original),
                len(payload),
                zlib.crc32(original),
            )
        )
        output.extend(payload)
    return bytes(output)


def _summarize_recipes(segments: List[EncodedSegment]) -> str:
    counts = Counter(recipe for recipe, _, _ in segments)
    detail = ",".join(
        f"{_RECIPE_NAMES[recipe]}={counts[recipe]}" for recipe in sorted(counts)
    )
    return f"v3[{detail}]"


def compress(
    data: bytes,
    *,
    zstd_encode: Encoder,
    delta_transpose: Transform,
    transform_engine: str,
    codec_engine: str,
) -> Tuple[bytes, dict]:
    segmented: List[EncodedSegment] = []
    selector_ns = 0
    sampled_bytes = 0
    raw_sample_bytes = 0
    transformed_sample_bytes = 0

    for offset in range(0, len(data), SEGMENT_SIZE):
        segment, telemetry = _encode_segment(
            data[offset:offset + SEGMENT_SIZE],
            zstd_encode,
            delta_transpose,
        )
        segmented.append(segment)
        selector_ns += int(telemetry["selector_ns"])
        sampled_bytes += int(telemetry["sample_bytes"])
        raw_sample_bytes += int(telemetry["raw_sample_bytes"])
        transformed_sample_bytes += int(telemetry["transformed_sample_bytes"])

    segmented_frame = _pack_frame(data, segmented)
    selected_segments = segmented
    selector_reason = "segmented-smaller"

    if data:
        if len(segmented) == 1 and segmented[0][0] == RECIPE_ZSTD_3:
            whole_payload = segmented[0][2]
        else:
            whole_payload = zstd_encode(data)
        whole_recipe = RECIPE_ZSTD_3
        if len(whole_payload) >= len(data):
            whole_recipe = RECIPE_STORE
            whole_payload = data
        whole_segments = [(whole_recipe, data, whole_payload)]
        whole_frame = _pack_frame(data, whole_segments)
        if len(whole_frame) <= len(segmented_frame):
            selected_segments = whole_segments
            segmented_frame = whole_frame
            selector_reason = "whole-zstd-fallback"

    recipe_counts = Counter(recipe for recipe, _, _ in selected_segments)
    return segmented_frame, {
        "selected_backend": _summarize_recipes(selected_segments),
        "selector_ns": selector_ns,
        "sample_ratio": (
            raw_sample_bytes / sampled_bytes if sampled_bytes else 1.0
        ),
        "transformed_sample_ratio": (
            transformed_sample_bytes / sampled_bytes if sampled_bytes else 1.0
        ),
        "selector_stages": len(segmented),
        "selector_sample_bytes": sampled_bytes,
        "selector_reason": selector_reason,
        "transform_engine": transform_engine,
        "codec_engine": codec_engine,
        "frame_overhead_bytes": (
            FRAME_HEADER.size
            + SEGMENT_COUNT.size
            + len(selected_segments) * SEGMENT_HEADER.size
        ),
        "segment_count": len(selected_segments),
        "candidate_segment_count": len(segmented),
        "transformed_segments": recipe_counts[RECIPE_DELTA_TRANSPOSE_ZSTD_3],
        "stored_segments": recipe_counts[RECIPE_STORE],
    }


def decompress(
    encoded: bytes,
    *,
    zstd_decode: Decoder,
    inverse_delta_transpose: InverseTransform,
    transform_engine: str,
    codec_engine: str,
) -> Tuple[bytes, dict]:
    minimum_size = FRAME_HEADER.size + SEGMENT_COUNT.size
    if len(encoded) < minimum_size:
        raise ValueError("adaptive-v3 frame is truncated")
    magic, version, backend, original_size, expected_hash = FRAME_HEADER.unpack(
        encoded[:FRAME_HEADER.size]
    )
    if magic != MAGIC:
        raise ValueError("adaptive-v3 frame magic mismatch")
    if version != VERSION:
        raise ValueError(f"unsupported adaptive-v3 frame version: {version}")
    if backend != BACKEND_SEGMENTED:
        raise ValueError(f"unsupported adaptive-v3 backend: {backend}")

    offset = FRAME_HEADER.size
    segment_count = SEGMENT_COUNT.unpack(
        encoded[offset:offset + SEGMENT_COUNT.size]
    )[0]
    offset += SEGMENT_COUNT.size
    if original_size == 0 and segment_count != 0:
        raise ValueError("empty adaptive-v3 frame contains segments")
    if original_size > 0 and (segment_count == 0 or segment_count > original_size):
        raise ValueError("adaptive-v3 segment count is invalid")

    output = bytearray()
    recipe_counts: Counter[int] = Counter()
    for _ in range(segment_count):
        if len(encoded) - offset < SEGMENT_HEADER.size:
            raise ValueError("adaptive-v3 segment header is truncated")
        recipe, segment_size, payload_size, expected_crc = SEGMENT_HEADER.unpack(
            encoded[offset:offset + SEGMENT_HEADER.size]
        )
        offset += SEGMENT_HEADER.size
        if segment_size == 0:
            raise ValueError("adaptive-v3 segment is empty")
        if segment_size > original_size - len(output):
            raise ValueError("adaptive-v3 segment exceeds declared original size")
        if payload_size > len(encoded) - offset:
            raise ValueError("adaptive-v3 segment payload is truncated")
        payload = encoded[offset:offset + payload_size]
        offset += payload_size

        if recipe == RECIPE_STORE:
            segment = payload
        elif recipe == RECIPE_ZSTD_3:
            segment = zstd_decode(payload, segment_size)
        elif recipe == RECIPE_DELTA_TRANSPOSE_ZSTD_3:
            transformed = zstd_decode(payload, segment_size)
            segment = inverse_delta_transpose(transformed, segment_size)
        else:
            raise ValueError(f"unsupported adaptive-v3 segment recipe: {recipe}")
        if len(segment) != segment_size:
            raise ValueError("adaptive-v3 segment size mismatch")
        if zlib.crc32(segment) != expected_crc:
            raise ValueError("adaptive-v3 segment CRC mismatch")
        output.extend(segment)
        recipe_counts[recipe] += 1

    if offset != len(encoded):
        raise ValueError("adaptive-v3 frame has trailing data")
    data = bytes(output)
    if len(data) != original_size:
        raise ValueError("adaptive-v3 frame original-size mismatch")
    if hashlib.sha256(data).digest() != expected_hash:
        raise ValueError("adaptive-v3 frame SHA-256 mismatch")

    segments = [
        (recipe, b"", b"")
        for recipe, count in sorted(recipe_counts.items())
        for _ in range(count)
    ]
    return data, {
        "selected_backend": _summarize_recipes(segments),
        "selector_ns": 0,
        "selector_reason": "decoded-segment-index",
        "transform_engine": transform_engine,
        "codec_engine": codec_engine,
        "segment_count": segment_count,
        "transformed_segments": recipe_counts[RECIPE_DELTA_TRANSPOSE_ZSTD_3],
        "stored_segments": recipe_counts[RECIPE_STORE],
    }
