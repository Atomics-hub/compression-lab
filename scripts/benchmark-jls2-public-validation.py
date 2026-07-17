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
    decompress_json_log_file,
    inspect_json_log_frame,
)
from compresslab.json_log_codec import (  # noqa: E402
    FRAME_HEADER,
    SEGMENT_HEADER,
    STREAM_HEADER,
    ZSTD_LEVEL,
    compress_file,
)
from compresslab.native import (  # noqa: E402
    native_available,
    zstd_compress,
    zstd_decompress,
    zstd_engine,
)


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


def git_state() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "tracked_status": tracked_status}


def system_state(label: str) -> dict[str, Any]:
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


def run_command(command: list[str]) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    seconds = time.perf_counter() - started
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): "
            f"{' '.join(command)}\n{completed.stdout}{completed.stderr}"
        )
    return seconds


def brotli_compress(source: Path, destination: Path, level: int) -> float:
    return run_command(
        [
            "brotli",
            "-f",
            "-q",
            str(level),
            str(source),
            "-o",
            str(destination),
        ]
    )


def brotli_decompress(source: Path, destination: Path) -> float:
    return run_command(
        [
            "brotli",
            "-f",
            "-d",
            str(source),
            "-o",
            str(destination),
        ]
    )


def percentage_gain(reference_bytes: int, candidate_bytes: int) -> float:
    return (reference_bytes - candidate_bytes) / reference_bytes * 100.0


