#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import lzma
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from typing import Callable, TypeVar


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.corpus import _json_logs  # noqa: E402
from compresslab.log_transform import (  # noqa: E402
    decode,
    decode_recent,
    encode,
    encode_recent,
)
from compresslab.log_codec import (  # noqa: E402
    compress as compress_log_candidate,
    decompress as decompress_log_candidate,
)
from compresslab.native import (  # noqa: E402
    log_transform_decode as native_log_decode,
    log_transform_encode as native_log_encode,
    zstd_compress,
    zstd_decompress,
)


T = TypeVar("T")


def synthetic_access_logs(size: int) -> bytes:
    rows = []
    total = 0
    index = 0
    while total < size:
        row = json.dumps(
            {
                "@timestamp": f"2026-07-16T12:{(index // 60) % 60:02d}:{index % 60:02d}.000Z",
                "client": f"10.42.{(index // 256) % 32}.{index % 256}",
                "duration_us": 1200 + (index * 7919) % 900000,
                "method": ("GET", "GET", "POST", "PUT")[index % 4],
                "path": (
                    "/api/v1/users",
                    "/api/v1/orders",
                    "/healthz",
                    "/api/v1/search",
                )[index % 4],
                "request_id": f"{index:032x}",
                "status": (200, 200, 201, 404, 500)[index % 5],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode() + b"\n"
        rows.append(row)
        total += len(row)
        index += 1
    return b"".join(rows)[:size]


def synthetic_event_logs(size: int) -> bytes:
    rows = []
    total = 0
    index = 0
    while total < size:
        row = (
            f'{{"event":"job.{("started", "progress", "finished")[index % 3]}",'
            f'"job_id":"job-{index % 4096:08d}",'
            f'"node":"worker-{index % 64:03d}",'
            f'"progress":{index % 101:03d},'
            f'"sequence":{index:010d}}}\n'
        ).encode()
        rows.append(row)
        total += len(row)
        index += 1
    return b"".join(rows)[:size]


def external_encode(executable: str, arguments: list[str], data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source"
        destination = Path(directory) / "encoded"
        source.write_bytes(data)
        subprocess.run(
            [executable, *arguments, str(source), "-o", str(destination)],
            check=True,
            capture_output=True,
        )
        return destination.read_bytes()


def timed(function: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = function()
    return result, time.perf_counter() - start


def median_timed(
    function: Callable[[], T],
    repetitions: int,
) -> tuple[T, float]:
    if repetitions < 1:
        raise ValueError("timing repetitions must be positive")
    result: T
    samples = []
    for _ in range(repetitions):
        result, seconds = timed(function)
        samples.append(seconds)
    samples.sort()
    return result, samples[len(samples) // 2]


def fallback_probe_cases(size: int) -> dict[str, bytes]:
    rng = random.Random(20260716)
    probe_size = min(size, 1024 * 1024)
    already_compressed_source = synthetic_access_logs(probe_size)
    return {
        "random": rng.randbytes(probe_size),
        "already-compressed": zstd_compress(already_compressed_source, level=9),
        "non-line-oriented": (b"\x00ABCDEF0123456789" * (probe_size // 17 + 1))[
            :probe_size
        ],
        "long-record": (
            b'{"message":"' + b"x" * max(64 * 1024, probe_size - 20) + b'"}'
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("lwx1", "lwx2"), default="lwx1")
    args = parser.parse_args()
    if args.size < 1024:
        raise ValueError("discovery size must be at least 1024 bytes")

    corpora = {
        "existing-json-log-smoke": _json_logs(args.size),
        "access-jsonl": synthetic_access_logs(args.size),
        "event-jsonl": synthetic_event_logs(args.size),
    }
    rows = []
    for name, source in corpora.items():
        if args.mode == "lwx1":
            (transformed, telemetry), transform_seconds = timed(
                lambda source=source: encode(source)
            )
            restored, transform_decode_seconds = timed(
                lambda transformed=transformed: decode(
                    transformed, expected_size=len(source)
                )
            )
        else:
            reference, telemetry = encode_recent(source)
            transformed, transform_seconds = median_timed(
                lambda source=source: native_log_encode(source),
                5,
            )
            if transformed != reference:
                raise RuntimeError(
                    f"native and Python LWX2 streams differ for {name}"
                )
            restored, transform_decode_seconds = median_timed(
                lambda transformed=transformed: native_log_decode(
                    transformed, len(source)
                ),
                5,
            )
            if decode_recent(reference, expected_size=len(source)) != source:
                raise RuntimeError(f"Python LWX2 round trip failed for {name}")
        if restored != source:
            raise RuntimeError(f"log transform round trip failed for {name}")
        candidates: list[tuple[str, Callable[[], bytes]]] = [
            ("gzip-9", lambda source=source: gzip.compress(source, compresslevel=9)),
            ("lzma-9", lambda source=source: lzma.compress(source, preset=9)),
            ("zstd-3", lambda source=source: zstd_compress(source, level=3)),
            ("zstd-9", lambda source=source: zstd_compress(source, level=9)),
            (
                f"{args.mode}+zstd-3",
                lambda transformed=transformed: zstd_compress(transformed, level=3),
            ),
            (
                f"{args.mode}+zstd-9",
                lambda transformed=transformed: zstd_compress(transformed, level=9),
            ),
        ]
        if subprocess.run(
            ["sh", "-c", "command -v brotli"],
            capture_output=True,
            check=False,
        ).returncode == 0:
            candidates.append(
                (
                    "brotli-11",
                    lambda source=source: external_encode(
                        "brotli", ["-f", "-q", "11"], source
                    ),
                )
            )
        encoded_by_codec = {}
        for codec, function in candidates:
            if codec.startswith(f"{args.mode}+"):
                encoded, backend_seconds = median_timed(function, 5)
            else:
                encoded, backend_seconds = timed(function)
            encoded_by_codec[codec] = len(encoded)
            compression_seconds = backend_seconds
            decompression_seconds = 0.0
            if codec.startswith(f"{args.mode}+"):
                restored_transform, backend_decode_seconds = timed(
                    lambda encoded=encoded: zstd_decompress(
                        encoded, len(transformed)
                    )
                )
                if args.mode == "lwx1":
                    candidate_restored = decode(
                        restored_transform, expected_size=len(source)
                    )
                else:
                    candidate_restored = native_log_decode(
                        restored_transform, len(source)
                    )
                if candidate_restored != source:
                    raise RuntimeError(f"{codec} round trip failed for {name}")
                compression_seconds += transform_seconds
                decompression_seconds = (
                    backend_decode_seconds + transform_decode_seconds
                )
            rows.append(
                {
                    "corpus": name,
                    "codec": codec,
                    "original_bytes": len(source),
                    "transformed_bytes": len(transformed),
                    "encoded_bytes": len(encoded),
                    "encoded_percent": 100.0 * len(encoded) / len(source),
                    "backend_seconds": backend_seconds,
                    "transform_seconds": transform_seconds,
                    "transform_decode_seconds": transform_decode_seconds,
                    "compression_seconds": compression_seconds,
                    "compression_mbps": (
                        len(source) / max(compression_seconds, 1e-9) / 1_000_000
                    ),
                    "decompression_seconds": decompression_seconds,
                    "decompression_mbps": (
                        len(source)
                        / max(decompression_seconds, 1e-9)
                        / 1_000_000
                        if decompression_seconds
                        else 0.0
                    ),
                    "transform_mbps": (
                        len(source) / max(transform_seconds, 1e-9) / 1_000_000
                    ),
                    "transform_decode_mbps": (
                        len(source)
                        / max(transform_decode_seconds, 1e-9)
                        / 1_000_000
                    ),
                    **telemetry,
                }
            )
        if args.mode == "lwx2":
            (candidate_frame, candidate_detail), candidate_seconds = median_timed(
                lambda source=source: compress_log_candidate(source),
                5,
            )
            candidate_restored, candidate_decode_seconds = median_timed(
                lambda candidate_frame=candidate_frame: decompress_log_candidate(
                    candidate_frame
                ),
                5,
            )
            if candidate_restored != source:
                raise RuntimeError(f"CLG1 round trip failed for {name}")
            encoded_by_codec["clg1"] = len(candidate_frame)
            rows.append(
                {
                    "corpus": name,
                    "codec": "clg1",
                    "original_bytes": len(source),
                    "transformed_bytes": len(transformed),
                    "encoded_bytes": len(candidate_frame),
                    "encoded_percent": 100.0
                    * len(candidate_frame)
                    / len(source),
                    "backend_seconds": 0.0,
                    "transform_seconds": transform_seconds,
                    "transform_decode_seconds": transform_decode_seconds,
                    "compression_seconds": candidate_seconds,
                    "compression_mbps": len(source)
                    / max(candidate_seconds, 1e-9)
                    / 1_000_000,
                    "decompression_seconds": candidate_decode_seconds,
                    "decompression_mbps": len(source)
                    / max(candidate_decode_seconds, 1e-9)
                    / 1_000_000,
                    "transform_mbps": len(source)
                    / max(transform_seconds, 1e-9)
                    / 1_000_000,
                    "transform_decode_mbps": len(source)
                    / max(transform_decode_seconds, 1e-9)
                    / 1_000_000,
                    **telemetry,
                    **candidate_detail,
                }
            )
        gain = 100.0 * (
            encoded_by_codec["zstd-9"]
            - encoded_by_codec[f"{args.mode}+zstd-9"]
        ) / encoded_by_codec["zstd-9"]
        print(
            f"{name}: {args.mode}+zstd-9 "
            f"{encoded_by_codec[f'{args.mode}+zstd-9']:,} bytes, "
            f"zstd-9 {encoded_by_codec['zstd-9']:,}, gain {gain:.2f}%",
            flush=True,
        )

    fallback_rows = []
    if args.mode == "lwx2":
        for name, source in fallback_probe_cases(args.size).items():
            candidate, detail = compress_log_candidate(source)
            restored = decompress_log_candidate(candidate)
            if restored != source:
                raise RuntimeError(f"fallback candidate round trip failed for {name}")
            if not detail["no_expansion_vs_direct_frame"]:
                raise RuntimeError(f"direct fallback expanded on {name}")
            fallback_rows.append(
                {
                    "case": name,
                    "original_bytes": len(source),
                    **detail,
                }
            )
            print(
                f"{name}: fallback selected {detail['selected_mode']}, "
                f"{detail['selected_bytes']:,} bytes vs direct frame "
                f"{detail['direct_frame_bytes']:,}",
                flush=True,
            )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claim_ceiling": (
                        "synthetic and previously exposed discovery only; "
                        "not validation or market evidence"
                    ),
                    "mode": args.mode,
                    "fallback_rows": fallback_rows,
                    "rows": rows,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        csv_path = args.output.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=rows[0].keys(),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
