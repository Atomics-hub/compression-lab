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


REPOSITORY = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def gain(reference: int, candidate: int) -> float:
    return (reference - candidate) / reference * 100.0 if reference else 0.0


def throughput(byte_count: int, elapsed_ns: int) -> float:
    if byte_count <= 0 or elapsed_ns <= 0:
        return 0.0
    return byte_count / elapsed_ns * 1000.0


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
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


def by_codec(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["codec_id"]): row for row in rows}


def baseline_medians_by_item(
    result: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in result["medians"]:
        grouped[str(row["item_id"])][str(row["codec_id"])] = row
    return dict(grouped)


def repetition_aggregates(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate["trials"]:
        grouped[int(row["repetition"])].append(row)
    output = []
    for repetition, rows in sorted(grouped.items()):
        source_bytes = sum(int(row["original_bytes"]) for row in rows)
        output.append(
            {
                "repetition": repetition,
                "items": len(rows),
                "original_bytes": source_bytes,
                "compression_mbps": throughput(
                    source_bytes,
                    sum(int(row["compression_ns"]) for row in rows),
                ),
                "decompression_mbps": throughput(
                    source_bytes,
                    sum(int(row["decompression_ns"]) for row in rows),
                ),
            }
        )
    return output


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
        description="Evaluate the frozen first-score DMS2 public-validation gate"
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    requirements = gates["requirements"]
    validation = gates["validation"]
    expected = validation["expected_items"]
    expected_ids = [row["id"] for row in expected]
    baseline_ids = gates["baselines"]["codec_ids"]
    base = args.receipt.parent
    paths = {
        "baseline_performance": base
        / receipt.get("baseline_performance_results", "missing"),
        "baseline_memory": base / receipt.get("baseline_memory_results", "missing"),
        "candidate_performance": base
        / receipt.get("candidate_performance_results", "missing"),
        "candidate_memory": base
        / receipt.get("candidate_memory_results", "missing"),
    }
    if not receipt.get("completed") or not all(path.is_file() for path in paths.values()):
        write_json_atomic(
            args.output,
            {
                "schema_version": 1,
                "stage": "public-validation",
                "status": "not_passed",
                "claim_ceiling": gates["claim_ceiling"],
                "passed": False,
                "gate_results": {"first_score_completed": False},
                "retained_error": receipt.get(
                    "error", "scored attempt did not complete"
                ),
            },
        )
        return 2

    baseline = json.loads(paths["baseline_performance"].read_text())
    baseline_memory = json.loads(paths["baseline_memory"].read_text())
    candidate = json.loads(paths["candidate_performance"].read_text())
    candidate_memory = json.loads(paths["candidate_memory"].read_text())
    manifest_path = Path(receipt.get("manifest_path", "missing"))
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.is_file()
        else {"items": []}
    )
    baseline_summaries = by_codec(baseline["summary"])
    baseline_memory_summaries = by_codec(baseline_memory["summary"])
    medians_by_item = baseline_medians_by_item(baseline)
    candidate_medians = {
        str(row["item_id"]): row for row in candidate["medians"]
    }
    candidate_summary = candidate["summary"]
    candidate_memory_summary = candidate_memory["summary"]
    repetitions = repetition_aggregates(candidate)

    families = []
    for item in expected:
        item_id = item["id"]
        candidate_row = candidate_medians.get(item_id)
        baselines = medians_by_item.get(item_id, {})
        if candidate_row is None or not all(
            codec_id in baselines for codec_id in baseline_ids
        ):
            families.append(
                {
                    "id": item_id,
                    "family": item["family"],
                    "complete": False,
                    "passed": False,
                }
            )
            continue
        strongest = min(
            (baselines[codec_id] for codec_id in baseline_ids),
            key=lambda row: int(row["compressed_bytes"]),
        )
        improvement = gain(
            int(strongest["compressed_bytes"]),
            int(candidate_row["compressed_bytes"]),
        )
        families.append(
            {
                "id": item_id,
                "family": item["family"],
                "complete": True,
                "original_bytes": int(candidate_row["original_bytes"]),
                "candidate_bytes": int(candidate_row["compressed_bytes"]),
                "strongest_baseline": strongest["codec_id"],
                "strongest_baseline_bytes": int(strongest["compressed_bytes"]),
                "improvement_percent": improvement,
                "passed": improvement
                >= float(requirements["minimum_family_gain_percent"]),
            }
        )

    strongest_summary = min(
        (baseline_summaries[codec_id] for codec_id in baseline_ids),
        key=lambda row: int(row["compressed_bytes"]),
    )
    candidate_bytes = int(candidate_summary["compressed_bytes"])
    strongest_bytes = int(strongest_summary["compressed_bytes"])
    aggregate_gain = gain(strongest_bytes, candidate_bytes)
    proof = receipt.get("deterministic_integrity_fallback_proof", [])
    proof_by_id = {row.get("id"): row for row in proof}
    proof_complete = list(proof_by_id) == expected_ids
    manifest_identity = [
        {
            "id": item["id"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "split": item["split"],
            "license_spdx": item["license_spdx"],
        }
        for item in manifest.get("items", [])
    ]
    baseline_identity = corpus_identity(baseline)
    candidate_identity = corpus_identity(candidate)
    baseline_codecs = [row["id"] for row in baseline["codecs"]]
    candidate_trials_exact = all(
        row["roundtrip_ok"] and row["source_sha256"] == row["restored_sha256"]
        for row in candidate["trials"]
    )
    baseline_trials_exact = all(
        row["roundtrip_ok"] and row["source_sha256"] == row["restored_sha256"]
        for row in baseline["trials"]
    )
    candidate_memory_exact = all(row["roundtrip_ok"] for row in candidate_memory["trials"])
    baseline_memory_exact = all(
        row["roundtrip_ok"] and row["source_sha256"] == row["restored_sha256"]
        for row in baseline_memory["trials"]
    )
    development = gates["development_evidence"]
    cross_platform = json.loads(
        (REPOSITORY / development["cross_platform_path"]).read_text()
    )
    platform_jobs = cross_platform.get("platform_jobs", {})
    cross_platform_passed = set(platform_jobs) == {"linux", "macos", "windows"} and all(
        jobs["full_suite"]["conclusion"] == "success"
        and jobs["native_wheel"]["conclusion"] == "success"
        for jobs in platform_jobs.values()
    )
    candidate_compression_rss = float(
        candidate_memory_summary["compression_peak_rss_bytes"]
    ) / (1024 * 1024)
    candidate_decompression_rss = float(
        candidate_memory_summary["decompression_peak_rss_bytes"]
    ) / (1024 * 1024)

    digest_fields = {
        "baseline_performance": "baseline_performance_sha256",
        "baseline_memory": "baseline_memory_sha256",
        "candidate_performance": "candidate_performance_sha256",
        "candidate_memory": "candidate_memory_sha256",
    }
    gate_results = {
        "first_score_completed": bool(receipt.get("first_score"))
        and bool(receipt.get("completed")),
        "lock_verified": bool(receipt.get("lock_receipt", {}).get("passed")),
        "gates_digest": receipt.get("gates_sha256") == sha256_file(args.gates),
        "result_digests": all(
            receipt.get(digest_fields[name]) == sha256_file(path)
            for name, path in paths.items()
        ),
        "manifest_digest": manifest_path.is_file()
        and receipt.get("manifest_sha256") == sha256_file(manifest_path),
        "frozen_candidate_paths": receipt.get("frozen_candidate_paths")
        == gates["candidate"]["frozen_paths"],
        "development_evidence_paths": receipt.get("development_evidence_paths")
        == {
            development["speed_ratio_path"]: development["speed_ratio_sha256"],
            development["operational_path"]: development["operational_sha256"],
            development["cross_platform_path"]: development[
                "cross_platform_sha256"
            ],
        },
        "clean_tracked_commit": not receipt["repository"]["tracked_status"],
        "eligible_preflight_load": float(receipt["normalized_preflight_load_1m"])
        <= float(validation["max_normalized_preflight_load_1m"]),
        "frozen_codec_roster": baseline_codecs == baseline_ids,
        "frozen_execution": (
            int(baseline["config"]["repetitions"])
            >= int(validation["minimum_repetitions"])
            and int(baseline["config"]["warmups"]) == int(validation["warmups"])
            and baseline["config"]["execution_mode"]
            == validation["baseline_execution_mode"]
            and candidate["config"]["execution_mode"]
            == validation["candidate_execution_mode"]
            and int(candidate["config"]["repetitions"])
            >= int(validation["minimum_repetitions"])
            and int(candidate["config"]["warmups"]) == int(validation["warmups"])
            and int(candidate["config"]["order_seed"])
            == int(validation["order_seed"])
            and baseline_memory["config"]["execution_mode"]
            == validation["memory_execution_mode"]
            and candidate_memory["config"]["execution_mode"]
            == validation["memory_execution_mode"]
        ),
        "frozen_corpus": [item["id"] for item in candidate["corpus"]]
        == expected_ids
        and [item["id"] for item in baseline["corpus"]] == expected_ids,
        "manifest_identity": manifest_identity
        == baseline_identity
        == candidate_identity,
        "shared_corpus": baseline_identity
        == candidate_identity
        == corpus_identity(baseline_memory),
        "all_baselines_present": set(baseline_summaries) == set(baseline_ids),
        "no_benchmark_failures": not baseline["failures"]
        and not baseline_memory["failures"]
        and not candidate["failures"],
        "exact_roundtrip": candidate_trials_exact
        and baseline_trials_exact
        and candidate_memory_exact
        and baseline_memory_exact
        and proof_complete
        and all(row["exact_roundtrip"] for row in proof),
        "deterministic_output": proof_complete
        and all(row["deterministic"] for row in proof),
        "corruption_rejection": proof_complete
        and all(row["corruption_rejected"] for row in proof),
        "complete_frame_accounting": candidate_bytes
        == sum(int(row["compressed_bytes"]) for row in candidate["medians"]),
        "equally_framed_fallback": proof_complete
        and all(
            row["fallback_safety"]["passed"]
            and int(row["fallback_safety"]["maximum_regression_bytes"])
            <= int(
                requirements[
                    "maximum_segment_regression_vs_equally_framed_direct_fallback_bytes"
                ]
            )
            for row in proof
        ),
        "aggregate_ratio": aggregate_gain
        >= float(
            requirements[
                "minimum_aggregate_gain_vs_strongest_complete_exact_byte_baseline_percent"
            ]
        ),
        "family_ratio_count": sum(row.get("passed", False) for row in families)
        >= int(
            requirements[
                "minimum_families_with_five_percent_gain_vs_strongest_complete_exact_byte_baseline"
            ]
        ),
        "compression_speed": float(candidate_summary["compression_mbps"])
        >= float(requirements["minimum_aggregate_compression_mbps"]),
        "decompression_speed": float(candidate_summary["decompression_mbps"])
        >= float(requirements["minimum_aggregate_decompression_mbps"]),
        "minimum_repetition_compression_speed": len(repetitions)
        >= int(validation["minimum_repetitions"])
        and min(row["compression_mbps"] for row in repetitions)
        >= float(requirements["minimum_repetition_compression_mbps"]),
        "minimum_repetition_decompression_speed": len(repetitions)
        >= int(validation["minimum_repetitions"])
        and min(row["decompression_mbps"] for row in repetitions)
        >= float(requirements["minimum_repetition_decompression_mbps"]),
        "cold_compression_memory": candidate_compression_rss
        <= float(requirements["maximum_cold_compression_peak_rss_mib"]),
        "cold_decompression_memory": candidate_decompression_rss
        <= float(requirements["maximum_cold_decompression_peak_rss_mib"]),
        "portable_reference_decoder": "tests/test_dense_matrix_transform.py"
        in gates["candidate"]["frozen_paths"],
        "cross_platform_wheels": cross_platform_passed,
        "private_holdout_sealed": gates["private_holdout"]["status"] == "sealed",
    }

    comparison_chart = [
        {
            "codec": "dms2-stream",
            "tested": True,
            "complete_bytes": candidate_bytes,
            "candidate_improvement_percent": 0.0,
            "compression_mbps": float(candidate_summary["compression_mbps"]),
            "decompression_mbps": float(candidate_summary["decompression_mbps"]),
            "cold_compression_peak_rss_mib": candidate_compression_rss,
            "cold_decompression_peak_rss_mib": candidate_decompression_rss,
            "roundtrip_failures": int(candidate_summary["roundtrip_failures"]),
            "candidate_smaller": None,
            "portable": cross_platform_passed,
        }
    ]
    for codec_id in baseline_ids:
        row = baseline_summaries[codec_id]
        memory = baseline_memory_summaries[codec_id]
        baseline_bytes = int(row["compressed_bytes"])
        comparison_chart.append(
            {
                "codec": codec_id,
                "tested": True,
                "complete_bytes": baseline_bytes,
                "candidate_improvement_percent": gain(
                    baseline_bytes, candidate_bytes
                ),
                "compression_mbps": float(row["compression_mbps"]),
                "decompression_mbps": float(row["decompression_mbps"]),
                "cold_compression_peak_rss_mib": float(
                    memory["compression_peak_rss_bytes"]
                )
                / (1024 * 1024),
                "cold_decompression_peak_rss_mib": float(
                    memory["decompression_peak_rss_bytes"]
                )
                / (1024 * 1024),
                "roundtrip_failures": int(row["roundtrip_failures"]),
                "candidate_smaller": candidate_bytes < baseline_bytes,
                "portable": True,
            }
        )

    passed = all(gate_results.values())
    payload = {
        "schema_version": 1,
        "stage": "public-validation",
        "status": "passed" if passed else "not_passed",
        "claim_ceiling": gates["claim_ceiling"],
        "decision_rule": gates["decision_rule"],
        "runner_comparability": {
            "ratio_and_exactness": "directly comparable: identical manifest bytes and complete artifacts",
            "speed": "contextual: same host and worker-wall scope, adjacent persistent batches, but candidate and baselines were not paired within one shuffled schedule",
            "memory": "directly comparable cold-process peak RSS on the same host",
        },
        "private_holdout": gates["private_holdout"],
        "receipt_path": str(args.receipt),
        "receipt_sha256": sha256_file(args.receipt),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "candidate": {
            "codec": "dms2-stream",
            "complete_bytes": candidate_bytes,
            "strongest_fixed_baseline": strongest_summary["codec_id"],
            "strongest_fixed_baseline_bytes": strongest_bytes,
            "aggregate_gain_percent": aggregate_gain,
            "compression_mbps": float(candidate_summary["compression_mbps"]),
            "decompression_mbps": float(candidate_summary["decompression_mbps"]),
            "minimum_repetition_compression_mbps": min(
                row["compression_mbps"] for row in repetitions
            ),
            "minimum_repetition_decompression_mbps": min(
                row["decompression_mbps"] for row in repetitions
            ),
            "cold_compression_peak_rss_mib": candidate_compression_rss,
            "cold_decompression_peak_rss_mib": candidate_decompression_rss,
        },
        "families": families,
        "repetitions": repetitions,
        "comparison_chart": comparison_chart,
        "gate_results": gate_results,
        "passed": passed,
    }
    write_json_atomic(args.output, payload)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
