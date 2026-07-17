#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.codecs import resolve_codecs  # noqa: E402
from compresslab.dense_matrix_transform import (  # noqa: E402
    SELECTOR_DIRECT,
    SELECTOR_STARTS_WITH_TOKEN,
    STREAM_HEADER,
    STREAM_LENGTH,
    STREAM_TRAILER,
    _selector_frame,
    _stream_segments,
    selector_backend,
    selector_stream_decompress,
)
from compresslab.dense_native import (  # noqa: E402
    dense_parallel_native_available,
    dense_plane_native_available,
)
from compresslab.runner import run_benchmark  # noqa: E402


WORKER = REPOSITORY / "scripts" / "dms2-validation-worker.py"
LOCK_VERIFIER = REPOSITORY / "scripts" / "verify-dms2-public-validation-lock.py"
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


def git_state() -> dict[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "tracked_status": status}


def git_blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout


def verify_frozen_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    base = str(candidate["frozen_base_commit"])
    verified: dict[str, str] = {}
    for relative, expected in candidate["frozen_paths"].items():
        working = sha256_file(REPOSITORY / relative)
        committed = sha256_bytes(git_blob(base, relative))
        if working != expected:
            raise ValueError(f"working candidate path drifted: {relative}")
        if committed != expected:
            raise ValueError(f"frozen base candidate path drifted: {relative}")
        verified[relative] = expected
    return verified


def verify_development_evidence(gates: dict[str, Any]) -> dict[str, str]:
    evidence = gates["development_evidence"]
    pairs = (
        ("speed_ratio_path", "speed_ratio_sha256"),
        ("operational_path", "operational_sha256"),
        ("cross_platform_path", "cross_platform_sha256"),
    )
    verified = {}
    for path_key, digest_key in pairs:
        relative = str(evidence[path_key])
        expected = str(evidence[digest_key])
        if sha256_file(REPOSITORY / relative) != expected:
            raise ValueError(f"development evidence drifted: {relative}")
        verified[relative] = expected
    return verified


