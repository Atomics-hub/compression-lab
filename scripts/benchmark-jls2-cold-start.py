#!/usr/bin/env python3
"""Paired cold-process benchmark for JLS2 CLI and worker delivery."""

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
VARIANTS = ("baseline", "candidate")
MODES = ("cli", "worker")
MAX_RSS_BYTES = 512 * 1024 * 1024
SOURCE_FILES = (
    "src/compresslab/__init__.py",
    "src/compresslab/cli.py",
    "src/compresslab/codecs.py",
    "src/compresslab/worker.py",
    "src/compresslab/json_log_codec.py",
    "src/compresslab/json_columnar.py",
    "native/src/lib.rs",
    "scripts/benchmark-jls2-cold-start.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / statistics.mean(values) * 100


def native_library() -> Path:
    if sys.platform == "darwin":
        filename = "libcompression_lab_native.dylib"
    elif sys.platform == "win32":
        filename = "compression_lab_native.dll"
    else:
        filename = "libcompression_lab_native.so"
    path = REPOSITORY / "native" / "target" / "release" / filename
    if not path.is_file():
        raise ValueError(f"native release library is missing: {path}")
    return path


def environment(root: Path) -> dict[str, str]:
    result = os.environ.copy()
    result["PYTHONPATH"] = str(root / "src")
    result["COMPRESSION_LAB_NATIVE_LIB"] = str(native_library())
    return result


def load_items(corpus: Path) -> list[dict[str, Any]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    expected_bytes = {
        row["item_id"]: row["jls2_bytes"] for row in comparison["family_rows"]
    }
    items = []
    for item in config["selection"]["development"]:
        source = corpus / f"{item['id']}.jsonl"
        if source.stat().st_size != item["size_bytes"]:
            raise ValueError(f"source size mismatch: {source}")
        if sha256_file(source) != item["sha256"]:
            raise ValueError(f"source SHA-256 mismatch: {source}")
        items.append(
            {
                **item,
                "source": source,
                "expected_encoded_bytes": expected_bytes[item["id"]],
            }
        )
    return items


def prepare_fixtures(items: list[dict[str, Any]], fixture_dir: Path) -> None:
    from compresslab.json_log_codec import compress_file

    fixture_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        frame = fixture_dir / f"{item['id']}.jls2"
        compress_file(item["source"], frame, overwrite=True)
        if frame.stat().st_size != item["expected_encoded_bytes"]:
            raise ValueError(f"encoded byte drift: {item['id']}")


def measurement_schedule(
    family_ids: list[str], rounds: int
) -> list[list[tuple[str, str, str]]]:
    schedule = []
    for round_index in range(rounds):
        families = list(family_ids)
        if round_index % 2:
            families.reverse()
        pairs = []
        for family_index, family in enumerate(families):
            modes = list(MODES)
            variants = list(VARIANTS)
            if (round_index + family_index) % 2:
                modes.reverse()
            if round_index % 2:
                variants.reverse()
            for mode in modes:
                pairs.extend((family, mode, variant) for variant in variants)
        schedule.append(pairs)
    return schedule


def command_for(
    mode: str,
    frame: Path,
    destination: Path,
    telemetry: Path,
) -> list[str]:
    if mode == "cli":
        return [
            sys.executable,
            "-m",
            "compresslab",
            "json-decompress",
            str(frame),
            "-o",
            str(destination),
            "--force",
        ]
    if mode == "worker":
        return [
            sys.executable,
            "-m",
            "compresslab.worker",
            "--codec",
            "jls2",
            "--operation",
            "decompress",
            "--source",
            str(frame),
            "--destination",
            str(destination),
            "--telemetry",
            str(telemetry),
        ]
    raise ValueError(f"unknown mode: {mode}")


def run_trial(
    root: Path,
    variant: str,
    mode: str,
    item: dict[str, Any],
    fixture_dir: Path,
    work_dir: Path,
    label: str,
) -> dict[str, Any]:
    frame = fixture_dir / f"{item['id']}.jls2"
    destination = work_dir / f"{label}-{variant}-{mode}-{item['id']}.jsonl"
    telemetry_path = work_dir / f"{label}-{variant}-{mode}-{item['id']}.json"
    command = command_for(mode, frame, destination, telemetry_path)
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment(root),
        check=False,
        capture_output=True,
        text=True,
    )
    parent_wall_ns = time.perf_counter_ns() - started
    telemetry = {}
    if telemetry_path.exists():
        telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    try:
        exact = (
            completed.returncode == 0
            and destination.is_file()
            and destination.stat().st_size == item["size_bytes"]
            and sha256_file(destination) == item["sha256"]
        )
    finally:
        destination.unlink(missing_ok=True)
        telemetry_path.unlink(missing_ok=True)
    if not exact:
        raise ValueError(
            f"trial failed: {variant} {mode} {item['id']}: "
            f"{completed.stderr.strip()} {telemetry}"
        )
    return {
        "variant": variant,
        "mode": mode,
        "family": item["id"],
        "source_bytes": item["size_bytes"],
        "source_sha256": item["sha256"],
        "encoded_bytes": frame.stat().st_size,
        "encoded_sha256": sha256_file(frame),
        "parent_wall_ns": parent_wall_ns,
        "parent_mbps": item["size_bytes"] / parent_wall_ns * 1_000,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exact": exact,
        "worker": telemetry,
    }


def run_probe(root: Path, command: list[str]) -> int:
    started = time.perf_counter_ns()
    subprocess.run(
        command,
        cwd=root,
        env=environment(root),
        check=True,
        capture_output=True,
    )
    return time.perf_counter_ns() - started


def summarize(
    trials: list[dict[str, Any]], rounds: int
) -> dict[str, Any]:
    measured = [trial for trial in trials if not trial["warmup"]]
    summaries = []
    for variant in VARIANTS:
        for mode in MODES:
            rows = [
                trial
                for trial in measured
                if trial["variant"] == variant and trial["mode"] == mode
            ]
            round_rates = []
            for round_number in range(1, rounds + 1):
                round_rows = [row for row in rows if row["round"] == round_number]
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
            summaries.append(
                {
                    "variant": variant,
                    "mode": mode,
                    "median_aggregate_parent_mbps": statistics.median(round_rates),
                    "minimum_aggregate_parent_mbps": min(round_rates),
                    "aggregate_cv_percent": coefficient_of_variation(round_rates),
                    "rounds_at_or_above_250_mbps": sum(
                        rate >= 250 for rate in round_rates
                    ),
                    "round_rates_mbps": round_rates,
                    "family_rows": family_rows,
                    "peak_rss_bytes": max(
                        [
                            int(row["worker"].get("peak_rss_bytes", 0))
                            for row in rows
                        ]
                        or [0]
                    ),
                    "all_exact": all(row["exact"] for row in rows),
                }
            )

    gates = {}
    for mode in MODES:
        baseline = next(
            row
            for row in summaries
            if row["variant"] == "baseline" and row["mode"] == mode
        )
        candidate = next(
            row
            for row in summaries
            if row["variant"] == "candidate" and row["mode"] == mode
        )
        improvements = [
            (candidate_rate / baseline_rate - 1) * 100
            for baseline_rate, candidate_rate in zip(
                baseline["round_rates_mbps"], candidate["round_rates_mbps"]
            )
        ]
        candidate["paired_improvements_percent"] = improvements
        candidate["median_paired_improvement_percent"] = statistics.median(
            improvements
        )
        gates[mode] = {
            "all_exact": candidate["all_exact"],
            "all_rounds_at_or_above_250_mbps": candidate[
                "rounds_at_or_above_250_mbps"
            ]
            == rounds,
            "all_family_medians_at_or_above_250_mbps": all(
                row["median_parent_mbps"] >= 250
                for row in candidate["family_rows"]
            ),
            "aggregate_cv_at_or_below_20_percent": candidate[
                "aggregate_cv_percent"
            ]
            <= 20,
            "paired_improvement_at_or_above_10_percent": candidate[
                "median_paired_improvement_percent"
            ]
            >= 10,
        }
    gates["worker"]["peak_rss_at_or_below_512_mib"] = next(
        row
        for row in summaries
        if row["variant"] == "candidate" and row["mode"] == "worker"
    )["peak_rss_bytes"] <= MAX_RSS_BYTES
    encoded_identity = all(
        len(
            {
                (row["encoded_bytes"], row["encoded_sha256"])
                for row in trials
                if row["family"] == family
            }
        )
        == 1
        for family in {row["family"] for row in trials}
    )
    return {
        "summaries": summaries,
        "gates": {"encoded_identity": encoded_identity, **gates},
        "candidate_qualifies": encoded_identity
        and all(all(values.values()) for values in gates.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, default=REPOSITORY)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPOSITORY / "corpora" / "clue-json-log-development-v1",
    )
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=7)
    args = parser.parse_args()
    if args.rounds < 1:
        raise ValueError("rounds must be at least one")

    roots = {
        "baseline": args.baseline_root.resolve(),
        "candidate": args.candidate_root.resolve(),
    }
    items = load_items(args.corpus)
    prepare_fixtures(items, args.fixture_dir)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    trials = []
    warmups = [
        (item["id"], mode, variant)
        for item in items
        for mode in MODES
        for variant in VARIANTS
    ]
    schedule = [warmups] + measurement_schedule(
        [item["id"] for item in items], args.rounds
    )
    by_id = {item["id"]: item for item in items}
    for schedule_index, pairs in enumerate(schedule):
        warmup = schedule_index == 0
        round_number = 0 if warmup else schedule_index
        for trial_index, (family, mode, variant) in enumerate(pairs):
            row = run_trial(
                roots[variant],
                variant,
                mode,
                by_id[family],
                args.fixture_dir,
                args.work_dir,
                f"r{round_number:02d}-t{trial_index:02d}",
            )
            row.update({"round": round_number, "warmup": warmup})
            trials.append(row)

    probe_commands = {
        "python-pass": [sys.executable, "-c", "pass"],
        "import-compresslab": [sys.executable, "-c", "import compresslab"],
        "cli-version": [sys.executable, "-m", "compresslab", "--version"],
        "worker-help": [sys.executable, "-m", "compresslab.worker", "--help"],
    }
    probes = {}
    for name, command in probe_commands.items():
        probes[name] = {}
        for variant in VARIANTS:
            run_probe(roots[variant], command)
            values = [run_probe(roots[variant], command) for _ in range(7)]
            probes[name][variant] = {
                "median_ms": statistics.median(values) / 1_000_000,
                "minimum_ms": min(values) / 1_000_000,
                "maximum_ms": max(values) / 1_000_000,
                "values_ns": values,
            }

    result = {
        "schema_version": 1,
        "protocol": "jls2-cold-start-v1",
        "created_at_epoch": int(time.time()),
        "platform": platform.platform(),
        "python": sys.version,
        "logical_cpu_count": os.cpu_count(),
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
        "roots": {name: str(root) for name, root in roots.items()},
        "native_library": {
            "path": str(native_library()),
            "sha256": sha256_file(native_library()),
        },
        "source_hashes": {
            variant: {
                path: sha256_file(root / path)
                for path in SOURCE_FILES
                if (root / path).is_file()
            }
            for variant, root in roots.items()
        },
        "frames": {
            item["id"]: {
                "bytes": (args.fixture_dir / f"{item['id']}.jls2").stat().st_size,
                "sha256": sha256_file(
                    args.fixture_dir / f"{item['id']}.jls2"
                ),
            }
            for item in items
        },
        "rounds": args.rounds,
        "warmups": 1,
        "probes": probes,
        "trials": trials,
        "summary": summarize(trials, args.rounds),
        "claim_ceiling": (
            "Development-only cold-process delivery evidence on the three frozen "
            "CLUE-LDS development ranges; not public validation, private holdout, "
            "independent reproduction, universal, market-leading, world-best, or "
            "state-of-the-art evidence"
        ),
    }
    write_json(args.output, result)


if __name__ == "__main__":
    main()
