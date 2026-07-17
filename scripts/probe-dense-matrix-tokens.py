#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.dense_matrix_transform import compress, decompress, transform  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--levels", default="3,9,19")
    args = parser.parse_args()
    levels = [int(level) for level in args.levels.split(",")]
    manifest_path = args.corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    baseline = gates["frozen_baseline"]["family_bytes"]

    rows = []
    for item in manifest["items"]:
        if item["track"] != "dense_feature_matrix":
            continue
        source = (args.corpus / item["path"]).read_bytes()
        transformed_bytes = len(transform(source))
        candidates = []
        for level in levels:
            start = time.perf_counter_ns()
            frame = compress(source, level=level)
            compression_ns = time.perf_counter_ns() - start
            start = time.perf_counter_ns()
            restored = decompress(frame)
            decompression_ns = time.perf_counter_ns() - start
            if restored != source:
                raise RuntimeError(f"DMT1 round trip failed: {item['id']}")
            candidates.append(
                {
                    "level": level,
                    "complete_bytes": len(frame),
                    "compression_mbps": len(source) / compression_ns * 1000,
                    "decompression_mbps": len(source) / decompression_ns * 1000,
                }
            )
        best = min(candidates, key=lambda row: row["complete_bytes"])
        baseline_bytes = baseline[item["family"]]
        rows.append(
            {
                "id": item["id"],
                "family": item["family"],
                "source_bytes": len(source),
                "transformed_bytes": transformed_bytes,
                "baseline_codec": "bz2-9",
                "baseline_bytes": baseline_bytes,
                "best_level": best["level"],
                "complete_bytes": best["complete_bytes"],
                "gain_vs_baseline_percent": (
                    (baseline_bytes - best["complete_bytes"])
                    / baseline_bytes
                    * 100
                ),
                "levels": candidates,
                "exact_roundtrip": True,
            }
        )
        print(
            item["family"],
            f"DMT1={best['complete_bytes']:,}",
            f"bz2={baseline_bytes:,}",
            f"gain={rows[-1]['gain_vs_baseline_percent']:.2f}%",
        )

    aggregate_bytes = sum(row["complete_bytes"] for row in rows)
    baseline_bytes = gates["frozen_baseline"]["aggregate_bytes"]
    target = gates["ratio_gates"][
        "maximum_aggregate_bytes_for_five_percent_gain_vs_bz2_9"
    ]
    result = {
        "schema_version": 1,
        "name": "dmt1-separator-aware-token-probe-v1",
        "stage": "fresh-development-representation-probe",
        "claim_ceiling": gates["claim_ceiling"],
        "corpus_manifest": str(manifest_path),
        "corpus_manifest_sha256": sha256_file(manifest_path),
        "gates": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "levels": levels,
        "rows": rows,
        "aggregate": {
            "source_bytes": sum(row["source_bytes"] for row in rows),
            "complete_bytes": aggregate_bytes,
            "bz2_9_bytes": baseline_bytes,
            "gain_vs_bz2_9_percent": (
                (baseline_bytes - aggregate_bytes) / baseline_bytes * 100
            ),
            "five_percent_target_bytes": target,
            "ratio_gate_passed": aggregate_bytes <= target,
            "families_with_five_percent_gain": sum(
                row["gain_vs_baseline_percent"] >= 5.0 for row in rows
            ),
        },
        "public_validation": "unopened",
        "private_holdout": "sealed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
