#!/usr/bin/env python3
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, TypeVar


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.experimental import (  # noqa: E402
    compress_json_log_file,
    decompress_json_log_file,
    inspect_json_log_frame,
)
from compresslab.native import native_available, zstd_engine  # noqa: E402


T = TypeVar("T")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def timed(function: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter()
    result = function()
    return result, time.perf_counter() - started


def system_state(label: str) -> dict[str, object]:
    logical_cpus = os.cpu_count()
    load = list(os.getloadavg())
    return {
        "label": label,
        "load_average_1m_5m_15m": load,
        "logical_cpus": logical_cpus,
        "normalized_load_1m": (
            load[0] / logical_cpus if logical_cpus else None
        ),
    }


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


def accepted_rows(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["family"]: row for row in payload["rows"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the complete experimental JLS2 file product"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--work-directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    accepted = accepted_rows(args.accepted)
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    requirements = gates["requirements"]
    start_state = system_state("run-start")
    normalized_load = start_state["normalized_load_1m"]
    if (
        normalized_load is None
        or normalized_load
        > requirements["max_normalized_preflight_load_1m"]
    ):
        raise SystemExit(
            "ineligible host load: "
            f"{normalized_load!r} > "
            f"{requirements['max_normalized_preflight_load_1m']}"
        )

    repository = git_state()
    if requirements["require_clean_commit"] and repository["dirty"]:
        raise SystemExit("benchmark requires a clean commit")
    if not native_available():
        raise SystemExit("native transform library is unavailable")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "claim_ceiling": (
            "quiet-host complete-product development evidence only; "
            "validation remains sealed"
        ),
        "manifest_path": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "accepted_path": str(args.accepted),
        "accepted_sha256": sha256_file(args.accepted),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "repetitions": args.repetitions,
        "segment_target_bytes": requirements["segment_target_bytes"],
        "git": repository,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "zstd_engine": zstd_engine(),
            "native_available": True,
        },
        "system_states": [start_state],
        "rows": [],
    }
    rows: list[dict[str, Any]] = []

    work_parent = args.work_directory
    if work_parent is not None:
        work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="compression-lab-jls2-product-",
        dir=work_parent,
    ) as temporary_directory:
        work = Path(temporary_directory)
        for item in manifest["items"]:
            family = item["family"]
            source = Path(item["path"])
            if source.stat().st_size != item["size_bytes"]:
                raise ValueError(f"corpus size mismatch: {source}")
            if sha256_file(source) != item["sha256"]:
                raise ValueError(f"corpus digest mismatch: {source}")
            if family not in accepted:
                raise ValueError(f"accepted result is missing family: {family}")

            warm_encoded = work / f"{family}.warm.jls2"
            warm_restored = work / f"{family}.warm.restored"
            compress_json_log_file(
                source,
                warm_encoded,
                segment_size=requirements["segment_target_bytes"],
            )
            decompress_json_log_file(
                warm_encoded,
                warm_restored,
                max_output_size=item["size_bytes"],
            )
            if sha256_file(warm_restored) != item["sha256"]:
                raise RuntimeError(f"warm round trip failed for {family}")
            warm_encoded.unlink()
            warm_restored.unlink()

            compression_samples: list[float] = []
            encoded_digests: list[str] = []
            encoded_sizes: list[int] = []
            canonical_encoded: Path | None = None
            for repetition in range(args.repetitions):
                destination = work / f"{family}.{repetition}.jls2"
                _, seconds = timed(
                    partial(
                        compress_json_log_file,
                        source,
                        destination,
                        segment_size=requirements["segment_target_bytes"],
                    )
                )
                compression_samples.append(seconds)
                encoded_digests.append(sha256_file(destination))
                encoded_sizes.append(destination.stat().st_size)
                if canonical_encoded is None:
                    canonical_encoded = destination
                else:
                    destination.unlink()
            if canonical_encoded is None:
                raise AssertionError("compression produced no output")

            deterministic = len(set(encoded_digests)) == 1
            exact_accepted_bytes = (
                len(set(encoded_sizes)) == 1
                and encoded_sizes[0] == accepted[family]["encoded_bytes"]
                and encoded_digests[0]
                == accepted[family]["encoded_sha256"]
            )
            frame_info = inspect_json_log_frame(
                canonical_encoded.read_bytes()
            )

            decompression_samples: list[float] = []
            for repetition in range(args.repetitions):
                restored = work / f"{family}.{repetition}.restored"
                _, seconds = timed(
                    partial(
                        decompress_json_log_file,
                        canonical_encoded,
                        restored,
                        max_output_size=item["size_bytes"],
                    )
                )
                decompression_samples.append(seconds)
                if restored.stat().st_size != item["size_bytes"]:
                    raise RuntimeError(
                        f"restored size mismatch for {family}"
                    )
                if sha256_file(restored) != item["sha256"]:
                    raise RuntimeError(
                        f"restored digest mismatch for {family}"
                    )
                restored.unlink()
            canonical_encoded.unlink()

            compression_seconds = statistics.median(compression_samples)
            decompression_seconds = statistics.median(
                decompression_samples
            )
            original_bytes = item["size_bytes"]
            row = {
                "family": family,
                "original_bytes": original_bytes,
                "encoded_bytes": encoded_sizes[0],
                "encoded_sha256": encoded_digests[0],
                "accepted_encoded_bytes": accepted[family][
                    "encoded_bytes"
                ],
                "accepted_encoded_sha256": accepted[family][
                    "encoded_sha256"
                ],
                "deterministic_frame": deterministic,
                "exact_accepted_bytes": exact_accepted_bytes,
                "segment_count": frame_info.segment_count,
                "direct_segments": frame_info.direct_segments,
                "columnar_segments": frame_info.columnar_segments,
                "maximum_segment_size": frame_info.maximum_segment_size,
                "compression_seconds": compression_seconds,
                "compression_mbps": (
                    original_bytes
                    / max(compression_seconds, 1e-9)
                    / 1_000_000
                ),
                "compression_samples": compression_samples,
                "decompression_seconds": decompression_seconds,
                "decompression_mbps": (
                    original_bytes
                    / max(decompression_seconds, 1e-9)
                    / 1_000_000
                ),
                "decompression_samples": decompression_samples,
                "roundtrip_verified": True,
            }
            rows.append(row)
            payload["rows"] = rows
            payload["system_states"].append(
                system_state(f"checkpoint-{family}")
            )
            write_output(args.output, payload)
            print(
                f"{family}: compress {row['compression_mbps']:.2f} MB/s, "
                f"decompress {row['decompression_mbps']:.2f} MB/s",
                flush=True,
            )

    original_bytes = sum(row["original_bytes"] for row in rows)
    compression_seconds = sum(row["compression_seconds"] for row in rows)
    decompression_seconds = sum(
        row["decompression_seconds"] for row in rows
    )
    aggregate_compression_mbps = (
        original_bytes / max(compression_seconds, 1e-9) / 1_000_000
    )
    aggregate_decompression_mbps = (
        original_bytes / max(decompression_seconds, 1e-9) / 1_000_000
    )
    payload["aggregate"] = {
        "original_bytes": original_bytes,
        "encoded_bytes": sum(row["encoded_bytes"] for row in rows),
        "compression_seconds": compression_seconds,
        "compression_mbps": aggregate_compression_mbps,
        "decompression_seconds": decompression_seconds,
        "decompression_mbps": aggregate_decompression_mbps,
    }
    payload["gate_results"] = {
        "preflight_load": True,
        "clean_commit": (
            not requirements["require_clean_commit"]
            or not repository["dirty"]
        ),
        "repetitions": (
            args.repetitions >= requirements["minimum_repetitions"]
        ),
        "exact_accepted_bytes": (
            not requirements["require_exact_accepted_bytes"]
            or all(row["exact_accepted_bytes"] for row in rows)
        ),
        "deterministic_frames": (
            not requirements["require_deterministic_frames"]
            or all(row["deterministic_frame"] for row in rows)
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
        "decompression_per_family": all(
            row["decompression_mbps"]
            >= requirements["minimum_decompression_mbps_per_family"]
            for row in rows
        ),
        "roundtrip": all(row["roundtrip_verified"] for row in rows),
    }
    payload["passed"] = all(payload["gate_results"].values())
    payload["system_states"].append(system_state("run-end"))
    write_output(args.output, payload)
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
