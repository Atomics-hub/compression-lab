#!/usr/bin/env python3
"""Evaluate the frozen first-score CLUE-LDS JLS2 v2 validation gate.

Candidate compression and standalone decode peak RSS are taken from the
clean-child instrument rows carried in the receipt. Each candidate resource
reading is eligible only when its shim floor is within the frozen bounds; an
ineligible reading fails the shim-floor gate rather than being scored as a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def percentage_gain(reference_bytes: int, candidate_bytes: int) -> float:
    if reference_bytes <= 0:
        raise ValueError("reference byte count must be positive")
    return (reference_bytes - candidate_bytes) / reference_bytes * 100.0


def exact_roster(rows: list[dict[str, Any]], expected: list[str]) -> bool:
    return [row.get("id", row.get("codec_id")) for row in rows] == expected


def evaluate(
    receipt: dict[str, Any],
    performance: dict[str, Any],
    pbc: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    if not receipt.get("first_score") or not receipt.get("completed"):
        raise ValueError("JLS2 v2 first-score receipt is incomplete")
    if performance.get("schema_version") != 5:
        raise ValueError("CLUE validation requires benchmark schema version 5")
    if performance.get("failures"):
        raise ValueError("standard benchmark contains failed trials")
    if not pbc.get("passed"):
        raise ValueError("PBC specialist reproduction did not pass")

    validation = gates["validation"]
    requirements = gates["requirements"]
    candidate_id = gates["candidate"]["codec_id"]
    standard_ids = gates["baselines"]["standard_codec_ids"]
    expected_ids = [row["id"] for row in validation["expected_items"]]
    family_by_id = {row["id"]: row["family"] for row in validation["expected_items"]}
    medians = performance["medians"]
    summaries = {row["codec_id"]: row for row in performance["summary"]}
    expected_codecs = [candidate_id, *standard_ids]
    observed_codecs = [row["id"] for row in performance["codecs"]]
    if observed_codecs != expected_codecs:
        raise ValueError("standard codec roster or order differs from frozen contract")
    if set(summaries) != set(expected_codecs):
        raise ValueError("aggregate summary codec roster differs from frozen contract")

    pbc_method = gates["baselines"]["specialist"]["method"]
    pbc_rows = [row for row in pbc["rows"] if row["method"] == pbc_method]
    if len(pbc_rows) != len(expected_ids):
        raise ValueError("PBC family row count differs from frozen contract")
    pbc_by_family = {row["family"]: row for row in pbc_rows}
    if list(pbc_by_family) != [family_by_id[item_id] for item_id in expected_ids]:
        raise ValueError("PBC family roster or order differs from frozen contract")

    family_rows = []
    for item_id in expected_ids:
        family = family_by_id[item_id]
        by_codec = {
            row["codec_id"]: row for row in medians if row["item_id"] == item_id
        }
        if set(by_codec) != set(expected_codecs):
            raise ValueError(
                f"family codec roster differs from frozen contract: {item_id}"
            )
        candidate = by_codec[candidate_id]
        competitors = [
            {
                "codec_id": codec_id,
                "compressed_bytes": int(by_codec[codec_id]["compressed_bytes"]),
                "role": "standard",
            }
            for codec_id in standard_ids
        ]
        specialist = pbc_by_family[family]
        if specialist["source_sha256"] != candidate["source_sha256"]:
            raise ValueError(f"PBC source digest differs for {family}")
        if int(specialist["original_bytes"]) != int(candidate["original_bytes"]):
            raise ValueError(f"PBC source size differs for {family}")
        competitors.append(
            {
                "codec_id": "pbc-only",
                "compressed_bytes": int(specialist["archive_bytes"]),
                "role": "eligible specialist",
            }
        )
        strongest = min(competitors, key=lambda row: row["compressed_bytes"])
        candidate_bytes = int(candidate["compressed_bytes"])
        gain = percentage_gain(strongest["compressed_bytes"], candidate_bytes)
        family_rows.append(
            {
                "item_id": item_id,
                "family": family,
                "original_bytes": int(candidate["original_bytes"]),
                "candidate_bytes": candidate_bytes,
                "strongest_eligible_codec": strongest["codec_id"],
                "strongest_eligible_bytes": strongest["compressed_bytes"],
                "gain_vs_strongest_eligible_percent": gain,
                "ratio_gate_passed": gain
                >= requirements[
                    "minimum_family_gain_vs_strongest_complete_exact_byte_baseline_percent"
                ],
            }
        )

    candidate_summary = summaries[candidate_id]
    standard_summaries = [summaries[codec_id] for codec_id in standard_ids]
    pbc_aggregate = pbc["aggregates"][pbc_method]
    aggregate_competitors = [
        {
            "codec_id": row["codec_id"],
            "compressed_bytes": int(row["compressed_bytes"]),
            "role": "standard",
        }
        for row in standard_summaries
    ] + [
        {
            "codec_id": "pbc-only",
            "compressed_bytes": int(pbc_aggregate["archive_bytes"]),
            "role": "eligible specialist",
        }
    ]
    strongest_aggregate = min(
        aggregate_competitors, key=lambda row: row["compressed_bytes"]
    )
    candidate_bytes = int(candidate_summary["compressed_bytes"])
    aggregate_gain = percentage_gain(
        strongest_aggregate["compressed_bytes"], candidate_bytes
    )

    proof = receipt["candidate_proof"]
    decode = proof["standalone_decode_summary"]
    compression_rss = proof["compression_rss_summary"]
    candidate_compression_peak = int(compression_rss["peak_rss_bytes"])
    candidate_decode_peak = int(decode["peak_rss_bytes"])
    deterministic_rows = proof["deterministic_rows"]
    candidate_trials = [
        row for row in performance["trials"] if row["codec_id"] == candidate_id
    ]
    measured_decode_trials = [
        row for row in proof["standalone_decode_trials"] if not row["warmup"]
    ]
    ratio_family_passes = sum(row["ratio_gate_passed"] for row in family_rows)
    shim_floor_eligible = (
        bool(compression_rss["all_shim_floor_eligible"])
        and bool(decode["all_shim_floor_eligible"])
        and all(row["shim_floor_eligible"] for row in proof["compression_rss_rows"])
        and all(row["shim_floor_eligible"] for row in measured_decode_trials)
    )
    gate_results = {
        "aggregate_ratio": aggregate_gain
        >= requirements[
            "minimum_aggregate_gain_vs_strongest_complete_exact_byte_baseline_percent"
        ],
        "all_family_ratio": ratio_family_passes
        >= requirements["minimum_families_passing_ratio_gate"],
        "aggregate_compression_speed": float(candidate_summary["compression_mbps"])
        >= requirements["minimum_aggregate_compression_mbps"],
        "minimum_compression_repetition_speed": min(
            float(row["compression_mbps"]) for row in candidate_trials
        )
        >= requirements["minimum_repetition_compression_mbps"],
        "aggregate_standalone_decompression_speed": float(
            decode["median_aggregate_mbps"]
        )
        >= requirements["minimum_aggregate_standalone_decompression_mbps"],
        "minimum_standalone_decompression_repetition_speed": min(
            float(row["mbps"]) for row in measured_decode_trials
        )
        >= requirements["minimum_repetition_standalone_decompression_mbps"],
        "clean_child_shim_floor_eligibility": shim_floor_eligible,
        "compression_memory": candidate_compression_peak
        <= requirements["maximum_cold_compression_peak_rss_bytes"],
        "decompression_memory": candidate_decode_peak
        <= requirements["maximum_cold_decompression_peak_rss_bytes"],
        "exact_roundtrip": all(row["roundtrip_ok"] for row in performance["trials"])
        and bool(decode["all_exact"]),
        "deterministic_output": all(row["deterministic"] for row in deterministic_rows),
        "corruption_rejection": all(
            row["corruption_rejected"] for row in deterministic_rows
        ),
        "bounded_direct_fallback": all(
            row["fallback_safety"]["maximum_regression_bytes"]
            <= requirements[
                "maximum_segment_regression_vs_equally_framed_direct_fallback_bytes"
            ]
            for row in deterministic_rows
        ),
        "complete_frame_accounting": all(
            row["fallback_safety"].get("complete_frame_accounting", False)
            and row["fallback_safety"].get("stream_bytes")
            == row["fallback_safety"].get("accounted_stream_bytes")
            for row in deterministic_rows
        ),
        "complete_standard_roster": exact_roster(
            performance["codecs"], expected_codecs
        ),
        "pbc_specialist_present": pbc["decision"]["primary_method"] == pbc_method,
        "frozen_candidate_paths": receipt["frozen_candidate_paths"]
        == gates["candidate"]["frozen_paths"],
        "development_evidence": len(receipt["verified_development_evidence"]) == 3,
        "first_score_receipt": bool(receipt["first_score"] and receipt["completed"]),
        "unavailable_markers": set(gates["baselines"]["unavailable_context"])
        == {"LogFold", "LogPrism", "LogLite", "DeLog"},
    }

    comparison_rows = []
    for codec_id in expected_codecs:
        row = summaries[codec_id]
        is_candidate = codec_id == candidate_id
        comparison_rows.append(
            {
                "codec_id": codec_id,
                "role": "candidate" if is_candidate else "standard",
                "compressed_bytes": int(row["compressed_bytes"]),
                "ratio": int(row["original_bytes"]) / int(row["compressed_bytes"]),
                "compression_mbps": float(row["compression_mbps"]),
                "decompression_mbps": (
                    float(decode["median_aggregate_mbps"])
                    if is_candidate
                    else float(row["decompression_mbps"])
                ),
                "compression_peak_rss_bytes": (
                    candidate_compression_peak
                    if is_candidate
                    else int(row["compression_peak_rss_bytes"])
                ),
                "decompression_peak_rss_bytes": (
                    candidate_decode_peak
                    if is_candidate
                    else int(row["decompression_peak_rss_bytes"])
                ),
                "exact_roundtrip": int(row["roundtrip_failures"]) == 0,
                "size_runner": "same-run complete-file",
                "speed_runner": (
                    "standalone native pass on same host and corpus"
                    if is_candidate
                    else "same-run complete-file"
                ),
                "memory_runner": (
                    "clean-child instrument (measure-clean-rss.py)"
                    if is_candidate
                    else "same-run cold-process worker"
                ),
                "candidate_smaller": (
                    None
                    if is_candidate
                    else candidate_bytes < int(row["compressed_bytes"])
                ),
            }
        )
    comparison_rows.append(
        {
            "codec_id": "pbc-only",
            "role": "eligible specialist",
            "compressed_bytes": int(pbc_aggregate["archive_bytes"]),
            "ratio": int(pbc_aggregate["original_bytes"])
            / int(pbc_aggregate["archive_bytes"]),
            "compression_mbps": float(pbc_aggregate["complete_compression_mbps"]),
            "decompression_mbps": float(pbc_aggregate["decompression_mbps"]),
            "compression_peak_rss_bytes": None,
            "decompression_peak_rss_bytes": None,
            "exact_roundtrip": True,
            "size_runner": "identical bytes; separate pinned specialist run",
            "speed_runner": "separate pinned specialist run; contextual",
            "memory_runner": "not measured",
            "candidate_smaller": candidate_bytes < int(pbc_aggregate["archive_bytes"]),
        }
    )
    for name in gates["baselines"]["unavailable_context"]:
        comparison_rows.append(
            {
                "codec_id": name,
                "role": "unavailable specialist context",
                "compressed_bytes": None,
                "ratio": None,
                "compression_mbps": None,
                "decompression_mbps": None,
                "compression_peak_rss_bytes": None,
                "decompression_peak_rss_bytes": None,
                "exact_roundtrip": None,
                "size_runner": "unavailable or ineligible",
                "speed_runner": "unavailable or ineligible",
                "memory_runner": "unavailable or ineligible",
                "candidate_smaller": None,
            }
        )

    passed = all(gate_results.values())
    return {
        "schema_version": 1,
        "name": "clue-jls2-public-validation-v2-first-score",
        "stage": "public-validation",
        "result": "passed" if passed else "not_passed",
        "category_gate_passed": passed,
        "claim_ceiling": gates["claim_ceiling"],
        "decision_rule": gates["decision_rule"],
        "prior_score": gates["prior_score"],
        "aggregate": {
            "original_bytes": int(candidate_summary["original_bytes"]),
            "candidate_bytes": candidate_bytes,
            "strongest_eligible_codec": strongest_aggregate["codec_id"],
            "strongest_eligible_bytes": strongest_aggregate["compressed_bytes"],
            "gain_vs_strongest_eligible_percent": aggregate_gain,
            "compression_mbps": float(candidate_summary["compression_mbps"]),
            "standalone_decompression_mbps": float(decode["median_aggregate_mbps"]),
            "compression_peak_rss_bytes": candidate_compression_peak,
            "standalone_decompression_peak_rss_bytes": candidate_decode_peak,
            "compression_shim_maxrss_bytes": int(
                compression_rss["worst_shim_maxrss_bytes"]
            ),
            "standalone_decompression_shim_maxrss_bytes": int(
                decode["worst_shim_maxrss_bytes"]
            ),
        },
        "family_rows": family_rows,
        "gate_results": gate_results,
        "comparison_rows": comparison_rows,
        "unavailable_is_not_a_win": True,
        "private_holdout": gates["private_holdout"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--pbc", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists():
        raise SystemExit("refusing to replace the first-score decision")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    performance = json.loads(args.performance.read_text(encoding="utf-8"))
    pbc = json.loads(args.pbc.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    result = evaluate(receipt, performance, pbc, gates)
    result["sources"] = {
        "receipt_sha256": sha256_file(args.receipt),
        "performance_sha256": sha256_file(args.performance),
        "pbc_sha256": sha256_file(args.pbc),
        "gates_sha256": sha256_file(args.gates),
    }
    write_json_atomic(args.output, result)
    print(json.dumps(result["gate_results"], indent=2, sort_keys=True))
    return 0 if result["category_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
