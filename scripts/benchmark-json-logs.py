#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections.abc import Mapping
from functools import partial
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, TypeVar


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.log_codec import (  # noqa: E402
    compress as compress_log_candidate,
    decompress as decompress_log_candidate,
)
from compresslab.native import zstd_compress, zstd_decompress  # noqa: E402


T = TypeVar("T")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def median_timed(
    function: Callable[[], T],
    repetitions: int,
) -> tuple[T, float, list[float]]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    result: T
    samples = []
    for _ in range(repetitions):
        start = time.perf_counter()
        result = function()
        samples.append(time.perf_counter() - start)
    ordered = sorted(samples)
    return result, ordered[len(ordered) // 2], samples


def external_brotli(data: bytes, level: int) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source"
        destination = Path(directory) / "encoded.br"
        source.write_bytes(data)
        subprocess.run(
            [
                "brotli",
                "-f",
                "-q",
                str(level),
                str(source),
                "-o",
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
        return destination.read_bytes()


def add_row(
    rows: list[dict[str, object]],
    *,
    family: str,
    codec: str,
    source_size: int,
    encoded: bytes,
    compression_seconds: float,
    decompression_seconds: float,
    detail: Mapping[str, object] | None = None,
    compression_samples: list[float] | None = None,
    decompression_samples: list[float] | None = None,
) -> None:
    rows.append(
        {
            "family": family,
            "codec": codec,
            "original_bytes": source_size,
            "encoded_bytes": len(encoded),
            "encoded_percent": 100.0 * len(encoded) / max(1, source_size),
            "compression_seconds": compression_seconds,
            "compression_mbps": source_size
            / max(compression_seconds, 1e-9)
            / 1_000_000,
            "decompression_seconds": decompression_seconds,
            "decompression_mbps": (
                source_size
                / max(decompression_seconds, 1e-9)
                / 1_000_000
                if decompression_seconds
                else 0.0
            ),
            "compression_samples": compression_samples or [],
            "decompression_samples": decompression_samples or [],
            **(detail or {}),
        }
    )


def benchmark_family(
    family: str,
    data: bytes,
    repetitions: int,
    baseline_set: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    direct_by_level: dict[int, bytes] = {}
    zstd_levels = (3, 9) if baseline_set == "core" else (3, 9, 19)
    for level in zstd_levels:
        encoded, compression_seconds, compression_samples = median_timed(
            partial(zstd_compress, data, level=level),
            repetitions,
        )
        restored, decompression_seconds, decompression_samples = median_timed(
            partial(zstd_decompress, encoded, len(data)),
            repetitions,
        )
        if restored != data:
            raise RuntimeError(f"zstd-{level} round trip failed for {family}")
        direct_by_level[level] = encoded
        add_row(
            rows,
            family=family,
            codec=f"zstd-{level}",
            source_size=len(data),
            encoded=encoded,
            compression_seconds=compression_seconds,
            decompression_seconds=decompression_seconds,
            compression_samples=compression_samples,
            decompression_samples=decompression_samples,
        )

    (candidate, detail), compression_seconds, compression_samples = median_timed(
        partial(compress_log_candidate, data),
        repetitions,
    )
    restored, decompression_seconds, decompression_samples = median_timed(
        partial(decompress_log_candidate, candidate),
        repetitions,
    )
    if restored != data:
        raise RuntimeError(f"CLG1 round trip failed for {family}")
    add_row(
        rows,
        family=family,
        codec="clg1",
        source_size=len(data),
        encoded=candidate,
        compression_seconds=compression_seconds,
        decompression_seconds=decompression_seconds,
        detail=detail,
        compression_samples=compression_samples,
        decompression_samples=decompression_samples,
    )

    if not shutil.which("brotli"):
        raise RuntimeError("brotli CLI is required for the JSON-log benchmark")
    brotli_levels = (11,) if baseline_set == "core" else (6, 11)
    for level in brotli_levels:
        encoded, compression_seconds, compression_samples = median_timed(
            partial(external_brotli, data, level),
            1,
        )
        add_row(
            rows,
            family=family,
            codec=f"brotli-{level}",
            source_size=len(data),
            encoded=encoded,
            compression_seconds=compression_seconds,
            decompression_seconds=0.0,
            compression_samples=compression_samples,
        )

    if baseline_set == "full":
        baseline_functions: list[
            tuple[
                str,
                Callable[[], bytes],
                Callable[[bytes], bytes],
            ]
        ] = [
            (
                "gzip-9",
                lambda: gzip.compress(data, compresslevel=9),
                gzip.decompress,
            ),
            (
                "lzma-9",
                lambda: lzma.compress(data, preset=9),
                lzma.decompress,
            ),
        ]
        for codec, encode, decode in baseline_functions:
            encoded, compression_seconds, compression_samples = median_timed(
                encode,
                1,
            )
            restored, decompression_seconds, decompression_samples = median_timed(
                partial(decode, encoded),
                1,
            )
            if restored != data:
                raise RuntimeError(f"{codec} round trip failed for {family}")
            add_row(
                rows,
                family=family,
                codec=codec,
                source_size=len(data),
                encoded=encoded,
                compression_seconds=compression_seconds,
                decompression_seconds=decompression_seconds,
                compression_samples=compression_samples,
                decompression_samples=decompression_samples,
            )

    candidate_size = len(candidate)
    zstd_size = len(direct_by_level[9])
    print(
        f"{family}: CLG1 {candidate_size:,} bytes, zstd-9 {zstd_size:,}, "
        f"gain {(zstd_size - candidate_size) * 100 / zstd_size:.2f}%, "
        f"mode={detail['selected_mode']}",
        flush=True,
    )
    return rows


def write_results(
    output_path: Path,
    payload: dict[str, object],
    rows: list[dict[str, object]],
) -> None:
    payload["rows"] = rows
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    csv_path = output_path.with_suffix(".csv")
    csv_rows = [
        {
            key: json.dumps(value) if isinstance(value, list) else value
            for key, value in row.items()
        }
        for row in rows
    ]
    csv_temporary = csv_path.with_suffix(csv_path.suffix + ".partial")
    with csv_temporary.open("w", newline="", encoding="utf-8") as output:
        fieldnames = sorted({key for row in csv_rows for key in row})
        writer = csv.DictWriter(
            output,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(csv_rows)
    csv_temporary.replace(csv_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--baseline-set",
        choices=("core", "full"),
        default="core",
    )
    parser.add_argument(
        "--family",
        action="append",
        help="benchmark only the named family; repeat to select multiple",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest_sha256 = sha256_file(args.manifest)
    rows: list[dict[str, object]] = []
    system_states: list[dict[str, object]] = [
        {
            "label": "run-start",
            "load_average_1m_5m_15m": list(os.getloadavg()),
            "logical_cpus": os.cpu_count(),
        }
    ]
    if args.output.is_file():
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        expected = (
            existing.get("manifest_sha256"),
            existing.get("repetitions"),
            existing.get("baseline_set"),
        )
        actual = (manifest_sha256, args.repetitions, args.baseline_set)
        if expected != actual:
            raise ValueError(
                "refusing to resume benchmark with different inputs or settings"
            )
        rows = existing["rows"]
        system_states = existing["system_states"]
        system_states.append(
            {
                "label": "resume",
                "load_average_1m_5m_15m": list(os.getloadavg()),
                "logical_cpus": os.cpu_count(),
            }
        )
    selected_families = set(args.family or [])
    completed_families = {str(row["family"]) for row in rows}
    payload: dict[str, object] = {
        "schema_version": 1,
        "claim_ceiling": manifest["claim_ceiling"],
        "manifest_path": str(args.manifest),
        "manifest_sha256": manifest_sha256,
        "repetitions": args.repetitions,
        "baseline_set": args.baseline_set,
        "system_states": system_states,
        "rows": rows,
    }
    for item in manifest["items"]:
        family = item["family"]
        if selected_families and family not in selected_families:
            continue
        if family in completed_families:
            print(f"skip completed family {family}", flush=True)
            continue
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        rows.extend(
            benchmark_family(
                family,
                path.read_bytes(),
                args.repetitions,
                args.baseline_set,
            )
        )
        system_states.append(
            {
                "label": f"checkpoint-{family}",
                "load_average_1m_5m_15m": list(os.getloadavg()),
                "logical_cpus": os.cpu_count(),
            }
        )
        write_results(args.output, payload, rows)
    system_states.append(
        {
            "label": "run-end",
            "load_average_1m_5m_15m": list(os.getloadavg()),
            "logical_cpus": os.cpu_count(),
        }
    )
    write_results(args.output, payload, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
