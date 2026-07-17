#!/usr/bin/env python3
"""Paired cold-process benchmark for the Python and standalone JLS2 decoders."""

from __future__ import annotations

import argparse
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
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "config" / "clue-json-log-corpus-v1.json"
COMPARISON = (
    REPOSITORY / "runs" / "clue-json-log-development-census-v1" / "comparison.json"
)
VARIANTS = ("python", "native")
ROUNDS = 7
TARGET_MBPS = 250.0
MAX_CV_PERCENT = 20.0
MAX_RSS_BYTES = 512 * 1024 * 1024
MINIMUM_PAIRED_IMPROVEMENT_PERCENT = 10.0
BASELINE_COMMIT = "604271cbc89a11c739848f68a7739ed523fb9a1b"
EXPECTED_FRAMES = {
    "clue-early-development": {
        "bytes": 1_382_653,
        "sha256": "550387af5ef18e8a98e85175fbfcede14160ccc45967031cafe8168a973e995d",
    },
    "clue-middle-development": {
        "bytes": 738_259,
        "sha256": "e11442252db4e6739cd452bc602a5fa7a8466fa2968b898c674c30d531ef36e1",
    },
    "clue-late-development": {
        "bytes": 1_402_809,
        "sha256": "0cb5342a88fba36c6dec41c5cd34cc873e867bed48f371d66ed8cd594d7d3724",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / statistics.mean(values) * 100


def write_json(path: Path, payload: dict[str, Any]) -> None:
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


def measurement_schedule(
    family_ids: list[str], rounds: int = ROUNDS
) -> list[list[tuple[str, str]]]:
    schedule = []
    for round_index in range(rounds):
        families = list(family_ids)
        if round_index % 2:
            families.reverse()
        rows = []
        for family_index, family in enumerate(families):
            variants = list(VARIANTS)
            if (round_index + family_index) % 2:
                variants.reverse()
            rows.extend((family, variant) for variant in variants)
        schedule.append(rows)
    return schedule


def summarize(trials: list[dict[str, Any]], rounds: int = ROUNDS) -> dict[str, Any]:
    measured = [trial for trial in trials if not trial["warmup"]]
    variants = []
    for variant in VARIANTS:
        rows = [trial for trial in measured if trial["variant"] == variant]
        round_rates = []
        for round_number in range(1, rounds + 1):
            round_rows = [row for row in rows if row["round"] == round_number]
            if not round_rows:
                raise ValueError(f"missing {variant} round {round_number}")
            round_rates.append(
                sum(row["source_bytes"] for row in round_rows)
                / sum(row["parent_wall_ns"] for row in round_rows)
                * 1_000
            )
        family_rows = []
        for family in sorted({row["family"] for row in rows}):
            rates = [row["parent_mbps"] for row in rows if row["family"] == family]
            family_rows.append(
                {
                    "family": family,
                    "median_parent_mbps": statistics.median(rates),
                    "minimum_parent_mbps": min(rates),
                }
            )
        variants.append(
            {
                "variant": variant,
                "median_aggregate_parent_mbps": statistics.median(round_rates),
                "minimum_aggregate_parent_mbps": min(round_rates),
                "aggregate_cv_percent": coefficient_of_variation(round_rates),
                "rounds_at_or_above_250_mbps": sum(
                    rate >= TARGET_MBPS for rate in round_rates
                ),
                "round_rates_mbps": round_rates,
                "family_rows": family_rows,
                "peak_rss_bytes": max(
                    [int(row.get("peak_rss_bytes", 0)) for row in rows] or [0]
                ),
                "all_exact": all(row["exact"] for row in rows),
            }
        )

    baseline = next(row for row in variants if row["variant"] == "python")
    candidate = next(row for row in variants if row["variant"] == "native")
    paired = [
        (native_rate / python_rate - 1) * 100
        for python_rate, native_rate in zip(
            baseline["round_rates_mbps"], candidate["round_rates_mbps"]
        )
    ]
    candidate["paired_improvements_percent"] = paired
    candidate["median_paired_improvement_percent"] = statistics.median(paired)
    gates = {
        "all_exact": candidate["all_exact"],
        "all_rounds_at_or_above_250_mbps": candidate["rounds_at_or_above_250_mbps"]
        == rounds,
        "all_family_medians_at_or_above_250_mbps": all(
            row["median_parent_mbps"] >= TARGET_MBPS for row in candidate["family_rows"]
        ),
        "aggregate_cv_at_or_below_20_percent": candidate["aggregate_cv_percent"]
        <= MAX_CV_PERCENT,
        "peak_rss_at_or_below_512_mib": 0
        < candidate["peak_rss_bytes"]
        <= MAX_RSS_BYTES,
        "median_paired_improvement_at_or_above_10_percent": candidate[
            "median_paired_improvement_percent"
        ]
        >= MINIMUM_PAIRED_IMPROVEMENT_PERCENT,
    }
    return {
        "variants": variants,
        "gates": gates,
        "candidate_qualifies_performance": all(gates.values()),
    }


def load_items(corpus: Path, fixtures: Path) -> list[dict[str, Any]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    census_sizes = {
        row["item_id"]: row["jls2_bytes"] for row in comparison["family_rows"]
    }
    items = []
    for item in config["selection"]["development"]:
        source = corpus / f"{item['id']}.jsonl"
        frame = fixtures / f"{item['id']}.jls2"
        expected = EXPECTED_FRAMES[item["id"]]
        if census_sizes[item["id"]] != expected["bytes"]:
            raise ValueError(f"census size drift: {item['id']}")
        if source.stat().st_size != item["size_bytes"]:
            raise ValueError(f"source size mismatch: {source}")
        if sha256_file(source) != item["sha256"]:
            raise ValueError(f"source SHA-256 mismatch: {source}")
        if frame.stat().st_size != expected["bytes"]:
            raise ValueError(f"frame size mismatch: {frame}")
        if sha256_file(frame) != expected["sha256"]:
            raise ValueError(f"frame SHA-256 mismatch: {frame}")
        items.append({**item, "source": source, "frame": frame})
    return items


def prepare_fixtures(corpus: Path, fixtures: Path) -> None:
    from compresslab.json_log_codec import compress_file

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    fixtures.mkdir(parents=True, exist_ok=True)
    for item in config["selection"]["development"]:
        compress_file(
            corpus / f"{item['id']}.jsonl",
            fixtures / f"{item['id']}.jls2",
            overwrite=True,
        )


def run_process(
    command: list[str], cwd: Path, environment: dict[str, str]
) -> tuple[int, str, str, int, int]:
    """Run one child and return exit/output/wall/RSS without pipe backpressure."""
    started = time.perf_counter_ns()
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=stdout_file,
            stderr=stderr_file,
        )
        if hasattr(os, "wait4"):
            _, wait_status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(wait_status)
            peak_rss_bytes = int(usage.ru_maxrss)
            if sys.platform != "darwin":
                peak_rss_bytes *= 1024
        else:
            process.wait()
            peak_rss_bytes = -1
        parent_wall_ns = time.perf_counter_ns() - started
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
    return process.returncode, stdout, stderr, parent_wall_ns, peak_rss_bytes


def command_for(
    variant: str,
    baseline_root: Path,
    native_binary: Path,
    frame: Path,
    destination: Path,
) -> tuple[list[str], dict[str, str]]:
    environment = os.environ.copy()
    if variant == "python":
        environment["PYTHONPATH"] = str(baseline_root / "src")
        environment["COMPRESSION_LAB_NATIVE_LIB"] = str(
            baseline_root
            / "native"
            / "target"
            / "release"
            / (
                "libcompression_lab_native.dylib"
                if sys.platform == "darwin"
                else "compression_lab_native.dll"
                if sys.platform == "win32"
                else "libcompression_lab_native.so"
            )
        )
        return (
            [
                sys.executable,
                "-m",
                "compresslab",
                "json-decompress",
                str(frame),
                "-o",
                str(destination),
                "--force",
            ],
            environment,
        )
    if variant == "native":
        return (
            [
                str(native_binary),
                "decompress",
                str(frame),
                "-o",
                str(destination),
                "--force",
            ],
            environment,
        )
    raise ValueError(f"unknown variant: {variant}")


def run_trial(
    variant: str,
    item: dict[str, Any],
    baseline_root: Path,
    native_binary: Path,
    work_dir: Path,
    label: str,
) -> dict[str, Any]:
    destination = work_dir / f"{label}-{variant}-{item['id']}.jsonl"
    command, environment = command_for(
        variant, baseline_root, native_binary, item["frame"], destination
    )
    returncode, stdout, stderr, parent_wall_ns, peak_rss_bytes = run_process(
        command,
        baseline_root if variant == "python" else REPOSITORY,
        environment,
    )
    try:
        exact = (
            returncode == 0
            and destination.is_file()
            and destination.stat().st_size == item["size_bytes"]
            and sha256_file(destination) == item["sha256"]
        )
    finally:
        destination.unlink(missing_ok=True)
    if not exact:
        raise ValueError(f"trial failed: {variant} {item['id']}: {stderr.strip()}")
    return {
        "variant": variant,
        "family": item["id"],
        "source_bytes": item["size_bytes"],
        "source_sha256": item["sha256"],
        "encoded_bytes": item["frame"].stat().st_size,
        "encoded_sha256": sha256_file(item["frame"]),
        "parent_wall_ns": parent_wall_ns,
        "parent_mbps": item["size_bytes"] / parent_wall_ns * 1_000,
        "peak_rss_bytes": peak_rss_bytes,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "command": command,
        "exact": exact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--prepare-fixtures", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    if not args.native_binary.is_file():
        parser.error(f"native binary is missing: {args.native_binary}")
    corpus = args.corpus.resolve()
    fixtures = args.fixtures.resolve()
    if args.prepare_fixtures:
        prepare_fixtures(corpus, fixtures)
    items = load_items(corpus, fixtures)
    family_by_id = {item["id"]: item for item in items}
    trials = []
    with tempfile.TemporaryDirectory(prefix="jls2-native-gate-") as temporary:
        work_dir = Path(temporary)
        for family in family_by_id:
            for variant in VARIANTS:
                row = run_trial(
                    variant,
                    family_by_id[family],
                    args.baseline_root.resolve(),
                    args.native_binary.resolve(),
                    work_dir,
                    f"warmup-{family}",
                )
                row.update({"round": 0, "warmup": True})
                trials.append(row)
        for round_number, rows in enumerate(
            measurement_schedule(list(family_by_id), args.rounds), start=1
        ):
            for family, variant in rows:
                row = run_trial(
                    variant,
                    family_by_id[family],
                    args.baseline_root.resolve(),
                    args.native_binary.resolve(),
                    work_dir,
                    f"round-{round_number}",
                )
                row.update({"round": round_number, "warmup": False})
                trials.append(row)
    linkage_command = (
        ["otool", "-L", str(args.native_binary.resolve())]
        if sys.platform == "darwin"
        else ["ldd", str(args.native_binary.resolve())]
        if sys.platform.startswith("linux")
        else ["where", str(args.native_binary.resolve())]
    )
    linkage = subprocess.run(
        linkage_command,
        check=False,
        capture_output=True,
        text=True,
    )
    candidate_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = {
        "schema_version": 1,
        "protocol": "jls2-standalone-native-decoder-v1",
        "claim_scope": "development-only",
        "baseline_commit": BASELINE_COMMIT,
        "candidate_commit": candidate_commit,
        "created_at_epoch_seconds": int(time.time()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "load_average_after": list(os.getloadavg())
            if hasattr(os, "getloadavg")
            else [],
        },
        "native_binary": {
            "path": str(args.native_binary.resolve()),
            "sha256": sha256_file(args.native_binary),
            "linkage_command": linkage_command,
            "linkage_returncode": linkage.returncode,
            "linkage_stdout": linkage.stdout,
            "linkage_stderr": linkage.stderr,
        },
        "all_scheduled_exact": all(trial["exact"] for trial in trials),
        "trials": trials,
        "summary": summarize(trials, args.rounds),
    }
    write_json(args.output.resolve(), result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0 if result["summary"]["candidate_qualifies_performance"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
