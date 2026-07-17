#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, cast


REPOSITORY = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def throughput(byte_count: int, elapsed_ns: int) -> float:
    return byte_count / elapsed_ns * 1000.0 if byte_count > 0 and elapsed_ns > 0 else 0.0


def size_delta(candidate_bytes: int, reference_bytes: int) -> float:
    return (
        (candidate_bytes - reference_bytes) / reference_bytes * 100.0
        if reference_bytes
        else 0.0
    )


def build_comparison(
    *,
    gates: dict[str, Any],
    decision: dict[str, Any],
    baseline: dict[str, Any],
    baseline_memory: dict[str, Any],
    candidate: dict[str, Any],
    candidate_memory: dict[str, Any],
) -> dict[str, Any]:
    expected_ids = [item["id"] for item in gates["validation"]["expected_items"]]
    baseline_ids = list(gates["baselines"]["codec_ids"])
    candidate_summary = candidate["summary"]
    candidate_bytes = int(candidate_summary["compressed_bytes"])
    original_bytes = int(candidate_summary["original_bytes"])
    candidate_memory_summary = candidate_memory["summary"]

    rows = [
        {
            "codec": "dms2-stream",
            "complete_bytes": candidate_bytes,
            "compressed_percent": candidate_bytes / original_bytes * 100.0,
            "dms2_size_delta_percent": 0.0,
            "compression_mbps": float(candidate_summary["compression_mbps"]),
            "decompression_mbps": float(candidate_summary["decompression_mbps"]),
            "cold_compression_peak_rss_mib": float(
                candidate_memory_summary["compression_peak_rss_bytes"]
            )
            / (1024 * 1024),
            "cold_decompression_peak_rss_mib": float(
                candidate_memory_summary["decompression_peak_rss_bytes"]
            )
            / (1024 * 1024),
            "exact": all(row["roundtrip_ok"] for row in candidate["trials"]),
            "dms2_smaller": None,
        }
    ]
    performance = {
        (str(row["item_id"]), str(row["codec_id"])): row
        for row in baseline["medians"]
        if row["item_id"] in expected_ids
    }
    memory = {
        (str(row["item_id"]), str(row["codec_id"])): row
        for row in baseline_memory["medians"]
        if row["item_id"] in expected_ids
    }
    for codec_id in baseline_ids:
        codec_rows = [performance[(item_id, codec_id)] for item_id in expected_ids]
        memory_rows = [memory[(item_id, codec_id)] for item_id in expected_ids]
        compressed_bytes = sum(int(row["compressed_bytes"]) for row in codec_rows)
        rows.append(
            {
                "codec": codec_id,
                "complete_bytes": compressed_bytes,
                "compressed_percent": compressed_bytes / original_bytes * 100.0,
                "dms2_size_delta_percent": size_delta(candidate_bytes, compressed_bytes),
                "compression_mbps": throughput(
                    original_bytes,
                    sum(int(row["compression_ns"]) for row in codec_rows),
                ),
                "decompression_mbps": throughput(
                    original_bytes,
                    sum(int(row["decompression_ns"]) for row in codec_rows),
                ),
                "cold_compression_peak_rss_mib": max(
                    int(row["compression_peak_rss_bytes"]) for row in memory_rows
                )
                / (1024 * 1024),
                "cold_decompression_peak_rss_mib": max(
                    int(row["decompression_peak_rss_bytes"]) for row in memory_rows
                )
                / (1024 * 1024),
                "exact": all(
                    row["roundtrip_ok"]
                    for row in baseline["trials"]
                    if row["item_id"] in expected_ids and row["codec_id"] == codec_id
                ),
                "dms2_smaller": candidate_bytes < compressed_bytes,
            }
        )

    strongest = min(
        rows[1:], key=lambda row: cast(int, row["complete_bytes"])
    )
    strongest_bytes = cast(int, strongest["complete_bytes"])
    return {
        "schema_version": 1,
        "name": "dms2-public-validation-first-score-publication-v1",
        "status": "not_passed",
        "frozen_decision_passed": bool(decision["passed"]),
        "expected_item_ids": expected_ids,
        "candidate_corpus_ids": [item["id"] for item in candidate["corpus"]],
        "baseline_corpus_ids": [item["id"] for item in baseline["corpus"]],
        "original_bytes": original_bytes,
        "candidate_bytes": candidate_bytes,
        "strongest_baseline": strongest["codec"],
        "strongest_baseline_bytes": strongest_bytes,
        "candidate_vs_strongest_percent": size_delta(
            candidate_bytes, strongest_bytes
        ),
        "families": decision["families"],
        "comparison_chart": rows,
        "gate_results": decision["gate_results"],
        "validity": {
            "frozen_aggregate_gate_valid": False,
            "reason": (
                "The baseline runner opened the four-item acquisition manifest while "
                "the candidate used the two-item locked projection."
            ),
            "two_item_ratio_diagnostic_valid": True,
            "two_item_ratio_basis": (
                "Exact complete candidate frames and per-item baseline medians for "
                "the two predeclared IDs from the retained first attempt."
            ),
            "speed_comparability": (
                "Contextual same-host medians. Baselines and candidate ran in adjacent "
                "batches, and the baseline schedule included two extra unscored items."
            ),
            "cold_memory_comparability": (
                "Same-host cold-process peak RSS restricted to the two predeclared IDs."
            ),
        },
        "claim_ceiling": (
            "The frozen DMS2 public-validation gate did not pass. These rows disclose "
            "the retained first attempt and support no category-win or state-of-the-art claim."
        ),
    }


