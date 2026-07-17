#!/usr/bin/env python3
"""Characterize cold-process JLS2 decode scheduling on frozen CLUE data."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
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

try:
    import resource
except ImportError:  # pragma: no cover - exercised by Windows CI
    resource = None  # type: ignore[assignment]


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "config" / "clue-json-log-corpus-v1.json"
COMPARISON = (
    REPOSITORY / "runs" / "clue-json-log-development-census-v1" / "comparison.json"
)
BASELINE = "outer2-innerauto"
VARIANTS = {
    "outer2-innerauto": {"outer_workers": 2, "inner_workers": None},
    "outer1-innerauto": {"outer_workers": 1, "inner_workers": None},
    "outer2-inner1": {"outer_workers": 2, "inner_workers": 1},
    "outer2-inner2": {"outer_workers": 2, "inner_workers": 2},
}
SOURCE_FILES = (
    "src/compresslab/json_columnar.py",
    "src/compresslab/json_log_codec.py",
    "src/compresslab/native.py",
    "native/src/lib.rs",
    "scripts/benchmark-clue-jls2-decode-scheduling.py",
)
MAX_RSS_BYTES = 512 * 1024 * 1024


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


def worker_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY / "src")
    environment["COMPRESSION_LAB_NATIVE_LIB"] = str(native_library())
    return environment


def load_items(corpus_dir: Path) -> list[dict[str, Any]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    expected_bytes = {
        row["item_id"]: row["jls2_bytes"] for row in comparison["family_rows"]
    }
    items = []
    for item in config["selection"]["development"]:
        source = corpus_dir / f"{item['id']}.jsonl"
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
        telemetry = compress_file(item["source"], frame)
        if frame.stat().st_size != item["expected_encoded_bytes"]:
            raise ValueError(f"encoded byte drift: {item['id']}")
        if telemetry["original_bytes"] != item["size_bytes"]:
            raise ValueError(f"encoded source-size drift: {item['id']}")


def measurement_schedule(
    variant_ids: list[str], family_ids: list[str], rounds: int
) -> list[list[tuple[str, str]]]:
    schedule = []
    for round_index in range(rounds):
        families = list(family_ids)
        if round_index % 2:
            families.reverse()
        pairs = []
        for family_index, family_id in enumerate(families):
            rotation = (round_index + family_index) % len(variant_ids)
            variants = variant_ids[rotation:] + variant_ids[:rotation]
            if round_index % 2:
                variants = list(reversed(variants))
            pairs.extend((family_id, variant_id) for variant_id in variants)
        schedule.append(pairs)
    return schedule


def configure_worker(variant_id: str) -> None:
    import compresslab.json_columnar as columnar
    import compresslab.json_log_codec as codec

    variant = VARIANTS[variant_id]
    codec.MAX_DECOMPRESSION_SEGMENT_WORKERS = variant["outer_workers"]
    inner_workers = variant["inner_workers"]
    if inner_workers is None:
        return

    def bounded_decompress_channels(
        payloads: list[bytes], raw_sizes: list[int]
    ) -> list[bytes]:
        items = list(zip(payloads, raw_sizes))
        workers = min(len(items), inner_workers)
        if workers <= 1:
            return [columnar._decompress_channel(item) for item in items]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(columnar._decompress_channel, items))

    columnar._decompress_channels = bounded_decompress_channels


def cpu_time_ns() -> int:
    if resource is None:
        return time.process_time_ns()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return int((usage.ru_utime + usage.ru_stime) * 1_000_000_000)


def peak_rss_bytes() -> int:
    if resource is None:
        return 0
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def run_worker(args: argparse.Namespace) -> int:
    configure_worker(args.variant)
    from compresslab.json_log_codec import decompress_file

    started_wall = time.perf_counter_ns()
    started_cpu = cpu_time_ns()
    telemetry = decompress_file(args.frame, args.destination)
    result = {
        "variant": args.variant,
        "worker_wall_ns": time.perf_counter_ns() - started_wall,
        "worker_cpu_ns": cpu_time_ns() - started_cpu,
        "peak_rss_bytes": peak_rss_bytes(),
        "segment_count": telemetry["segment_count"],
        "restored_bytes": telemetry["restored_bytes"],
    }
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


def run_trial(
    variant_id: str,
    item: dict[str, Any],
    fixture_dir: Path,
    work_dir: Path,
    label: str,
) -> dict[str, Any]:
    frame = fixture_dir / f"{item['id']}.jls2"
    destination = work_dir / f"{label}-{item['id']}-{variant_id}.jsonl"
    started = time.perf_counter_ns()
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--variant",
            variant_id,
            "--frame",
            str(frame),
            "--destination",
            str(destination),
        ],
        cwd=REPOSITORY,
        env=worker_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    parent_wall_ns = time.perf_counter_ns() - started
    worker = json.loads(completed.stdout)
    try:
        exact = (
            destination.stat().st_size == item["size_bytes"]
            and sha256_file(destination) == item["sha256"]
        )
    finally:
        destination.unlink(missing_ok=True)
    if not exact:
        raise ValueError(f"restored output mismatch: {item['id']} {variant_id}")
    return {
        "family": item["id"],
        "variant": variant_id,
        "source_bytes": item["size_bytes"],
        "source_sha256": item["sha256"],
        "encoded_bytes": frame.stat().st_size,
        "encoded_sha256": sha256_file(frame),
        "parent_wall_ns": parent_wall_ns,
        "parent_mbps": item["size_bytes"] / parent_wall_ns * 1_000,
        "worker_mbps": item["size_bytes"] / worker["worker_wall_ns"] * 1_000,
        "exact": exact,
        **worker,
    }


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / statistics.mean(values) * 100


def summarize(
    trials: list[dict[str, Any]], variant_ids: list[str], rounds: int
) -> dict[str, Any]:
    measured = [trial for trial in trials if not trial["warmup"]]
    baseline_round_rates = {}
    summaries = []
    for variant_id in variant_ids:
        variant_trials = [trial for trial in measured if trial["variant"] == variant_id]
        round_rates = []
        for round_number in range(1, rounds + 1):
            rows = [trial for trial in variant_trials if trial["round"] == round_number]
            round_rates.append(
                sum(row["source_bytes"] for row in rows)
                / sum(row["parent_wall_ns"] for row in rows)
                * 1_000
            )
        if variant_id == BASELINE:
            baseline_round_rates = {
                index: value for index, value in enumerate(round_rates, start=1)
            }
        family_rows = []
        for family in sorted({trial["family"] for trial in variant_trials}):
            rates = [
                trial["parent_mbps"]
                for trial in variant_trials
                if trial["family"] == family
            ]
            family_rows.append(
                {
                    "family": family,
                    "median_parent_mbps": statistics.median(rates),
                    "minimum_parent_mbps": min(rates),
                    "cv_percent": coefficient_of_variation(rates),
                }
            )
        summaries.append(
            {
                "variant": variant_id,
                "outer_workers": VARIANTS[variant_id]["outer_workers"],
                "inner_workers": VARIANTS[variant_id]["inner_workers"],
                "median_aggregate_parent_mbps": statistics.median(round_rates),
                "minimum_aggregate_parent_mbps": min(round_rates),
                "aggregate_cv_percent": coefficient_of_variation(round_rates),
                "rounds_at_or_above_250_mbps": sum(rate >= 250 for rate in round_rates),
                "round_rates_mbps": round_rates,
                "family_rows": family_rows,
                "peak_rss_bytes": max(
                    trial["peak_rss_bytes"] for trial in variant_trials
                ),
                "all_exact": all(trial["exact"] for trial in variant_trials),
            }
        )
    if not baseline_round_rates:
        raise ValueError("baseline trials are missing")

    baseline_summary = next(row for row in summaries if row["variant"] == BASELINE)
    for row in summaries:
        paired_improvements = [
            (rate / baseline_round_rates[index] - 1) * 100
            for index, rate in enumerate(row["round_rates_mbps"], start=1)
        ]
        row["median_paired_improvement_percent"] = statistics.median(
            paired_improvements
        )
        row["selection_gates"] = {
            "encoded_identity": all(
                len(
                    {
                        (trial["encoded_bytes"], trial["encoded_sha256"])
                        for trial in measured
                        if trial["family"] == family
                    }
                )
                == 1
                for family in {trial["family"] for trial in measured}
            ),
            "all_exact": row["all_exact"],
            "all_rounds_at_or_above_250_mbps": row["rounds_at_or_above_250_mbps"]
            == rounds,
            "all_family_medians_at_or_above_250_mbps": all(
                family["median_parent_mbps"] >= 250 for family in row["family_rows"]
            ),
            "aggregate_cv_at_or_below_20_percent": row["aggregate_cv_percent"] <= 20,
            "peak_rss_at_or_below_512_mib": row["peak_rss_bytes"] <= MAX_RSS_BYTES,
            "paired_improvement_at_or_above_5_percent": row[
                "median_paired_improvement_percent"
            ]
            >= 5,
        }
        row["qualifies"] = row["variant"] != BASELINE and all(
            row["selection_gates"].values()
        )

    qualifiers = [row for row in summaries if row["qualifies"]]
    qualifiers.sort(
        key=lambda row: (
            row["minimum_aggregate_parent_mbps"],
            row["median_aggregate_parent_mbps"],
        ),
        reverse=True,
    )
    return {
        "baseline": baseline_summary,
        "variants": summaries,
        "selected_variant": qualifiers[0]["variant"] if qualifiers else None,
    }


def git_state() -> dict[str, Any]:
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
    return {
        "commit": commit,
        "dirty": dirty,
        "source_sha256": {
            relative: sha256_file(REPOSITORY / relative) for relative in SOURCE_FILES
        },
        "native_library_sha256": sha256_file(native_library()),
    }


def run_benchmark(args: argparse.Namespace) -> int:
    if args.rounds < 1 or args.warmups < 0:
        raise ValueError("rounds must be positive and warmups nonnegative")
    items = load_items(args.corpus_dir)
    item_by_id = {item["id"]: item for item in items}
    variant_ids = list(VARIANTS)
    load_before = list(os.getloadavg()) if hasattr(os, "getloadavg") else None
    with tempfile.TemporaryDirectory(prefix="clue-jls2-scheduling-") as name:
        work_dir = Path(name)
        fixture_dir = work_dir / "fixtures"
        prepare_fixtures(items, fixture_dir)
        trials = []
        for warmup in range(1, args.warmups + 1):
            for family_id, variant_id in measurement_schedule(
                variant_ids, list(item_by_id), 1
            )[0]:
                trial = run_trial(
                    variant_id,
                    item_by_id[family_id],
                    fixture_dir,
                    work_dir,
                    f"warmup-{warmup}",
                )
                trial.update({"warmup": True, "round": 0})
                trials.append(trial)
        for round_number, pairs in enumerate(
            measurement_schedule(variant_ids, list(item_by_id), args.rounds),
            start=1,
        ):
            for position, (family_id, variant_id) in enumerate(pairs, start=1):
                trial = run_trial(
                    variant_id,
                    item_by_id[family_id],
                    fixture_dir,
                    work_dir,
                    f"round-{round_number}-position-{position}",
                )
                trial.update(
                    {
                        "warmup": False,
                        "round": round_number,
                        "position": position,
                    }
                )
                trials.append(trial)
                print(
                    f"round {round_number}/{args.rounds} {family_id} "
                    f"{variant_id}: {trial['parent_mbps']:.2f} MB/s",
                    flush=True,
                )
    result = {
        "schema_version": 1,
        "name": "clue-jls2-decode-scheduling-v1",
        "claim_ceiling": "Development-only decode-scheduling evidence on the three frozen CLUE-LDS development ranges; not public validation, private holdout, independent reproduction, universal, market-leading, world-best, or state-of-the-art evidence",
        "settings": {
            "rounds": args.rounds,
            "warmups": args.warmups,
            "timing_scope": "parent wall clock including fresh worker startup and complete atomic file decode",
            "variants": VARIANTS,
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "load_average_before": load_before,
            "load_average_after": list(os.getloadavg())
            if hasattr(os, "getloadavg")
            else None,
        },
        "git": git_state(),
        "corpus": [
            {
                key: item[key]
                for key in (
                    "id",
                    "family",
                    "size_bytes",
                    "sha256",
                    "expected_encoded_bytes",
                )
            }
            for item in items
        ],
        "summary": summarize(trials, variant_ids, args.rounds),
        "trials": trials,
    }
    write_json(args.output, result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=REPOSITORY / "corpora" / "clue-json-log-development-v1",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--variant", choices=VARIANTS)
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--destination", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.worker:
        if args.variant is None or args.frame is None or args.destination is None:
            raise ValueError("worker requires variant, frame, and destination")
        return run_worker(args)
    if args.output is None:
        raise ValueError("benchmark requires --output")
    args.corpus_dir = args.corpus_dir.resolve()
    args.output = args.output.resolve()
    return run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
