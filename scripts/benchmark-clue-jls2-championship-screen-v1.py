#!/usr/bin/env python3
"""Run the first and only frozen CLUE-LDS JLS2 championship screen.

This runner extends the frozen JLS2 v2 benchmark. The JLS2 candidate is measured
exactly as v2 (frozen encoder; determinism, corruption rejection, complete-frame
accounting, and cold-process compression + standalone-decode peak RSS through the
clean-child instrument scripts/measure-clean-rss.py). It then runs each frozen
opponent tool built on the runner - Kanzi-max, ZPAQ -method 54, Brotli-11,
zstd --ultra -22, xz 9e, 7-Zip mx=9, and the PBC specialist projection - capturing
each built binary's SHA-256 at execution and classifying every opponent execution
as a valid byte-exact roundtrip or an invalid-tool-failure (crash, timeout, or
mis-restore). The contextual -method 510 and zstd --long=31 ceilings are run for
context only and never enter the eligible comparison.

The output is a score bundle consumed by the frozen integer reducer
(scripts/reduce-clue-jls2-championship-screen-v1.py) via the evaluator. This
runner performs the measurement only; it does not decide the contender question.
Opponent binaries are built by the workflow from pinned sources and passed in by
path; the frozen per-codec command templates live here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.json_log_codec import (  # noqa: E402
    FRAME_HEADER,
    SEGMENT_HEADER,
    STREAM_HEADER,
    ZSTD_LEVEL,
    compress_file,
)
from compresslab.native import zstd_compress  # noqa: E402


LOCK_VERIFIER = (
    REPOSITORY / "scripts" / "verify-clue-jls2-championship-screen-v1-lock.py"
)
MEASURE_CLEAN_RSS = REPOSITORY / "scripts" / "measure-clean-rss.py"
CANDIDATE_COMPRESS_DRIVER = REPOSITORY / "scripts" / "jls2-candidate-compress-v2.py"
PBC_BENCHMARK = REPOSITORY / "scripts" / "benchmark-pbc-competitor.py"
CHUNK_SIZE = 1024 * 1024

# Frozen per-codec command templates. Each template expands with {source},
# {archive}, {restored}, and {bin} (the built binary path passed by the workflow).
# The archive is the complete file that exactly restores the source; its byte
# count is the complete-archive size scored by the reducer.
OPPONENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "kanzi-max": {
        "role": "eligible",
        "compress": ["{bin}", "--compress", "--input", "{source}", "--output",
                     "{archive}", "--level", "9", "--block", "1g", "--jobs", "1",
                     "--force"],
        "decompress": ["{bin}", "--decompress", "--input", "{archive}", "--output",
                       "{restored}", "--jobs", "1", "--force"],
    },
    "zpaq-5-m54": {
        "role": "eligible",
        "compress": ["{bin}", "add", "{archive}", "{source}", "-method", "54",
                     "-threads", "1", "-noattributes", "-until", "20000101000000"],
        "decompress": ["{bin}", "extract", "{archive}", "-to", "{restored}",
                       "-threads", "1", "-force"],
    },
    "brotli-11": {
        "role": "eligible",
        "compress": ["{bin}", "--quality", "11", "--force", "--output", "{archive}",
                     "{source}"],
        "decompress": ["{bin}", "--decompress", "--force", "--output", "{restored}",
                       "{archive}"],
    },
    "zstd-22": {
        "role": "eligible",
        "compress": ["{bin}", "--ultra", "-22", "-T1", "-f", "-o", "{archive}",
                     "{source}"],
        "decompress": ["{bin}", "-d", "-f", "-o", "{restored}", "{archive}"],
    },
    "xz-lzma2-9e": {
        "role": "eligible",
        "compress": ["{bin}", "--format=xz", "--check=crc64", "--lzma2=preset=9e",
                     "--threads=1", "-k", "-f", "-c", "{source}"],
        "compress_stdout": "{archive}",
        "decompress": ["{bin}", "-d", "-k", "-f", "-c", "{archive}"],
        "decompress_stdout": "{restored}",
    },
    "7zip-9": {
        "role": "eligible",
        "compress": ["{bin}", "a", "-t7z", "-m0=LZMA2", "-mx=9", "-bd", "{archive}",
                     "{source}"],
        "decompress": ["{bin}", "e", "-bd", "-y", "{archive}"],
    },
    "zpaq-5-m510": {
        "role": "contextual",
        "compress": ["{bin}", "add", "{archive}", "{source}", "-method", "510",
                     "-threads", "1", "-noattributes", "-until", "20000101000000"],
        "decompress": ["{bin}", "extract", "{archive}", "-to", "{restored}",
                       "-threads", "1", "-force"],
    },
    "zstd-22-long31": {
        "role": "contextual",
        "compress": ["{bin}", "--ultra", "-22", "--long=31", "-T1", "-f", "-o",
                     "{archive}", "{source}"],
        "decompress": ["{bin}", "-d", "--long=31", "-f", "-o", "{restored}",
                       "{archive}"],
    },
}


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
        "verify_clue_jls2_championship_screen_v1_lock",
        LOCK_VERIFIER,
    )
    if specification is None or specification.loader is None:
        raise ValueError("unable to load championship readiness-lock verifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.verify_lock(lock_path)


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
        raise ValueError("manifest items, ranges, or order differ from the frozen split")
    if manifest.get("split") != validation["expected_split"]:
        raise ValueError("manifest is not the frozen public-validation split")
    items = manifest["items"]
    for item in items:
        if item.get("license_spdx") != validation["expected_license_spdx"]:
            raise ValueError(f"unexpected license for {item.get('id')}")
        item_path = manifest_path.parent / item["path"]
        size = int(item["size_bytes"])
        expected_count = validation["expected_record_counts"][item["id"]]
        if int(item["record_count"]) != int(expected_count):
            raise ValueError(f"record count mismatch for {item.get('id')}")
        if size <= 0 or item_path.stat().st_size != size:
            raise ValueError(f"item size mismatch for {item.get('id')}")
        if sha256_file(item_path) != item["sha256"]:
            raise ValueError(f"item digest mismatch for {item.get('id')}")
    return items


def shim_floor_eligible(report: dict[str, Any], requirements: dict[str, Any]) -> bool:
    shim = int(report["shim_maxrss_bytes"])
    maxrss = int(report["maxrss_bytes"])
    floor_ok = shim <= int(requirements["maximum_shim_floor_bytes"])
    fraction_ok = maxrss > 0 and shim <= float(
        requirements["maximum_shim_fraction_of_maxrss"]
    ) * float(maxrss)
    return bool(floor_ok and fraction_ok)


def clean_child_measure(command: list[str], report_path: Path) -> dict[str, Any]:
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
    completed = subprocess.run(shim_command, cwd=REPOSITORY, capture_output=True, text=True)
    if not report_path.is_file():
        raise ValueError(
            f"clean-rss instrument produced no report (exit {completed.returncode})"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["outer_returncode"] = completed.returncode
    report["outer_stderr"] = completed.stderr
    return report


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
            source_size, frame_size = SEGMENT_HEADER.unpack_from(encoded_data, encoded_offset)
            encoded_offset = header_end
            frame_end = encoded_offset + frame_size
            if frame_end > len(encoded_data):
                raise ValueError("JLS2 segment frame is truncated")
            source_segment = source_file.read(source_size)
            if len(source_segment) != source_size:
                raise ValueError("JLS2 source segment exceeds input")
            direct_size = FRAME_HEADER.size + len(zstd_compress(source_segment, level=ZSTD_LEVEL))
            rows.append(
                {
                    "segment": index,
                    "selected_frame_bytes": int(frame_size),
                    "direct_frame_bytes": direct_size,
                    "regression_bytes": int(frame_size) - direct_size,
                    "passed": int(frame_size) - direct_size <= 0,
                }
            )
            encoded_offset = frame_end
        if source_file.read(1):
            raise ValueError("JLS2 stream omits source bytes")
    if encoded_offset != len(encoded_data):
        raise ValueError("JLS2 stream has trailing data")
    accounted = STREAM_HEADER.size + sum(
        SEGMENT_HEADER.size + row["selected_frame_bytes"] for row in rows
    )
    return {
        "segments": segment_count,
        "stream_bytes": len(encoded_data),
        "accounted_stream_bytes": accounted,
        "complete_frame_accounting": accounted == len(encoded_data),
        "maximum_regression_bytes": max((row["regression_bytes"] for row in rows), default=0),
        "passed": all(row["passed"] for row in rows) and accounted == len(encoded_data),
        "rows": rows,
    }


def run_plain(command: list[str], timeout: float) -> tuple[int, bool]:
    """Run a target without a peak-RSS reading (used for corruption rejection)."""
    try:
        completed = subprocess.run(
            command, cwd=REPOSITORY, capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, True
    return completed.returncode, False


def _expand(template: list[str], mapping: dict[str, str]) -> list[str]:
    return [token.format(**mapping) for token in template]


def _run_redirected(
    argv: list[str], stdout_path: Path | None, timeout: float
) -> tuple[int, bool, int]:
    """Run a command (optionally redirecting stdout to a file) and time it.

    Returns (returncode, timed_out, wall_ns). Every invocation - including the
    stdout-redirected and determinism re-runs - is timed the same way, so no
    measurement is untimed.
    """
    started = time.perf_counter_ns()
    try:
        if stdout_path is not None:
            with stdout_path.open("wb") as handle:
                completed = subprocess.run(
                    argv,
                    cwd=REPOSITORY,
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                )
        else:
            completed = subprocess.run(
                argv, cwd=REPOSITORY, capture_output=True, timeout=timeout
            )
    except subprocess.TimeoutExpired:
        return 124, True, time.perf_counter_ns() - started
    return completed.returncode, False, time.perf_counter_ns() - started


def _compress(spec: dict[str, Any], mapping: dict[str, str], wall: float) -> tuple[int, bool, int]:
    stdout_path = (
        Path(spec["compress_stdout"].format(**mapping)) if "compress_stdout" in spec else None
    )
    return _run_redirected(_expand(spec["compress"], mapping), stdout_path, wall)


def _decompress(spec: dict[str, Any], mapping: dict[str, str], wall: float) -> tuple[int, bool, int]:
    stdout_path = (
        Path(spec["decompress_stdout"].format(**mapping)) if "decompress_stdout" in spec else None
    )
    return _run_redirected(_expand(spec["decompress"], mapping), stdout_path, wall)


def run_opponent_item(
    codec_id: str,
    spec: dict[str, Any],
    binary: Path,
    source: Path,
    source_sha256: str,
    family: str,
    work: Path,
    wall_seconds: float,
) -> dict[str, Any]:
    """Run one opponent on ONE item (family) and classify that item independently.

    Determinism is checked by compressing twice and comparing archive bytes;
    exactness by restoring and comparing the SHA-256 to the source (a byte-exact
    roundtrip preserves record order and timezone text). A failure here is an
    invalid-tool-failure for THIS item only; another item's result stands.
    Every compress/decompress invocation (including the stdout-redirected and
    determinism re-runs) is timed.
    """
    tag = f"{codec_id}.{family}"
    mapping = {
        "bin": str(binary),
        "source": str(source),
        "archive": str(work / f"{tag}.archive"),
        "restored": str(work / f"{tag}.restored"),
    }
    archive = Path(mapping["archive"])
    restored = Path(mapping["restored"])
    second_archive = work / f"{tag}.archive.second"

    compress_rc, compress_timeout, compress_wall_ns = _compress(spec, mapping, wall_seconds)
    archive_bytes = archive.stat().st_size if archive.is_file() else None

    deterministic = False
    second_wall_ns = 0
    if archive.is_file() and not compress_timeout and compress_rc == 0:
        second_mapping = dict(mapping, archive=str(second_archive))
        _rc2, _to2, second_wall_ns = _compress(spec, second_mapping, wall_seconds)
        deterministic = second_archive.is_file() and sha256_file(archive) == sha256_file(second_archive)

    decompress_rc, decompress_timeout, decompress_wall_ns = 1, False, 0
    restored_sha256 = None
    if archive.is_file() and compress_rc == 0 and not compress_timeout:
        decompress_rc, decompress_timeout, decompress_wall_ns = _decompress(
            spec, mapping, wall_seconds
        )
        if restored.is_file():
            restored_sha256 = sha256_file(restored)

    exact = restored_sha256 == source_sha256
    finished_within_wall = not compress_timeout and not decompress_timeout
    valid = bool(
        finished_within_wall
        and compress_rc == 0
        and decompress_rc == 0
        and archive_bytes is not None
        and exact
        and deterministic
    )
    for scratch in (archive, second_archive, restored):
        scratch.unlink(missing_ok=True)
    return {
        "codec_id": codec_id,
        "family": family,
        "complete_bytes": archive_bytes if valid else None,
        "measured_archive_bytes": archive_bytes,
        "compress_wall_ns": compress_wall_ns,
        "determinism_recompress_wall_ns": second_wall_ns,
        "decompress_wall_ns": decompress_wall_ns,
        "execution": {
            "finished_within_wall": finished_within_wall,
            "exact_roundtrip": exact,
            "order_preserved": exact,
            "timezone_preserved": exact,
            "deterministic_output": deterministic,
            "compress_returncode": compress_rc,
            "decompress_returncode": decompress_rc,
        },
        "classification": "valid" if valid else "invalid-tool-failure",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--gates",
        type=Path,
        default=REPOSITORY / "config" / "clue-jls2-championship-screen-v1-gates.json",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=REPOSITORY / "config" / "clue-jls2-championship-screen-v1-lock.json",
    )
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument(
        "--bin-dir",
        type=Path,
        required=True,
        help="directory of opponent binaries built by the workflow, named by codec_id",
    )
    parser.add_argument(
        "--pbc-binary",
        type=Path,
        required=True,
        help="the official PBC binary built on the runner from the pinned commit",
    )
    parser.add_argument(
        "--pbc-repository",
        type=Path,
        required=True,
        help="the PBC source checkout at the pinned commit (commit/license verified)",
    )
    parser.add_argument(
        "--pbc-gates",
        type=Path,
        default=REPOSITORY / "config" / "clue-pbc-championship-screen-v1-gates.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def native_decode_measure(
    native_binary: Path,
    frame: Path,
    item: dict[str, Any],
    work: Path,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    output = work / f"decode-{item['id']}.jsonl"
    report_path = work / f"decode-rss-{item['id']}.clean-rss.json"
    report = clean_child_measure(
        [str(native_binary), "decompress", str(frame), "-o", str(output), "--force"],
        report_path,
    )
    exact = (
        int(report.get("exit_code", 1)) == 0
        and output.is_file()
        and output.stat().st_size == item["size_bytes"]
        and sha256_file(output) == item["sha256"]
    )
    wall_ns = int(report["wall_ns"])
    output.unlink(missing_ok=True)
    return {
        "exact": exact,
        "peak_rss_bytes": int(report["maxrss_bytes"]),
        "shim_floor_eligible": shim_floor_eligible(report, requirements),
        "wall_ns": wall_ns,
        "mbps": int(item["size_bytes"]) / wall_ns * 1000.0 if wall_ns else 0.0,
    }


def candidate_proof(
    manifest_path: Path,
    native_binary: Path,
    items: list[dict[str, Any]],
    work: Path,
    requirements: dict[str, Any],
) -> tuple[dict[str, int], dict[str, Any]]:
    """Compress each item with the frozen JLS2 encoder and prove the candidate.

    Mirrors the v2 candidate proof: determinism, complete-frame accounting and
    bounded direct fallback, corruption rejection, cold-process compression peak
    RSS and standalone-decode peak RSS through the clean-child instrument, plus
    compression and standalone-decode throughput.
    """
    family_bytes: dict[str, int] = {}
    proof_rows = []
    compression_peak = 0
    decode_peak = 0
    compression_mbps: list[float] = []
    decode_mbps: list[float] = []
    all_deterministic = True
    all_accounting = True
    all_bounded_fallback = True
    all_corruption_rejected = True
    all_decode_exact = True
    all_shim_eligible = True
    for item in items:
        source = manifest_path.parent / item["path"]
        first = work / f"{item['id']}.first.jls2"
        second = work / f"{item['id']}.second.jls2"
        started = time.perf_counter_ns()
        compress_file(source, first, overwrite=True)
        compress_wall_ns = time.perf_counter_ns() - started
        compress_file(source, second, overwrite=True)
        deterministic = sha256_file(first) == sha256_file(second)
        safety = no_expansion_vs_direct(source, first)
        family_bytes[item["family"]] = first.stat().st_size
        compression_mbps.append(
            int(item["size_bytes"]) / compress_wall_ns * 1000.0 if compress_wall_ns else 0.0
        )

        report = clean_child_measure(
            [
                sys.executable,
                str(CANDIDATE_COMPRESS_DRIVER),
                "--source",
                str(source),
                "--destination",
                str(work / f"compress-rss-{item['id']}.jls2"),
            ],
            work / f"compress-rss-{item['id']}.clean-rss.json",
        )
        compression_peak = max(compression_peak, int(report["maxrss_bytes"]))
        compress_floor_ok = shim_floor_eligible(report, requirements)

        corrupt = work / f"{item['id']}.corrupt.jls2"
        corrupted = bytearray(first.read_bytes())
        corrupted[len(corrupted) // 2] ^= 1
        corrupt.write_bytes(corrupted)
        corrupt_output = work / f"{item['id']}.corrupt-output"
        corrupt_rc, _ = run_plain(
            [str(native_binary), "decompress", str(corrupt), "-o", str(corrupt_output)],
            float(requirements.get("corruption_wall_seconds", 600.0)),
        )
        corruption_rejected = corrupt_rc != 0 and not corrupt_output.exists()

        decode = native_decode_measure(native_binary, first, item, work, requirements)
        decode_peak = max(decode_peak, decode["peak_rss_bytes"])
        decode_mbps.append(decode["mbps"])

        all_deterministic = all_deterministic and deterministic
        all_accounting = all_accounting and safety["complete_frame_accounting"]
        all_bounded_fallback = all_bounded_fallback and (
            safety["maximum_regression_bytes"]
            <= requirements["maximum_segment_regression_vs_equally_framed_direct_fallback_bytes"]
        )
        all_corruption_rejected = all_corruption_rejected and corruption_rejected
        all_decode_exact = all_decode_exact and decode["exact"]
        all_shim_eligible = all_shim_eligible and compress_floor_ok and decode["shim_floor_eligible"]
        proof_rows.append(
            {
                "id": item["id"],
                "family": item["family"],
                "frame_bytes": first.stat().st_size,
                "deterministic": deterministic,
                "fallback_safety": safety,
                "corruption_rejected": corruption_rejected,
                "decode": decode,
            }
        )
        for scratch in (
            first,
            second,
            corrupt,
            work / f"compress-rss-{item['id']}.jls2",
        ):
            scratch.unlink(missing_ok=True)

    aggregate_source = sum(int(item["size_bytes"]) for item in items)
    aggregate_compress_ns = sum(
        int(item["size_bytes"]) / rate * 1000.0 if rate else 0.0
        for item, rate in zip(items, compression_mbps)
    )
    aggregate_compress_mbps = (
        aggregate_source / aggregate_compress_ns * 1000.0 if aggregate_compress_ns else 0.0
    )
    aggregate_decode_ns = sum(
        int(item["size_bytes"]) / rate * 1000.0 if rate else 0.0
        for item, rate in zip(items, decode_mbps)
    )
    aggregate_decode_mbps = (
        aggregate_source / aggregate_decode_ns * 1000.0 if aggregate_decode_ns else 0.0
    )

    gates = {
        "deterministic_output": all_deterministic,
        "complete_frame_accounting": all_accounting,
        "bounded_direct_fallback": all_bounded_fallback,
        "corruption_rejection": all_corruption_rejected,
        "exact_standalone_decode": all_decode_exact,
        "clean_child_shim_floor_eligibility": all_shim_eligible,
        "compression_memory": compression_peak
        <= requirements["maximum_cold_compression_peak_rss_bytes"],
        "decompression_memory": decode_peak
        <= requirements["maximum_cold_decompression_peak_rss_bytes"],
        "aggregate_compression_speed": aggregate_compress_mbps
        >= requirements["minimum_aggregate_compression_mbps"],
        "aggregate_standalone_decompression_speed": aggregate_decode_mbps
        >= requirements["minimum_aggregate_standalone_decompression_mbps"],
        "minimum_compression_repetition_speed": min(compression_mbps, default=0.0)
        >= requirements["minimum_repetition_compression_mbps"],
        "minimum_standalone_decompression_repetition_speed": min(decode_mbps, default=0.0)
        >= requirements["minimum_repetition_standalone_decompression_mbps"],
    }
    proof = {
        "rows": proof_rows,
        "compression_peak_rss_bytes": compression_peak,
        "standalone_decode_peak_rss_bytes": decode_peak,
        "aggregate_compression_mbps": aggregate_compress_mbps,
        "aggregate_standalone_decompression_mbps": aggregate_decode_mbps,
        "gates": gates,
    }
    return family_bytes, proof


def run_pbc_opponent(
    pbc_binary: Path,
    pbc_repository: Path,
    pbc_gates: Path,
    manifest_path: Path,
    items: list[dict[str, Any]],
    family_bytes: dict[str, int],
    work: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Attempt the PBC specialist as a first-class opponent via the v2 machinery.

    Runs scripts/benchmark-pbc-competitor.py (the exact script that produced the
    v2 pbc-result.json) with the frozen PBC commit/license/settings, captures the
    built binary SHA-256 at execution, and classifies each family. If PBC cannot
    run comparably it flows through the same tool-failure classification as any
    opponent: recorded as invalid-tool-failure, never silently dropped and never
    counted as beaten.
    """
    accepted = output_dir / "pbc-accepted.json"
    accepted_rows = [
        {
            "id": item["id"],
            "family": item["family"],
            "original_bytes": int(item["size_bytes"]),
            "source_sha256": item["sha256"],
            "encoded_bytes": int(family_bytes[item["family"]]),
            "zstd9_bytes": int(family_bytes[item["family"]]),
        }
        for item in items
    ]
    write_json_atomic(accepted, {"schema_version": 1, "rows": accepted_rows})
    result_path = output_dir / "pbc-result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(PBC_BENCHMARK),
            "--pbc-binary",
            str(pbc_binary),
            "--pbc-repository",
            str(pbc_repository),
            "--manifest",
            str(manifest_path),
            "--accepted",
            str(accepted),
            "--gates",
            str(pbc_gates),
            "--output",
            str(result_path),
            "--repetitions",
            "5",
            "--training-repetitions",
            "2",
            "--work-directory",
            str(work),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    passed = bool(result.get("passed"))
    binary_sha256 = result.get("pbc", {}).get("binary_sha256")
    if binary_sha256 is None and pbc_binary.is_file():
        binary_sha256 = sha256_file(pbc_binary)
    by_family = {
        row["family"]: row
        for row in result.get("rows", [])
        if row.get("method") == "pbc_only"
    }
    item_map: dict[str, Any] = {}
    for item in items:
        family = item["family"]
        row = by_family.get(family)
        roundtrip = bool(row and row.get("roundtrip_verified"))
        deterministic = bool(row and row.get("payload_deterministic_for_fixed_pattern"))
        archive_bytes = int(row["archive_bytes"]) if row and row.get("archive_bytes") else None
        valid = bool(passed and roundtrip and deterministic and archive_bytes)
        item_map[family] = {
            "complete_bytes": archive_bytes if valid else None,
            "measured_archive_bytes": archive_bytes,
            "execution": {
                "finished_within_wall": completed.returncode != 124,
                "exact_roundtrip": roundtrip,
                "order_preserved": roundtrip,
                "timezone_preserved": roundtrip,
                "deterministic_output": deterministic,
            },
            "classification": "valid" if valid else "invalid-tool-failure",
        }
    return {
        "codec_id": "pbc-only",
        "eligibility_class": "eligible",
        "binary_sha256": binary_sha256,
        "pbc_result_passed": passed,
        "pbc_benchmark_returncode": completed.returncode,
        "pbc_benchmark_stderr_tail": completed.stderr[-2000:],
        "items": item_map,
    }


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists():
        raise SystemExit("refusing to replace or resume a scored championship directory")
    lock_receipt = verify_lock(args.lock)
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    repository = git_state()
    requirements = gates["requirements"]
    if requirements["require_clean_tracked_commit"] and repository["tracked_status"]:
        raise SystemExit("championship screen requires a clean tracked commit")
    native_binary = args.native_binary.resolve()
    if not native_binary.is_file() or not os.access(native_binary, os.X_OK):
        raise SystemExit(f"standalone native decoder is missing: {native_binary}")
    verified_paths = verify_frozen_candidate(gates["candidate"])
    items = verify_manifest(args.manifest, manifest, gates)

    args.output.mkdir(parents=True)
    work = args.output / "work"
    work.mkdir()
    walls = gates["walls"]
    default_wall = float(walls["per_item_wall_seconds_default"])
    overrides = walls["per_codec_wall_overrides_seconds"]

    family_bytes, proof = candidate_proof(
        args.manifest, native_binary, items, work, requirements
    )
    candidate_aggregate = sum(family_bytes.values())

    # Every opponent is scored per item; a failure on one item leaves the other
    # item's result standing (per-item tool-failure classification).
    opponents: list[dict[str, Any]] = []
    for codec_id, spec in OPPONENT_TEMPLATES.items():
        binary = args.bin_dir / codec_id
        wall = float(overrides.get(codec_id, default_wall))
        binary_sha256 = sha256_file(binary) if binary.is_file() else None
        item_map: dict[str, Any] = {}
        for item in items:
            source = args.manifest.parent / item["path"]
            row = run_opponent_item(
                codec_id, spec, binary, source, item["sha256"], item["family"], work, wall
            )
            item_map[item["family"]] = row
        opponents.append(
            {
                "codec_id": codec_id,
                "eligibility_class": spec["role"],
                "binary_sha256": binary_sha256,
                "items": item_map,
            }
        )

    # PBC is a first-class attempted eligible opponent via the exact v2 machinery.
    opponents.append(
        run_pbc_opponent(
            args.pbc_binary.resolve(),
            args.pbc_repository.resolve(),
            args.pbc_gates,
            args.manifest,
            items,
            family_bytes,
            work,
            args.output,
        )
    )

    bundle = {
        "schema_version": 1,
        "name": "clue-jls2-championship-screen-v1-bundle",
        "claim_ceiling": gates["claim_ceiling"],
        "repository": repository,
        "lock_receipt": lock_receipt,
        "frozen_candidate_paths": verified_paths,
        "native_binary_sha256": sha256_file(native_binary),
        "families": [item["family"] for item in items],
        "candidate": {
            "codec_id": "jls2",
            "aggregate_complete_bytes": candidate_aggregate,
            "family_complete_bytes": family_bytes,
            "compression_peak_rss_bytes": proof["compression_peak_rss_bytes"],
            "standalone_decode_peak_rss_bytes": proof["standalone_decode_peak_rss_bytes"],
            "gates": proof["gates"],
        },
        "candidate_proof": proof,
        "opponents": [
            {
                "codec_id": o["codec_id"],
                "eligibility_class": o["eligibility_class"],
                "binary_sha256": o.get("binary_sha256"),
                "items": {
                    family: {
                        "complete_bytes": row["complete_bytes"],
                        "execution": row["execution"],
                    }
                    for family, row in o["items"].items()
                },
            }
            for o in opponents
        ],
        "opponent_detail": opponents,
    }
    write_json_atomic(args.output / "bundle.json", bundle)
    print(args.output / "bundle.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