def format_bool(value: bool | None) -> str:
    if value is None:
        return "candidate"
    return "yes" if value else "no"


def render_report(comparison: dict[str, Any]) -> str:
    lines = [
        "# DMS2 public-validation first score",
        "",
        "Status: **not passed**.",
        "",
        (
            f"On {comparison['original_bytes']:,} locked Gisette and Madelon bytes, "
            f"DMS2 produced {comparison['candidate_bytes']:,} bytes. The strongest "
            f"two-item baseline was {comparison['strongest_baseline']} at "
            f"{comparison['strongest_baseline_bytes']:,} bytes, so DMS2 was "
            f"{comparison['candidate_vs_strongest_percent']:.2f}% larger."
        ),
        "",
        "## Family decisions",
        "",
        "| Family | DMS2 bytes | Strongest standard | Standard bytes | DMS2 delta | Passed |",
        "| --- | ---: | --- | ---: | ---: | --- |",
    ]
    for family in comparison["families"]:
        family_delta = -float(family["improvement_percent"])
        lines.append(
            f"| `{family['id']}` | {family['candidate_bytes']:,} | "
            f"{family['strongest_baseline']} | {family['strongest_baseline_bytes']:,} | "
            f"{family_delta:.2f}% larger | {'yes' if family['passed'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Two-item diagnostic comparison",
            "",
            "| Codec | Complete bytes | DMS2 delta | Compress MB/s | Decompress MB/s | Cold RSS C/D MiB | Exact | DMS2 smaller? |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in comparison["comparison_chart"]:
        comparison_delta = (
            "candidate"
            if row["codec"] == "dms2-stream"
            else f"{row['dms2_size_delta_percent']:+.2f}%"
        )
        lines.append(
            f"| {row['codec']} | {row['complete_bytes']:,} | {comparison_delta} | "
            f"{row['compression_mbps']:.2f} | {row['decompression_mbps']:.2f} | "
            f"{row['cold_compression_peak_rss_mib']:.1f} / "
            f"{row['cold_decompression_peak_rss_mib']:.1f} | "
            f"{'yes' if row['exact'] else 'no'} | {format_bool(row['dms2_smaller'])} |"
        )
    failed = [name for name, passed in comparison["gate_results"].items() if not passed]
    lines.extend(
        [
            "",
            "## Decision and comparability",
            "",
            f"Failed frozen gates: {', '.join(f'`{name}`' for name in failed)}.",
            "",
            comparison["validity"]["reason"],
            comparison["validity"]["speed_comparability"],
            comparison["validity"]["cold_memory_comparability"],
            "",
            comparison["claim_ceiling"],
            "",
        ]
    )
    return "\n".join(lines)


def publish(
    *,
    score_dir: Path,
    acquisition_manifest: Path,
    projected_manifest: Path,
    acquisition_receipt: Path,
    gates_path: Path,
    output: Path,
) -> Path:
    if output.exists():
        raise ValueError("refusing to replace an existing public-validation bundle")
    receipt = json.loads((score_dir / "receipt.json").read_text(encoding="utf-8"))
    decision = json.loads((score_dir / "decision.json").read_text(encoding="utf-8"))
    gates = json.loads(gates_path.read_text(encoding="utf-8"))
    if not receipt.get("completed") or decision.get("status") != "not_passed":
        raise ValueError("first score is not a completed frozen no-pass decision")
    if receipt["manifest_sha256"] != sha256_file(projected_manifest):
        raise ValueError("projected manifest digest differs from first-score receipt")
    if decision["receipt_sha256"] != sha256_file(score_dir / "receipt.json"):
        raise ValueError("decision does not bind the retained receipt")

    baseline = json.loads(
        (score_dir / "baseline-performance" / "results.json").read_text()
    )
    baseline_memory = json.loads(
        (score_dir / "baseline-memory" / "results.json").read_text()
    )
    candidate = json.loads((score_dir / "candidate-performance.json").read_text())
    candidate_memory = json.loads((score_dir / "candidate-memory.json").read_text())
    comparison = build_comparison(
        gates=gates,
        decision=decision,
        baseline=baseline,
        baseline_memory=baseline_memory,
        candidate=candidate,
        candidate_memory=candidate_memory,
    )

    output.mkdir(parents=True)
    sources = {
        "attempt.json": score_dir / "attempt.json",
        "receipt.json": score_dir / "receipt.json",
        "decision.json": score_dir / "decision.json",
        "baseline-performance.json": score_dir / "baseline-performance" / "results.json",
        "baseline-memory.json": score_dir / "baseline-memory" / "results.json",
        "candidate-performance.json": score_dir / "candidate-performance.json",
        "candidate-memory.json": score_dir / "candidate-memory.json",
        "acquisition-manifest.json": acquisition_manifest,
        "scoring-manifest.json": projected_manifest,
        "acquisition-receipt.json": acquisition_receipt,
        "gates.json": gates_path,
    }
    artifact_digests = {}
    for name, source in sources.items():
        destination = output / name
        shutil.copyfile(source, destination)
        artifact_digests[name] = sha256_file(destination)
    (output / "comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    artifact_digests["comparison.json"] = sha256_file(output / "comparison.json")
    (output / "README.md").write_text(render_report(comparison), encoding="utf-8")
    artifact_digests["README.md"] = sha256_file(output / "README.md")
    bundle = {
        "schema_version": 1,
        "name": "dms2-public-validation-first-score-bundle-v1",
        "status": "not_passed",
        "artifacts": artifact_digests,
        "claim_ceiling": comparison["claim_ceiling"],
    }
    (output / "bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output / "bundle.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish the immutable DMS2 first public-validation score"
    )
    parser.add_argument("--score-dir", type=Path, required=True)
    parser.add_argument("--acquisition-manifest", type=Path, required=True)
    parser.add_argument("--projected-manifest", type=Path, required=True)
    parser.add_argument("--acquisition-receipt", type=Path, required=True)
    parser.add_argument(
        "--gates",
        type=Path,
        default=REPOSITORY / "config" / "dms2-public-validation-gates.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = publish(
            score_dir=args.score_dir,
            acquisition_manifest=args.acquisition_manifest,
            projected_manifest=args.projected_manifest,
            acquisition_receipt=args.acquisition_receipt,
            gates_path=args.gates,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise SystemExit(f"DMS2 publication refused: {error}") from error
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
