#!/usr/bin/env python3
"""Audit declared JLS2 buffer concurrency for the frozen A3 memory hypothesis."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


STREAM_MAGIC = b"JLS2"
FRAME_MAGIC = b"JLF2"
COLUMN_MAGIC = b"JLC1"
VERSION = 1
MODE_DIRECT = 0
MODE_COLUMNAR = 1
STREAM_HEADER_SIZE = 84
SEGMENT_HEADER_SIZE = 16
FRAME_HEADER_SIZE = 88
COLUMN_HEADER_SIZE = 68
COLUMN_ENTRY_SIZE = 16
MAX_CHANNELS = 256
MAX_RAW_EXPANSION = 4
MAX_RAW_OVERHEAD = 4096
MAX_SEGMENT_WORKERS = 8
DEVELOPMENT_LIMIT_BYTES = 460 * 1024 * 1024
PRODUCT_LIMIT_BYTES = 512 * 1024 * 1024
BASELINE_PEAK_RSS_BYTES = 657_682_432
BATCH_BUDGET_BYTES = 32 * 1024 * 1024
ATTRIBUTION_PERCENT = 60
NAME = "jls2-a3-declared-size-lifetime-audit-v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_u32(data: bytes, offset: int, label: str) -> int:
    end = offset + 4
    if end > len(data):
        raise ValueError(f"{label} is truncated")
    return int.from_bytes(data[offset:end], "big")


def read_u64(data: bytes, offset: int, label: str) -> int:
    end = offset + 8
    if end > len(data):
        raise ValueError(f"{label} is truncated")
    return int.from_bytes(data[offset:end], "big")


def read_digest(data: bytes, offset: int, label: str) -> bytes:
    end = offset + 32
    if end > len(data):
        raise ValueError(f"{label} is truncated")
    return data[offset:end]


def parse_columnar(payload: bytes, segment_size: int) -> dict[str, Any]:
    if len(payload) < COLUMN_HEADER_SIZE:
        raise ValueError("JSON-column frame is truncated")
    if payload[:4] != COLUMN_MAGIC:
        raise ValueError("JSON-column frame magic mismatch")
    if payload[4] != VERSION or payload[5:8] != b"\0\0\0":
        raise ValueError("JSON-column version or reserved bits drifted")
    original_size = read_u64(payload, 8, "JSON-column original size")
    if original_size != segment_size:
        raise ValueError("JSON-column original size does not match segment")
    channel_count = read_u32(payload, 48, "JSON-column channel count")
    if channel_count > MAX_CHANNELS:
        raise ValueError("JSON-column frame has too many channels")
    skeleton_size = read_u64(payload, 52, "JSON-column skeleton size")
    skeleton_payload_size = read_u64(
        payload, 60, "JSON-column skeleton payload size"
    )
    table_end = COLUMN_HEADER_SIZE + channel_count * COLUMN_ENTRY_SIZE
    if table_end > len(payload):
        raise ValueError("JSON-column channel table is truncated")
    maximum_raw_size = original_size * MAX_RAW_EXPANSION + MAX_RAW_OVERHEAD
    raw_sizes = [skeleton_size]
    encoded_payload_sizes = [skeleton_payload_size]
    for channel in range(channel_count):
        entry = COLUMN_HEADER_SIZE + channel * COLUMN_ENTRY_SIZE
        raw_sizes.append(read_u64(payload, entry, "JSON-column channel size"))
        encoded_payload_sizes.append(
            read_u64(payload, entry + 8, "JSON-column channel payload size")
        )
    total_raw_size = sum(raw_sizes)
    if any(size > maximum_raw_size for size in raw_sizes):
        raise ValueError("JSON-column stream size exceeds its bound")
    if total_raw_size > maximum_raw_size:
        raise ValueError("JSON-column raw sizes exceed their total bound")
    if table_end + sum(encoded_payload_sizes) != len(payload):
        raise ValueError("JSON-column payload sizes do not consume the frame")
    return {
        "mode": "columnar",
        "channel_count": channel_count,
        "declared_raw_stream_bytes": total_raw_size,
        "declared_output_bytes": original_size,
        "declared_live_working_bytes": total_raw_size + original_size,
        "encoded_column_payload_bytes": sum(encoded_payload_sizes),
    }


def parse_frame(frame: bytes, segment_size: int) -> dict[str, Any]:
    if len(frame) < FRAME_HEADER_SIZE:
        raise ValueError("JLF2 frame is truncated")
    if frame[:4] != FRAME_MAGIC:
        raise ValueError("JLF2 magic mismatch")
    if frame[4] != VERSION or frame[6:8] != b"\0\0":
        raise ValueError("JLF2 version or reserved bits drifted")
    mode = frame[5]
    original_size = read_u64(frame, 8, "JLF2 original size")
    payload_size = read_u64(frame, 16, "JLF2 payload size")
    if original_size != segment_size:
        raise ValueError("JLF2 original size does not match segment")
    if payload_size != len(frame) - FRAME_HEADER_SIZE:
        raise ValueError("JLF2 payload size mismatch")
    payload = frame[FRAME_HEADER_SIZE:]
    if hashlib.sha256(payload).digest() != read_digest(
        frame, 56, "JLF2 payload SHA-256"
    ):
        raise ValueError("JLF2 payload SHA-256 mismatch")
    if mode == MODE_DIRECT:
        details = {
            "mode": "direct",
            "channel_count": 0,
            "declared_raw_stream_bytes": original_size,
            "declared_output_bytes": original_size,
            "declared_live_working_bytes": original_size,
            "encoded_column_payload_bytes": 0,
        }
    elif mode == MODE_COLUMNAR:
        details = parse_columnar(payload, segment_size)
    else:
        raise ValueError(f"unsupported JLF2 mode: {mode}")
    return {**details, "encoded_frame_bytes": len(frame)}


def parse_stream(encoded: bytes) -> list[dict[str, Any]]:
    if len(encoded) < STREAM_HEADER_SIZE:
        raise ValueError("JLS2 stream is truncated")
    if encoded[:4] != STREAM_MAGIC:
        raise ValueError("JLS2 magic mismatch")
    if encoded[4] != VERSION or encoded[5:8] != b"\0\0\0":
        raise ValueError("JLS2 version, flags, or reserved bits drifted")
    original_size = read_u64(encoded, 8, "JLS2 original size")
    if hashlib.sha256(encoded[STREAM_HEADER_SIZE:]).digest() != read_digest(
        encoded, 48, "JLS2 encoded SHA-256"
    ):
        raise ValueError("JLS2 encoded SHA-256 mismatch")
    segment_count = read_u32(encoded, 80, "JLS2 segment count")
    offset = STREAM_HEADER_SIZE
    declared_size = 0
    segments = []
    for index in range(segment_count):
        header_end = offset + SEGMENT_HEADER_SIZE
        if header_end > len(encoded):
            raise ValueError("JLS2 segment header is truncated")
        segment_size = read_u64(encoded, offset, "JLS2 segment size")
        frame_size = read_u64(encoded, offset + 8, "JLS2 frame size")
        frame_end = header_end + frame_size
        if frame_end > len(encoded):
            raise ValueError("JLS2 segment frame is truncated")
        details = parse_frame(encoded[header_end:frame_end], segment_size)
        segments.append({"index": index, **details})
        declared_size += segment_size
        offset = frame_end
    if offset != len(encoded):
        raise ValueError("JLS2 stream has trailing data")
    if declared_size != original_size:
        raise ValueError("JLS2 declared segment sizes do not match output")
    return segments


def current_batches(segment_count: int, logical_cpus: int) -> list[list[int]]:
    if logical_cpus < 1:
        raise ValueError("logical CPU count must be positive")
    workers = min(segment_count, logical_cpus, MAX_SEGMENT_WORKERS)
    if segment_count == 0:
        return []
    return [
        list(range(offset, min(offset + workers, segment_count)))
        for offset in range(0, segment_count, workers)
    ]


def proposed_batches(
    segments: list[dict[str, Any]], budget_bytes: int
) -> list[list[int]]:
    if budget_bytes < 1:
        raise ValueError("batch budget must be positive")
    batches: list[list[int]] = []
    current: list[int] = []
    current_bytes = 0
    for segment in segments:
        working = segment["declared_live_working_bytes"]
        if current and current_bytes + working > budget_bytes:
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(segment["index"])
        current_bytes += working
        if working > budget_bytes:
            batches.append(current)
            current = []
            current_bytes = 0
    if current:
        batches.append(current)
    return batches


def describe_plan(
    segments: list[dict[str, Any]], batches: list[list[int]]
) -> dict[str, Any]:
    rows = []
    for indices in batches:
        selected = [segments[index] for index in indices]
        rows.append(
            {
                "segment_indices": indices,
                "declared_live_working_bytes": sum(
                    row["declared_live_working_bytes"] for row in selected
                ),
                "encoded_frame_bytes": sum(
                    row["encoded_frame_bytes"] for row in selected
                ),
            }
        )
    return {
        "batches": rows,
        "peak_declared_live_working_bytes": max(
            (row["declared_live_working_bytes"] for row in rows), default=0
        ),
        "peak_encoded_frame_bytes": max(
            (row["encoded_frame_bytes"] for row in rows), default=0
        ),
    }


def audit(
    encoded: bytes,
    *,
    logical_cpus: int,
    baseline_peak_rss_bytes: int = BASELINE_PEAK_RSS_BYTES,
    development_limit_bytes: int = DEVELOPMENT_LIMIT_BYTES,
    batch_budget_bytes: int = BATCH_BUDGET_BYTES,
) -> dict[str, Any]:
    segments = parse_stream(encoded)
    current = describe_plan(segments, current_batches(len(segments), logical_cpus))
    proposed = describe_plan(segments, proposed_batches(segments, batch_budget_bytes))
    decoded_upper = max(
        0,
        current["peak_declared_live_working_bytes"]
        - proposed["peak_declared_live_working_bytes"],
    )
    encoded_upper = max(
        0, len(encoded) - proposed["peak_encoded_frame_bytes"]
    )
    combined_upper = decoded_upper + encoded_upper
    overage = max(0, baseline_peak_rss_bytes - development_limit_bytes)
    required = (overage * ATTRIBUTION_PERCENT + 99) // 100
    upper_bound_reaches_threshold = combined_upper >= required
    return {
        "schema_version": 1,
        "name": NAME,
        "claim_scope": "synthetic declared-memory planning; not observed RSS attribution",
        "input": {
            "encoded_bytes": len(encoded),
            "encoded_sha256": sha256(encoded),
            "segment_count": len(segments),
        },
        "settings": {
            "logical_cpus": logical_cpus,
            "baseline_peak_rss_bytes": baseline_peak_rss_bytes,
            "development_limit_bytes": development_limit_bytes,
            "product_limit_bytes": PRODUCT_LIMIT_BYTES,
            "batch_budget_bytes": batch_budget_bytes,
            "attribution_percent": ATTRIBUTION_PERCENT,
        },
        "segments": segments,
        "current_a2_plan": current,
        "proposed_a3_plan": proposed,
        "upper_bounds_not_observed": {
            "decoded_live_reduction_bytes": decoded_upper,
            "encoded_lifetime_reduction_bytes": encoded_upper,
            "combined_reduction_bytes": combined_upper,
        },
        "allocator_retained_pages": {
            "observed_bytes": None,
            "measurement_required": True,
        },
        "kill_gate": {
            "baseline_overage_bytes": overage,
            "required_attributed_bytes": required,
            "upper_bound_reaches_threshold": upper_bound_reaches_threshold,
            "status": "measurement_required",
            "preliminary_finding": (
                "declared_upper_bound_reaches_threshold"
                if upper_bound_reaches_threshold
                else "allocator_attribution_required"
            ),
            "passed": False,
        },
        "claim_ceiling": (
            "No candidate authorization until Linux phase RSS and allocator telemetry "
            "attribute the frozen minimum to releasable buffers."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logical-cpus", type=int, default=4)
    parser.add_argument(
        "--baseline-peak-rss-bytes", type=int, default=BASELINE_PEAK_RSS_BYTES
    )
    parser.add_argument(
        "--development-limit-bytes", type=int, default=DEVELOPMENT_LIMIT_BYTES
    )
    parser.add_argument("--batch-budget-bytes", type=int, default=BATCH_BUDGET_BYTES)
    args = parser.parse_args()
    report = audit(
        args.input.read_bytes(),
        logical_cpus=args.logical_cpus,
        baseline_peak_rss_bytes=args.baseline_peak_rss_bytes,
        development_limit_bytes=args.development_limit_bytes,
        batch_budget_bytes=args.batch_budget_bytes,
    )
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["kill_gate"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
