#!/usr/bin/env python3
"""Run the first and only frozen CLUE-LDS JLS2 v2 public-validation score.

Every candidate resource row - cold-process compression peak RSS and
standalone native decode peak RSS - is measured through the clean-child
instrument (scripts/measure-clean-rss.py). v1 read the standalone decode peak
with os.wait4 reaped directly from this large benchmark parent, which folds the
parent's resident watermark into the child reading; that path is retired here.
Each clean-child reading carries its shim floor and is eligible only when the
floor is at most 64 MiB and at most 25% of the reading; a violation voids the
attempt as an instrument failure and is never converted into a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.benchmark_runner import run_benchmark  # noqa: E402
from compresslab.codecs import probe_codec_versions, resolve_codecs  # noqa: E402
from compresslab.json_log_codec import (  # noqa: E402
    FRAME_HEADER,
    SEGMENT_HEADER,
    STREAM_HEADER,
    ZSTD_LEVEL,
    compress_file,
)
from compresslab.native import zstd_compress  # noqa: E402


LOCK_VERIFIER = REPOSITORY / "scripts" / "verify-clue-jls2-public-validation-v2-lock.py"
MEASURE_CLEAN_RSS = REPOSITORY / "scripts" / "measure-clean-rss.py"
CANDIDATE_COMPRESS_DRIVER = REPOSITORY / "scripts" / "jls2-candidate-compress-v2.py"
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
    tracked_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "tracked_status": tracked_status}


def git_blob(commit: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout


def verify_lock(lock_path: Path) -> dict[str, Any]:
    specification = importlib.util.spec_from_file_location(
        "verify_clue_jls2_public_validation_v2_lock",
        LOCK_VERIFIER,
    )
    if specification is None or specification.loader is None:
        raise ValueError("unable to load readiness-lock verifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.verify_lock(lock_path)


def verify_instrument(gates: dict[str, Any]) -> dict[str, str]:
    instrument = gates["instrument"]
    checks = {
        instrument["clean_rss_path"]: instrument["clean_rss_sha256"],
        instrument["candidate_compress_driver_path"]: instrument[
            "candidate_compress_driver_sha256"
        ],
    }
    verified: dict[str, str] = {}
    for relative, expected in checks.items():
        working = sha256_file(REPOSITORY / relative)
        if working != expected:
            raise ValueError(f"instrument drifted from frozen digest: {relative}")
        verified[relative] = expected
    return verified


def verify_frozen_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    commit = str(candidate["frozen_implementation_commit"])
    verified: dict[str, str] = {}
    for relative, expected in candidate["frozen_paths"].items():
        committed = sha256_bytes(git_blob(commit, relative))
        working = sha256_file(REPOSITORY / relative)
        if committed != expected:
            raise ValueError(f"frozen candidate commit digest mismatch: {relative}")
        if working != expected:
            raise ValueError(f"working candidate path drifted: {relative}")
        verified[relative] = expected
    return verified


def verify_development_evidence(gates: dict[str, Any]) -> dict[str, str]:
    evidence = gates["development_evidence"]
    verified: dict[str, str] = {}
    for prefix in ("ratio_census", "standalone_local", "standalone_hosted"):
        relative = evidence[f"{prefix}_path"]
        expected = evidence[f"{prefix}_sha256"]
        if sha256_file(REPOSITORY / relative) != expected:
            raise ValueError(f"development evidence drifted: {relative}")
        verified[relative] = expected
    return verified


def verify_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    gates: dict[str, Any],
) -> list[dict[str, Any]]:
    validation = gates["validation"]
    expected = validation["expected_items"]
    observed = [
        {
            "id": item.get("id"),
            "family": item.get("family"),
            "first_record_id": item.get("first_record_id"),
            "last_record_id": item.get("last_record_id"),
        }
        for item in manifest.get("items", [])
    ]
    if observed != expected:
        raise ValueError(
            "manifest items, ranges, or order differ from the frozen split"
        )
    if manifest.get("split") != validation["expected_split"]:
        raise ValueError("manifest is not the frozen public-validation split")
    if manifest.get("config_sha256") != validation["corpus_config_sha256"]:
        raise ValueError(
            "manifest corpus configuration digest differs from frozen value"
        )
    items = manifest["items"]
    for item in items:
        if item.get("license_spdx") != validation["expected_license_spdx"]:
            raise ValueError(f"unexpected license for {item.get('id')}")
        item_path = manifest_path.parent / item["path"]
        size = int(item["size_bytes"])
        if size <= 0 or item_path.stat().st_size != size:
            raise ValueError(f"item size mismatch for {item.get('id')}")
        if sha256_file(item_path) != item["sha256"]:
            raise ValueError(f"item digest mismatch for {item.get('id')}")
    return items


def verify_codec_versions(gates: dict[str, Any]) -> list[Any]:
    codec_ids = [
        gates["candidate"]["codec_id"],
        *gates["baselines"]["standard_codec_ids"],
    ]
    codecs = probe_codec_versions(resolve_codecs(codec_ids))
    by_id = {codec.id: codec for codec in codecs}
    required = gates["baselines"]["required_external_versions"]
    probes = {
        "lz4": by_id["lz4-1"].version,
        "zstd": by_id["zstd-9"].version,
        "brotli": by_id["brotli-11"].version,
        "7zip": by_id["7zip-9"].version,
    }
    for name, expected in required.items():
        if expected not in probes[name]:
            raise ValueError(
                f"{name} version differs from frozen {expected}: {probes[name]}"
            )
    return codecs


def normalized_load_1m() -> float:
    cpus = os.cpu_count()
    getloadavg = getattr(os, "getloadavg", None)
    if not cpus or getloadavg is None:
        raise RuntimeError("validation host must expose CPU count and load average")
    return float(getloadavg()[0]) / cpus


def shim_floor_eligible(report: dict[str, Any], requirements: dict[str, Any]) -> bool:
    shim = int(report["shim_maxrss_bytes"])
    maxrss = int(report["maxrss_bytes"])
    floor_ok = shim <= int(requirements["maximum_shim_floor_bytes"])
    fraction_ok = maxrss > 0 and shim <= float(
        requirements["maximum_shim_fraction_of_maxrss"]
    ) * float(maxrss)
    return bool(floor_ok and fraction_ok)


def clean_child_measure(
    command: list[str], report_path: Path
) -> tuple[dict[str, Any], int, str, str]:
    if report_path.exists():
        raise ValueError(f"refusing to overwrite clean-rss report: {report_path}")
    shim_command = [
        sys.executable,
        str(MEASURE_CLEAN_RSS),
        "--json-out",
        str(report_path),
        "--",
        *command,
    ]
    completed = subprocess.run(
        shim_command,
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if not report_path.is_file():
        raise ValueError(
            f"clean-rss instrument produced no report (exit {completed.returncode})"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return report, completed.returncode, completed.stdout, completed.stderr


def require_eligible(
    report: dict[str, Any], requirements: dict[str, Any], label: str
) -> None:
    if not shim_floor_eligible(report, requirements):
        raise ValueError(
            "clean-child shim floor voids the attempt (instrument failure) for "
            f"{label}: shim_maxrss_bytes={report['shim_maxrss_bytes']} "
            f"maxrss_bytes={report['maxrss_bytes']}"
        )


def no_expansion_vs_direct(source: Path, encoded: Path) -> dict[str, Any]:
    encoded_data = encoded.read_bytes()
    if len(encoded_data) < STREAM_HEADER.size:
        raise ValueError("JLS2 stream is truncated")
    segment_count = int(STREAM_HEADER.unpack_from(encoded_data)[-1])
    encoded_offset = STREAM_HEADER.size
    rows: list[dict[str, Any]] = []
    with source.open("rb") as source_file:
        for index in range(segment_count):
            header_end = encoded_offset + SEGMENT_HEADER.size
            if header_end > len(encoded_data):
                raise ValueError("JLS2 segment header is truncated")
            source_size, frame_size = SEGMENT_HEADER.unpack_from(
                encoded_data, encoded_offset
            )
            encoded_offset = header_end
            frame_end = encoded_offset + frame_size
            if frame_end > len(encoded_data):
                raise ValueError("JLS2 segment frame is truncated")
            source_segment = source_file.read(source_size)
            if len(source_segment) != source_size:
                raise ValueError("JLS2 source segment exceeds input")
            direct_size = FRAME_HEADER.size + len(
                zstd_compress(source_segment, level=ZSTD_LEVEL)
            )
            regression = int(frame_size) - direct_size
            rows.append(
                {
                    "segment": index,
                    "selected_frame_bytes": int(frame_size),
                    "direct_frame_bytes": direct_size,
                    "regression_bytes": regression,
                    "passed": regression <= 0,
                }
            )
            encoded_offset = frame_end
        if source_file.read(1):
            raise ValueError("JLS2 stream omits source bytes")
    if encoded_offset != len(encoded_data):
        raise ValueError("JLS2 stream has trailing data")
    accounted_stream_bytes = STREAM_HEADER.size + sum(
        SEGMENT_HEADER.size + row["selected_frame_bytes"] for row in rows
    )
    return {
        "segments": segment_count,
        "stream_bytes": len(encoded_data),
        "accounted_stream_bytes": accounted_stream_bytes,
        "complete_frame_accounting": accounted_stream_bytes == len(encoded_data),
        "maximum_regression_bytes": max(
            (row["regression_bytes"] for row in rows), default=0
        ),
        "passed": all(row["passed"] for row in rows)
        and accounted_stream_bytes == len(encoded_data),
        "rows": rows,
    }


def run_process_plain(command: list[str]) -> tuple[int, str, str]:
    """Run a target without a peak-RSS reading (used for corruption rejection)."""
    completed = subprocess.run(
        command,
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout, completed.stderr


def candidate_compress_rss(
    item: dict[str, Any],
    source: Path,
    work: Path,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    destination = work / f"compress-rss-{item['id']}.jls2"
    report_path = work / f"compress-rss-{item['id']}.clean-rss.json"
    command = [
        sys.executable,
        str(CANDIDATE_COMPRESS_DRIVER),
        "--source",
        str(source),
        "--destination",
        str(destination),
    ]
    report, returncode, _stdout, stderr = clean_child_measure(command, report_path)
    if returncode != 0 or int(report.get("exit_code", 1)) != 0:
        raise ValueError(f"candidate compression failed for {item['id']}: {stderr}")
    require_eligible(report, requirements, f"compression:{item['id']}")
    destination.unlink(missing_ok=True)
    return {
        "item_id": item["id"],
        "family": item["family"],
        "source_bytes": int(item["size_bytes"]),
        "maxrss_bytes": int(report["maxrss_bytes"]),
        "shim_maxrss_bytes": int(report["shim_maxrss_bytes"]),
        "shim_floor_eligible": True,
    }


def native_decode_trial(
    native_binary: Path,
    item: dict[str, Any],
    frame: Path,
    work: Path,
    label: str,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    output = work / f"{label}-{item['id']}.jsonl"
    report_path = work / f"{label}-{item['id']}.clean-rss.json"
    command = [
        str(native_binary),
        "decompress",
        str(frame),
        "-o",
        str(output),
        "--force",
    ]
    report, returncode, stdout, stderr = clean_child_measure(command, report_path)
    exact = (
        returncode == 0
        and int(report.get("exit_code", 1)) == 0
        and output.is_file()
        and output.stat().st_size == item["size_bytes"]
        and sha256_file(output) == item["sha256"]
    )
    output.unlink(missing_ok=True)
    if not exact:
        raise ValueError(f"standalone decode failed for {item['id']}: {stderr}")
    require_eligible(report, requirements, f"decode:{label}:{item['id']}")
    wall_ns = int(report["wall_ns"])
    return {
        "item_id": item["id"],
        "family": item["family"],
        "source_bytes": int(item["size_bytes"]),
        "source_sha256": item["sha256"],
        "encoded_bytes": frame.stat().st_size,
        "encoded_sha256": sha256_file(frame),
        "wall_ns": wall_ns,
        "mbps": int(item["size_bytes"]) / wall_ns * 1000.0,
        "peak_rss_bytes": int(report["maxrss_bytes"]),
        "shim_maxrss_bytes": int(report["shim_maxrss_bytes"]),
        "shim_floor_eligible": True,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "exact": exact,
    }


def summarize_native_trials(
    trials: list[dict[str, Any]], rounds: int
) -> dict[str, Any]:
    measured = [row for row in trials if not row["warmup"]]
    round_rates = []
    for round_number in range(1, rounds + 1):
        rows = [row for row in measured if row["round"] == round_number]
        if not rows:
            raise ValueError(f"missing standalone decode round {round_number}")
        round_rates.append(
            sum(row["source_bytes"] for row in rows)
            / sum(row["wall_ns"] for row in rows)
            * 1000.0
        )
    family_rows = []
    for family in sorted({row["family"] for row in measured}):
        rates = [row["mbps"] for row in measured if row["family"] == family]
        family_rows.append(
            {
                "family": family,
                "median_mbps": statistics.median(rates),
                "minimum_mbps": min(rates),
            }
        )
    return {
        "rounds": rounds,
        "round_rates_mbps": round_rates,
        "median_aggregate_mbps": statistics.median(round_rates),
        "minimum_aggregate_mbps": min(round_rates),
        "peak_rss_bytes": max(row["peak_rss_bytes"] for row in measured),
        "worst_shim_maxrss_bytes": max(row["shim_maxrss_bytes"] for row in measured),
        "all_exact": all(row["exact"] for row in measured),
        "all_shim_floor_eligible": all(row["shim_floor_eligible"] for row in measured),
        "family_rows": family_rows,
    }


def candidate_proof(
    manifest_path: Path,
    items: list[dict[str, Any]],
    native_binary: Path,
    work: Path,
    rounds: int,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    fixtures = work / "fixtures"
    fixtures.mkdir()
    frames: dict[str, Path] = {}
    deterministic_rows = []
    compression_rss_rows = []
    for item in items:
        source = manifest_path.parent / item["path"]
        first = fixtures / f"{item['id']}.first.jls2"
        second = fixtures / f"{item['id']}.second.jls2"
        compress_file(source, first, overwrite=True)
        compress_file(source, second, overwrite=True)
        deterministic = sha256_file(first) == sha256_file(second)
        safety = no_expansion_vs_direct(source, first)
        corrupt = fixtures / f"{item['id']}.corrupt.jls2"
        corrupted = bytearray(first.read_bytes())
        corrupted[len(corrupted) // 2] ^= 1
        corrupt.write_bytes(corrupted)
        corrupt_output = work / f"{item['id']}.corrupt-output"
        corrupt_result = run_process_plain(
            [
                str(native_binary),
                "decompress",
                str(corrupt),
                "-o",
                str(corrupt_output),
            ]
        )
        corruption_rejected = corrupt_result[0] != 0 and not corrupt_output.exists()
        if not deterministic or not safety["passed"] or not corruption_rejected:
            raise ValueError(f"candidate proof failed for {item['id']}")
        compression_rss_rows.append(
            candidate_compress_rss(item, source, work, requirements)
        )
        frames[item["id"]] = first
        deterministic_rows.append(
            {
                "id": item["id"],
                "family": item["family"],
                "source_sha256": item["sha256"],
                "frame_bytes": first.stat().st_size,
                "frame_sha256": sha256_file(first),
                "deterministic": deterministic,
                "fallback_safety": safety,
                "corruption_rejected": corruption_rejected,
            }
        )

    trials = []
    for item in items:
        row = native_decode_trial(
            native_binary,
            item,
            frames[item["id"]],
            work,
            f"warmup-{item['id']}",
            requirements,
        )
        row.update({"round": 0, "warmup": True})
        trials.append(row)
    for round_number in range(1, rounds + 1):
        ordered = list(items)
        if round_number % 2 == 0:
            ordered.reverse()
        for item in ordered:
            row = native_decode_trial(
                native_binary,
                item,
                frames[item["id"]],
                work,
                f"round-{round_number}-{item['id']}",
                requirements,
            )
            row.update({"round": round_number, "warmup": False})
            trials.append(row)
    worst_compression = max(row["maxrss_bytes"] for row in compression_rss_rows)
    return {
        "deterministic_rows": deterministic_rows,
        "compression_rss_rows": compression_rss_rows,
        "compression_rss_summary": {
            "peak_rss_bytes": worst_compression,
            "worst_shim_maxrss_bytes": max(
                row["shim_maxrss_bytes"] for row in compression_rss_rows
            ),
            "all_shim_floor_eligible": all(
                row["shim_floor_eligible"] for row in compression_rss_rows
            ),
        },
        "standalone_decode_trials": trials,
        "standalone_decode_summary": summarize_native_trials(trials, rounds),
    }


def write_pbc_accepted(
    results_path: Path,
    items: list[dict[str, Any]],
    output: Path,
) -> None:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    medians = results["medians"]
    rows = []
    for item in items:
        by_codec = {
            row["codec_id"]: row for row in medians if row["item_id"] == item["id"]
        }
        if "jls2" not in by_codec or "zstd-9" not in by_codec:
            raise ValueError(f"PBC projection is missing candidate rows: {item['id']}")
        candidate = by_codec["jls2"]
        zstd9 = by_codec["zstd-9"]
        if candidate["source_sha256"] != item["sha256"]:
            raise ValueError(f"PBC projection source mismatch: {item['id']}")
        rows.append(
            {
                "id": item["id"],
                "family": item["family"],
                "original_bytes": int(item["size_bytes"]),
                "source_sha256": item["sha256"],
                "encoded_bytes": int(candidate["compressed_bytes"]),
                "zstd9_bytes": int(zstd9["compressed_bytes"]),
            }
        )
    write_json_atomic(output, {"schema_version": 1, "rows": rows})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--gates",
        type=Path,
        default=REPOSITORY / "config" / "clue-jls2-public-validation-v2-gates.json",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=REPOSITORY / "config" / "clue-jls2-public-validation-v2-lock.json",
    )
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists():
        raise SystemExit("refusing to replace or resume a scored validation directory")
    lock_receipt = verify_lock(args.lock)
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    repository = git_state()
    requirements = gates["requirements"]
    if requirements["require_clean_tracked_commit"] and repository["tracked_status"]:
        raise SystemExit("validation requires a clean tracked commit")
    native_binary = args.native_binary.resolve()
    if not native_binary.is_file() or not os.access(native_binary, os.X_OK):
        raise SystemExit(f"standalone native decoder is missing: {native_binary}")
    verified_instrument = verify_instrument(gates)
    verified_paths = verify_frozen_candidate(gates["candidate"])
    verified_evidence = verify_development_evidence(gates)
    items = verify_manifest(args.manifest, manifest, gates)
    codecs = verify_codec_versions(gates)
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
        "clean_rss_instrument_sha256": verified_instrument[
            gates["instrument"]["clean_rss_path"]
        ],
        "verified_instrument_paths": verified_instrument,
        "native_binary_sha256": sha256_file(native_binary),
        "frozen_candidate_paths": verified_paths,
        "verified_development_evidence": verified_evidence,
        "codec_ids": [codec.id for codec in codecs],
        "codec_versions": {codec.id: codec.version for codec in codecs},
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
            execution_mode=validation["standard_execution_mode"],
            order_seed=int(validation["order_seed"]),
            confidence_level=0.95,
            bootstrap_samples=2000,
            minimum_trial_time_ms=0.0,
            max_batch_iterations=4096,
            manifest_path=args.manifest,
        )
        proof_work = args.output / "proof-work"
        proof_work.mkdir()
        proof = candidate_proof(
            args.manifest,
            items,
            native_binary,
            proof_work,
            int(validation["minimum_repetitions"]),
            requirements,
        )
        pbc_accepted = args.output / "pbc-accepted.json"
        write_pbc_accepted(performance / "results.json", items, pbc_accepted)
        shutil.rmtree(proof_work)
        receipt = attempt | {
            "completed": True,
            "performance_results": "performance/results.json",
            "performance_results_sha256": sha256_file(performance / "results.json"),
            "candidate_proof": proof,
            "pbc_accepted": "pbc-accepted.json",
            "pbc_accepted_sha256": sha256_file(pbc_accepted),
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