def no_expansion_vs_direct(source: Path, encoded: Path) -> bool:
    encoded_data = encoded.read_bytes()
    if len(encoded_data) < STREAM_HEADER.size:
        raise ValueError("JLS2 stream is truncated")
    stream_fields = STREAM_HEADER.unpack_from(encoded_data)
    segment_count = stream_fields[-1]
    encoded_offset = STREAM_HEADER.size
    with source.open("rb") as source_file:
        for _ in range(segment_count):
            header_end = encoded_offset + SEGMENT_HEADER.size
            if header_end > len(encoded_data):
                raise ValueError("JLS2 segment header is truncated")
            source_size, frame_size = SEGMENT_HEADER.unpack_from(
                encoded_data,
                encoded_offset,
            )
            encoded_offset = header_end
            frame_end = encoded_offset + frame_size
            if frame_end > len(encoded_data):
                raise ValueError("JLS2 segment frame is truncated")
            source_segment = source_file.read(source_size)
            if len(source_segment) != source_size:
                raise ValueError("JLS2 source segment exceeds input")
            direct_frame_size = FRAME_HEADER.size + len(
                zstd_compress(source_segment, level=ZSTD_LEVEL)
            )
            if frame_size > direct_frame_size:
                return False
            encoded_offset = frame_end
        if source_file.read(1):
            raise ValueError("JLS2 stream omits source bytes")
    if encoded_offset != len(encoded_data):
        raise ValueError("JLS2 stream has trailing data")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the first and only frozen JLS2 public validation score"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--work-directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    validation = gates["validation"]
    candidate = gates["candidate"]
    requirements = gates["requirements"]
    if args.repetitions < validation["minimum_repetitions"]:
        raise SystemExit("insufficient validation repetitions")
    if candidate["internal_zstd_level"] != ZSTD_LEVEL:
        raise SystemExit("candidate internal zstd level differs from code")
    if not native_available():
        raise SystemExit("native JLS2 transform library is unavailable")

    repository = git_state()
    if requirements["require_clean_commit"] and repository["tracked_status"]:
        raise SystemExit("validation requires clean tracked source")

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

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest_families = [item["family"] for item in manifest["items"]]
    if manifest_families != validation["expected_families"]:
        raise SystemExit(
            "manifest families or order differ from the frozen validation"
        )

    brotli_version = subprocess.run(
        ["brotli", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "claim_ceiling": gates["claim_ceiling"],
        "first_score": True,
        "manifest_path": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "repetitions": args.repetitions,
        "segment_target_bytes": candidate["segment_target_bytes"],
        "frozen_base_commit": candidate["frozen_base_commit"],
        "git": repository,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "native_available": True,
            "zstd_engine": zstd_engine(),
            "brotli": brotli_version,
        },
        "system_states": [start_state],
        "rows": [],
    }
    rows: list[dict[str, Any]] = []

    work_parent = args.work_directory
    if work_parent is not None:
        work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="compression-lab-jls2-validation-",
        dir=work_parent,
    ) as temporary_directory:
        work = Path(temporary_directory)
        for item in manifest["items"]:
            family = item["family"]
            source = Path(item["path"]).resolve()
            if source.stat().st_size != item["size_bytes"]:
                raise ValueError(f"corpus size mismatch: {source}")
            if sha256_file(source) != item["sha256"]:
                raise ValueError(f"corpus digest mismatch: {source}")

            source_data = source.read_bytes()
            zstd_encoded, zstd_compression_seconds = timed(
                partial(
                    zstd_compress,
                    source_data,
                    level=gates["baselines"]["zstd_level"],
                )
            )
            zstd_restored, zstd_decompression_seconds = timed(
                partial(
                    zstd_decompress,
                    zstd_encoded,
                    len(source_data),
                )
            )
            if zstd_restored != source_data:
                raise RuntimeError(f"zstd-9 round trip failed for {family}")

            brotli_encoded = work / f"{family}.br"
            brotli_restored = work / f"{family}.brotli-restored"
            brotli_compression_seconds = brotli_compress(
                source,
                brotli_encoded,
                gates["baselines"]["brotli_level"],
            )
            brotli_decompression_seconds = brotli_decompress(
                brotli_encoded,
                brotli_restored,
            )
            if brotli_restored.stat().st_size != item["size_bytes"]:
                raise RuntimeError(
                    f"Brotli restored size mismatch for {family}"
                )
            if sha256_file(brotli_restored) != item["sha256"]:
                raise RuntimeError(
                    f"Brotli restored digest mismatch for {family}"
                )

            warm_encoded = work / f"{family}.warm.jls2"
            warm_restored = work / f"{family}.warm.restored"
            compress_file(
                source,
                warm_encoded,
                segment_size=candidate["segment_target_bytes"],
            )
            decompress_json_log_file(
                warm_encoded,
                warm_restored,
                max_output_size=item["size_bytes"],
            )
            if sha256_file(warm_restored) != item["sha256"]:
                raise RuntimeError(f"JLS2 warm round trip failed for {family}")
            warm_encoded.unlink()
            warm_restored.unlink()

            compression_samples: list[float] = []
            encoded_sizes: list[int] = []
            encoded_digests: list[str] = []
            canonical_encoded: Path | None = None
            for repetition in range(args.repetitions):
                encoded = work / f"{family}.{repetition}.jls2"
                _, seconds = timed(
                    partial(
                        compress_file,
                        source,
                        encoded,
                        segment_size=candidate["segment_target_bytes"],
                    )
                )
                compression_samples.append(seconds)
                encoded_sizes.append(encoded.stat().st_size)
                encoded_digests.append(sha256_file(encoded))
                if canonical_encoded is None:
                    canonical_encoded = encoded
                else:
                    encoded.unlink()
            if canonical_encoded is None:
                raise AssertionError("JLS2 compression produced no output")

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
                        f"JLS2 restored size mismatch for {family}"
                    )
                if sha256_file(restored) != item["sha256"]:
                    raise RuntimeError(
                        f"JLS2 restored digest mismatch for {family}"
                    )
                restored.unlink()

            frame_info = inspect_json_log_frame(
                canonical_encoded.read_bytes()
            )
            no_expansion = no_expansion_vs_direct(
                source,
                canonical_encoded,
            )
            canonical_encoded.unlink()
            brotli_bytes = brotli_encoded.stat().st_size
            brotli_digest = sha256_file(brotli_encoded)
            brotli_encoded.unlink()
            brotli_restored.unlink()

            compression_seconds = statistics.median(
                compression_samples
            )
            decompression_seconds = statistics.median(
                decompression_samples
            )
            encoded_bytes = encoded_sizes[0]
            zstd9_bytes = len(zstd_encoded)
            original_bytes = item["size_bytes"]
            row = {
                "family": family,
                "original_bytes": original_bytes,
                "source_sha256": item["sha256"],
                "encoded_bytes": encoded_bytes,
                "encoded_sha256": encoded_digests[0],
                "deterministic_frame": (
                    len(set(encoded_sizes)) == 1
                    and len(set(encoded_digests)) == 1
                ),
                "no_expansion_vs_direct_frame": no_expansion,
                "segment_count": frame_info.segment_count,
                "direct_segments": frame_info.direct_segments,
                "columnar_segments": frame_info.columnar_segments,
                "maximum_segment_size": frame_info.maximum_segment_size,
                "compression_seconds": compression_seconds,
                "compression_samples": compression_samples,
                "compression_mbps": (
                    original_bytes
                    / max(compression_seconds, 1e-9)
                    / 1_000_000
                ),
                "decompression_seconds": decompression_seconds,
                "decompression_samples": decompression_samples,
                "decompression_mbps": (
                    original_bytes
                    / max(decompression_seconds, 1e-9)
                    / 1_000_000
                ),
                "roundtrip_verified": True,
                "zstd9_bytes": zstd9_bytes,
                "zstd9_sha256": hashlib.sha256(
                    zstd_encoded
                ).hexdigest(),
                "zstd9_compression_seconds": zstd_compression_seconds,
                "zstd9_decompression_seconds": (
                    zstd_decompression_seconds
                ),
                "gain_vs_zstd9_percent": percentage_gain(
                    zstd9_bytes,
                    encoded_bytes,
                ),
                "brotli11_bytes": brotli_bytes,
                "brotli11_sha256": brotli_digest,
                "brotli11_compression_seconds": (
                    brotli_compression_seconds
                ),
                "brotli11_decompression_seconds": (
                    brotli_decompression_seconds
                ),
                "gain_vs_brotli11_percent": percentage_gain(
                    brotli_bytes,
                    encoded_bytes,
                ),
            }
            rows.append(row)
            payload["rows"] = rows
            payload["system_states"].append(
                system_state(f"checkpoint-{family}")
            )
            write_output(args.output, payload)
            print(
                f"{family}: JLS2={encoded_bytes}, zstd-9={zstd9_bytes}, "
                f"Brotli-11={brotli_bytes}, "
                f"compress={row['compression_mbps']:.2f} MB/s, "
                f"decompress={row['decompression_mbps']:.2f} MB/s",
                flush=True,
            )

    original_bytes = sum(row["original_bytes"] for row in rows)
    encoded_bytes = sum(row["encoded_bytes"] for row in rows)
    zstd9_bytes = sum(row["zstd9_bytes"] for row in rows)
    brotli11_bytes = sum(row["brotli11_bytes"] for row in rows)
    compression_seconds = sum(row["compression_seconds"] for row in rows)
    decompression_seconds = sum(
        row["decompression_seconds"] for row in rows
    )
    payload["aggregate"] = {
        "original_bytes": original_bytes,
        "encoded_bytes": encoded_bytes,
        "zstd9_bytes": zstd9_bytes,
        "brotli11_bytes": brotli11_bytes,
        "gain_vs_zstd9_percent": percentage_gain(
            zstd9_bytes,
            encoded_bytes,
        ),
        "gain_vs_brotli11_percent": percentage_gain(
            brotli11_bytes,
            encoded_bytes,
        ),
        "compression_seconds": compression_seconds,
        "compression_mbps": (
            original_bytes / max(compression_seconds, 1e-9) / 1_000_000
        ),
        "decompression_seconds": decompression_seconds,
        "decompression_mbps": (
            original_bytes
            / max(decompression_seconds, 1e-9)
            / 1_000_000
        ),
    }
    payload["completed"] = True
    payload["system_states"].append(system_state("run-end"))
    write_output(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
