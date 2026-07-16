#!/usr/bin/env python3
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, TypeVar


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.json_columnar import (  # noqa: E402
    compress,
    decompress,
    pack_transform,
    transform_reference,
)
from compresslab.native import (  # noqa: E402
    json_columnar_reassemble,
    json_columnar_transform,
)


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
) -> tuple[T, float, list[float]]:
    function()
    samples = [timed(function) for _ in range(repetitions)]
    ordered = sorted(samples, key=lambda item: item[1])
    result, median = ordered[len(ordered) // 2]
    return result, median, [seconds for _, seconds in samples]


def system_state(label: str) -> dict[str, object]:
    return {
        "label": label,
        "load_average_1m_5m_15m": list(os.getloadavg()),
        "logical_cpus": os.cpu_count(),
    }


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    baseline_payload = json.loads(args.baselines.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    baselines = {
        (row["family"], row["codec"]): row
        for row in baseline_payload["rows"]
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "claim_ceiling": (
            "quiet-host development evidence only; validation remains sealed"
        ),
        "manifest_path": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "baseline_path": str(args.baselines),
        "baseline_sha256": sha256_file(args.baselines),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "repetitions": args.repetitions,
        "zstd_level": 6,
        "system_states": [system_state("run-start")],
        "rows": [],
    }
    rows: list[dict[str, Any]] = []
    for item in manifest["items"]:
        family = item["family"]
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        source = path.read_bytes()

        skeleton, channels, telemetry = transform_reference(source)
        reference_transform = pack_transform(
            skeleton,
            channels,
            telemetry,
        )
        native_transform = json_columnar_transform(source)
        if native_transform != reference_transform:
            raise RuntimeError(
                f"native/reference JCT1 mismatch for {family}"
            )
        if json_columnar_reassemble(native_transform, len(source)) != source:
            raise RuntimeError(f"native JCT1 round trip failed for {family}")

        raw_transform, transform_seconds, transform_samples = median_timed(
            partial(json_columnar_transform, source),
            args.repetitions,
        )
        restored, reassemble_seconds, reassemble_samples = median_timed(
            partial(
                json_columnar_reassemble,
                raw_transform,
                len(source),
            ),
            args.repetitions,
        )
        if restored != source:
            raise RuntimeError(f"native reassembly failed for {family}")

        (frame, frame_telemetry), compression_seconds, compression_samples = (
            median_timed(
                partial(compress, source, level=6),
                args.repetitions,
            )
        )
        for _ in range(2):
            repeated_frame, _ = compress(source, level=6)
            if repeated_frame != frame:
                raise RuntimeError(
                    f"JLC2 output is nondeterministic for {family}"
                )
        restored, decompression_seconds, decompression_samples = median_timed(
            partial(decompress, frame),
            args.repetitions,
        )
        if restored != source:
            raise RuntimeError(f"JLC2 round trip failed for {family}")

        zstd9_bytes = baselines[(family, "zstd-9")]["encoded_bytes"]
        brotli11_bytes = baselines[(family, "brotli-11")]["encoded_bytes"]
        row = {
            "family": family,
            "original_bytes": len(source),
            "encoded_bytes": len(frame),
            "zstd9_bytes": zstd9_bytes,
            "brotli11_bytes": brotli11_bytes,
            "gain_vs_zstd9_percent": 100.0
            * (zstd9_bytes - len(frame))
            / zstd9_bytes,
            "gain_vs_brotli11_percent": 100.0
            * (brotli11_bytes - len(frame))
            / brotli11_bytes,
            "transform_seconds": transform_seconds,
            "transform_mbps": len(source)
            / max(transform_seconds, 1e-9)
            / 1_000_000,
            "transform_samples": transform_samples,
            "reassemble_seconds": reassemble_seconds,
            "reassemble_mbps": len(source)
            / max(reassemble_seconds, 1e-9)
            / 1_000_000,
            "reassemble_samples": reassemble_samples,
            "compression_seconds": compression_seconds,
            "compression_mbps": len(source)
            / max(compression_seconds, 1e-9)
            / 1_000_000,
            "compression_samples": compression_samples,
            "decompression_seconds": decompression_seconds,
            "decompression_mbps": len(source)
            / max(decompression_seconds, 1e-9)
            / 1_000_000,
            "decompression_samples": decompression_samples,
            "native_reference_identical": True,
            "deterministic_frame": True,
            **frame_telemetry,
        }
        rows.append(row)
        payload["rows"] = rows
        payload["system_states"].append(system_state(f"checkpoint-{family}"))
        write_output(args.output, payload)
        print(
            f"{family}: transform {row['transform_mbps']:.2f} MB/s, "
            f"compress {row['compression_mbps']:.2f} MB/s, "
            f"decompress {row['decompression_mbps']:.2f} MB/s",
            flush=True,
        )

    requirements = gates["requirements"]
    original_bytes = sum(row["original_bytes"] for row in rows)
    compression_seconds = sum(row["compression_seconds"] for row in rows)
    aggregate_compression_mbps = (
        original_bytes / max(compression_seconds, 1e-9) / 1_000_000
    )
    load = payload["system_states"][0]["load_average_1m_5m_15m"][0]
    logical_cpus = payload["system_states"][0]["logical_cpus"]
    normalized_load = load / logical_cpus if logical_cpus else None
    payload["aggregate"] = {
        "original_bytes": original_bytes,
        "compression_seconds": compression_seconds,
        "compression_mbps": aggregate_compression_mbps,
    }
    payload["gate_results"] = {
        "preflight_load": (
            normalized_load is not None
            and normalized_load
            <= requirements["max_normalized_preflight_load_1m"]
        ),
        "repetitions": (
            args.repetitions >= requirements["minimum_repetitions"]
        ),
        "transform": all(
            row["transform_mbps"]
            >= requirements["minimum_transform_mbps_per_family"]
            for row in rows
        ),
        "compression_per_family": all(
            row["compression_mbps"]
            >= requirements["minimum_compression_mbps_per_family"]
            for row in rows
        ),
        "compression_aggregate": (
            aggregate_compression_mbps
            >= requirements["minimum_aggregate_compression_mbps"]
        ),
        "decompression": all(
            row["decompression_mbps"]
            >= requirements["minimum_decompression_mbps_per_family"]
            for row in rows
        ),
        "channels": all(
            row["channel_count"] <= requirements["maximum_channels"]
            for row in rows
        ),
    }
    payload["system_states"].append(system_state("run-end"))
    write_output(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
