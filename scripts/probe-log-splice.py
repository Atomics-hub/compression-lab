#!/usr/bin/env python3
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Callable, TypeVar


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.native import zstd_compress, zstd_decompress  # noqa: E402
from compresslab.splice_transform import decode, encode  # noqa: E402


T = TypeVar("T")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def timed(function: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = function()
    return result, time.perf_counter() - start


def median_timed(
    function: Callable[[], T],
    repetitions: int,
) -> tuple[T, float]:
    samples = [timed(function) for _ in range(repetitions)]
    samples.sort(key=lambda item: item[1])
    return samples[len(samples) // 2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baselines", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    baseline_payload = json.loads(args.baselines.read_text(encoding="utf-8"))
    baselines = {
        (row["family"], row["codec"]): row
        for row in baseline_payload["rows"]
    }
    rows = []
    for item in manifest["items"]:
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        source = path.read_bytes()
        (transformed, telemetry), transform_seconds = timed(
            partial(encode, source)
        )
        restored, transform_decode_seconds = timed(
            partial(decode, transformed, expected_size=len(source))
        )
        if restored != source:
            raise RuntimeError(f"LWS1 round trip failed for {item['family']}")
        encoded, backend_seconds = median_timed(
            partial(zstd_compress, transformed, level=3),
            3,
        )
        decoded_transform, backend_decode_seconds = median_timed(
            partial(zstd_decompress, encoded, len(transformed)),
            3,
        )
        if (
            decode(decoded_transform, expected_size=len(source))
            != source
        ):
            raise RuntimeError(
                f"LWS1+zstd-3 round trip failed for {item['family']}"
            )
        family = item["family"]
        zstd9_bytes = baselines[(family, "zstd-9")]["encoded_bytes"]
        brotli11_bytes = baselines[(family, "brotli-11")]["encoded_bytes"]
        row = {
            "family": family,
            "original_bytes": len(source),
            "transformed_bytes": len(transformed),
            "encoded_bytes": len(encoded),
            "zstd9_bytes": zstd9_bytes,
            "brotli11_bytes": brotli11_bytes,
            "gain_vs_zstd9_percent": 100.0
            * (zstd9_bytes - len(encoded))
            / zstd9_bytes,
            "gain_vs_brotli11_percent": 100.0
            * (brotli11_bytes - len(encoded))
            / brotli11_bytes,
            "transform_seconds": transform_seconds,
            "transform_mbps": len(source)
            / max(transform_seconds, 1e-9)
            / 1_000_000,
            "complete_compression_seconds": (
                transform_seconds + backend_seconds
            ),
            "complete_compression_mbps": len(source)
            / max(transform_seconds + backend_seconds, 1e-9)
            / 1_000_000,
            "complete_decompression_seconds": (
                transform_decode_seconds + backend_decode_seconds
            ),
            "complete_decompression_mbps": len(source)
            / max(
                transform_decode_seconds + backend_decode_seconds,
                1e-9,
            )
            / 1_000_000,
            **telemetry,
        }
        rows.append(row)
        print(
            f"{family}: LWS1+zstd-3 {len(encoded):,}, "
            f"zstd-9 {zstd9_bytes:,}, "
            f"gain {row['gain_vs_zstd9_percent']:.2f}%, "
            f"spliced {telemetry['spliced_records']:,}/"
            f"{telemetry['record_count']:,}",
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "claim_ceiling": (
                    "opened LogTrie development families only; "
                    "not blind validation or market evidence"
                ),
                "manifest_path": str(args.manifest),
                "manifest_sha256": sha256_file(args.manifest),
                "baseline_path": str(args.baselines),
                "baseline_sha256": sha256_file(args.baselines),
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
