#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.dense_matrix_transform import (  # noqa: E402
    HEADER,
    _sample_alphabet_python,
    parallel_transform,
    plane_transform,
    selector_backend,
    selector_compress,
    selector_decompress,
    selector_stream_compress,
    selector_stream_decompress,
)
from compresslab.native import zstd_compress  # noqa: E402
from compresslab.tabular_transform import compress_stream  # noqa: E402


MAX_RSS_PATTERN = re.compile(r"^\s*(\d+)\s+maximum resident set size\s*$")
PEAK_FOOTPRINT_PATTERN = re.compile(r"^\s*(\d+)\s+peak memory footprint\s*$")
RECORD_TABLE_IDS = {
    "uci-appliances-energy",
    "uci-bike-sharing-hour",
    "uci-seoul-bike",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
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


def parse_time_output(stderr: str) -> dict[str, int]:
    maximum_resident_set = None
    peak_memory_footprint = None
    for line in stderr.splitlines():
        if match := MAX_RSS_PATTERN.match(line):
            maximum_resident_set = int(match.group(1))
        elif match := PEAK_FOOTPRINT_PATTERN.match(line):
            peak_memory_footprint = int(match.group(1))
    if maximum_resident_set is None:
        raise RuntimeError("/usr/bin/time did not report maximum resident set")
    result = {"maximum_resident_set_bytes": maximum_resident_set}
    if peak_memory_footprint is not None:
        result["peak_memory_footprint_bytes"] = peak_memory_footprint
    return result


def measure_worker(
    mode: str,
    source: Path,
    destination: Path,
    *,
    segment_size: int,
    max_output_size: int,
) -> dict[str, int]:
    command = [
        "/usr/bin/time",
        "-l",
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-mode",
        mode,
        "--source",
        str(source),
        "--destination",
        str(destination),
        "--segment-size",
        str(segment_size),
        "--max-output-size",
        str(max_output_size),
    ]
    completed = subprocess.run(
        command, cwd=REPOSITORY, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{mode} memory worker failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return parse_time_output(completed.stderr)


def run_worker(args: argparse.Namespace) -> int:
    if args.source is None or args.destination is None:
        raise SystemExit("worker source and destination are required")
    if args.worker_mode == "compress-frame":
        args.destination.write_bytes(selector_compress(args.source.read_bytes()))
    elif args.worker_mode == "decompress-frame":
        args.destination.write_bytes(selector_decompress(args.source.read_bytes()))
    elif args.worker_mode == "compress-stream":
        with args.source.open("rb") as source, args.destination.open("wb") as output:
            selector_stream_compress(
                source, output, segment_size=args.segment_size
            )
    elif args.worker_mode == "decompress-stream":
        with args.source.open("rb") as source, args.destination.open("wb") as output:
            selector_stream_decompress(
                source, output, max_output_size=args.max_output_size
            )
    else:
        raise AssertionError(args.worker_mode)
    return 0


def direct_frame_bytes(data: bytes) -> int:
    return HEADER.size + len(zstd_compress(data, level=1))


def specialist_bytes(data: bytes, use_planes: bool) -> int:
    transformed = plane_transform(data) if use_planes else parallel_transform(data)
    return HEADER.size + len(zstd_compress(transformed, level=19))


def copy_repeated(source: Path, destination: Path, repetitions: int) -> None:
    with source.open("rb") as input_file:
        data = input_file.read()
    with destination.open("wb") as output:
        for _ in range(repetitions):
            output.write(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit DMS2 memory, streaming, selector, and regression gates"
    )
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--gates", type=Path)
    parser.add_argument("--baseline-results", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--segment-size", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--stream-repetitions", type=int, default=64)
    parser.add_argument(
        "--worker-mode",
        choices=(
            "compress-frame",
            "decompress-frame",
            "compress-stream",
            "decompress-stream",
        ),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--destination", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--max-output-size", type=int, default=2 * 1024**3, help=argparse.SUPPRESS
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.worker_mode is not None:
        return run_worker(args)
    if None in (args.corpus, args.gates, args.baseline_results, args.output):
        raise SystemExit("corpus, gates, baseline results, and output are required")
    if args.stream_repetitions < 2:
        raise ValueError("stream repetitions must be at least two")

    repository = git_state()
    if repository["dirty"]:
        raise SystemExit("operational audit requires a clean commit")
    manifest_path = args.corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_results.read_text(encoding="utf-8"))
    ceiling_bytes = int(
        gates["operational_gates"]["maximum_peak_rss_mib"] * 1024 * 1024
    )
    median_rows = {
        (row["item_id"], row["codec_id"]): row
        for row in baseline["medians"]
    }

    dense_items = [
        item for item in manifest["items"] if item["track"] == "dense_feature_matrix"
    ]
    record_items = [
        item for item in manifest["items"] if item["id"] in RECORD_TABLE_IDS
    ]
    memory_rows: list[dict[str, Any]] = []
    selector_rows: list[dict[str, Any]] = []
    record_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="compression-lab-dms2-operational-") as root:
        work = Path(root)
        for item in dense_items:
            source = args.corpus / item["path"]
            if source.stat().st_size != item["size_bytes"]:
                raise ValueError(f"corpus size mismatch: {source}")
            if sha256_file(source) != item["sha256"]:
                raise ValueError(f"corpus digest mismatch: {source}")
            frame = work / f"{item['id']}.dms2"
            restored = work / f"{item['id']}.restored"
            compression = measure_worker(
                "compress-frame",
                source,
                frame,
                segment_size=args.segment_size,
                max_output_size=item["size_bytes"],
            )
            decompression = measure_worker(
                "decompress-frame",
                frame,
                restored,
                segment_size=args.segment_size,
                max_output_size=item["size_bytes"],
            )
            if sha256_file(restored) != item["sha256"]:
                raise RuntimeError(f"memory worker round trip failed: {item['id']}")
            memory_rows.append(
                {
                    "id": item["id"],
                    "source_bytes": item["size_bytes"],
                    "complete_bytes": frame.stat().st_size,
                    "compression": {
                        **compression,
                        "gate_passed": compression["maximum_resident_set_bytes"]
                        <= ceiling_bytes,
                    },
                    "decompression": {
                        **decompression,
                        "gate_passed": decompression["maximum_resident_set_bytes"]
                        <= ceiling_bytes,
                    },
                }
            )
            data = source.read_bytes()
            alphabet = _sample_alphabet_python(data)
            dmp1_bytes = specialist_bytes(data, True)
            dma2_bytes = specialist_bytes(data, False)
            selected_frame = selector_compress(data)
            selected_bytes = len(selected_frame)
            direct_bytes = direct_frame_bytes(data)
            oracle_bytes = min(dmp1_bytes, dma2_bytes, direct_bytes)
            selector_rows.append(
                {
                    "id": item["id"],
                    "sample_bytes": min(len(data), 64 * 1024),
                    "sample_alphabet_bucket": alphabet,
                    "selected_backend": selector_backend(selected_frame),
                    "selected_bytes": selected_bytes,
                    "dmp1_bytes": dmp1_bytes,
                    "dma2_bytes": dma2_bytes,
                    "direct_zstd1_bytes": direct_bytes,
                    "oracle_bytes": oracle_bytes,
                    "oracle_selected": selected_bytes == oracle_bytes,
                    "no_expansion_vs_direct": selected_bytes <= direct_bytes,
                }
            )

        for item in record_items:
            source = args.corpus / item["path"]
            encoded = work / f"{item['id']}.tbs1"
            compress_stream(source, encoded)
            current_bytes = encoded.stat().st_size
            frozen_bytes = median_rows[
                (item["id"], "tbl1-stream-dense")
            ]["compressed_bytes"]
            record_rows.append(
                {
                    "id": item["id"],
                    "source_bytes": item["size_bytes"],
                    "frozen_tbs1_bytes": frozen_bytes,
                    "current_tbs1_bytes": current_bytes,
                    "regression_percent": (current_bytes - frozen_bytes)
                    / frozen_bytes
                    * 100,
                    "exact_byte_count_preserved": current_bytes == frozen_bytes,
                }
            )

        seed = args.corpus / next(
            item["path"]
            for item in dense_items
            if item["id"] == "uci-semeion"
        )
        streaming_rows: list[dict[str, Any]] = []
        saturated_repetitions = max(2, args.stream_repetitions // 2)
        for repetitions in (saturated_repetitions, args.stream_repetitions):
            source = work / f"stream-{repetitions}.matrix"
            encoded = work / f"stream-{repetitions}.dss1"
            restored = work / f"stream-{repetitions}.restored"
            copy_repeated(seed, source, repetitions)
            compression = measure_worker(
                "compress-stream",
                source,
                encoded,
                segment_size=args.segment_size,
                max_output_size=source.stat().st_size,
            )
            decompression = measure_worker(
                "decompress-stream",
                encoded,
                restored,
                segment_size=args.segment_size,
                max_output_size=source.stat().st_size,
            )
            if sha256_file(source) != sha256_file(restored):
                raise RuntimeError("streaming memory worker round trip failed")
            streaming_rows.append(
                {
                    "repetitions": repetitions,
                    "source_bytes": source.stat().st_size,
                    "complete_bytes": encoded.stat().st_size,
                    "compression": compression,
                    "decompression": decompression,
                }
            )

    record_frozen = sum(row["frozen_tbs1_bytes"] for row in record_rows)
    record_current = sum(row["current_tbs1_bytes"] for row in record_rows)
    record_regression = (record_current - record_frozen) / record_frozen * 100
    small_stream, large_stream = streaming_rows
    streaming_rss_growth = {
        operation: large_stream[operation]["maximum_resident_set_bytes"]
        - small_stream[operation]["maximum_resident_set_bytes"]
        for operation in ("compression", "decompression")
    }
    bounded_growth_limit = 2 * args.segment_size
    fixed_selector_loo = [
        {
            "held_out_id": row["id"],
            "training_family_ids": [
                other["id"] for other in selector_rows if other["id"] != row["id"]
            ],
            "fitted_parameters": 0,
            "held_out_oracle_selected": row["oracle_selected"],
            "held_out_sample_bytes": row["sample_bytes"],
        }
        for row in selector_rows
    ]
    gates_result = {
        "peak_rss_passed": all(
            row[operation]["gate_passed"]
            for row in memory_rows
            for operation in ("compression", "decompression")
        ),
        "bounded_streaming_passed": all(
            large_stream[operation]["maximum_resident_set_bytes"] <= ceiling_bytes
            and streaming_rss_growth[operation] <= bounded_growth_limit
            for operation in ("compression", "decompression")
        ),
        "record_table_regression_passed": record_regression
        <= gates["ratio_gates"]["maximum_record_table_aggregate_regression_percent"],
        "selector_loo_passed": all(
            row["held_out_oracle_selected"]
            and row["held_out_sample_bytes"]
            <= gates["selector_gates"]["maximum_sample_bytes"]
            for row in fixed_selector_loo
        ),
        "no_expansion_vs_direct_passed": all(
            row["no_expansion_vs_direct"] for row in selector_rows
        ),
    }
    gates_result["all_passed"] = all(gates_result.values())
    payload = {
        "schema_version": 1,
        "name": "dms2-operational-development-gate-v1",
        "stage": "fresh-development-operational-gate",
        "claim_ceiling": gates["claim_ceiling"],
        "git": repository,
        "measurement_tool": "/usr/bin/time -l cold child processes",
        "corpus_manifest": str(manifest_path),
        "corpus_manifest_sha256": sha256_file(manifest_path),
        "gates": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "baseline_results": str(args.baseline_results),
        "baseline_results_sha256": sha256_file(args.baseline_results),
        "memory_ceiling_bytes": ceiling_bytes,
        "frame_memory": memory_rows,
        "streaming": {
            "segment_size": args.segment_size,
            "bounded_growth_limit_bytes": bounded_growth_limit,
            "rows": streaming_rows,
            "large_minus_small_rss_bytes": streaming_rss_growth,
        },
        "selector": {
            "rule": "training-free: DMP1 when bounded prefix alphabet bucket is at most four, DMA2 otherwise, then choose the smaller complete frame against direct zstd-1",
            "maximum_sample_bytes": 64 * 1024,
            "rows": selector_rows,
            "leave_one_family_out": fixed_selector_loo,
        },
        "record_table_regression": {
            "rows": record_rows,
            "frozen_tbs1_bytes": record_frozen,
            "current_tbs1_bytes": record_current,
            "regression_percent": record_regression,
        },
        "gate_results": gates_result,
        "public_validation": "unopened",
        "private_holdout": "sealed",
    }
    write_output(args.output, payload)
    print(json.dumps(gates_result, indent=2, sort_keys=True))
    print(args.output)
    return 0 if gates_result["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
