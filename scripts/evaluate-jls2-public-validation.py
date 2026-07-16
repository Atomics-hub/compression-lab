#!/usr/bin/env python3
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


def percentage_gain(reference_bytes: int, candidate_bytes: int) -> float:
    return (reference_bytes - candidate_bytes) / reference_bytes * 100.0


def write_output(path: Path, payload: dict[str, Any]) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen first-score JLS2 validation gate"
    )
    parser.add_argument("--jls2", type=Path, required=True)
    parser.add_argument("--pbc", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    jls2 = json.loads(args.jls2.read_text(encoding="utf-8"))
    pbc = json.loads(args.pbc.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    requirements = gates["requirements"]
    validation = gates["validation"]
    baselines = gates["baselines"]
    expected_families = validation["expected_families"]

    if len(jls2["rows"]) != len(expected_families):
        raise SystemExit("JLS2 result has an unexpected row count")
    if len(pbc["rows"]) != len(expected_families):
        raise SystemExit("PBC result has an unexpected row count")
    jls2_by_family = {row["family"]: row for row in jls2["rows"]}
    pbc_by_family = {row["family"]: row for row in pbc["rows"]}
    if list(jls2_by_family) != expected_families:
        raise SystemExit("JLS2 families or order differ from frozen validation")
    if list(pbc_by_family) != expected_families:
        raise SystemExit("PBC families or order differ from frozen validation")

    rows: list[dict[str, Any]] = []
    for family in expected_families:
        candidate = jls2_by_family[family]
        competitor = pbc_by_family[family]
        if competitor["method"] != baselines["pbc_method"]:
            raise SystemExit(f"unexpected PBC method for {family}")
        if competitor["original_bytes"] != candidate["original_bytes"]:
            raise SystemExit(f"source size mismatch for {family}")
        if competitor["source_sha256"] != candidate["source_sha256"]:
            raise SystemExit(f"source digest mismatch for {family}")
        if competitor["jls2_bytes"] != candidate["encoded_bytes"]:
            raise SystemExit(f"PBC accepted JLS2 size mismatch for {family}")
        if competitor["zstd9_bytes"] != candidate["zstd9_bytes"]:
            raise SystemExit(f"PBC accepted zstd-9 size mismatch for {family}")
        rows.append(
            {
                "family": family,
                "original_bytes": candidate["original_bytes"],
                "jls2_bytes": candidate["encoded_bytes"],
                "zstd9_bytes": candidate["zstd9_bytes"],
                "brotli11_bytes": candidate["brotli11_bytes"],
                "pbc_archive_bytes": competitor["archive_bytes"],
                "gain_vs_zstd9_percent": percentage_gain(
                    candidate["zstd9_bytes"],
                    candidate["encoded_bytes"],
                ),
                "gain_vs_brotli11_percent": percentage_gain(
                    candidate["brotli11_bytes"],
                    candidate["encoded_bytes"],
                ),
                "gain_vs_pbc_percent": percentage_gain(
                    competitor["archive_bytes"],
                    candidate["encoded_bytes"],
                ),
                "jls2_roundtrip_verified": candidate[
                    "roundtrip_verified"
                ],
                "pbc_roundtrip_verified": competitor[
                    "roundtrip_verified"
                ],
                "jls2_deterministic": candidate["deterministic_frame"],
                "jls2_no_expansion": candidate[
                    "no_expansion_vs_direct_frame"
                ],
            }
        )

    original_bytes = sum(row["original_bytes"] for row in rows)
    jls2_bytes = sum(row["jls2_bytes"] for row in rows)
    zstd9_bytes = sum(row["zstd9_bytes"] for row in rows)
    brotli11_bytes = sum(row["brotli11_bytes"] for row in rows)
    pbc_bytes = sum(row["pbc_archive_bytes"] for row in rows)
    families_smaller_than_brotli = sum(
        row["jls2_bytes"] < row["brotli11_bytes"] for row in rows
    )

    aggregate = {
        "original_bytes": original_bytes,
        "jls2_bytes": jls2_bytes,
        "zstd9_bytes": zstd9_bytes,
        "brotli11_bytes": brotli11_bytes,
        "pbc_archive_bytes": pbc_bytes,
        "gain_vs_zstd9_percent": percentage_gain(
            zstd9_bytes,
            jls2_bytes,
        ),
        "gain_vs_brotli11_percent": percentage_gain(
            brotli11_bytes,
            jls2_bytes,
        ),
        "gain_vs_pbc_percent": percentage_gain(
            pbc_bytes,
            jls2_bytes,
        ),
        "jls2_compression_mbps": jls2["aggregate"][
            "compression_mbps"
        ],
        "jls2_decompression_mbps": jls2["aggregate"][
            "decompression_mbps"
        ],
        "families_smaller_than_brotli11": (
            families_smaller_than_brotli
        ),
    }
    gate_results = {
        "frozen_candidate": (
            jls2["frozen_base_commit"]
            == gates["candidate"]["frozen_base_commit"]
            and jls2["segment_target_bytes"]
            == gates["candidate"]["segment_target_bytes"]
        ),
        "shared_manifest": (
            jls2["manifest_sha256"] == pbc["manifest_sha256"]
        ),
        "accepted_jls2_result": (
            pbc["accepted_sha256"] == sha256_file(args.jls2)
        ),
        "shared_benchmark_commit": (
            jls2["git"]["commit"]
            == pbc["benchmark_source"]["commit"]
        ),
        "first_score_completed": bool(jls2.get("first_score"))
        and bool(jls2.get("completed")),
        "jls2_repetitions": (
            jls2["repetitions"] >= validation["minimum_repetitions"]
        ),
        "pbc_repetitions": (
            pbc["repetitions"] >= validation["minimum_repetitions"]
            and pbc["training_repetitions"]
            >= baselines["pbc_training_repetitions"]
        ),
        "exact_roundtrip": (
            not requirements["require_exact_roundtrip"]
            or all(
                row["jls2_roundtrip_verified"]
                and row["pbc_roundtrip_verified"]
                for row in rows
            )
        ),
        "deterministic_jls2": (
            not requirements["require_deterministic_jls2"]
            or all(row["jls2_deterministic"] for row in rows)
        ),
        "no_expansion": (
            not requirements[
                "require_no_expansion_vs_equally_framed_direct"
            ]
            or all(row["jls2_no_expansion"] for row in rows)
        ),
        "zstd9_per_family": all(
            row["gain_vs_zstd9_percent"]
            >= requirements[
                "minimum_gain_vs_zstd9_percent_per_family"
            ]
            for row in rows
        ),
        "zstd9_aggregate": (
            aggregate["gain_vs_zstd9_percent"]
            >= requirements["minimum_aggregate_gain_vs_zstd9_percent"]
        ),
        "brotli11_family_count": (
            families_smaller_than_brotli
            >= requirements[
                "minimum_families_smaller_than_brotli11"
            ]
        ),
        "brotli11_aggregate": (
            not requirements["require_aggregate_smaller_than_brotli11"]
            or jls2_bytes < brotli11_bytes
        ),
        "compression_speed": (
            aggregate["jls2_compression_mbps"]
            >= requirements["minimum_aggregate_compression_mbps"]
        ),
        "decompression_speed": (
            aggregate["jls2_decompression_mbps"]
            >= requirements["minimum_aggregate_decompression_mbps"]
        ),
        "pbc_reproduction": bool(pbc["passed"])
        and pbc["decision"]["primary_method"] == baselines["pbc_method"],
        "pbc_per_family": (
            not requirements[
                "require_jls2_smaller_than_fixed_pbc_per_family"
            ]
            or all(row["jls2_bytes"] < row["pbc_archive_bytes"] for row in rows)
        ),
        "pbc_aggregate": (
            not requirements[
                "require_jls2_smaller_than_fixed_pbc_aggregate"
            ]
            or jls2_bytes < pbc_bytes
        ),
    }
    payload = {
        "schema_version": 1,
        "claim_ceiling": gates["claim_ceiling"],
        "decision_rule": gates["decision_rule"],
        "private_holdout": gates["private_holdout"],
        "jls2_result_path": str(args.jls2),
        "jls2_result_sha256": sha256_file(args.jls2),
        "pbc_result_path": str(args.pbc),
        "pbc_result_sha256": sha256_file(args.pbc),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "rows": rows,
        "aggregate": aggregate,
        "gate_results": gate_results,
        "passed": all(gate_results.values()),
    }
    payload["decision"] = (
        "pass: bounded unseen LogTrie family result; private holdout sealed"
        if payload["passed"]
        else "fail: retain first score; no tuning or validation rerun"
    )
    write_output(args.output, payload)
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
