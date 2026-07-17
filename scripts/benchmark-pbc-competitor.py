#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time
from typing import Any, Sequence


REPOSITORY = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def run_command(command: Sequence[str], cwd: Path | None = None) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    seconds = time.perf_counter() - started
    if completed.returncode:
        rendered = " ".join(command)
        raise RuntimeError(
            f"command failed ({completed.returncode}): {rendered}\n"
            f"{completed.stdout}"
        )
    return seconds


def git_text(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def source_state(repository: Path) -> dict[str, Any]:
    return {
        "commit": git_text(repository, "rev-parse", "HEAD"),
        "tracked_status": git_text(
            repository,
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
        "origin": git_text(
            repository,
            "config",
            "--get",
            "remote.origin.url",
        ),
    }


def benchmark_source_state() -> dict[str, Any]:
    return {
        "commit": git_text(REPOSITORY, "rev-parse", "HEAD"),
        "tracked_status": git_text(
            REPOSITORY,
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
    }


def system_state(label: str) -> dict[str, Any]:
    cpu_count = os.cpu_count()
    load = list(os.getloadavg())
    return {
        "label": label,
        "load_average_1m_5m_15m": load,
        "logical_cpus": cpu_count,
        "normalized_load_1m": load[0] / cpu_count if cpu_count else None,
    }


def inspect_records(path: Path) -> dict[str, int]:
    record_count = 0
    maximum_record_bytes = 0
    with path.open("rb") as source:
        for line in source:
            record_count += 1
            record_bytes = len(line[:-1]) if line.endswith(b"\n") else len(line)
            maximum_record_bytes = max(maximum_record_bytes, record_bytes)
    return {
        "record_count": record_count,
        "maximum_record_bytes": maximum_record_bytes,
    }


def percentage_gain(reference_bytes: int, candidate_bytes: int) -> float:
    return (reference_bytes - candidate_bytes) / reference_bytes * 100.0


def pbc_command(
    binary: Path,
    operation: str,
    source: Path,
    pattern: Path,
    method: str,
    destination: Path | None = None,
    *,
    pattern_size: int | None = None,
    train_data_number: int | None = None,
    train_thread_num: int | None = None,
) -> list[str]:
    command = [
        str(binary),
        operation,
        "-i",
        str(source),
        "-p",
        str(pattern),
        "--compress-method",
        method,
        "--log-level",
        "4",
    ]
    if destination is not None:
        command.extend(["-o", str(destination)])
    if pattern_size is not None:
        command.extend(["--pattern-size", str(pattern_size)])
    if train_data_number is not None:
        command.extend(["--train-data-number", str(train_data_number)])
    if train_thread_num is not None:
        command.extend(["--train-thread-num", str(train_thread_num)])
    return command


def prepare_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)


def accepted_rows(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {row["family"]: row for row in payload["rows"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproduce the official PBC CLI on the LogTrie corpus"
    )
    parser.add_argument("--pbc-binary", type=Path, required=True)
    parser.add_argument("--pbc-repository", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--training-repetitions", type=int, default=2)
    parser.add_argument("--work-directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    source_config = gates["source"]
    settings = gates["settings"]
    requirements = gates["requirements"]

    if args.repetitions < requirements["minimum_repetitions"]:
        raise SystemExit("insufficient online repetitions")
    if (
        args.training_repetitions
        < requirements["minimum_training_repetitions"]
    ):
        raise SystemExit("insufficient pattern-training repetitions")

    binary = args.pbc_binary.resolve()
    pbc_repository = args.pbc_repository.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SystemExit(f"PBC binary is missing or not executable: {binary}")

    source = source_state(pbc_repository)
    license_path = pbc_repository / "LICENSE"
    license_sha256 = sha256_file(license_path)
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

    exact_commit = source["commit"] == source_config["commit"]
    clean_tracked_source = not source["tracked_status"]
    exact_license = license_sha256 == source_config["license_sha256"]
    if requirements["require_exact_source_commit"] and not exact_commit:
        raise SystemExit("PBC source commit does not match the frozen commit")
    if requirements["require_clean_tracked_source"] and not clean_tracked_source:
        raise SystemExit("PBC tracked source files are dirty")
    if requirements["require_exact_license"] and not exact_license:
        raise SystemExit("PBC license digest does not match the frozen digest")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    accepted = accepted_rows(args.accepted)
    methods = settings["methods"]
    expected_families = requirements["expected_families"]
    manifest_families = [item["family"] for item in manifest["items"]]
    if manifest_families != expected_families:
        raise SystemExit(
            "manifest families or order differ from the frozen contract"
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "claim_ceiling": gates["claim_ceiling"],
        "manifest_path": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "accepted_path": str(args.accepted),
        "accepted_sha256": sha256_file(args.accepted),
        "gates_path": str(args.gates),
        "gates_sha256": sha256_file(args.gates),
        "repetitions": args.repetitions,
        "training_repetitions": args.training_repetitions,
        "benchmark_source": benchmark_source_state(),
        "pbc": {
            **source,
            "license_path": str(license_path),
            "license_sha256": license_sha256,
            "exact_commit": exact_commit,
            "clean_tracked_source": clean_tracked_source,
            "exact_license": exact_license,
            "binary": str(binary),
            "binary_sha256": sha256_file(binary),
        },
        "settings": settings,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "system_states": [start_state],
        "rows": [],
    }
    rows: list[dict[str, Any]] = []

    work_parent = args.work_directory
    if work_parent is not None:
        work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="compression-lab-pbc-",
        dir=work_parent,
    ) as temporary_directory:
        work = Path(temporary_directory)
        for item in manifest["items"]:
            family = item["family"]
            source_path = Path(item["path"]).resolve()
            if source_path.stat().st_size != item["size_bytes"]:
                raise ValueError(f"corpus size mismatch: {source_path}")
            if sha256_file(source_path) != item["sha256"]:
                raise ValueError(f"corpus digest mismatch: {source_path}")
            if family not in accepted:
                raise ValueError(f"accepted result is missing family: {family}")

            record_info = inspect_records(source_path)
            if (
                record_info["maximum_record_bytes"]
                > requirements["maximum_record_bytes"]
            ):
                raise ValueError(
                    f"{family} exceeds PBC's maximum record size"
                )

            for method in methods:
                pattern_samples: list[float] = []
                pattern_sizes: list[int] = []
                pattern_digests: list[str] = []
                canonical_pattern: Path | None = None
                for repetition in range(args.training_repetitions):
                    pattern = work / f"{family}.{method}.{repetition}.pattern"
                    prepare_output(pattern)
                    seconds = run_command(
                        pbc_command(
                            binary,
                            "--train-pattern",
                            source_path,
                            pattern,
                            method,
                            pattern_size=settings["pattern_size"],
                            train_data_number=settings[
                                "train_data_number"
                            ],
                            train_thread_num=settings["train_thread_num"],
                        ),
                        cwd=pbc_repository,
                    )
                    pattern_samples.append(seconds)
                    pattern_sizes.append(pattern.stat().st_size)
                    pattern_digests.append(sha256_file(pattern))
                    if canonical_pattern is None:
                        canonical_pattern = pattern
                    else:
                        pattern.unlink()
                if canonical_pattern is None:
                    raise AssertionError("pattern training produced no output")

                compression_samples: list[float] = []
                payload_sizes: list[int] = []
                payload_digests: list[str] = []
                canonical_payload: Path | None = None
                for repetition in range(args.repetitions):
                    compressed = (
                        work / f"{family}.{method}.{repetition}.pbc"
                    )
                    prepare_output(compressed)
                    seconds = run_command(
                        pbc_command(
                            binary,
                            "--compress",
                            source_path,
                            canonical_pattern,
                            method,
                            compressed,
                        ),
                        cwd=pbc_repository,
                    )
                    compression_samples.append(seconds)
                    payload_sizes.append(compressed.stat().st_size)
                    payload_digests.append(sha256_file(compressed))
                    if canonical_payload is None:
                        canonical_payload = compressed
                    else:
                        compressed.unlink()
                if canonical_payload is None:
                    raise AssertionError("compression produced no output")

                decompression_samples: list[float] = []
                for repetition in range(args.repetitions):
                    restored = (
                        work / f"{family}.{method}.{repetition}.restored"
                    )
                    prepare_output(restored)
                    seconds = run_command(
                        pbc_command(
                            binary,
                            "--decompress",
                            canonical_payload,
                            canonical_pattern,
                            method,
                            restored,
                        ),
                        cwd=pbc_repository,
                    )
                    decompression_samples.append(seconds)
                    if restored.stat().st_size != item["size_bytes"]:
                        raise RuntimeError(
                            f"restored size mismatch for {family}/{method}"
                        )
                    if sha256_file(restored) != item["sha256"]:
                        raise RuntimeError(
                            f"restored digest mismatch for {family}/{method}"
                        )
                    restored.unlink()

                pattern_seconds = statistics.median(pattern_samples)
                compression_seconds = statistics.median(
                    compression_samples
                )
                complete_compression_seconds = (
                    pattern_seconds + compression_seconds
                )
                decompression_seconds = statistics.median(
                    decompression_samples
                )
                pattern_bytes = pattern_sizes[0]
                payload_bytes = payload_sizes[0]
                archive_bytes = pattern_bytes + payload_bytes
                original_bytes = item["size_bytes"]
                jls2_bytes = accepted[family]["encoded_bytes"]
                zstd9_bytes = accepted[family]["zstd9_bytes"]
                row = {
                    "family": family,
                    "method": method,
                    "original_bytes": original_bytes,
                    "source_sha256": item["sha256"],
                    **record_info,
                    "pattern_bytes": pattern_bytes,
                    "pattern_sha256": pattern_digests[0],
                    "pattern_deterministic": (
                        len(set(pattern_digests)) == 1
                        and len(set(pattern_sizes)) == 1
                    ),
                    "pattern_training_seconds": pattern_seconds,
                    "pattern_training_samples": pattern_samples,
                    "payload_bytes": payload_bytes,
                    "payload_sha256": payload_digests[0],
                    "payload_deterministic_for_fixed_pattern": (
                        len(set(payload_digests)) == 1
                        and len(set(payload_sizes)) == 1
                    ),
                    "archive_bytes": archive_bytes,
                    "online_compression_seconds": compression_seconds,
                    "online_compression_samples": compression_samples,
                    "online_compression_mbps": (
                        original_bytes
                        / max(compression_seconds, 1e-9)
                        / 1_000_000
                    ),
                    "complete_compression_seconds": (
                        complete_compression_seconds
                    ),
                    "complete_compression_mbps": (
                        original_bytes
                        / max(complete_compression_seconds, 1e-9)
                        / 1_000_000
                    ),
                    "decompression_seconds": decompression_seconds,
                    "decompression_samples": decompression_samples,
                    "decompression_mbps": (
                        original_bytes
                        / max(decompression_seconds, 1e-9)
                        / 1_000_000
                    ),
                    "jls2_bytes": jls2_bytes,
                    "zstd9_bytes": zstd9_bytes,
                    "pbc_gain_vs_jls2_percent": percentage_gain(
                        jls2_bytes,
                        archive_bytes,
                    ),
                    "pbc_gain_vs_zstd9_percent": percentage_gain(
                        zstd9_bytes,
                        archive_bytes,
                    ),
                    "roundtrip_verified": True,
                }
                rows.append(row)
                payload["rows"] = rows
                payload["system_states"].append(
                    system_state(f"checkpoint-{family}-{method}")
                )
                write_output(args.output, payload)
                print(
                    f"{family}/{method}: archive={archive_bytes} "
                    f"complete={row['complete_compression_mbps']:.2f} MB/s "
                    f"online={row['online_compression_mbps']:.2f} MB/s "
                    f"decode={row['decompression_mbps']:.2f} MB/s",
                    flush=True,
                )
                canonical_payload.unlink()
                canonical_pattern.unlink()

    aggregates: dict[str, dict[str, Any]] = {}
    for method in methods:
        method_rows = [row for row in rows if row["method"] == method]
        original_bytes = sum(row["original_bytes"] for row in method_rows)
        pattern_bytes = sum(row["pattern_bytes"] for row in method_rows)
        payload_bytes = sum(row["payload_bytes"] for row in method_rows)
        archive_bytes = pattern_bytes + payload_bytes
        jls2_bytes = sum(row["jls2_bytes"] for row in method_rows)
        zstd9_bytes = sum(row["zstd9_bytes"] for row in method_rows)
        training_seconds = sum(
            row["pattern_training_seconds"] for row in method_rows
        )
        online_seconds = sum(
            row["online_compression_seconds"] for row in method_rows
        )
        complete_seconds = training_seconds + online_seconds
        decompression_seconds = sum(
            row["decompression_seconds"] for row in method_rows
        )
        aggregates[method] = {
            "original_bytes": original_bytes,
            "pattern_bytes": pattern_bytes,
            "payload_bytes": payload_bytes,
            "archive_bytes": archive_bytes,
            "jls2_bytes": jls2_bytes,
            "zstd9_bytes": zstd9_bytes,
            "pattern_training_seconds": training_seconds,
            "online_compression_seconds": online_seconds,
            "complete_compression_seconds": complete_seconds,
            "decompression_seconds": decompression_seconds,
            "online_compression_mbps": (
                original_bytes / max(online_seconds, 1e-9) / 1_000_000
            ),
            "complete_compression_mbps": (
                original_bytes / max(complete_seconds, 1e-9) / 1_000_000
            ),
            "decompression_mbps": (
                original_bytes
                / max(decompression_seconds, 1e-9)
                / 1_000_000
            ),
            "pbc_gain_vs_jls2_percent": percentage_gain(
                jls2_bytes,
                archive_bytes,
            ),
            "pbc_gain_vs_zstd9_percent": percentage_gain(
                zstd9_bytes,
                archive_bytes,
            ),
        }
    payload["aggregates"] = aggregates

    primary_method = min(
        methods,
        key=lambda method: aggregates[method]["archive_bytes"],
    )
    oracle_rows = [
        min(
            (row for row in rows if row["family"] == family),
            key=lambda row: row["archive_bytes"],
        )
        for family in expected_families
    ]
    oracle_archive_bytes = sum(row["archive_bytes"] for row in oracle_rows)
    oracle_jls2_bytes = sum(row["jls2_bytes"] for row in oracle_rows)
    oracle_zstd9_bytes = sum(row["zstd9_bytes"] for row in oracle_rows)
    payload["decision"] = {
        "primary_method": primary_method,
        "primary": aggregates[primary_method],
        "oracle_context_only": {
            "selected_methods": {
                row["family"]: row["method"] for row in oracle_rows
            },
            "archive_bytes": oracle_archive_bytes,
            "jls2_bytes": oracle_jls2_bytes,
            "zstd9_bytes": oracle_zstd9_bytes,
            "pbc_gain_vs_jls2_percent": percentage_gain(
                oracle_jls2_bytes,
                oracle_archive_bytes,
            ),
            "pbc_gain_vs_zstd9_percent": percentage_gain(
                oracle_zstd9_bytes,
                oracle_archive_bytes,
            ),
        },
    }

    payload["gate_results"] = {
        "exact_source_commit": exact_commit,
        "clean_tracked_source": clean_tracked_source,
        "exact_license": exact_license,
        "expected_methods": (
            {row["method"] for row in rows} == set(methods)
        ),
        "expected_families": (
            {row["family"] for row in rows} == set(expected_families)
        ),
        "repetitions": (
            args.repetitions >= requirements["minimum_repetitions"]
        ),
        "training_repetitions": (
            args.training_repetitions
            >= requirements["minimum_training_repetitions"]
        ),
        "record_size_eligible": all(
            row["maximum_record_bytes"]
            <= requirements["maximum_record_bytes"]
            for row in rows
        ),
        "deterministic_payload_for_fixed_pattern": (
            not requirements[
                "require_deterministic_payload_for_fixed_pattern"
            ]
            or all(
                row["payload_deterministic_for_fixed_pattern"]
                for row in rows
            )
        ),
        "byte_exact_roundtrip": (
            not requirements["require_byte_exact_roundtrip"]
            or all(row["roundtrip_verified"] for row in rows)
        ),
        "complete_archive_accounting": (
            not requirements["require_complete_archive_accounting"]
            or all(
                row["archive_bytes"]
                == row["pattern_bytes"] + row["payload_bytes"]
                for row in rows
            )
        ),
    }
    payload["passed"] = all(payload["gate_results"].values())
    payload["system_states"].append(system_state("run-end"))
    write_output(args.output, payload)
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
