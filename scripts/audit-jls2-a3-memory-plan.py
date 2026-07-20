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
EXPECTED_A2_RUN_ID = 29_676_674_924
EXPECTED_A2_JOB_ID = 88_165_232_780
EXPECTED_A2_RUN_ATTEMPT = 1
EXPECTED_A2_ARTIFACT_ID = 8_439_147_016
EXPECTED_A2_ARTIFACT_DIGEST = (
    "sha256:b6930b7b9739a2e8768733096ba534406e1b87afa49a40b950e79bb6d72ec83d"
)
EXPECTED_A2_BASELINE_COMMIT = "131547f35747cc0ff9dedbdef66d8a9516a7464f"
EXPECTED_A2_CANDIDATE_COMMIT = "0f3377dff647e8a6d99b65d8f8a269687faa8ec6"
EXPECTED_A2_LOGICAL_CPUS = 4
EXPECTED_A2_PLATFORM = "Linux-6.8.0-1062-azure-x86_64-with-glibc2.35"
EXPECTED_A2_PYTHON = "3.12.13"
EXPECTED_A2_RUSTC = "rustc 1.97.0 (2d8144b78 2026-07-07)"
EXPECTED_A2_CARGO = "cargo 1.97.0 (c980f4866 2026-06-30)"
EXPECTED_A2_RUNNER_SHA256 = (
    "e5c538910b48afad74d930ce557fa6269f68e8e390c9bd6d02502c0f227ab6b4"
)
EXPECTED_A2_WORKFLOW_SHA256 = (
    "aa9c1cb696750a6fd546da7c5767f97fc1726d721b42eedefb298f3f83884f27"
)
EXPECTED_A2_BASELINE_BINARY_SHA256 = (
    "31db3a25eb0d935f43dc2411ada64e811ddd53b967a87c6d4aab113f3424a7e9"
)
EXPECTED_A2_CANDIDATE_BINARY_SHA256 = (
    "c67e9c9b1902414c2b2e67991631d4cd065041242e6dd39392d673da2ca752fd"
)
EXPECTED_A2_CARGO_LOCK_SHA256 = (
    "a905547d069da6d55bf6739307ffe9c75202cc15e87a6ae399e10b8890544783"
)
EXPECTED_A2_JLS2_RS_SHA256 = (
    "e39441d60ab40d4ffe403cf0c84a30dda012997783f8ce3312d97d9580bc0c86"
)
EXPECTED_A2_ZSTD = {
    "zstd": "0.13.3",
    "zstd-safe": "7.2.4",
    "zstd-sys": "2.0.16+zstd.1.5.7",
    "libzstd": "1.5.7",
}
EXPECTED_A2_FIXTURES = {
    "clue-early-development": {
        "source_bytes": 62_267_473,
        "source_sha256": "4f1571569ebdf98621bbd29da45ba84ab37b4f1f1033aacf822dd5b3f40358fe",
        "encoded_bytes": 1_589_812,
        "encoded_sha256": "46d38bedd6c2b2d9c0187b25bfb4417890ac49265703376f124b43088ec75043",
        "segment_count": 4,
    },
    "clue-middle-development": {
        "source_bytes": 69_847_327,
        "source_sha256": "5ee50c36db110b023faf412e05398402e25ed59776ef5ee9323339f8b1aa4fa5",
        "encoded_bytes": 840_515,
        "encoded_sha256": "9a5c53d076dfcd8310451752e11563978ae9b76dbca59fddd943a2a9dcc63417",
        "segment_count": 5,
    },
    "clue-late-development": {
        "source_bytes": 71_463_332,
        "source_sha256": "71091e9fa5d8fd20944e1bd5707f1c832470c56d4b662fc6ef3d34e9478eb739",
        "encoded_bytes": 1_545_500,
        "encoded_sha256": "9a42acbbe659f5507e007d2b46326ac6a510b5247715f874082a6dbc8bf065ec",
        "segment_count": 5,
    },
    "jls2-context-stress-256": {
        "source_bytes": 50_270_800,
        "source_sha256": "873b0a0a7565fe8ee59c7f6deb377b83bd64677ccd87dc25e570ccd6b05a51c5",
        "encoded_bytes": 50_070,
        "encoded_sha256": "2fd97c117fab3e9410c5f266ef15e42790d06d1971f0849e0b4a295fd000319f",
        "segment_count": 3,
    },
}


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
    if logical_cpus != EXPECTED_A2_LOGICAL_CPUS:
        raise ValueError("logical CPU count drifted from the exact A2 evidence host")
    if baseline_peak_rss_bytes != BASELINE_PEAK_RSS_BYTES:
        raise ValueError("baseline peak RSS drifted from the exact A2 evidence")
    if development_limit_bytes != DEVELOPMENT_LIMIT_BYTES:
        raise ValueError("development limit drifted from the frozen A3 protocol")
    if batch_budget_bytes != BATCH_BUDGET_BYTES:
        raise ValueError("batch budget drifted from the frozen A3 protocol")
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
    # Encoded lifetime is report-only. It is too small in the retained A2
    # evidence to establish the hypothesis and can never authorize A/B work.
    decoded_upper_reaches_threshold = decoded_upper >= required
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
        "exact_a2_evidence_binding": {
            "workflow_run_id": EXPECTED_A2_RUN_ID,
            "workflow_job_id": EXPECTED_A2_JOB_ID,
            "workflow_run_attempt": EXPECTED_A2_RUN_ATTEMPT,
            "artifact_id": EXPECTED_A2_ARTIFACT_ID,
            "artifact_digest": EXPECTED_A2_ARTIFACT_DIGEST,
            "baseline_commit": EXPECTED_A2_BASELINE_COMMIT,
            "candidate_commit": EXPECTED_A2_CANDIDATE_COMMIT,
            "platform": EXPECTED_A2_PLATFORM,
            "logical_cpus": EXPECTED_A2_LOGICAL_CPUS,
            "python": EXPECTED_A2_PYTHON,
            "rustc": EXPECTED_A2_RUSTC,
            "cargo": EXPECTED_A2_CARGO,
            "runner_sha256": EXPECTED_A2_RUNNER_SHA256,
            "workflow_sha256": EXPECTED_A2_WORKFLOW_SHA256,
            "baseline_binary_sha256": EXPECTED_A2_BASELINE_BINARY_SHA256,
            "candidate_binary_sha256": EXPECTED_A2_CANDIDATE_BINARY_SHA256,
            "cargo_lock_sha256": EXPECTED_A2_CARGO_LOCK_SHA256,
            "jls2_rs_sha256": EXPECTED_A2_JLS2_RS_SHA256,
            "zstd": EXPECTED_A2_ZSTD,
            "allocator": {
                "family": "glibc ptmalloc",
                "glibc_version_from_platform": "2.35",
                "a2_phase_counters_available": False,
                "hosted_preflight_requires_mallinfo2": True,
            },
            "fixture_metadata": EXPECTED_A2_FIXTURES,
            "exact_segment_sizes_and_modes_available_offline": False,
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
            "decoded_upper_bound_reaches_threshold": decoded_upper_reaches_threshold,
            "encoded_lifetime_authorization_credit_bytes": 0,
            "status": "hosted_attribution_required",
            "preliminary_finding": (
                "declared_decoded_upper_bound_reaches_threshold"
                if decoded_upper_reaches_threshold
                else "decoded_concurrency_attribution_insufficient"
            ),
            "passed": False,
        },
        "authorization": {
            "product_ab_authorized": False,
            "lifetime_only_release_can_authorize": False,
            "required_next_evidence": (
                "strict ubuntu-22.04 development-only hosted attribution preflight "
                "bound to the exact A2 fixture metadata and complete segment topology"
            ),
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
    parser.add_argument("--logical-cpus", type=int, default=EXPECTED_A2_LOGICAL_CPUS)
    args = parser.parse_args()
    report = audit(
        args.input.read_bytes(),
        logical_cpus=args.logical_cpus,
    )
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["kill_gate"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
