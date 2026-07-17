#!/usr/bin/env python3
"""Publish the rejected CLUE JLS2 decode-scheduling experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
EXPECTED_COMMIT = "9fa2e9f2c80b857e729728f53f2f88e25eaa7c9f"
BASELINE = "outer2-innerauto"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def coefficient_of_variation(values: list[float]) -> float:
    return statistics.stdev(values) / statistics.mean(values) * 100


def derive(results: dict[str, Any]) -> list[dict[str, Any]]:
    measured = [trial for trial in results["trials"] if not trial["warmup"]]
    rows = []
    variant_ids = [
        BASELINE,
        *sorted(
            variant
            for variant in results["settings"]["variants"]
            if variant != BASELINE
        ),
    ]
    for variant in variant_ids:
        trials = [trial for trial in measured if trial["variant"] == variant]
        parent_rounds = []
        worker_rounds = []
        for round_number in range(1, results["settings"]["rounds"] + 1):
            round_trials = [trial for trial in trials if trial["round"] == round_number]
            source_bytes = sum(trial["source_bytes"] for trial in round_trials)
            parent_rounds.append(
                source_bytes
                / sum(trial["parent_wall_ns"] for trial in round_trials)
                * 1_000
            )
            worker_rounds.append(
                source_bytes
                / sum(trial["worker_wall_ns"] for trial in round_trials)
                * 1_000
            )
        overhead_ms = [
            (trial["parent_wall_ns"] - trial["worker_wall_ns"]) / 1_000_000
            for trial in trials
        ]
        source_summary = next(
            row for row in results["summary"]["variants"] if row["variant"] == variant
        )
        rows.append(
            {
                "variant": variant,
                "outer_workers": source_summary["outer_workers"],
                "inner_workers": source_summary["inner_workers"],
                "parent_median_mbps": statistics.median(parent_rounds),
                "parent_minimum_mbps": min(parent_rounds),
                "parent_cv_percent": coefficient_of_variation(parent_rounds),
                "parent_rounds_at_or_above_250": sum(
                    rate >= 250 for rate in parent_rounds
                ),
                "worker_median_mbps": statistics.median(worker_rounds),
                "worker_minimum_mbps": min(worker_rounds),
                "worker_cv_percent": coefficient_of_variation(worker_rounds),
                "cold_process_overhead_median_ms": statistics.median(overhead_ms),
                "cold_process_overhead_maximum_ms": max(overhead_ms),
                "peak_rss_mib": source_summary["peak_rss_bytes"] / (1024 * 1024),
                "median_paired_improvement_percent": source_summary[
                    "median_paired_improvement_percent"
                ],
                "qualifies": source_summary["qualifies"],
                "all_exact": source_summary["all_exact"],
                "family_rows": source_summary["family_rows"],
            }
        )
    return rows


def validate(results: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if results["name"] != "clue-jls2-decode-scheduling-v1":
        raise ValueError("unexpected scheduling result name")
    if results["git"]["commit"] != EXPECTED_COMMIT or results["git"]["dirty"]:
        raise ValueError("scheduling result is not bound to the clean protocol commit")
    if results["summary"]["selected_variant"] is not None:
        raise ValueError("scheduling experiment unexpectedly selected a variant")
    if set(results["settings"]["variants"]) != {
        "outer2-innerauto",
        "outer1-innerauto",
        "outer2-inner1",
        "outer2-inner2",
    }:
        raise ValueError("scheduling variant roster changed")
    measured = [trial for trial in results["trials"] if not trial["warmup"]]
    warmups = [trial for trial in results["trials"] if trial["warmup"]]
    if len(measured) != 84 or len(warmups) != 12:
        raise ValueError("unexpected scheduling trial count")
    if not all(trial["exact"] for trial in results["trials"]):
        raise ValueError("scheduling evidence includes an inexact round trip")
    for family in {trial["family"] for trial in results["trials"]}:
        identities = {
            (trial["encoded_bytes"], trial["encoded_sha256"])
            for trial in results["trials"]
            if trial["family"] == family
        }
        if len(identities) != 1:
            raise ValueError(f"encoded fixture drift: {family}")
    baseline = next(row for row in rows if row["variant"] == BASELINE)
    if baseline["parent_rounds_at_or_above_250"] != 6:
        raise ValueError("baseline cold-process result changed")
    if baseline["worker_minimum_mbps"] < 250:
        raise ValueError("baseline worker kernel unexpectedly missed 250 MB/s")
    if any(row["qualifies"] for row in rows):
        raise ValueError("a rejected scheduling variant is marked qualified")
    if baseline["parent_median_mbps"] != max(row["parent_median_mbps"] for row in rows):
        raise ValueError("baseline is not the fastest parent-wall topology")
    for relative, expected in results["git"]["source_sha256"].items():
        if sha256_file(REPOSITORY / relative) != expected:
            raise ValueError(f"bound source changed before publication: {relative}")
    config = json.loads(
        (REPOSITORY / "config" / "clue-json-log-corpus-v1.json").read_text(
            encoding="utf-8"
        )
    )
    if any(
        item["size_bytes"] is not None or item["sha256"] is not None
        for item in config["selection"]["public_validation"]
    ):
        raise ValueError("CLUE public-validation ranges are no longer sealed")


def worker_label(value: int | None) -> str:
    return "auto" if value is None else str(value)


def render(results: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    baseline = next(row for row in rows if row["variant"] == BASELINE)
    lines = [
        "# CLUE-LDS JLS2 decode-scheduling development gate",
        "",
        "**Outcome: scheduling hypothesis rejected; product unchanged.** The current two-segment-worker, auto-channel topology remained the fastest measured option at **{:.2f} MB/s** median cold-process throughput. None of the three bounded alternatives passed the frozen selection gates.".format(
            baseline["parent_median_mbps"]
        ),
        "",
        "The current decode kernel itself reached **{:.2f} MB/s** median and never fell below **{:.2f} MB/s** in aggregate worker timing. The primary parent-wall result missed 250 MB/s in one of seven rounds because cold-process overhead ranged up to {:.2f} ms. The next experiment should target startup/native product delivery, not reduce decode parallelism.".format(
            baseline["worker_median_mbps"],
            baseline["worker_minimum_mbps"],
            baseline["cold_process_overhead_maximum_ms"],
        ),
        "",
        "## Full topology chart",
        "",
        "All variants decoded identical JLS2 bytes in fresh worker processes. Parent wall is the frozen primary timing and includes interpreter startup plus complete atomic file decode.",
        "",
        "| Variant | Segment / channel workers | Parent median | Parent minimum | Parent CV | Parent rounds ≥250 | Worker median | Worker minimum | Cold-process overhead median / max | Peak RSS | Paired vs current | Exact | Selected |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |",
    ]
    for row in rows:
        lines.append(
            "| {} | {} / {} | {:.2f} MB/s | {:.2f} MB/s | {:.2f}% | {}/7 | {:.2f} MB/s | {:.2f} MB/s | {:.2f} / {:.2f} ms | {:.1f} MiB | {:+.2f}% | yes | {} |".format(
                row["variant"],
                row["outer_workers"],
                worker_label(row["inner_workers"]),
                row["parent_median_mbps"],
                row["parent_minimum_mbps"],
                row["parent_cv_percent"],
                row["parent_rounds_at_or_above_250"],
                row["worker_median_mbps"],
                row["worker_minimum_mbps"],
                row["cold_process_overhead_median_ms"],
                row["cold_process_overhead_maximum_ms"],
                row["peak_rss_mib"],
                row["median_paired_improvement_percent"],
                "no" if not row["qualifies"] else "yes",
            )
        )
    lines.extend(
        [
            "",
            "## Family parent-wall medians",
            "",
            "| Variant | Early | Middle | Late |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        families = {
            family["family"]: family["median_parent_mbps"]
            for family in row["family_rows"]
        }
        lines.append(
            "| {} | {:.2f} MB/s | {:.2f} MB/s | {:.2f} MB/s |".format(
                row["variant"],
                families["clue-early-development"],
                families["clue-middle-development"],
                families["clue-late-development"],
            )
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "Retain `outer2-innerauto`. Do not change JLS2 compressed bytes or decode scheduling. The byte-identical worker kernel already has substantial headroom above 250 MB/s; the remaining failed gate is cold-process delivery reliability under variable host scheduling.",
            "",
            "## Evidence boundary",
            "",
            f"- Clean benchmark commit: `{results['git']['commit']}`",
            f"- Platform: `{results['host']['platform']}`; Python `{results['host']['python']}`; {results['host']['logical_cpus']} logical CPUs",
            f"- Schedule: {results['settings']['warmups']} discarded warmup + {results['settings']['rounds']} measured rounds × 3 families × 4 topologies",
            "- Exactness: 96/96 total round trips exact; 84/84 measured",
            "- Complete frames: 3,523,721 bytes aggregate, identical for every topology",
            "- Raw trials, order, worker CPU, RSS, source/frame hashes, load averages, source hashes, and native-library hash: [`results.json`](results.json)",
            "- Frozen protocol: [`2026-07-17-clue-jls2-decode-scheduling-protocol.md`](../../docs/benchmarks/2026-07-17-clue-jls2-decode-scheduling-protocol.md)",
            "",
            "Claim ceiling: **development-only decode-scheduling evidence on the three frozen CLUE-LDS development ranges.** The CLUE public-validation ranges remain unmaterialized and unopened. This result is not public validation, private holdout, independent reproduction, universal, market-leading, world-best, or state-of-the-art evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    rows = derive(results)
    validate(results, rows)
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.results, args.output / "results.json")
    write_text(args.output / "README.md", render(results, rows))
    artifacts = {
        name: sha256_file(args.output / name) for name in ("results.json", "README.md")
    }
    receipt = {
        "schema_version": 1,
        "name": "clue-jls2-decode-scheduling-v1-receipt",
        "status": "rejected",
        "benchmark_commit": results["git"]["commit"],
        "selected_variant": None,
        "retained_variant": BASELINE,
        "baseline_parent_median_mbps": next(
            row["parent_median_mbps"] for row in rows if row["variant"] == BASELINE
        ),
        "baseline_worker_median_mbps": next(
            row["worker_median_mbps"] for row in rows if row["variant"] == BASELINE
        ),
        "baseline_worker_minimum_mbps": next(
            row["worker_minimum_mbps"] for row in rows if row["variant"] == BASELINE
        ),
        "artifacts": artifacts,
        "publisher_source": "scripts/publish-clue-jls2-decode-scheduling.py",
        "publisher_source_sha256": sha256_file(Path(__file__)),
        "claim_ceiling": results["claim_ceiling"],
    }
    write_json(args.output / "receipt.json", receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
