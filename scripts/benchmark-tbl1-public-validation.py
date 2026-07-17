#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.codecs import resolve_codecs  # noqa: E402
from compresslab import native as native_module  # noqa: E402
from compresslab.runner import run_benchmark  # noqa: E402
from compresslab.tabular_transform import (  # noqa: E402
    BACKEND_COLUMN,
    BACKEND_DIRECT,
    BACKEND_STORE,
    DENSE_COLUMN_SAFETY_LEVEL,
    DENSE_DEFAULT_LEVEL,
    DENSE_FALLBACK_THREADS,
    HEADER,
    STREAM_HEADER,
    STREAM_SEGMENT_HEADER,
    _compress_dense_direct,
    _pack_frame,
    compress_stream,
    decompress_stream,
    frame_delimiter,
)


CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
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
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "tracked_status": tracked_status}


def git_blob(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def verify_frozen_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    base = candidate["frozen_base_commit"]
    verified: dict[str, str] = {}
    for relative, expected in candidate["frozen_paths"].items():
        working_digest = sha256_file(REPOSITORY / relative)
        base_digest = sha256_bytes(git_blob(base, relative))
        if working_digest != expected:
            raise ValueError(
                f"working candidate path differs from frozen digest: {relative}"
            )
        if base_digest != expected:
            raise ValueError(
                f"frozen base commit differs from declared digest: {relative}"
            )
        verified[relative] = expected
    return verified


def verify_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    gates: dict[str, Any],
) -> list[dict[str, Any]]:
    validation = gates["validation"]
    expected = validation["expected_items"]
    items = manifest.get("items", [])
    observed = [
        {"id": item.get("id"), "family": item.get("family")}
        for item in items
    ]
    if observed != expected:
        raise ValueError("manifest items or order differ from frozen validation")
    if manifest.get("source_split") != "public_validation":
        raise ValueError("manifest is not the frozen public-validation split")
    if manifest.get("benchmark_split") != validation["expected_split"]:
        raise ValueError("manifest benchmark split differs from frozen validation")
    if manifest.get("config_sha256") != validation["corpus_config_sha256"]:
        raise ValueError("manifest corpus configuration digest differs from frozen value")
    maximum = int(validation["maximum_item_bytes"])
    for item in items:
        if item.get("license_spdx") != validation["expected_license_spdx"]:
            raise ValueError(f"unexpected license for {item.get('id')}")
        size = int(item["size_bytes"])
        if not 0 < size <= maximum:
            raise ValueError(f"invalid frozen item size for {item.get('id')}")
        item_path = manifest_path.parent / item["path"]
        if item_path.stat().st_size != size:
            raise ValueError(f"item size mismatch for {item.get('id')}")
        if sha256_file(item_path) != item["sha256"]:
            raise ValueError(f"item digest mismatch for {item.get('id')}")
    return items


def normalized_load_1m() -> float:
    cpus = os.cpu_count()
    if not cpus:
        raise ValueError("logical CPU count is unavailable")
    getloadavg = getattr(os, "getloadavg", None)
    if getloadavg is None:
        raise RuntimeError(
            "one-time validation requires a host that exposes load average"
        )
    return float(getloadavg()[0]) / cpus


def verify_stream_safety(source_path: Path, frame_path: Path) -> dict[str, Any]:
    source = source_path.read_bytes()
    frame = frame_path.read_bytes()
    if len(frame) < STREAM_HEADER.size:
        raise ValueError("TBS1 proof frame is truncated")
    fields = STREAM_HEADER.unpack_from(frame)
    original_size = int(fields[6])
    payload_size = int(fields[7])
    segment_count = int(fields[-1])
    if original_size != len(source):
        raise ValueError("TBS1 proof source size mismatch")
    if payload_size != len(frame) - STREAM_HEADER.size:
        raise ValueError("TBS1 proof payload size mismatch")

    source_offset = 0
    frame_offset = STREAM_HEADER.size
    rows: list[dict[str, Any]] = []
    for index in range(segment_count):
        header_end = frame_offset + STREAM_SEGMENT_HEADER.size
        if header_end > len(frame):
            raise ValueError("TBS1 proof segment header is truncated")
        source_size, inner_size = STREAM_SEGMENT_HEADER.unpack_from(frame, frame_offset)
        frame_offset = header_end
        inner_end = frame_offset + inner_size
        if inner_end > len(frame):
            raise ValueError("TBS1 proof inner frame is truncated")
        inner = frame[frame_offset:inner_end]
        chunk = source[source_offset : source_offset + source_size]
        if len(chunk) != source_size or len(inner) < HEADER.size:
            raise ValueError("TBS1 proof segment source is truncated")
        _magic, _version, delimiter, backend, _size, _digest = HEADER.unpack_from(inner)
        if delimiter != frame_delimiter(inner):
            raise ValueError("TBS1 proof delimiter mismatch")
        if backend == BACKEND_COLUMN:
            payload, fallback_backend, _threads = _compress_dense_direct(
                chunk,
                DENSE_COLUMN_SAFETY_LEVEL,
                1,
            )
            fallback_level = DENSE_COLUMN_SAFETY_LEVEL
        elif backend in {BACKEND_DIRECT, BACKEND_STORE}:
            payload, fallback_backend, _threads = _compress_dense_direct(
                chunk,
                DENSE_DEFAULT_LEVEL,
                DENSE_FALLBACK_THREADS,
            )
            fallback_level = DENSE_DEFAULT_LEVEL
        else:
            raise ValueError("TBS1 proof has an unknown inner backend")
        fallback = _pack_frame(chunk, delimiter, fallback_backend, payload)
        regression = len(inner) - len(fallback)
        rows.append(
            {
                "segment": index,
                "source_bytes": len(chunk),
                "selected_backend": int(backend),
                "selected_frame_bytes": len(inner),
                "fallback_backend": int(fallback_backend),
                "fallback_level": fallback_level,
                "fallback_frame_bytes": len(fallback),
                "regression_bytes": regression,
                "passed": regression <= 0,
            }
        )
        source_offset += source_size
        frame_offset = inner_end
    if source_offset != len(source) or frame_offset != len(frame):
        raise ValueError("TBS1 proof accounting mismatch")
    return {
        "segments": segment_count,
        "maximum_regression_bytes": max(
            (row["regression_bytes"] for row in rows), default=0
        ),
        "passed": all(row["passed"] for row in rows),
        "rows": rows,
    }


