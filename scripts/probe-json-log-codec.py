#!/usr/bin/env python3
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Callable, TypeVar


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.json_log_codec import (  # noqa: E402
    compress,
    compress_frame,
    decompress,
    decompress_frame,
)
from compresslab.native import zstd_compress  # noqa: E402


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
        family = item["family"]
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        source = path.read_bytes()
        (encoded, telemetry), compression_seconds = timed(
            partial(compress, source)
        )
        restored, decompression_seconds = timed(partial(decompress, encoded))
        if restored != source:
            raise RuntimeError(f"JLS2 round trip failed for {family}")
        repeated, _ = compress(source)
        if repeated != encoded:
            raise RuntimeError(f"JLS2 output is nondeterministic for {family}")
        zstd9_bytes = baselines[(family, "zstd-9")]["encoded_bytes"]
        brotli11_bytes = baselines[(family, "brotli-11")]["encoded_bytes"]
        row = {
            "family": family,
            "original_bytes": len(source),
            "encoded_bytes": len(encoded),
            "zstd9_bytes": zstd9_bytes,
            "brotli11_bytes": brotli11_bytes,
            "gain_vs_zstd9_percent": 100.0
            * (zstd9_bytes - len(encoded))
            / zstd9_bytes,
            "gain_vs_brotli11_percent": 100.0
            * (brotli11_bytes - len(encoded))
            / brotli11_bytes,
            "compression_seconds": compression_seconds,
            "compression_mbps": len(source)
            / max(compression_seconds, 1e-9)
            / 1_000_000,
            "decompression_seconds": decompression_seconds,
            "decompression_mbps": len(source)
            / max(decompression_seconds, 1e-9)
            / 1_000_000,
            "deterministic": True,
            **telemetry,
        }
        rows.append(row)
        print(
            f"{family}: JLS2 {len(encoded):,}, zstd-9 {zstd9_bytes:,}, "
            f"gain {row['gain_vs_zstd9_percent']:.2f}%",
            flush=True,
        )

    rng = random.Random(20260716)
    adversarial_sources = {
        "random": rng.randbytes(1024 * 1024),
        "already-compressed": zstd_compress(
            rng.randbytes(1024 * 1024),
            level=9,
        ),
        "non-json": b"plain text record\n" * 50_000,
        "long-record": b'{"value":"' + b"x" * (1024 * 1024 + 1) + b'"}',
    }
    adversarial = []
    for name, source in adversarial_sources.items():
        encoded, detail = compress_frame(source)
        if decompress_frame(encoded) != source:
            raise RuntimeError(f"JLF2 adversarial round trip failed for {name}")
        if not detail["no_expansion_vs_direct_frame"]:
            raise RuntimeError(f"JLF2 exact fallback failed for {name}")
        adversarial.append(
            {
                "case": name,
                "original_bytes": len(source),
                **detail,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "claim_ceiling": (
                    "development selector and segmentation evidence only; "
                    "validation remains sealed"
                ),
                "manifest_path": str(args.manifest),
                "manifest_sha256": sha256_file(args.manifest),
                "baseline_path": str(args.baselines),
                "baseline_sha256": sha256_file(args.baselines),
                "rows": rows,
                "adversarial": adversarial,
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