def verify_lock(lock_path: Path) -> dict[str, Any]:
    specification = importlib.util.spec_from_file_location(
        "verify_dms2_public_validation_lock", LOCK_VERIFIER
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("unable to load DMS2 validation lock verifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.verify_lock(lock_path)


def verify_manifest(
    manifest_path: Path, manifest: dict[str, Any], gates: dict[str, Any]
) -> list[dict[str, Any]]:
    validation = gates["validation"]
    expected = validation["expected_items"]
    items = manifest.get("items", [])
    observed = [
        {
            "id": item.get("id"),
            "family": item.get("family"),
            "track": item.get("track"),
        }
        for item in items
    ]
    if observed != expected:
        raise ValueError("manifest items, order, family, or track differ from lock")
    if manifest.get("source_split") != "public_validation":
        raise ValueError("manifest is not the frozen public-validation split")
    if manifest.get("benchmark_split") != validation["expected_split"]:
        raise ValueError("manifest benchmark split differs from lock")
    if manifest.get("config_sha256") != validation["corpus_config_sha256"]:
        raise ValueError("manifest corpus configuration digest differs from lock")
    maximum = int(validation["maximum_item_bytes"])
    for item in items:
        if item.get("license_spdx") != validation["expected_license_spdx"]:
            raise ValueError(f"unexpected license for {item.get('id')}")
        size = int(item["size_bytes"])
        if not 0 < size <= maximum:
            raise ValueError(f"invalid item size for {item.get('id')}")
        item_path = manifest_path.parent / item["path"]
        if item_path.stat().st_size != size:
            raise ValueError(f"item size mismatch for {item.get('id')}")
        if sha256_file(item_path) != item["sha256"]:
            raise ValueError(f"item digest mismatch for {item.get('id')}")
    return items


def normalized_load_1m() -> float:
    cpus = os.cpu_count()
    getloadavg = getattr(os, "getloadavg", None)
    if not cpus or getloadavg is None:
        raise RuntimeError("one-time validation host must expose CPU and load average")
    return float(getloadavg()[0]) / cpus


class PersistentDMS2Worker:
    def __init__(self) -> None:
        environment = os.environ.copy()
        existing = environment.get("PYTHONPATH")
        source = str(REPOSITORY / "src")
        environment["PYTHONPATH"] = (
            source if not existing else source + os.pathsep + existing
        )
        self.process = subprocess.Popen(
            [sys.executable, str(WORKER), "--server"],
            cwd=REPOSITORY,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self.process.stdout is None:
            raise RuntimeError("DMS2 worker stdout is unavailable")
        ready = json.loads(self.process.stdout.readline())
        if ready != {"ready": True}:
            raise RuntimeError(f"unexpected DMS2 worker readiness: {ready}")
        self.request_number = 0

    def run(
        self,
        operation: str,
        source: Path,
        destination: Path,
        *,
        segment_size: int,
        level: int,
        max_output_size: int,
    ) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("DMS2 worker pipes are unavailable")
        self.request_number += 1
        request_id = str(self.request_number)
        request = {
            "request_id": request_id,
            "operation": operation,
            "source": str(source),
            "destination": str(destination),
            "segment_size": segment_size,
            "level": level,
            "max_output_size": max_output_size,
        }
        self.process.stdin.write(json.dumps(request, sort_keys=True) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if response.get("request_id") != request_id:
            raise RuntimeError("DMS2 worker response ID mismatch")
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        return dict(response["telemetry"])

    def close(self) -> None:
        if self.process.poll() is None and self.process.stdin is not None:
            self.request_number += 1
            self.process.stdin.write(
                json.dumps(
                    {"request_id": str(self.request_number), "command": "shutdown"}
                )
                + "\n"
            )
            self.process.stdin.flush()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def _corruption_rejected(frame_path: Path, output: Path, maximum: int) -> bool:
    damaged = bytearray(frame_path.read_bytes())
    if not damaged:
        return False
    damaged[-1] ^= 1
    corrupt_path = frame_path.with_suffix(".corrupt")
    corrupt_path.write_bytes(damaged)
    try:
        with corrupt_path.open("rb") as source, output.open("wb") as destination:
            selector_stream_decompress(
                source, destination, max_output_size=maximum
            )
    except ValueError:
        return True
    finally:
        corrupt_path.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
    return False


def verify_stream_safety(source_path: Path, frame_path: Path) -> dict[str, Any]:
    frame = frame_path.read_bytes()
    if len(frame) < STREAM_HEADER.size + STREAM_LENGTH.size + STREAM_TRAILER.size:
        raise ValueError("DSS1 proof frame is truncated")
    _magic, _version, segment_size = STREAM_HEADER.unpack_from(frame)
    with source_path.open("rb") as source_file:
        source_segments = list(_stream_segments(source_file, segment_size))
    offset = STREAM_HEADER.size
    rows: list[dict[str, Any]] = []
    for index, segment in enumerate(source_segments):
        (frame_size,) = STREAM_LENGTH.unpack_from(frame, offset)
        offset += STREAM_LENGTH.size
        inner = frame[offset : offset + frame_size]
        if len(inner) != frame_size:
            raise ValueError("DSS1 proof inner frame is truncated")
        offset += frame_size
        start_flag = (
            SELECTOR_STARTS_WITH_TOKEN
            if not segment or segment[0] not in b" \t,;|\r\n"
            else 0
        )
        direct = _selector_frame(
            segment,
            segment,
            flags=start_flag | SELECTOR_DIRECT,
            level=1,
        )
        rows.append(
            {
                "segment": index,
                "source_bytes": len(segment),
                "selected_backend": selector_backend(inner),
                "selected_frame_bytes": len(inner),
                "direct_frame_bytes": len(direct),
                "regression_bytes": len(inner) - len(direct),
                "passed": len(inner) <= len(direct),
            }
        )
    (terminator,) = STREAM_LENGTH.unpack_from(frame, offset)
    offset += STREAM_LENGTH.size
    if terminator != 0 or offset + STREAM_TRAILER.size != len(frame):
        raise ValueError("DSS1 proof accounting mismatch")
    return {
        "segments": len(rows),
        "maximum_regression_bytes": max(
            (row["regression_bytes"] for row in rows), default=0
        ),
        "passed": all(row["passed"] for row in rows),
        "rows": rows,
    }


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) // 2
    )


def run_candidate_performance(
    manifest_path: Path,
    items: list[dict[str, Any]],
    gates: dict[str, Any],
    output: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation = gates["validation"]
    candidate = gates["candidate"]
    repetitions = int(validation["minimum_repetitions"])
    warmups = int(validation["warmups"])
    segment_size = int(candidate["segment_target_bytes"])
    level = int(candidate["specialist_level"])
    work = output / "candidate-work"
    work.mkdir()
    worker = PersistentDMS2Worker()
    trials: list[dict[str, Any]] = []
    frame_digests: dict[str, list[str]] = defaultdict(list)
    canonical_frames: dict[str, Path] = {}
    failures: list[dict[str, Any]] = []
    try:
        for repetition in range(-warmups, repetitions):
            order = list(items)
            random.Random(int(validation["order_seed"]) + repetition).shuffle(order)
            for order_index, item in enumerate(order):
                source = manifest_path.parent / item["path"]
                frame = work / f"{item['id']}.r{repetition}.dss1"
                restored = work / f"{item['id']}.r{repetition}.restored"
                try:
                    compression = worker.run(
                        "compress",
                        source,
                        frame,
                        segment_size=segment_size,
                        level=level,
                        max_output_size=int(item["size_bytes"]),
                    )
                    decompression = worker.run(
                        "decompress",
                        frame,
                        restored,
                        segment_size=segment_size,
                        level=level,
                        max_output_size=int(item["size_bytes"]),
                    )
                    restored_sha256 = sha256_file(restored)
                    frame_sha256 = sha256_file(frame)
                    frame_digests[item["id"]].append(frame_sha256)
                    if item["id"] not in canonical_frames:
                        canonical = work / f"{item['id']}.canonical.dss1"
                        shutil.copyfile(frame, canonical)
                        canonical_frames[item["id"]] = canonical
                    if repetition >= 0:
                        trials.append(
                            {
                                "item_id": item["id"],
                                "family": item["family"],
                                "repetition": repetition + 1,
                                "order_index": order_index,
                                "original_bytes": int(item["size_bytes"]),
                                "compressed_bytes": frame.stat().st_size,
                                "compression_ns": int(compression["wall_ns"]),
                                "decompression_ns": int(decompression["wall_ns"]),
                                "compression_cpu_ns": int(compression["cpu_ns"]),
                                "decompression_cpu_ns": int(decompression["cpu_ns"]),
                                "compression_peak_rss_bytes": int(
                                    compression["peak_rss_bytes"]
                                ),
                                "decompression_peak_rss_bytes": int(
                                    decompression["peak_rss_bytes"]
                                ),
                                "roundtrip_ok": restored_sha256 == item["sha256"],
                                "source_sha256": item["sha256"],
                                "restored_sha256": restored_sha256,
                                "frame_sha256": frame_sha256,
                                "segments": int(compression["segments"]),
                            }
                        )
                except Exception as error:
                    failures.append(
                        {
                            "item_id": item["id"],
                            "repetition": repetition,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
                finally:
                    frame.unlink(missing_ok=True)
                    restored.unlink(missing_ok=True)
    finally:
        worker.close()

    medians = []
    for item in items:
        rows = [row for row in trials if row["item_id"] == item["id"]]
        medians.append(
            {
                "item_id": item["id"],
                "family": item["family"],
                "codec_id": "dms2-stream",
                "original_bytes": int(item["size_bytes"]),
                "compressed_bytes": _median(
                    [int(row["compressed_bytes"]) for row in rows]
                ),
                "compression_ns": _median(
                    [int(row["compression_ns"]) for row in rows]
                ),
                "decompression_ns": _median(
                    [int(row["decompression_ns"]) for row in rows]
                ),
                "roundtrip_ok": all(row["roundtrip_ok"] for row in rows),
            }
        )
    source_bytes = sum(int(row["original_bytes"]) for row in medians)
    compression_ns = sum(int(row["compression_ns"]) for row in medians)
    decompression_ns = sum(int(row["decompression_ns"]) for row in medians)
    summary = {
        "codec_id": "dms2-stream",
        "original_bytes": source_bytes,
        "compressed_bytes": sum(int(row["compressed_bytes"]) for row in medians),
        "compression_mbps": source_bytes / compression_ns * 1000,
        "decompression_mbps": source_bytes / decompression_ns * 1000,
        "compression_peak_rss_bytes": max(
            (int(row["compression_peak_rss_bytes"]) for row in trials), default=0
        ),
        "decompression_peak_rss_bytes": max(
            (int(row["decompression_peak_rss_bytes"]) for row in trials), default=0
        ),
        "roundtrip_failures": sum(not row["roundtrip_ok"] for row in trials),
    }
    proof = []
    for item in items:
        canonical = canonical_frames[item["id"]]
        source = manifest_path.parent / item["path"]
        proof.append(
            {
                "id": item["id"],
                "family": item["family"],
                "source_sha256": item["sha256"],
                "frame_sha256": sha256_file(canonical),
                "deterministic": len(set(frame_digests[item["id"]])) == 1,
                "exact_roundtrip": all(
                    row["roundtrip_ok"]
                    for row in trials
                    if row["item_id"] == item["id"]
                ),
                "corruption_rejected": _corruption_rejected(
                    canonical,
                    work / f"{item['id']}.corrupt-restored",
                    int(item["size_bytes"]),
                ),
                "fallback_safety": verify_stream_safety(source, canonical),
            }
        )
    payload = {
        "schema_version": 1,
        "codec": {"id": "dms2-stream", "format": candidate["format"]},
        "corpus": [
            {
                "id": item["id"],
                "family": item["family"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
                "split": item["split"],
                "license_spdx": item["license_spdx"],
            }
            for item in items
        ],
        "config": {
            "repetitions": repetitions,
            "warmups": warmups,
            "execution_mode": validation["candidate_execution_mode"],
            "order_seed": validation["order_seed"],
            "splits": [validation["expected_split"]],
            "timing_scope": "persistent worker wall time excluding process startup",
        },
        "failures": failures,
        "trials": trials,
        "medians": medians,
        "summary": summary,
    }
    write_json_atomic(output / "candidate-performance.json", payload)
    return payload, proof


def run_candidate_memory(
    manifest_path: Path,
    items: list[dict[str, Any]],
    gates: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    candidate = gates["candidate"]
    trials = []
    work = output / "candidate-memory-work"
    work.mkdir()
    for item in items:
        source = manifest_path.parent / item["path"]
        frame = work / f"{item['id']}.dss1"
        restored = work / f"{item['id']}.restored"
        compression_telemetry = work / f"{item['id']}.compress.json"
        decompression_telemetry = work / f"{item['id']}.decompress.json"
        common = [
            "--segment-size",
            str(candidate["segment_target_bytes"]),
            "--level",
            str(candidate["specialist_level"]),
            "--max-output-size",
            str(item["size_bytes"]),
        ]
        subprocess.run(
            [
                sys.executable,
                str(WORKER),
                "--operation",
                "compress",
                "--source",
                str(source),
                "--destination",
                str(frame),
                "--telemetry",
                str(compression_telemetry),
                *common,
            ],
            cwd=REPOSITORY,
            check=True,
            timeout=float(gates["validation"]["timeout_seconds"]),
        )
        subprocess.run(
            [
                sys.executable,
                str(WORKER),
                "--operation",
                "decompress",
                "--source",
                str(frame),
                "--destination",
                str(restored),
                "--telemetry",
                str(decompression_telemetry),
                *common,
            ],
            cwd=REPOSITORY,
            check=True,
            timeout=float(gates["validation"]["timeout_seconds"]),
        )
        compression = json.loads(compression_telemetry.read_text())
        decompression = json.loads(decompression_telemetry.read_text())
        trials.append(
            {
                "item_id": item["id"],
                "compression_peak_rss_bytes": compression["peak_rss_bytes"],
                "decompression_peak_rss_bytes": decompression["peak_rss_bytes"],
                "roundtrip_ok": sha256_file(restored) == item["sha256"],
            }
        )
    payload = {
        "schema_version": 1,
        "config": {
            "repetitions": gates["validation"]["memory_repetitions"],
            "execution_mode": gates["validation"]["memory_execution_mode"],
        },
        "trials": trials,
        "summary": {
            "codec_id": "dms2-stream",
            "compression_peak_rss_bytes": max(
                int(row["compression_peak_rss_bytes"]) for row in trials
            ),
            "decompression_peak_rss_bytes": max(
                int(row["decompression_peak_rss_bytes"]) for row in trials
            ),
            "roundtrip_failures": sum(not row["roundtrip_ok"] for row in trials),
        },
    }
    write_json_atomic(output / "candidate-memory.json", payload)
    shutil.rmtree(work)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the first and only frozen DMS2 public-validation score"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--gates",
        type=Path,
        default=REPOSITORY / "config" / "dms2-public-validation-gates.json",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=REPOSITORY / "config" / "dms2-public-validation-lock.json",
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
    if gates["requirements"]["require_clean_tracked_commit"] and repository[
        "tracked_status"
    ]:
        raise SystemExit("validation requires a clean tracked commit")
    if not dense_parallel_native_available() or not dense_plane_native_available():
        raise SystemExit("native DMA2 and DMP1 libraries are unavailable")
    lock_receipt = verify_lock(args.lock)
    candidate_paths = verify_frozen_candidate(gates["candidate"])
    development_paths = verify_development_evidence(gates)
    items = verify_manifest(args.manifest, manifest, gates)
    validation = gates["validation"]
    load = normalized_load_1m()
    if load > float(validation["max_normalized_preflight_load_1m"]):
        raise SystemExit(
            f"ineligible host load: {load} > "
            f"{validation['max_normalized_preflight_load_1m']}"
        )

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
        "gates_path": str(args.gates.resolve()),
        "gates_sha256": sha256_file(args.gates),
        "lock_receipt": lock_receipt,
        "benchmark_script_sha256": sha256_file(Path(__file__)),
        "worker_script_sha256": sha256_file(WORKER),
        "frozen_candidate_paths": candidate_paths,
        "development_evidence_paths": development_paths,
        "baseline_codec_ids": gates["baselines"]["codec_ids"],
    }
    write_json_atomic(attempt_path, attempt)
    try:
        baseline_performance = args.output / "baseline-performance"
        run_benchmark(
            corpus_root=args.manifest.parent,
            output_dir=baseline_performance,
            codecs=resolve_codecs(gates["baselines"]["codec_ids"]),
            repetitions=int(validation["minimum_repetitions"]),
            warmups=int(validation["warmups"]),
            splits=[validation["expected_split"]],
            bandwidths_mbps=[10.0, 100.0, 1000.0],
            timeout_seconds=float(validation["timeout_seconds"]),
            keep_work=False,
            execution_mode=validation["baseline_execution_mode"],
            order_seed=int(validation["order_seed"]),
            confidence_level=0.95,
            bootstrap_samples=2000,
            minimum_trial_time_ms=0.0,
            max_batch_iterations=1,
        )
        baseline_memory = args.output / "baseline-memory"
        run_benchmark(
            corpus_root=args.manifest.parent,
            output_dir=baseline_memory,
            codecs=resolve_codecs(gates["baselines"]["codec_ids"]),
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
            max_batch_iterations=1,
        )
        candidate_performance, proof = run_candidate_performance(
            args.manifest, items, gates, args.output
        )
        candidate_memory = run_candidate_memory(
            args.manifest, items, gates, args.output
        )
        shutil.rmtree(args.output / "candidate-work")
        receipt = attempt | {
            "completed": True,
            "baseline_performance_results": "baseline-performance/results.json",
            "baseline_performance_sha256": sha256_file(
                baseline_performance / "results.json"
            ),
            "baseline_memory_results": "baseline-memory/results.json",
            "baseline_memory_sha256": sha256_file(
                baseline_memory / "results.json"
            ),
            "candidate_performance_results": "candidate-performance.json",
            "candidate_performance_sha256": sha256_file(
                args.output / "candidate-performance.json"
            ),
            "candidate_memory_results": "candidate-memory.json",
            "candidate_memory_sha256": sha256_file(
                args.output / "candidate-memory.json"
            ),
            "deterministic_integrity_fallback_proof": proof,
            "candidate_summary": candidate_performance["summary"],
            "candidate_memory_summary": candidate_memory["summary"],
        }
        write_json_atomic(receipt_path, receipt)
    except BaseException as error:
        write_json_atomic(
            receipt_path,
            attempt
            | {
                "completed": False,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        raise
    print(receipt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