def deterministic_proof(
    manifest_path: Path,
    items: list[dict[str, Any]],
    work: Path,
) -> list[dict[str, Any]]:
    proof: list[dict[str, Any]] = []
    for item in items:
        source = manifest_path.parent / item["path"]
        first = work / f"{item['id']}.first.tbs1"
        second = work / f"{item['id']}.second.tbs1"
        restored = work / f"{item['id']}.restored"
        first_metadata = compress_stream(source, first)
        second_metadata = compress_stream(source, second)
        decompress_stream(first, restored, max_output_size=int(item["size_bytes"]))
        first_sha256 = sha256_file(first)
        second_sha256 = sha256_file(second)
        exact = sha256_file(restored) == item["sha256"]
        safety = verify_stream_safety(source, first)
        proof.append(
            {
                "id": item["id"],
                "family": item["family"],
                "source_sha256": item["sha256"],
                "first_frame_sha256": first_sha256,
                "second_frame_sha256": second_sha256,
                "deterministic": first_sha256 == second_sha256,
                "exact_roundtrip": exact,
                "first_metadata": first_metadata,
                "second_metadata": second_metadata,
                "fallback_safety": safety,
            }
        )
    return proof


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the first and only frozen TBL1 public-validation score"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--gates",
        type=Path,
        default=REPOSITORY / "config" / "tbl1-public-validation-gates.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists():
        raise SystemExit("refusing to replace or resume a scored validation directory")
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    repository = git_state()
    requirements = gates["requirements"]
    if requirements["require_clean_tracked_commit"] and repository["tracked_status"]:
        raise SystemExit("validation requires a clean tracked commit")
    if not getattr(native_module, "tabular_native_available")():
        raise SystemExit("native TBL1 transform library is unavailable")
    verified_paths = verify_frozen_candidate(gates["candidate"])
    items = verify_manifest(args.manifest, manifest, gates)
    validation = gates["validation"]
    load = normalized_load_1m()
    if load > float(validation["max_normalized_preflight_load_1m"]):
        raise SystemExit(
            f"ineligible host load: {load} > "
            f"{validation['max_normalized_preflight_load_1m']}"
        )

    codec_ids = [gates["candidate"]["codec_id"], *gates["baselines"]["codec_ids"]]
    codecs = resolve_codecs(codec_ids)
    args.output.mkdir(parents=True)
    attempt_path = args.output / "attempt.json"
    receipt_path = args.output / "receipt.json"
    attempt: dict[str, Any] = {
        "schema_version": 1,
        "first_score": True,
        "completed": False,
        "claim_ceiling": gates["claim_ceiling"],
        "repository": repository,
        "normalized_preflight_load_1m": load,
        "manifest_path": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "benchmark_script_sha256": sha256_file(Path(__file__)),
        "frozen_candidate_paths": verified_paths,
        "codec_ids": codec_ids,
    }
    write_json_atomic(attempt_path, attempt)

    try:
        performance = args.output / "performance"
        run_benchmark(
            corpus_root=args.manifest.parent,
            output_dir=performance,
            codecs=codecs,
            repetitions=int(validation["minimum_repetitions"]),
            warmups=int(validation["warmups"]),
            splits=[validation["expected_split"]],
            bandwidths_mbps=[10.0, 100.0, 1000.0],
            timeout_seconds=float(validation["timeout_seconds"]),
            keep_work=False,
            execution_mode=validation["execution_mode"],
            order_seed=int(validation["order_seed"]),
            confidence_level=0.95,
            bootstrap_samples=2000,
            minimum_trial_time_ms=0.0,
            max_batch_iterations=4096,
        )
        memory = args.output / "memory"
        run_benchmark(
            corpus_root=args.manifest.parent,
            output_dir=memory,
            codecs=resolve_codecs([gates["candidate"]["codec_id"]]),
            repetitions=int(validation["memory_repetitions"]),
            warmups=0,
            splits=[validation["expected_split"]],
            bandwidths_mbps=[100.0],
            timeout_seconds=float(validation["timeout_seconds"]),
            keep_work=False,
            execution_mode=validation["memory_execution_mode"],
            order_seed=int(validation["order_seed"]),
            confidence_level=0.95,
            bootstrap_samples=2000,
            minimum_trial_time_ms=0.0,
            max_batch_iterations=4096,
        )
        proof_work = args.output / "proof-work"
        proof_work.mkdir()
        proof = deterministic_proof(args.manifest, items, proof_work)
        shutil.rmtree(proof_work)
        receipt = attempt | {
            "completed": True,
            "performance_results": "performance/results.json",
            "performance_results_sha256": sha256_file(
                performance / "results.json"
            ),
            "memory_results": "memory/results.json",
            "memory_results_sha256": sha256_file(memory / "results.json"),
            "deterministic_proof": proof,
        }
        write_json_atomic(receipt_path, receipt)
    except BaseException as exc:
        failed = attempt | {
            "completed": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        write_json_atomic(receipt_path, failed)
        raise
    print(receipt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
