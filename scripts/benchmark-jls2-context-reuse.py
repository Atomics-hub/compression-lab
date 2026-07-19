#!/usr/bin/env python3
"""Frozen Linux A/B gate for reusable JLS2 Zstandard decode contexts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "7b081f6f11c2561c36289cfc57f7d3715ab8c594"
ROUNDS = 7
VARIANTS = ("baseline", "candidate")
STRESS_ID = "jls2-context-stress-256"
STRESS_RECORDS = 21_800
MIB = 1024 * 1024


def load_native_gate() -> Any:
    path = ROOT / "scripts" / "benchmark-jls2-native-decoder.py"
    spec = importlib.util.spec_from_file_location("jls2_native_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load native JLS2 benchmark helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NATIVE_GATE = load_native_gate()


def sha256_file(path: Path) -> str:
    return NATIVE_GATE.sha256_file(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    NATIVE_GATE.write_json(path, payload)


def build_stress_source(path: Path) -> None:
    keys = [f'"k{index:03d}":'.encode() for index in range(256)]
    with path.open("xb") as output:
        for record_index in range(STRESS_RECORDS):
            output.write(b"{")
            for key_index, key in enumerate(keys):
                if key_index:
                    output.write(b",")
                output.write(key)
                output.write(bytes((48 + (record_index + key_index) % 10,)))
            output.write(b"}\n")


def prepare_items(corpus: Path, work: Path) -> list[dict[str, Any]]:
    fixtures = work / "fixtures"
    NATIVE_GATE.prepare_fixtures(corpus, fixtures)
    items = NATIVE_GATE.load_items(corpus, fixtures)
    stress_source = work / f"{STRESS_ID}.jsonl"
    stress_frame = fixtures / f"{STRESS_ID}.jls2"
    build_stress_source(stress_source)
    from compresslab.json_log_codec import compress_file

    telemetry = compress_file(stress_source, stress_frame, overwrite=True)
    if telemetry["segment_count"] != 3:
        raise ValueError("stress fixture must contain exactly three JLS2 segments")
    items.append(
        {
            "id": STRESS_ID,
            "family": STRESS_ID,
            "size_bytes": stress_source.stat().st_size,
            "sha256": sha256_file(stress_source),
            "source": stress_source,
            "frame": stress_frame,
        }
    )
    return items


def schedule(item_ids: list[str], rounds: int) -> list[list[tuple[str, str]]]:
    output = []
    for round_index in range(rounds):
        ids = item_ids if round_index % 2 == 0 else list(reversed(item_ids))
        rows = []
        for item_index, item_id in enumerate(ids):
            variants = list(VARIANTS)
            if (round_index + item_index) % 2:
                variants.reverse()
            rows.extend((item_id, variant) for variant in variants)
        output.append(rows)
    return output


def run_trial(
    variant: str,
    binary: Path,
    item: dict[str, Any],
    work: Path,
    label: str,
) -> dict[str, Any]:
    destination = work / f"{label}-{item['id']}-{variant}.restored"
    command = [
        str(binary),
        "decompress",
        str(item["frame"]),
        "-o",
        str(destination),
        "--force",
    ]
    environment = os.environ.copy()
    result = NATIVE_GATE.run_process(command, ROOT, environment)
    returncode, stdout, stderr, wall_ns, peak_rss_bytes = result
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
        raise ValueError(f"inexact {variant} decode for {item['id']}: {stderr}")
    return {
        "variant": variant,
        "item_id": item["id"],
        "source_bytes": item["size_bytes"],
        "source_sha256": item["sha256"],
        "encoded_bytes": item["frame"].stat().st_size,
        "encoded_sha256": sha256_file(item["frame"]),
        "command": command,
        "wall_ns": wall_ns,
        "mbps": item["size_bytes"] / wall_ns * 1000.0,
        "peak_rss_bytes": peak_rss_bytes,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "exact": exact,
    }


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / statistics.mean(values) * 100.0


def summarize(trials: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
    measured = [row for row in trials if not row["warmup"]]
    variants = []
    for variant in VARIANTS:
        rows = [row for row in measured if row["variant"] == variant]
        round_rates = []
        for round_number in range(1, rounds + 1):
            group = [row for row in rows if row["round"] == round_number]
            round_rates.append(
                sum(row["source_bytes"] for row in group)
                / sum(row["wall_ns"] for row in group)
                * 1000.0
            )
        item_rows = []
        for item_id in sorted({row["item_id"] for row in rows}):
            group = [row for row in rows if row["item_id"] == item_id]
            item_rows.append(
                {
                    "item_id": item_id,
                    "median_mbps": statistics.median(row["mbps"] for row in group),
                    "minimum_mbps": min(row["mbps"] for row in group),
                    "peak_rss_bytes": max(row["peak_rss_bytes"] for row in group),
                }
            )
        variants.append(
            {
                "variant": variant,
                "median_aggregate_mbps": statistics.median(round_rates),
                "minimum_aggregate_mbps": min(round_rates),
                "aggregate_cv_percent": coefficient_of_variation(round_rates),
                "round_rates_mbps": round_rates,
                "peak_rss_bytes": max(row["peak_rss_bytes"] for row in rows),
                "all_exact": all(row["exact"] for row in rows),
                "item_rows": item_rows,
            }
        )
    baseline = next(row for row in variants if row["variant"] == "baseline")
    candidate = next(row for row in variants if row["variant"] == "candidate")
    baseline_items = {row["item_id"]: row for row in baseline["item_rows"]}
    candidate_items = {row["item_id"]: row for row in candidate["item_rows"]}
    stress_baseline = baseline_items[STRESS_ID]["peak_rss_bytes"]
    stress_candidate = candidate_items[STRESS_ID]["peak_rss_bytes"]
    clue_ids = set(candidate_items) - {STRESS_ID}
    gates = {
        "all_exact": candidate["all_exact"] and baseline["all_exact"],
        "candidate_peak_rss_at_or_below_448_mib": all(
            row["peak_rss_bytes"] <= 448 * MIB for row in candidate["item_rows"]
        ),
        "stress_peak_rss_reduction_at_least_20_percent": (
            stress_candidate <= stress_baseline * 0.80
        ),
        "no_clue_family_peak_rss_regression": all(
            candidate_items[item_id]["peak_rss_bytes"]
            <= baseline_items[item_id]["peak_rss_bytes"]
            for item_id in clue_ids
        ),
        "candidate_median_throughput_at_least_95_percent_of_baseline": (
            candidate["median_aggregate_mbps"]
            >= baseline["median_aggregate_mbps"] * 0.95
        ),
        "all_candidate_item_medians_at_or_above_250_mbps": all(
            row["median_mbps"] >= 250.0 for row in candidate["item_rows"]
        ),
        "all_candidate_rounds_at_or_above_225_mbps": all(
            rate >= 225.0 for rate in candidate["round_rates_mbps"]
        ),
        "candidate_cv_at_or_below_20_percent": (
            candidate["aggregate_cv_percent"] <= 20.0
        ),
    }
    return {
        "variants": variants,
        "gates": gates,
        "passed": all(gates.values()),
        "stress_peak_rss_reduction_percent": (
            (1.0 - stress_candidate / stress_baseline) * 100.0
        ),
    }


def git_state() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"commit": commit, "dirty": dirty}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline-binary", type=Path, required=True)
    parser.add_argument("--candidate-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    for binary in (args.baseline_binary, args.candidate_binary):
        if not binary.is_file():
            parser.error(f"binary is missing: {binary}")
    binaries = {
        "baseline": args.baseline_binary.resolve(),
        "candidate": args.candidate_binary.resolve(),
    }
    trials = []
    with tempfile.TemporaryDirectory(prefix="jls2-context-reuse-") as name:
        work = Path(name)
        items = prepare_items(args.corpus.resolve(), work)
        by_id = {item["id"]: item for item in items}
        for item_id in by_id:
            for variant in VARIANTS:
                row = run_trial(
                    variant, binaries[variant], by_id[item_id], work, "warmup"
                )
                row.update({"round": 0, "warmup": True})
                trials.append(row)
        for round_number, rows in enumerate(
            schedule(list(by_id), args.rounds), start=1
        ):
            for item_id, variant in rows:
                row = run_trial(
                    variant,
                    binaries[variant],
                    by_id[item_id],
                    work,
                    f"round-{round_number}",
                )
                row.update({"round": round_number, "warmup": False})
                trials.append(row)
    repository = git_state()
    if repository["dirty"]:
        raise ValueError("context-reuse benchmark requires a clean candidate commit")
    result = {
        "schema_version": 1,
        "name": "jls2-context-reuse-development-v1",
        "claim_scope": "development-only decoder-memory evidence",
        "baseline_commit": BASELINE_COMMIT,
        "candidate": repository,
        "created_at_epoch_seconds": int(time.time()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "load_average_after": list(os.getloadavg()),
        },
        "binaries": {
            key: {"path": str(path), "sha256": sha256_file(path)}
            for key, path in binaries.items()
        },
        "settings": {
            "rounds": args.rounds,
            "warmups": 1,
            "stress_id": STRESS_ID,
            "stress_records": STRESS_RECORDS,
        },
        "trials": trials,
        "summary": summarize(trials, args.rounds),
        "claim_ceiling": (
            "Development-only decoder-memory evidence; consumed public-validation "
            "ranges and the private holdout were not used."
        ),
    }
    write_json(args.output.resolve(), result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
