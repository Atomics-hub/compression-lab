#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def gain(reference: int, candidate: int) -> float:
    return (reference - candidate) / reference * 100.0


def throughput(byte_count: int, elapsed_ns: int) -> float:
    if byte_count <= 0 or elapsed_ns <= 0:
        return 0.0
    return (byte_count / 1_000_000.0) / (elapsed_ns / 1_000_000_000.0)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def summary_by_codec(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["codec_id"]: row for row in result["summary"]}


def medians_by_item(
    result: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in result["medians"]:
        grouped[row["item_id"]][row["codec_id"]] = row
    return dict(grouped)


def repetition_aggregates(
    result: dict[str, Any], candidate_id: str
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for trial in result["trials"]:
        if trial["codec_id"] == candidate_id:
            grouped[int(trial["repetition"])].append(trial)
    rows = []
    for repetition, trials in sorted(grouped.items()):
        original = sum(int(row["original_bytes"]) for row in trials)
        compression_ns = sum(int(row["compression_ns"]) for row in trials)
        decompression_ns = sum(int(row["decompression_ns"]) for row in trials)
        rows.append(
            {
                "repetition": repetition,
                "items": len(trials),
                "original_bytes": original,
                "compression_mbps": throughput(original, compression_ns),
                "decompression_mbps": throughput(original, decompression_ns),
            }
        )
    return rows


def expected_manifest_rows(gates: dict[str, Any]) -> list[dict[str, str]]:
    return gates["validation"]["expected_items"]


def corpus_identity(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "split": item["split"],
            "license_spdx": item["license_spdx"],
        }
        for item in result["corpus"]
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen first-score TBL1 public-validation gate"
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    candidate_id = gates["candidate"]["codec_id"]
    requirements = gates["requirements"]
    validation = gates["validation"]
    baseline_ids = gates["baselines"]["codec_ids"]
    expected_codecs = [candidate_id, *baseline_ids]
    base = args.receipt.parent

    completed = bool(receipt.get("completed"))
    performance_path = base / receipt.get("performance_results", "missing")
    memory_path = base / receipt.get("memory_results", "missing")
    manifest_path = Path(receipt.get("manifest_path", "missing"))
    if not completed or not performance_path.is_file() or not memory_path.is_file():
        payload = {
            "schema_version": 1,
            "stage": "public-validation",
            "claim_ceiling": gates["claim_ceiling"],
            "passed": False,
            "gate_results": {"first_score_completed": False},
            "retained_error": receipt.get("error", "scored attempt did not complete"),
        }
        write_json_atomic(args.output, payload)
        return 2

    performance = json.loads(performance_path.read_text(encoding="utf-8"))
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {"items": []}
    )
    summaries = summary_by_codec(performance)
    memory_summaries = summary_by_codec(memory)
    medians = medians_by_item(performance)
    repetitions = repetition_aggregates(performance, candidate_id)

    observed_codecs = [codec["id"] for codec in performance["codecs"]]
    expected_items = expected_manifest_rows(gates)
    expected_ids = [row["id"] for row in expected_items]
    observed_items = [item["id"] for item in performance["corpus"]]
    memory_items = [item["id"] for item in memory["corpus"]]

    family_rows: list[dict[str, Any]] = []
    for expected in expected_items:
        item_id = expected["id"]
        by_codec = medians.get(item_id, {})
        candidate = by_codec.get(candidate_id)
        available_baselines = [
            by_codec[codec_id]
            for codec_id in baseline_ids
            if codec_id in by_codec
        ]
        if candidate is None or len(available_baselines) != len(baseline_ids):
            family_rows.append(
                {
                    "id": item_id,
                    "family": expected["family"],
                    "complete": False,
                    "passed": False,
                }
            )
            continue
        strongest = min(available_baselines, key=lambda row: row["compressed_bytes"])
        improvement = gain(
            int(strongest["compressed_bytes"]),
            int(candidate["compressed_bytes"]),
        )
        family_rows.append(
            {
                "id": item_id,
                "family": expected["family"],
                "complete": True,
                "original_bytes": int(candidate["original_bytes"]),
                "candidate_bytes": int(candidate["compressed_bytes"]),
                "strongest_baseline": strongest["codec_id"],
                "strongest_baseline_bytes": int(strongest["compressed_bytes"]),
                "improvement_percent": improvement,
                "passed": improvement
                >= float(requirements["minimum_family_gain_percent"]),
            }
        )

    candidate_summary = summaries.get(candidate_id, {})
    available_summary_baselines = [
        summaries[codec_id] for codec_id in baseline_ids if codec_id in summaries
    ]
    strongest_summary = (
        min(available_summary_baselines, key=lambda row: row["compressed_bytes"])
        if available_summary_baselines
        else {}
    )
    candidate_bytes = int(candidate_summary.get("compressed_bytes", 0))
    strongest_bytes = int(strongest_summary.get("compressed_bytes", 0))
    aggregate_gain = gain(strongest_bytes, candidate_bytes) if strongest_bytes else 0.0
    family_pass_count = sum(bool(row.get("passed")) for row in family_rows)

    proof = receipt.get("deterministic_proof", [])
    proof_by_id = {row.get("id"): row for row in proof}
    proof_complete = list(proof_by_id) == expected_ids
    proof_exact = proof_complete and all(
        row["exact_roundtrip"] for row in proof
    )
    proof_deterministic = proof_complete and all(
        row["deterministic"] for row in proof
    )
    proof_fallback = proof_complete and all(
        row["fallback_safety"]["passed"]
        and row["fallback_safety"]["maximum_regression_bytes"]
        <= int(
            requirements[
                "maximum_segment_regression_vs_equally_framed_fallback_bytes"
            ]
        )
        for row in proof
    )
    proof_accounting = proof_complete and all(
        row["first_metadata"]["segment_count"]
        == row["fallback_safety"]["segments"]
        for row in proof
    )

    all_performance_trials_exact = all(
        row["roundtrip_ok"] and row["source_sha256"] == row["restored_sha256"]
        for row in performance["trials"]
    )
    all_memory_trials_exact = all(
        row["roundtrip_ok"] and row["source_sha256"] == row["restored_sha256"]
        for row in memory["trials"]
    )
    candidate_medians = [
        row for row in performance["medians"] if row["codec_id"] == candidate_id
    ]
    complete_frame_accounting = (
        candidate_bytes
        == sum(int(row["compressed_bytes"]) for row in candidate_medians)
    )

    memory_summary = memory_summaries.get(candidate_id, {})
    compression_peak_mib = float(
        memory_summary.get("compression_peak_rss_bytes", 0)
    ) / (1024 * 1024)
    decompression_peak_mib = float(
        memory_summary.get("decompression_peak_rss_bytes", 0)
    ) / (1024 * 1024)

    config = performance["config"]
    memory_config = memory["config"]
    gate_results = {
        "first_score_completed": bool(receipt.get("first_score")) and completed,
        "gates_digest": receipt.get("gates_sha256") == sha256_file(args.gates),
        "result_digests": (
            receipt.get("performance_results_sha256")
            == sha256_file(performance_path)
            and receipt.get("memory_results_sha256") == sha256_file(memory_path)
        ),
        "manifest_digest": manifest_path.is_file()
        and receipt.get("manifest_sha256") == sha256_file(manifest_path),
        "frozen_candidate_paths": (
            receipt.get("frozen_candidate_paths")
            == gates["candidate"]["frozen_paths"]
        ),
        "clean_tracked_commit": (
            not requirements["require_clean_tracked_commit"]
            or not receipt["repository"]["tracked_status"]
        ),
        "eligible_preflight_load": (
            float(receipt["normalized_preflight_load_1m"])
            <= float(validation["max_normalized_preflight_load_1m"])
        ),
        "frozen_codec_roster": observed_codecs == expected_codecs,
        "frozen_execution": (
            int(config["repetitions"]) >= int(validation["minimum_repetitions"])
            and int(config["warmups"]) == int(validation["warmups"])
            and config["execution_mode"] == validation["execution_mode"]
            and int(config["order_seed"]) == int(validation["order_seed"])
            and config["splits"] == [validation["expected_split"]]
            and int(memory_config["repetitions"])
            == int(validation["memory_repetitions"])
            and memory_config["execution_mode"]
            == validation["memory_execution_mode"]
        ),
        "frozen_corpus": observed_items == expected_ids and memory_items == expected_ids,
        "manifest_identity": [
            {
                "id": item["id"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
                "split": item["split"],
                "license_spdx": item["license_spdx"],
            }
            for item in manifest.get("items", [])
        ]
        == corpus_identity(performance),
        "shared_corpus": corpus_identity(performance) == corpus_identity(memory),
        "all_baselines_present": (
            not requirements["require_all_baselines_present"]
            or set(summaries) == set(expected_codecs)
        ),
        "no_benchmark_failures": (
            not requirements["require_no_benchmark_failures"]
            or (not performance["failures"] and not memory["failures"])
        ),
        "exact_roundtrip": (
            not requirements["require_exact_roundtrip_for_every_trial"]
            or (all_performance_trials_exact and all_memory_trials_exact and proof_exact)
        ),
        "deterministic_output": (
            not requirements["require_deterministic_output"] or proof_deterministic
        ),
        "complete_frame_accounting": (
            not requirements["require_complete_frame_accounting"]
            or (complete_frame_accounting and proof_accounting)
        ),
        "equally_framed_fallback": proof_fallback,
        "aggregate_ratio": aggregate_gain
        >= float(
            requirements[
                "minimum_aggregate_gain_vs_strongest_complete_exact_byte_baseline_percent"
            ]
        ),
        "family_ratio_count": family_pass_count
        >= int(
            requirements[
                "minimum_families_with_five_percent_gain_vs_strongest_complete_exact_byte_baseline"
            ]
        ),
        "compression_speed": float(candidate_summary.get("compression_mbps", 0.0))
        >= float(requirements["minimum_aggregate_compression_mbps"]),
        "decompression_speed": float(
            candidate_summary.get("decompression_mbps", 0.0)
        )
        >= float(requirements["minimum_aggregate_decompression_mbps"]),
        "minimum_repetition_compression_speed": len(repetitions)
        >= int(validation["minimum_repetitions"])
        and min((row["compression_mbps"] for row in repetitions), default=0.0)
        >= float(requirements["minimum_repetition_compression_mbps"]),
        "minimum_repetition_decompression_speed": len(repetitions)
        >= int(validation["minimum_repetitions"])
        and min((row["decompression_mbps"] for row in repetitions), default=0.0)
        >= float(requirements["minimum_repetition_decompression_mbps"]),
        "cold_compression_memory": compression_peak_mib
        <= float(requirements["maximum_cold_compression_peak_rss_mib"]),
        "cold_decompression_memory": decompression_peak_mib
        <= float(requirements["maximum_cold_decompression_peak_rss_mib"]),
        "portable_reference_decoder": (
            not requirements["require_portable_reference_decoder"]
            or "tests/test_tabular_transform.py"
            in gates["candidate"]["frozen_paths"]
        ),
        "private_holdout_sealed": gates["private_holdout"]["status"] == "sealed",
    }

    comparison_chart: list[dict[str, Any]] = []
    for codec_id in expected_codecs:
        row = summaries.get(codec_id)
        if row is None:
            comparison_chart.append({"codec": codec_id, "tested": False})
            continue
        comparison_chart.append(
            {
                "codec": codec_id,
                "tested": True,
                "complete_bytes": int(row["compressed_bytes"]),
                "candidate_improvement_percent": (
                    0.0
                    if codec_id == candidate_id
                    else gain(int(row["compressed_bytes"]), candidate_bytes)
                ),
                "compression_mbps": float(row["compression_mbps"]),
                "decompression_mbps": float(row["decompression_mbps"]),
                "worker_high_water_compression_rss_mib": float(
                    row["compression_peak_rss_bytes"]
                )
                / (1024 * 1024),
                "worker_high_water_decompression_rss_mib": float(
                    row["decompression_peak_rss_bytes"]
                )
                / (1024 * 1024),
                "roundtrip_failures": int(row["roundtrip_failures"]),
                "candidate_smaller": candidate_bytes < int(row["compressed_bytes"])
                if codec_id != candidate_id
                else None,
            }
        )

    passed = all(gate_results.values())
    payload = {
        "schema_version": 1,
        "stage": "public-validation",
        "status": "passed" if passed else "not_passed",
        "claim_ceiling": gates["claim_ceiling"],
        "decision_rule": gates["decision_rule"],
        "private_holdout": gates["private_holdout"],
        "receipt_path": str(args.receipt),
        "receipt_sha256": sha256_file(args.receipt),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "candidate": {
            "codec": candidate_id,
            "complete_bytes": candidate_bytes,
            "strongest_fixed_baseline": strongest_summary.get("codec_id"),
            "strongest_fixed_baseline_bytes": strongest_bytes,
            "aggregate_gain_percent": aggregate_gain,
            "compression_mbps": float(candidate_summary.get("compression_mbps", 0.0)),
            "decompression_mbps": float(
                candidate_summary.get("decompression_mbps", 0.0)
            ),
            "minimum_repetition_compression_mbps": min(
                (row["compression_mbps"] for row in repetitions), default=0.0
            ),
            "minimum_repetition_decompression_mbps": min(
                (row["decompression_mbps"] for row in repetitions), default=0.0
            ),
            "cold_compression_peak_rss_mib": compression_peak_mib,
            "cold_decompression_peak_rss_mib": decompression_peak_mib,
        },
        "families": family_rows,
        "repetitions": repetitions,
        "comparison_chart": comparison_chart,
        "gate_results": gate_results,
        "passed": passed,
    }
    write_json_atomic(args.output, payload)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
