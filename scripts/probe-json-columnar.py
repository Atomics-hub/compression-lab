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

from compresslab.json_columnar import compress, decompress  # noqa: E402


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


def write_output(
    path: Path,
    payload: dict[str, object],
) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baselines", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--level", type=int, default=3)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    baseline_payload = json.loads(args.baselines.read_text(encoding="utf-8"))
    baselines = {
        (row["family"], row["codec"]): row
        for row in baseline_payload["rows"]
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "claim_ceiling": (
            "opened LogTrie development families only; "
            "not blind validation or market evidence"
        ),
        "manifest_path": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "baseline_path": str(args.baselines),
        "baseline_sha256": sha256_file(args.baselines),
        "zstd_level": args.level,
        "rows": [],
    }
    rows: list[dict[str, object]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for item in manifest["items"]:
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        source = path.read_bytes()
        (encoded, telemetry), compression_seconds = timed(
            partial(compress, source, level=args.level)
        )
        restored, decompression_seconds = timed(partial(decompress, encoded))
        if restored != source:
            raise RuntimeError(f"JLC1 round trip failed for {item['family']}")
        family = item["family"]
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
            **telemetry,
        }
        rows.append(row)
        payload["rows"] = rows
        write_output(args.output, payload)
        print(
            f"{family}: JLC{args.level} {len(encoded):,}, "
            f"zstd-9 {zstd9_bytes:,}, "
            f"gain {row['gain_vs_zstd9_percent']:.2f}%, "
            f"channels={telemetry['channel_count']}, "
            f"extracted={telemetry['extracted_records']}/"
            f"{telemetry['record_count']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
