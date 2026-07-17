#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import statistics
import subprocess
import sys
import time


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.dense_matrix_transform import (  # noqa: E402
    selector_backend,
    selector_compress,
    selector_decompress,
)
from compresslab.dense_native import (  # noqa: E402
    dense_parallel_native_available,
    dense_plane_native_available,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def median_int(values: list[int]) -> int:
    return int(statistics.median(values))


def git_state() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"commit": commit, "dirty": dirty}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--baseline-results", type=Path, required=True)
    parser.add_argument("--operational-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    if args.repetitions < 3 or args.warmups < 1:
        raise ValueError("at least three repetitions and one warmup are required")
    if not dense_parallel_native_available() or not dense_plane_native_available():
        raise RuntimeError("the native DMA2 and DMP1 paths must be built")
    repository = git_state()
    if repository["dirty"]:
        raise SystemExit("native DMS2 gate requires a clean commit")

    manifest_path = args.corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    baseline_payload = json.loads(
        args.baseline_results.read_text(encoding="utf-8")
    )
    operational_payload = None
    if args.operational_evidence is not None:
        operational_payload = json.loads(
            args.operational_evidence.read_text(encoding="utf-8")
        )
        if not operational_payload["gate_results"]["all_passed"]:
            raise ValueError("DMS2 operational evidence did not pass")
    dense_ids = {
        item["id"]
        for item in manifest["items"]
        if item["track"] == "dense_feature_matrix"
    }
    standards: dict[str, list[dict]] = {}
    for row in baseline_payload["medians"]:
        if row["item_id"] in dense_ids:
            standards.setdefault(row["codec_id"], []).append(row)

    rows = []
    for item in manifest["items"]:
        if item["track"] != "dense_feature_matrix":
            continue
        source = (args.corpus / item["path"]).read_bytes()
        canonical_frame: bytes | None = None
        compression_ns: list[int] = []
        decompression_ns: list[int] = []
        frame: bytes = b""
        for repetition in range(args.warmups + args.repetitions):
            started = time.perf_counter_ns()
            frame = selector_compress(source, level=19)
            encoded_ns = time.perf_counter_ns() - started
            if canonical_frame is None:
                canonical_frame = frame
            elif frame != canonical_frame:
                raise RuntimeError(f"DMS2 is nondeterministic: {item['id']}")
            started = time.perf_counter_ns()
            restored = selector_decompress(frame)
            decoded_ns = time.perf_counter_ns() - started
            if restored != source:
                raise RuntimeError(f"DMS2 round trip failed: {item['id']}")
            if repetition >= args.warmups:
                compression_ns.append(encoded_ns)
                decompression_ns.append(decoded_ns)
        corrupt = bytearray(frame)
        corrupt[-1] ^= 1
        try:
            selector_decompress(bytes(corrupt))
        except ValueError:
            corruption_rejected = True
        else:
            corruption_rejected = False
        baseline_bytes = gates["frozen_baseline"]["family_bytes"][item["family"]]
        complete_bytes = len(frame)
        rows.append(
            {
                "id": item["id"],
                "family": item["family"],
                "source_bytes": len(source),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "selected_backend": selector_backend(frame),
                "complete_bytes": complete_bytes,
                "bz2_9_bytes": baseline_bytes,
                "gain_vs_bz2_9_percent": (
                    (baseline_bytes - complete_bytes) / baseline_bytes * 100
                ),
                "compression_ns": compression_ns,
                "decompression_ns": decompression_ns,
                "median_compression_ns": median_int(compression_ns),
                "median_decompression_ns": median_int(decompression_ns),
                "compression_mbps": len(source) / median_int(compression_ns) * 1000,
                "decompression_mbps": len(source)
                / median_int(decompression_ns)
                * 1000,
                "exact_roundtrip": True,
                "deterministic": True,
                "corruption_rejected": corruption_rejected,
            }
        )

    source_bytes = sum(row["source_bytes"] for row in rows)
    complete_bytes = sum(row["complete_bytes"] for row in rows)
    aggregate_compression_ns = sum(row["median_compression_ns"] for row in rows)
    aggregate_decompression_ns = sum(
        row["median_decompression_ns"] for row in rows
    )
    standard_rows = []
    for codec_id, codec_rows in standards.items():
        standard_source = sum(row["original_bytes"] for row in codec_rows)
        standard_rows.append(
            {
                "codec_id": codec_id,
                "complete_bytes": sum(
                    row["compressed_bytes"] for row in codec_rows
                ),
                "compression_mbps": standard_source
                / sum(row["compression_ns"] for row in codec_rows)
                * 1000,
                "decompression_mbps": standard_source
                / sum(row["decompression_ns"] for row in codec_rows)
                * 1000,
                "all_roundtrips_exact": all(
                    row["roundtrip_ok"] for row in codec_rows
                ),
            }
        )
    standard_rows.sort(key=lambda row: row["complete_bytes"])
    baseline_bytes = gates["frozen_baseline"]["aggregate_bytes"]
    target_bytes = gates["ratio_gates"][
        "maximum_aggregate_bytes_for_five_percent_gain_vs_bz2_9"
    ]
    aggregate = {
        "source_bytes": source_bytes,
        "complete_bytes": complete_bytes,
        "bz2_9_bytes": baseline_bytes,
        "gain_vs_bz2_9_percent": (
            (baseline_bytes - complete_bytes) / baseline_bytes * 100
        ),
        "five_percent_target_bytes": target_bytes,
        "compression_mbps": source_bytes / aggregate_compression_ns * 1000,
        "decompression_mbps": source_bytes
        / aggregate_decompression_ns
        * 1000,
        "ratio_gate_passed": complete_bytes <= target_bytes,
        "compression_gate_passed": (
            source_bytes / aggregate_compression_ns * 1000 >= 50
        ),
        "decompression_gate_passed": (
            source_bytes / aggregate_decompression_ns * 1000 >= 250
        ),
        "families_with_five_percent_gain": sum(
            row["gain_vs_bz2_9_percent"] >= 5 for row in rows
        ),
        "exact_deterministic_corruption_gates_passed": all(
            row["exact_roundtrip"]
            and row["deterministic"]
            and row["corruption_rejected"]
            for row in rows
        ),
    }
    result = {
        "schema_version": 1,
        "name": "dms2-safe-selector-development-gate-v2",
        "stage": "fresh-development-native-gate",
        "claim_ceiling": gates["claim_ceiling"],
        "candidate": {
            "format": "DMS2",
            "entropy_level": 19,
            "selector_sample_bytes": 64 * 1024,
            "plane_rule": "use DMP1 when the bounded prefix has at most four numeric lexemes; otherwise use DMA2",
            "parallel_rule": "use seven lanes for alphabets at most eight and six lanes otherwise",
            "direct_fallback": "materialize equally framed zstd-1 concurrently and choose the smaller complete frame",
        },
        "corpus_manifest": str(manifest_path),
        "corpus_manifest_sha256": sha256_file(manifest_path),
        "gates": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "baseline_results": str(args.baseline_results),
        "baseline_results_sha256": sha256_file(args.baseline_results),
        "operational_evidence": (
            str(args.operational_evidence)
            if args.operational_evidence is not None
            else None
        ),
        "operational_evidence_sha256": (
            sha256_file(args.operational_evidence)
            if args.operational_evidence is not None
            else None
        ),
        "runner": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "repetitions": args.repetitions,
            "warmups": args.warmups,
        },
        "git": repository,
        "rows": rows,
        "aggregate": aggregate,
        "standards": standard_rows,
        "remaining_gates": (
            ["portable wheel verification on Linux and Windows"]
            if operational_payload is not None
            else [
                "peak RSS at most 512 MiB",
                "bounded streaming memory",
                "record-table regression at most 0.25%",
                "leave-one-family-out selector evaluation",
                "portable wheel verification on Linux and Windows",
            ]
        ),
        "public_validation": "unopened",
        "private_holdout": "sealed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
