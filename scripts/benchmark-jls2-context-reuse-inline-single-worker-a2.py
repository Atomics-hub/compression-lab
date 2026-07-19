#!/usr/bin/env python3
"""Frozen Linux A/B gate for the JLS2 inline-single-worker A2 ablation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
A1_RUNNER = ROOT / "scripts" / "benchmark-jls2-context-reuse.py"
A1_RUNNER_SHA256 = (
    "d8073d8c96e923fb88689be565051c1f03c0a362c2c1e28c0000dbc14e632f96"
)
FROZEN_SUPPORT_FILES = {
    ROOT / "scripts" / "benchmark-jls2-native-decoder.py": (
        "0ae16a0574a61b9e46cccce7f3abaddb1fc0facc760828f2a1b3241cef334297"
    ),
    ROOT / "config" / "clue-json-log-corpus-v1.json": (
        "9326b3c38835da96feabe0c3b8fcdae1f176d113301e95bc703169666c1f6cf5"
    ),
}
BASELINE_COMMIT = "131547f35747cc0ff9dedbdef66d8a9516a7464f"
RESULT_NAME = "jls2-context-reuse-inline-single-worker-a2-development-v1"
CLAIM_SCOPE = "development-only A2 decoder-memory evidence"
CLAIM_CEILING = (
    "Development-only A2 decoder-memory evidence; consumed public-validation "
    "ranges and the private holdout were not used."
)
ROUNDS = 7
VARIANTS = ("baseline", "candidate")
STRESS_ID = "jls2-context-stress-256"
STRESS_RECORDS = 21_800
STRESS_RSS_REDUCTION_MIN_PERCENT = 5.0
MIB = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_a1_runner() -> Any:
    observed = sha256_file(A1_RUNNER)
    if observed != A1_RUNNER_SHA256:
        raise RuntimeError(
            "frozen A1 runner drifted: "
            f"expected {A1_RUNNER_SHA256}, observed {observed}"
        )
    for path, expected in FROZEN_SUPPORT_FILES.items():
        observed = sha256_file(path)
        if observed != expected:
            raise RuntimeError(
                f"frozen A1 support file drifted: {path.relative_to(ROOT)}; "
                f"expected {expected}, observed {observed}"
            )
    spec = importlib.util.spec_from_file_location("jls2_context_reuse_a1", A1_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen A1 context-reuse runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        module.ROUNDS != ROUNDS
        or module.VARIANTS != VARIANTS
        or module.STRESS_ID != STRESS_ID
        or module.STRESS_RECORDS != STRESS_RECORDS
    ):
        raise RuntimeError("frozen A1 fixture or schedule constants drifted")
    return module


A1 = load_a1_runner()


def prepare_items(corpus: Path, work: Path) -> list[dict[str, Any]]:
    return A1.prepare_items(corpus, work)


def schedule(item_ids: list[str], rounds: int) -> list[list[tuple[str, str]]]:
    return A1.schedule(item_ids, rounds)


def run_trial(
    variant: str,
    binary: Path,
    item: dict[str, Any],
    work: Path,
    label: str,
) -> dict[str, Any]:
    return A1.run_trial(variant, binary, item, work, label)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    A1.write_json(path, payload)


def summarize(trials: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
    summary = A1.summarize(trials, rounds)
    baseline = next(
        row for row in summary["variants"] if row["variant"] == "baseline"
    )
    candidate = next(
        row for row in summary["variants"] if row["variant"] == "candidate"
    )
    baseline_items = {row["item_id"]: row for row in baseline["item_rows"]}
    candidate_items = {row["item_id"]: row for row in candidate["item_rows"]}
    del summary["gates"]["stress_peak_rss_reduction_at_least_20_percent"]
    summary["gates"]["stress_peak_rss_reduction_at_least_5_percent"] = (
        candidate_items[STRESS_ID]["peak_rss_bytes"]
        <= baseline_items[STRESS_ID]["peak_rss_bytes"]
        * (1.0 - STRESS_RSS_REDUCTION_MIN_PERCENT / 100.0)
    )
    summary["passed"] = all(summary["gates"].values())
    return summary


def candidate_git_state() -> dict[str, Any]:
    repository = A1.git_state()
    if repository["dirty"]:
        raise ValueError("A2 benchmark requires a clean candidate commit")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASELINE_COMMIT, repository["commit"]],
        cwd=ROOT,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValueError("A2 candidate must descend from the exact A1 baseline")
    return repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline-binary", type=Path, required=True)
    parser.add_argument("--candidate-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()
    if args.rounds != ROUNDS:
        parser.error(f"--rounds is frozen at {ROUNDS}")
    for binary in (args.baseline_binary, args.candidate_binary):
        if not binary.is_file():
            parser.error(f"binary is missing: {binary}")
    binaries = {
        "baseline": args.baseline_binary.resolve(),
        "candidate": args.candidate_binary.resolve(),
    }
    trials = []
    with tempfile.TemporaryDirectory(prefix="jls2-inline-worker-a2-") as name:
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
            schedule(list(by_id), ROUNDS), start=1
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
    repository = candidate_git_state()
    result = {
        "schema_version": 1,
        "name": RESULT_NAME,
        "ablation": "A1 reusable contexts plus inline execution when workers == 1",
        "claim_scope": CLAIM_SCOPE,
        "baseline_commit": BASELINE_COMMIT,
        "candidate": repository,
        "created_at_epoch_seconds": int(time.time()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "rustc": subprocess.run(
                ["rustc", "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "logical_cpus": os.cpu_count(),
            "load_average_after": list(os.getloadavg()),
        },
        "binaries": {
            key: {"path": str(path), "sha256": sha256_file(path)}
            for key, path in binaries.items()
        },
        "settings": {
            "rounds": ROUNDS,
            "warmups": 1,
            "stress_id": STRESS_ID,
            "stress_records": STRESS_RECORDS,
            "stress_rss_reduction_min_percent": STRESS_RSS_REDUCTION_MIN_PERCENT,
            "a1_runner_sha256": A1_RUNNER_SHA256,
            "frozen_support_sha256": {
                path.relative_to(ROOT).as_posix(): digest
                for path, digest in FROZEN_SUPPORT_FILES.items()
            },
        },
        "trials": trials,
        "summary": summarize(trials, ROUNDS),
        "claim_ceiling": CLAIM_CEILING,
    }
    write_json(args.output.resolve(), result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0 if result["summary"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
