#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from compresslab.corpus import load_corpus
from compresslab.native import zstd_compress, zstd_decompress
from compresslab.tabular_transform import (
    compress,
    decompress,
    frame_backend,
    transform,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def record_aligned_prefix(data: bytes, maximum: int) -> bytes:
    if len(data) <= maximum:
        return data
    end = data.rfind(b"\n", 0, maximum + 1)
    if end < 0:
        raise ValueError("no complete record in probe prefix")
    return data[: end + 1]


def timed(callable_):
    start = time.perf_counter_ns()
    result = callable_()
    return result, time.perf_counter_ns() - start


def git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run(
    corpus: Path,
    config_path: Path,
    output: Path,
    maximum_probe_bytes: int,
) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    delimiters = {
        item["id"]: ord(",") if item["delimiter"] == "comma" else ord(";")
        for item in config["development"]
    }
    families = {item["id"]: item["family"] for item in config["development"]}
    rows = []
    for item in load_corpus(corpus, ("train",)):
        source = record_aligned_prefix(item.path.read_bytes(), maximum_probe_bytes)
        delimiter = delimiters[item.id]
        transformed, transform_ns = timed(lambda: transform(source, delimiter))
        direct19, direct19_ns = timed(lambda: zstd_compress(source, level=19))
        candidate19, candidate19_ns = timed(
            lambda: compress(source, delimiter, level=19)
        )
        restored19, decode19_ns = timed(lambda: decompress(candidate19))
        if restored19 != source:
            raise ValueError(f"TBL1 round-trip failure: {item.id}")
        if zstd_decompress(direct19) != source:
            raise ValueError(f"direct Zstandard round-trip failure: {item.id}")
        rows.append(
            {
                "family": families[item.id],
                "source_bytes": len(source),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "transformed_bytes": len(transformed),
                "transform_mbps": len(source) / (transform_ns / 1e9) / 1e6,
                "direct_zstd19_bytes": len(direct19),
                "direct_zstd19_mbps": len(source) / (direct19_ns / 1e9) / 1e6,
                "tbl1_zstd19_bytes": len(candidate19),
                "gain_percent": (len(direct19) - len(candidate19))
                / len(direct19)
                * 100.0,
                "backend": frame_backend(candidate19),
                "compression_mbps": len(source)
                / (candidate19_ns / 1e9)
                / 1e6,
                "decompression_mbps": len(source)
                / (decode19_ns / 1e9)
                / 1e6,
                "exact_roundtrip": True,
            }
        )
        print(
            f"{item.id}: direct19={len(direct19):,} "
            f"tbl1-19={len(candidate19):,}",
            flush=True,
        )
    source_bytes = sum(row["source_bytes"] for row in rows)
    direct_bytes = sum(row["direct_zstd19_bytes"] for row in rows)
    candidate_bytes = sum(row["tbl1_zstd19_bytes"] for row in rows)
    manifest_path = corpus / "manifest.json"
    result = {
        "schema_version": 1,
        "name": "tbl1-column-transpose-selector-probe-v1",
        "stage": "development-probe",
        "candidate": "TBL1 reference column transpose plus exact direct fallback",
        "claim_ceiling": (
            "four bounded development slices and single local timings only; not a "
            "full-corpus, product, public-validation, private-holdout, independent, "
            "or market claim"
        ),
        "evidence": {
            "base_commit": git_text("rev-parse", "HEAD"),
            "git_dirty": bool(git_text("status", "--porcelain")),
            "maximum_probe_bytes": maximum_probe_bytes,
            "corpus_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
        },
        "aggregate": {
            "source_bytes": source_bytes,
            "direct_zstd19_bytes": direct_bytes,
            "tbl1_zstd19_selector_bytes": candidate_bytes,
            "gain_vs_direct_zstd19_percent": (direct_bytes - candidate_bytes)
            / direct_bytes
            * 100.0,
            "families_with_size_win": sum(
                row["tbl1_zstd19_bytes"] < row["direct_zstd19_bytes"]
                for row in rows
            ),
            "families": len(rows),
            "exact_roundtrip": all(row["exact_roundtrip"] for row in rows),
        },
        "families": rows,
        "decision": (
            "Retain the column-transpose representation and exact fallback. Reject "
            "the Python path for product use because it misses every speed gate. "
            "Implement bounded native transform and inverse paths, then run a clean "
            "full-development candidate decision against Brotli-11, zstd-19, "
            "zstd-9, zstd-3, and LZ4-1."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "config" / "tabular-corpus-v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-probe-bytes", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()
    run(args.corpus, args.config, args.output, args.maximum_probe_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
