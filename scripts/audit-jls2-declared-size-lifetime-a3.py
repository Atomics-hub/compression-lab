#!/usr/bin/env python3
"""Frozen hosted-only JLS2 A3 decoded-concurrency attribution preflight."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
A1_RUNNER = ROOT / "scripts" / "benchmark-jls2-context-reuse.py"
A1_RUNNER_SHA256 = (
    "d8073d8c96e923fb88689be565051c1f03c0a362c2c1e28c0000dbc14e632f96"
)
A2_COMMIT = "0f3377dff647e8a6d99b65d8f8a269687faa8ec6"
A2_BINARY_SHA256 = "c67e9c9b1902414c2b2e67991631d4cd065041242e6dd39392d673da2ca752fd"
A2_BASELINE_RSS_BYTES = 657_682_432
A3_OVERAGE_BYTES = 175_337_472
ATTRIBUTION_THRESHOLD_BYTES = 105_202_484
PROPOSED_BATCH_BUDGET_BYTES = 32 * 1024 * 1024
EXPECTED_PLATFORM = "Linux-6.8.0-1062-azure-x86_64-with-glibc2.35"
EXPECTED_LOGICAL_CPUS = 4
EXPECTED_PYTHON = "3.12.13"
EXPECTED_RUSTC = "rustc 1.97.0 (2d8144b78 2026-07-07)"
EXPECTED_CARGO = "cargo 1.97.0 (c980f4866 2026-06-30)"
EXPECTED_CARGO_LOCK_SHA256 = (
    "a905547d069da6d55bf6739307ffe9c75202cc15e87a6ae399e10b8890544783"
)
EXPECTED_GLIBC = "2.35"
EXPECTED_ALLOCATOR = "glibc-ptmalloc-mallinfo2"
EXPECTED_ZSTD = {
    "zstd": "0.13.3",
    "zstd-safe": "7.2.4",
    "zstd-sys": "2.0.16+zstd.1.5.7",
    "bundled-libzstd": "1.5.7",
}
EXPECTED_FRAMES = {
    "clue-early-development": {
        "source_bytes": 62_267_473,
        "encoded_bytes": 1_589_812,
        "encoded_sha256": "46d38bedd6c2b2d9c0187b25bfb4417890ac49265703376f124b43088ec75043",
        "segments": 4,
    },
    "clue-middle-development": {
        "source_bytes": 69_847_327,
        "encoded_bytes": 840_515,
        "encoded_sha256": "9a5c53d076dfcd8310451752e11563978ae9b76dbca59fddd943a2a9dcc63417",
        "segments": 5,
    },
    "clue-late-development": {
        "source_bytes": 71_463_332,
        "encoded_bytes": 1_545_500,
        "encoded_sha256": "9a42acbbe659f5507e007d2b46326ac6a510b5247715f874082a6dbc8bf065ec",
        "segments": 5,
    },
    "jls2-context-stress-256": {
        "source_bytes": 50_270_800,
        "encoded_bytes": 50_070,
        "encoded_sha256": "2fd97c117fab3e9410c5f266ef15e42790d06d1971f0849e0b4a295fd000319f",
        "segments": 3,
    },
}
TOPOLOGY_FIELDS = (
    "segment_index",
    "mode",
    "encoded_frame_bytes",
    "encoded_frame_borrowed",
    "declared_output_bytes",
    "declared_skeleton_raw_bytes",
    "declared_channel_raw_bytes",
    "declared_live_working_bytes",
    "a2_batch_index",
    "a2_batch_declared_live_working_bytes",
    "proposed_batch_index",
    "proposed_batch_declared_live_working_bytes",
)
PHASES = (
    "input_loaded",
    "before_batch",
    "maximum_live_batch",
    "after_decoded_buffers_drop",
    "after_output_buffers_drop",
    "after_malloc_trim",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_a1_runner() -> Any:
    observed = sha256_file(A1_RUNNER)
    if observed != A1_RUNNER_SHA256:
        raise RuntimeError(f"frozen A1 runner drifted: {observed}")
    spec = importlib.util.spec_from_file_location("jls2_a1_frozen", A1_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen A1 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command_output(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True
    ).stdout.strip()


def topology_key(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {field: segment[field] for field in TOPOLOGY_FIELDS}
        for segment in report["segments"]
    ]


def validate_diagnostic_report(
    report: dict[str, Any], fixture_id: str, expected: dict[str, Any]
) -> None:
    if report.get("schema_version") != 1:
        raise ValueError("diagnostic schema version mismatch")
    if report.get("fixture_id") != fixture_id:
        raise ValueError("diagnostic fixture identity mismatch")
    if report.get("encoded_bytes") != expected["encoded_bytes"]:
        raise ValueError("diagnostic encoded byte count mismatch")
    if report.get("encoded_sha256") != expected["encoded_sha256"]:
        raise ValueError("diagnostic encoded SHA-256 mismatch")
    if report.get("output_bytes") != expected["source_bytes"]:
        raise ValueError("diagnostic output byte count mismatch")
    if (
        not isinstance(report.get("output_sha256"), str)
        or len(report["output_sha256"]) != 64
    ):
        raise ValueError("diagnostic output SHA-256 is missing")
    if report.get("encoded_capacity_bytes", 0) < report["encoded_bytes"]:
        raise ValueError("diagnostic encoded capacity is invalid")
    if report.get("segment_count") != expected["segments"]:
        raise ValueError("diagnostic segment count mismatch")
    if not report.get("exact"):
        raise ValueError("diagnostic decode was not exact")
    segments = report.get("segments")
    if not isinstance(segments, list) or len(segments) != expected["segments"]:
        raise ValueError("diagnostic segment table is incomplete")
    for index, segment in enumerate(segments):
        if segment.get("segment_index") != index:
            raise ValueError("diagnostic segment order mismatch")
        missing = [field for field in TOPOLOGY_FIELDS if field not in segment]
        if missing:
            raise ValueError(f"diagnostic segment fields missing: {missing}")
        if segment["mode"] not in ("direct", "columnar"):
            raise ValueError("diagnostic segment mode is invalid")
        if segment["encoded_frame_borrowed"] is not True:
            raise ValueError("A2 encoded segment must be borrowed")
    snapshots = report.get("phase_snapshots")
    if not isinstance(snapshots, list):
        raise ValueError("diagnostic phase snapshots are missing")
    observed_phases = {row.get("phase") for row in snapshots}
    if not set(PHASES).issubset(observed_phases):
        raise ValueError("diagnostic phase snapshots are incomplete")
    for snapshot in snapshots:
        for field in (
            "rss_bytes",
            "allocator_in_use_bytes",
            "allocator_free_arena_bytes",
            "allocator_mmap_bytes",
        ):
            if not isinstance(snapshot.get(field), int) or snapshot[field] < 0:
                raise ValueError(f"invalid allocator/RSS field: {field}")
    attribution = report.get("attribution")
    if not isinstance(attribution, dict):
        raise ValueError("diagnostic attribution is missing")
    for field in (
        "decoded_concurrency_potential_bytes",
        "phase_correlated_rss_reduction_bytes",
        "phase_correlated_allocator_release_bytes",
        "credited_bytes",
        "live_encoded_bytes_report_only",
        "live_declared_decoded_reassembly_bytes",
        "allocator_in_use_not_represented_by_declared_buffers_bytes",
        "free_allocator_arenas_or_mappings_retained_bytes",
        "unclassified_resident_bytes",
    ):
        if not isinstance(attribution.get(field), int) or attribution[field] < 0:
            raise ValueError(f"invalid attribution field: {field}")
    expected_credit = min(
        attribution["phase_correlated_rss_reduction_bytes"],
        attribution["decoded_concurrency_potential_bytes"]
        + attribution["phase_correlated_allocator_release_bytes"],
    )
    if attribution["credited_bytes"] != expected_credit:
        raise ValueError("credited attribution does not use the frozen minimum")
    if attribution.get("encoded_lifetime_authorization_credit_bytes") != 0:
        raise ValueError("encoded lifetime received prohibited authorization credit")
    if attribution.get("declared_values_are_observed_allocations") is not False:
        raise ValueError("declared bounds were mislabeled as observed allocations")
    if report.get("corruption_results") != {
        "product_regression_suite": (
            "verified separately by frozen workflow before corpus access"
        )
    }:
        raise ValueError("frozen corruption regression evidence is missing")


def frozen_host() -> dict[str, Any]:
    host = {
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "rustc": command_output(["rustc", "--version"]),
        "cargo": command_output(["cargo", "--version"]),
        "glibc": command_output(["getconf", "GNU_LIBC_VERSION"]).split()[-1],
        "allocator": EXPECTED_ALLOCATOR,
        "zstandard": EXPECTED_ZSTD,
    }
    expected = {
        "platform": EXPECTED_PLATFORM,
        "logical_cpus": EXPECTED_LOGICAL_CPUS,
        "python": EXPECTED_PYTHON,
        "rustc": EXPECTED_RUSTC,
        "cargo": EXPECTED_CARGO,
        "glibc": EXPECTED_GLIBC,
        "allocator": EXPECTED_ALLOCATOR,
        "zstandard": EXPECTED_ZSTD,
    }
    if host != expected:
        raise ValueError(f"host identity mismatch: expected {expected}, observed {host}")
    return host


def run_diagnostic(
    binary: Path, frame: Path, fixture_id: str, source_sha256: str, output: Path
) -> dict[str, Any]:
    subprocess.run(
        [
            str(binary),
            "--input",
            str(frame),
            "--fixture-id",
            fixture_id,
            "--expected-output-sha256",
            source_sha256,
            "--output",
            str(output),
        ],
        check=True,
    )
    with output.open(encoding="utf-8") as source:
        return json.load(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--audit-binary", type=Path, required=True)
    parser.add_argument("--a2-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    args = parser.parse_args()
    for binary in (args.audit_binary, args.a2_binary):
        if not binary.is_file():
            parser.error(f"binary is missing: {binary}")
    if sha256_file(args.a2_binary) != A2_BINARY_SHA256:
        raise ValueError("exact A2 product binary SHA-256 mismatch")
    if not args.run_id.isdigit() or not args.job_id.isdigit() or args.run_attempt < 1:
        parser.error("hosted run/job/attempt identity is invalid")
    if sha256_file(ROOT / "native" / "Cargo.lock") != EXPECTED_CARGO_LOCK_SHA256:
        raise ValueError("Cargo.lock identity mismatch")
    host = frozen_host()
    a1 = load_a1_runner()
    generations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="jls2-a3-hosted-attribution-") as name:
        work = Path(name)
        for generation in (1, 2):
            generation_dir = work / f"generation-{generation}"
            generation_dir.mkdir()
            items = a1.prepare_items(args.corpus.resolve(), generation_dir)
            if {item["id"] for item in items} != set(EXPECTED_FRAMES):
                raise ValueError("development fixture identity mismatch")
            reports = []
            for item in items:
                expected = EXPECTED_FRAMES[item["id"]]
                if item["size_bytes"] != expected["source_bytes"]:
                    raise ValueError("source byte count mismatch")
                if item["frame"].stat().st_size != expected["encoded_bytes"]:
                    raise ValueError("encoded byte count mismatch")
                if sha256_file(item["frame"]) != expected["encoded_sha256"]:
                    raise ValueError("encoded SHA-256 mismatch")
                report_path = generation_dir / f"{item['id']}-audit.json"
                report = run_diagnostic(
                    args.audit_binary.resolve(),
                    item["frame"],
                    item["id"],
                    item["sha256"],
                    report_path,
                )
                validate_diagnostic_report(report, item["id"], expected)
                reports.append(report)
            generations.append({"generation": generation, "reports": reports})
    first = {row["fixture_id"]: row for row in generations[0]["reports"]}
    second = {row["fixture_id"]: row for row in generations[1]["reports"]}
    topology_identical = all(
        topology_key(first[item_id]) == topology_key(second[item_id])
        for item_id in EXPECTED_FRAMES
    )
    if not topology_identical:
        raise ValueError("two-generation topology mismatch")
    minimum_potential = min(
        row["attribution"]["decoded_concurrency_potential_bytes"]
        for generation in generations
        for row in generation["reports"]
    )
    minimum_rss = min(
        row["attribution"]["phase_correlated_rss_reduction_bytes"]
        for generation in generations
        for row in generation["reports"]
    )
    minimum_credit = min(
        row["attribution"]["credited_bytes"]
        for generation in generations
        for row in generation["reports"]
    )
    gates = {
        "exact_a2_commit": command_output(["git", "rev-parse", "HEAD"]) == A2_COMMIT,
        "exact_host_and_toolchain": True,
        "four_logical_cpus": host["logical_cpus"] == EXPECTED_LOGICAL_CPUS,
        "two_generation_topology_identical": topology_identical,
        "all_decodes_exact": all(
            row["exact"]
            for generation in generations
            for row in generation["reports"]
        ),
        "decoded_concurrency_potential_at_least_threshold": (
            minimum_potential >= ATTRIBUTION_THRESHOLD_BYTES
        ),
        "phase_correlated_rss_reduction_at_least_threshold": (
            minimum_rss >= ATTRIBUTION_THRESHOLD_BYTES
        ),
        "credited_attribution_at_least_threshold": (
            minimum_credit >= ATTRIBUTION_THRESHOLD_BYTES
        ),
        "encoded_lifetime_credit_is_zero": all(
            row["attribution"]["encoded_lifetime_authorization_credit_bytes"] == 0
            for generation in generations
            for row in generation["reports"]
        ),
    }
    passed = all(gates.values())
    result = {
        "schema_version": 1,
        "name": "jls2-declared-size-lifetime-a3-hosted-attribution-v1",
        "created_at_epoch_seconds": int(time.time()),
        "claim_scope": "development-only decoder-memory attribution",
        "claim_ceiling": (
            "Development-only attribution; no product A/B, validation, holdout, "
            "market-leading, world-best, or state-of-the-art claim."
        ),
        "a2_identity": {
            "commit": A2_COMMIT,
            "binary_sha256": A2_BINARY_SHA256,
            "baseline_peak_rss_bytes": A2_BASELINE_RSS_BYTES,
        },
        "hosted_identity": {
            "run_id": args.run_id,
            "job_id": args.job_id,
            "run_attempt": args.run_attempt,
            "a2_commit": command_output(["git", "rev-parse", "HEAD"]),
            "workflow_source_commit": os.environ.get("GITHUB_SHA", ""),
            "workflow_sha256": sha256_file(
                ROOT
                / ".github"
                / "workflows"
                / "jls2-declared-size-lifetime-a3-attribution.yml"
            ),
            "runner_sha256": sha256_file(Path(__file__).resolve()),
            "diagnostic_binary_sha256": sha256_file(args.audit_binary.resolve()),
            "a2_product_binary_sha256": sha256_file(args.a2_binary.resolve()),
            "artifact_name": f"jls2-declared-size-lifetime-a3-attribution-{args.run_id}",
        },
        "host": host,
        "settings": {
            "attribution_threshold_bytes": ATTRIBUTION_THRESHOLD_BYTES,
            "a3_overage_bytes": A3_OVERAGE_BYTES,
            "proposed_batch_budget_bytes": PROPOSED_BATCH_BUDGET_BYTES,
            "a1_runner_sha256": A1_RUNNER_SHA256,
            "cargo_lock_sha256": EXPECTED_CARGO_LOCK_SHA256,
            "development_fixtures_only": True,
            "validation_accessed": False,
            "holdout_accessed": False,
            "product_ab_authorized_before_this_result": False,
            "format_encoder_selector_changed": False,
        },
        "generations": generations,
        "summary": {
            "minimum_decoded_concurrency_potential_bytes": minimum_potential,
            "minimum_phase_correlated_rss_reduction_bytes": minimum_rss,
            "minimum_credited_bytes": minimum_credit,
            "gates": gates,
            "passed": passed,
            "product_ab_authorized": passed,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
