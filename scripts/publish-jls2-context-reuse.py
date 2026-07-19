#!/usr/bin/env python3
"""Verify and publish an offline JLS2 context-reuse benchmark result."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "scripts" / "benchmark-jls2-context-reuse.py"
PROTOCOL = ROOT / "docs" / "benchmarks" / "2026-07-18-jls2-context-reuse-protocol.md"
RATIO_EVIDENCE = ROOT / "runs" / "clue-json-log-development-census-v1" / "comparison.json"
PUBLISHER_NAME = "jls2-context-reuse-development-publication-v1"
EXPECTED_RESULT_NAME = "jls2-context-reuse-development-v1"
EXPECTED_CLAIM_SCOPE = "development-only decoder-memory evidence"
EXPECTED_RESULT_CLAIM_CEILING = (
    "Development-only decoder-memory evidence; consumed public-validation "
    "ranges and the private holdout were not used."
)
EXPECTED_ITEM_IDS = (
    "clue-early-development",
    "clue-middle-development",
    "clue-late-development",
    "jls2-context-stress-256",
)
EXPECTED_RATIO_EVIDENCE_SHA256 = (
    "66d8986ae2bf6beb2cc2a4fd4280f9dfe34f013f947e9097c80353853bf74a36"
)
RATIO_CONTEXT = {
    "scope": "unchanged immutable CLUE-LDS development census",
    "original_bytes": 203_578_132,
    "jls2_bytes": 3_523_721,
    "jls2_ratio": 57.77362396171547,
    "strongest_standard": "brotli-11",
    "strongest_standard_bytes": 4_301_558,
    "gain_vs_strongest_standard_percent": 18.082680740327106,
}
PUBLIC_VALIDATION_BOUNDARY = {
    "status": "immutable_not_passed",
    "source_bytes": 96_934_483,
    "jls2_bytes": 489_591,
    "gain_vs_strongest_eligible_percent": 52.9687,
    "standalone_decode_peak_rss_bytes": 651_517_952,
    "frozen_peak_rss_limit_bytes": 512 * 1024 * 1024,
    "ranges": "consumed and never eligible for tuning or rerun",
    "effect_of_this_result": "none; a development result cannot rewrite the first score",
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
ARTIFACT_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def load_benchmark() -> Any:
    spec = importlib.util.spec_from_file_location("jls2_context_reuse", BENCHMARK)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen context-reuse benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FROZEN_BENCHMARK = load_benchmark()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON object key is not allowed: {key}")
        output[key] = value
    return output


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_json_constant,
        object_pairs_hook=reject_duplicate_keys,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def require_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError(f"{label} must be a{' nonempty' if nonempty else ''} string")
    return value


def require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return value


def require_number(
    value: Any, label: str, *, positive: bool = False
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{label} must be finite{' and positive' if positive else ''}")
    return number


def require_sha256(value: Any, label: str) -> str:
    digest = require_string(value, label)
    if SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def require_git_commit(value: Any, label: str) -> str:
    commit = require_string(value, label)
    if GIT_COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError(f"{label} must be a lowercase 40-character Git commit")
    return commit


def require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(keys - set(value))
    if missing:
        raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")
    unexpected = sorted(set(value) - keys)
    if unexpected:
        raise ValueError(f"{label} has unexpected fields: {', '.join(unexpected)}")


def validate_ratio_context() -> None:
    if sha256_file(RATIO_EVIDENCE) != EXPECTED_RATIO_EVIDENCE_SHA256:
        raise ValueError("immutable JLS2 development ratio evidence drifted")
    evidence = load_json(RATIO_EVIDENCE)
    jls2 = require_mapping(evidence.get("jls2"), "ratio evidence jls2")
    if (
        jls2.get("original_bytes") != RATIO_CONTEXT["original_bytes"]
        or jls2.get("compressed_bytes") != RATIO_CONTEXT["jls2_bytes"]
        or not math.isclose(
            float(jls2.get("ratio", -1)),
            float(RATIO_CONTEXT["jls2_ratio"]),
            rel_tol=0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("immutable JLS2 development ratio totals drifted")
    rows = require_list(evidence.get("comparison_rows"), "ratio comparison rows")
    brotli = next(
        (row for row in rows if isinstance(row, dict) and row.get("codec_id") == "brotli-11"),
        None,
    )
    if not isinstance(brotli, dict) or brotli.get("compressed_bytes") != RATIO_CONTEXT[
        "strongest_standard_bytes"
    ]:
        raise ValueError("immutable Brotli-11 development ratio context drifted")


def validate_host(host: dict[str, Any], expected_platform: str) -> None:
    require_keys(
        host,
        {"platform", "python", "logical_cpus", "load_average_after"},
        "host",
    )
    if require_string(host["platform"], "host platform") != expected_platform:
        raise ValueError("supplied host platform does not match the raw result")
    require_string(host["python"], "host python")
    require_int(host["logical_cpus"], "host logical CPUs", minimum=1)
    load = require_list(host["load_average_after"], "host load average")
    if len(load) != 3:
        raise ValueError("host load average must contain three values")
    for index, value in enumerate(load):
        require_number(value, f"host load average {index}")


def validate_trial(
    trial: dict[str, Any], binaries: dict[str, Any], index: int
) -> tuple[str, str, int, bool]:
    label = f"trial {index}"
    require_keys(
        trial,
        {
            "variant",
            "item_id",
            "source_bytes",
            "source_sha256",
            "encoded_bytes",
            "encoded_sha256",
            "command",
            "wall_ns",
            "mbps",
            "peak_rss_bytes",
            "returncode",
            "stdout",
            "stderr",
            "exact",
            "round",
            "warmup",
        },
        label,
    )
    variant = require_string(trial["variant"], f"{label} variant")
    if variant not in FROZEN_BENCHMARK.VARIANTS:
        raise ValueError(f"{label} has an unexpected variant")
    item_id = require_string(trial["item_id"], f"{label} item ID")
    if item_id not in EXPECTED_ITEM_IDS:
        raise ValueError(f"{label} has an unexpected item ID")
    source_bytes = require_int(trial["source_bytes"], f"{label} source bytes", minimum=1)
    require_sha256(trial["source_sha256"], f"{label} source SHA-256")
    require_int(trial["encoded_bytes"], f"{label} encoded bytes", minimum=1)
    require_sha256(trial["encoded_sha256"], f"{label} encoded SHA-256")
    wall_ns = require_int(trial["wall_ns"], f"{label} wall ns", minimum=1)
    mbps = require_number(trial["mbps"], f"{label} MB/s", positive=True)
    expected_mbps = source_bytes / wall_ns * 1000.0
    if not math.isclose(mbps, expected_mbps, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"{label} MB/s does not match source bytes and wall time")
    require_int(trial["peak_rss_bytes"], f"{label} peak RSS", minimum=1)
    if require_int(trial["returncode"], f"{label} return code") != 0:
        raise ValueError(f"{label} did not exit successfully")
    require_string(trial["stdout"], f"{label} stdout", nonempty=False)
    require_string(trial["stderr"], f"{label} stderr", nonempty=False)
    if trial["exact"] is not True:
        raise ValueError(f"{label} is not exact")
    round_number = require_int(trial["round"], f"{label} round", minimum=0)
    if not isinstance(trial["warmup"], bool):
        raise ValueError(f"{label} warmup must be boolean")
    warmup = trial["warmup"]
    command = require_list(trial["command"], f"{label} command")
    if not all(isinstance(part, str) and part for part in command):
        raise ValueError(f"{label} command must contain nonempty strings")
    binary = require_mapping(binaries[variant], f"{variant} binary")
    expected_prefix = [binary["path"], "decompress"]
    if command[:2] != expected_prefix or len(command) != 6:
        raise ValueError(f"{label} command does not use the bound decoder interface")
    if command[3] != "-o" or command[5] != "--force":
        raise ValueError(f"{label} command does not use atomic forced publication")
    return variant, item_id, round_number, warmup


def frame_identities(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities = []
    for item_id in EXPECTED_ITEM_IDS:
        rows = [row for row in trials if row["item_id"] == item_id]
        values = {
            (
                row["source_bytes"],
                row["source_sha256"],
                row["encoded_bytes"],
                row["encoded_sha256"],
                row["command"][2],
            )
            for row in rows
        }
        if len(values) != 1:
            raise ValueError(f"source or exact same-frame identity drift: {item_id}")
        source_bytes, source_sha256, encoded_bytes, encoded_sha256, frame_path = values.pop()
        identities.append(
            {
                "item_id": item_id,
                "source_bytes": source_bytes,
                "source_sha256": source_sha256,
                "encoded_bytes": encoded_bytes,
                "encoded_sha256": encoded_sha256,
                "frame_path_recorded": frame_path,
                "scheduled_decodes": len(rows),
                "same_frame_for_both_variants": True,
            }
        )
    return identities


def validate_results(
    results: dict[str, Any],
    *,
    candidate_commit: str,
    baseline_binary_sha256: str,
    candidate_binary_sha256: str,
    host_platform: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    require_keys(
        results,
        {
            "schema_version",
            "name",
            "claim_scope",
            "baseline_commit",
            "candidate",
            "created_at_epoch_seconds",
            "host",
            "binaries",
            "settings",
            "trials",
            "summary",
            "claim_ceiling",
        },
        "result",
    )
    if (
        require_int(results["schema_version"], "result schema version") != 1
        or results["name"] != EXPECTED_RESULT_NAME
    ):
        raise ValueError("unexpected context-reuse result schema or identity")
    if results["claim_scope"] != EXPECTED_CLAIM_SCOPE:
        raise ValueError("context-reuse claim scope drifted")
    if results["claim_ceiling"] != EXPECTED_RESULT_CLAIM_CEILING:
        raise ValueError("context-reuse claim ceiling drifted")
    if results["baseline_commit"] != FROZEN_BENCHMARK.BASELINE_COMMIT:
        raise ValueError("frozen baseline commit drifted")
    require_int(results["created_at_epoch_seconds"], "result creation time", minimum=1)
    candidate = require_mapping(results["candidate"], "candidate")
    require_keys(candidate, {"commit", "dirty"}, "candidate")
    if candidate["commit"] != candidate_commit or candidate["dirty"] is not False:
        raise ValueError("supplied candidate commit does not match a clean raw result")
    require_git_commit(candidate_commit, "candidate commit")
    host = require_mapping(results["host"], "host")
    validate_host(host, host_platform)
    binaries = require_mapping(results["binaries"], "binaries")
    if set(binaries) != set(FROZEN_BENCHMARK.VARIANTS):
        raise ValueError("binary variant roster drifted")
    supplied_binary_hashes = {
        "baseline": require_sha256(baseline_binary_sha256, "baseline binary SHA-256"),
        "candidate": require_sha256(candidate_binary_sha256, "candidate binary SHA-256"),
    }
    for variant, expected_digest in supplied_binary_hashes.items():
        binary = require_mapping(binaries[variant], f"{variant} binary")
        require_keys(binary, {"path", "sha256"}, f"{variant} binary")
        require_string(binary["path"], f"{variant} binary path")
        observed = require_sha256(binary["sha256"], f"{variant} binary SHA-256")
        if observed != expected_digest:
            raise ValueError(f"supplied {variant} binary digest does not match raw result")
    settings = require_mapping(results["settings"], "settings")
    expected_settings = {
        "rounds": FROZEN_BENCHMARK.ROUNDS,
        "warmups": 1,
        "stress_id": FROZEN_BENCHMARK.STRESS_ID,
        "stress_records": FROZEN_BENCHMARK.STRESS_RECORDS,
    }
    require_keys(settings, set(expected_settings), "settings")
    observed_settings = {
        "rounds": require_int(settings["rounds"], "settings rounds", minimum=1),
        "warmups": require_int(settings["warmups"], "settings warmups", minimum=1),
        "stress_id": require_string(settings["stress_id"], "settings stress ID"),
        "stress_records": require_int(
            settings["stress_records"], "settings stress records", minimum=1
        ),
    }
    if observed_settings != expected_settings:
        raise ValueError("frozen context-reuse settings drifted")
    trials = require_list(results["trials"], "trials")
    if len(trials) != 64:
        raise ValueError("context-reuse result must contain exactly 64 trials")
    observed_schedule: list[tuple[int, bool, str, str]] = []
    for index, raw_trial in enumerate(trials):
        trial = require_mapping(raw_trial, f"trial {index}")
        variant, item_id, round_number, warmup = validate_trial(trial, binaries, index)
        if warmup != (round_number == 0):
            raise ValueError(f"trial {index} has inconsistent warmup/round fields")
        if round_number > FROZEN_BENCHMARK.ROUNDS:
            raise ValueError(f"trial {index} exceeds the frozen round count")
        observed_schedule.append((round_number, warmup, item_id, variant))
    expected_schedule = [
        (0, True, item_id, variant)
        for item_id in EXPECTED_ITEM_IDS
        for variant in FROZEN_BENCHMARK.VARIANTS
    ]
    for round_number, rows in enumerate(
        FROZEN_BENCHMARK.schedule(
            list(EXPECTED_ITEM_IDS), FROZEN_BENCHMARK.ROUNDS
        ),
        start=1,
    ):
        expected_schedule.extend(
            (round_number, False, item_id, variant) for item_id, variant in rows
        )
    if observed_schedule != expected_schedule:
        raise ValueError("context-reuse trial order does not match the frozen schedule")
    identities = frame_identities(trials)
    recomputed = FROZEN_BENCHMARK.summarize(trials, FROZEN_BENCHMARK.ROUNDS)
    stored_summary = require_mapping(results["summary"], "summary")
    if stored_summary != recomputed:
        raise ValueError("stored summary does not match the frozen benchmark recomputation")
    expected_gates = {
        "all_exact",
        "candidate_peak_rss_at_or_below_448_mib",
        "stress_peak_rss_reduction_at_least_20_percent",
        "no_clue_family_peak_rss_regression",
        "candidate_median_throughput_at_least_95_percent_of_baseline",
        "all_candidate_item_medians_at_or_above_250_mbps",
        "all_candidate_rounds_at_or_above_225_mbps",
        "candidate_cv_at_or_below_20_percent",
    }
    if set(recomputed["gates"]) != expected_gates:
        raise ValueError("frozen context-reuse gate roster drifted")
    return recomputed, identities


def variant(summary: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in summary["variants"] if row["variant"] == name)


def comparison_payload(
    results: dict[str, Any],
    summary: dict[str, Any],
    identities: list[dict[str, Any]],
) -> dict[str, Any]:
    decision = "passed" if summary["passed"] else "rejected"
    return {
        "schema_version": 1,
        "name": PUBLISHER_NAME,
        "decision": decision,
        "selected_variant": "candidate" if summary["passed"] else None,
        "retained_variant": "candidate" if summary["passed"] else "baseline",
        "claim_scope": EXPECTED_CLAIM_SCOPE,
        "claim_ceiling": EXPECTED_RESULT_CLAIM_CEILING,
        "baseline_commit": results["baseline_commit"],
        "candidate_commit": results["candidate"]["commit"],
        "host": results["host"],
        "schedule": {
            "total_trials": 64,
            "warmup_trials": 8,
            "measured_trials": 56,
            "rounds": 7,
            "items": 4,
            "variants": list(FROZEN_BENCHMARK.VARIANTS),
        },
        "frame_identities": identities,
        "summary": summary,
        "unchanged_ratio_context": RATIO_CONTEXT,
        "immutable_public_validation_boundary": PUBLIC_VALIDATION_BOUNDARY,
    }


def render_readme(
    comparison: dict[str, Any],
    *,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_run_url: str,
    workflow_run_conclusion: str,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
) -> str:
    summary = comparison["summary"]
    baseline = variant(summary, "baseline")
    candidate = variant(summary, "candidate")
    passed = comparison["decision"] == "passed"
    if passed:
        outcome = (
            "**Outcome: reusable Zstandard decode contexts passed the frozen "
            "development gate.** The candidate is retained for a separately frozen "
            "future validation gate."
        )
    else:
        failed = [name for name, value in summary["gates"].items() if not value]
        outcome = (
            "**Outcome: reusable Zstandard decode contexts were rejected by the "
            "frozen development gate; the baseline remains unchanged.** Failed gates: "
            + ", ".join(f"`{name}`" for name in failed)
            + "."
        )
    lines = [
        "# JLS2 reusable decode-context development result",
        "",
        outcome,
        "",
        "![JLS2 reusable decode-context comparison](comparison.svg)",
        "",
        "## Frozen A/B result",
        "",
        "Both standalone binaries decoded the exact same complete JLS2 frame for each input. Parent-wall timing includes cold process startup, complete file I/O, integrity verification, and atomic output publication.",
        "",
        "| Variant | Median aggregate | Minimum aggregate | CV | Peak RSS | Exact | Selected |",
        "| --- | ---: | ---: | ---: | ---: | :---: | :---: |",
    ]
    for row in (baseline, candidate):
        selected = comparison["selected_variant"] == row["variant"]
        lines.append(
            "| {} | {:.2f} MB/s | {:.2f} MB/s | {:.2f}% | {:.1f} MiB | {} | {} |".format(
                row["variant"],
                row["median_aggregate_mbps"],
                row["minimum_aggregate_mbps"],
                row["aggregate_cv_percent"],
                row["peak_rss_bytes"] / (1024 * 1024),
                "yes" if row["all_exact"] else "no",
                "yes" if selected else "no",
            )
        )
    baseline_items = {row["item_id"]: row for row in baseline["item_rows"]}
    candidate_items = {row["item_id"]: row for row in candidate["item_rows"]}
    lines.extend(
        [
            "",
            "## Per-input memory",
            "",
            "| Development input | Baseline peak | Candidate peak | Change | Candidate median |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item_id in EXPECTED_ITEM_IDS:
        old = baseline_items[item_id]
        new = candidate_items[item_id]
        change = (new["peak_rss_bytes"] / old["peak_rss_bytes"] - 1) * 100
        lines.append(
            f"| `{item_id}` | {old['peak_rss_bytes'] / (1024 * 1024):.1f} MiB | "
            f"{new['peak_rss_bytes'] / (1024 * 1024):.1f} MiB | {change:+.2f}% | "
            f"{new['median_mbps']:.2f} MB/s |"
        )
    lines.extend(["", "## Frozen gates", ""])
    for name, value in summary["gates"].items():
        lines.append(f"- {'✅' if value else '❌'} `{name}`")
    ratio = comparison["unchanged_ratio_context"]
    boundary = comparison["immutable_public_validation_boundary"]
    lines.extend(
        [
            "",
            "## Unchanged ratio context",
            "",
            f"No compression bytes were produced or changed by this decoder-only experiment. In the immutable development census, JLS2 encoded {ratio['original_bytes']:,} source bytes to **{ratio['jls2_bytes']:,} bytes** ({ratio['jls2_ratio']:.2f}x), **{ratio['gain_vs_strongest_standard_percent']:.2f}% smaller** than {ratio['strongest_standard']} at {ratio['strongest_standard_bytes']:,} bytes.",
            "",
            "## Immutable public-validation boundary",
            "",
            f"The first CLUE-LDS public-validation result remains an immutable **no-pass**. Its standalone decoder used **{boundary['standalone_decode_peak_rss_bytes'] / (1024 * 1024):.1f} MiB** against the frozen **{boundary['frozen_peak_rss_limit_bytes'] / (1024 * 1024):.0f} MiB** cap. Both ranges are consumed and will never be tuned on or rerun. This development result cannot retroactively alter that decision, even if the context-reuse candidate passed here.",
            "",
            "## Provenance",
            "",
            f"- Candidate commit: `{comparison['candidate_commit']}`",
            f"- Baseline commit: `{comparison['baseline_commit']}`",
            f"- Host: `{comparison['host']['platform']}`; Python `{comparison['host']['python']}`",
            "- Schedule: 8 discarded warmups + 56 measured trials = 64 exact scheduled decodes",
            f"- Workflow: [run {workflow_run_id}, attempt {workflow_run_attempt}]({workflow_run_url}) (`{workflow_run_conclusion}`)",
            f"- Uploaded artifact: ID `{artifact_id}`, `{artifact_name}`, `{artifact_digest}`",
            "- Raw result, benchmark log, runner provenance, comparison, visualization, and receipt are retained together in this publication directory.",
            "",
            "## Evidence boundary",
            "",
            "Claim ceiling: **development-only decoder-memory evidence.** This is not public validation, private-holdout evidence, independent reproduction, or a universal, market-leading, world-best, or state-of-the-art result.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    baseline = variant(summary, "baseline")
    candidate = variant(summary, "candidate")
    baseline_items = {row["item_id"]: row for row in baseline["item_rows"]}
    candidate_items = {row["item_id"]: row for row in candidate["item_rows"]}
    width = 1240
    height = 720
    left = 250
    plot_width = 850
    max_rss = max(
        512 * 1024 * 1024,
        baseline["peak_rss_bytes"],
        candidate["peak_rss_bytes"],
    )
    axis_max_mib = math.ceil(max_rss / (1024 * 1024) / 64) * 64
    gate_x = left + 448 / axis_max_mib * plot_width
    status = "PASSED" if summary["passed"] else "REJECTED"
    status_class = "pass" if summary["passed"] else "fail"
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">JLS2 reusable decode-context development comparison</title>',
        f'<desc id="desc">The frozen reusable Zstandard context experiment was {status.lower()}. The chart compares cold-process peak resident memory for the baseline and candidate across four development inputs.</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;fill:#24292f}.title{font-size:24px;font-weight:700}.subtitle,.axis,.note{font-size:13px;fill:#57606a}.section{font-size:17px;font-weight:600}.label{font-size:14px}.value{font-size:13px}.baseline{fill:#8c959f}.candidate{fill:#0969da}.pass{fill:#1a7f37}.fail{fill:#cf222e}.grid{stroke:#d0d7de}.gate{stroke:#bf8700;stroke-width:2;stroke-dasharray:6 5}.card{fill:#f6f8fa;stroke:#d0d7de}.divider{stroke:#d0d7de}",
        "@media(prefers-color-scheme:dark){text{fill:#f0f6fc}.subtitle,.axis,.note{fill:#8c959f}.baseline{fill:#6e7681}.candidate{fill:#58a6ff}.pass{fill:#3fb950}.fail{fill:#f85149}.grid,.divider{stroke:#30363d}.gate{stroke:#d29922}.card{fill:#161b22;stroke:#30363d}}",
        "</style>",
        '<text class="title" x="24" y="38">Reusable JLS2 decode contexts: frozen development gate</text>',
        f'<text class="{status_class}" x="1090" y="38" text-anchor="end" font-size="19" font-weight="700">{status}</text>',
        '<text class="subtitle" x="24" y="64">Cold standalone processes · identical complete frames · 8 warmups + 56 measured decodes</text>',
        '<text class="section" x="24" y="104">Per-input peak RSS (MiB, lower is better)</text>',
    ]
    top = 132
    for tick in range(0, axis_max_mib + 1, 64):
        x = left + tick / axis_max_mib * plot_width
        output.extend(
            [
                f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + 300}"/>',
                f'<text class="axis" x="{x:.1f}" y="{top + 320}" text-anchor="middle">{tick}</text>',
            ]
        )
    output.extend(
        [
            f'<line class="gate" x1="{gate_x:.1f}" y1="{top - 12}" x2="{gate_x:.1f}" y2="{top + 300}"/>',
            f'<text class="axis" x="{gate_x:.1f}" y="{top - 18}" text-anchor="middle">448 MiB frozen gate</text>',
        ]
    )
    for index, item_id in enumerate(EXPECTED_ITEM_IDS):
        y = top + index * 72 + 12
        old_mib = baseline_items[item_id]["peak_rss_bytes"] / (1024 * 1024)
        new_mib = candidate_items[item_id]["peak_rss_bytes"] / (1024 * 1024)
        output.extend(
            [
                f'<text class="label" x="24" y="{y + 21}">{html.escape(item_id)}</text>',
                f'<rect class="baseline" x="{left}" y="{y}" width="{old_mib / axis_max_mib * plot_width:.1f}" height="20" rx="3"/>',
                f'<text class="value" x="{left + old_mib / axis_max_mib * plot_width + 8:.1f}" y="{y + 15}">{old_mib:.1f}</text>',
                f'<rect class="candidate" x="{left}" y="{y + 26}" width="{new_mib / axis_max_mib * plot_width:.1f}" height="20" rx="3"/>',
                f'<text class="value" x="{left + new_mib / axis_max_mib * plot_width + 8:.1f}" y="{y + 41}">{new_mib:.1f}</text>',
            ]
        )
    cards_y = 492
    cards = (
        ("Baseline median", f"{baseline['median_aggregate_mbps']:.2f} MB/s"),
        ("Candidate median", f"{candidate['median_aggregate_mbps']:.2f} MB/s"),
        ("Stress RSS reduction", f"{summary['stress_peak_rss_reduction_percent']:.2f}%"),
        ("Frozen gates", f"{sum(summary['gates'].values())}/{len(summary['gates'])}"),
    )
    for index, (label, value) in enumerate(cards):
        x = 24 + index * 300
        output.extend(
            [
                f'<rect class="card" x="{x}" y="{cards_y}" width="276" height="72" rx="6"/>',
                f'<text class="note" x="{x + 14}" y="{cards_y + 25}">{label}</text>',
                f'<text class="section" x="{x + 14}" y="{cards_y + 52}">{value}</text>',
            ]
        )
    ratio = comparison["unchanged_ratio_context"]
    output.extend(
        [
            '<line class="divider" x1="24" y1="598" x2="1216" y2="598"/>',
            f'<text class="section" x="24" y="630">Unchanged ratio context: JLS2 {ratio["jls2_bytes"]:,} bytes · {ratio["jls2_ratio"]:.2f}x · {ratio["gain_vs_strongest_standard_percent"]:.2f}% smaller than Brotli-11</text>',
            '<text class="note" x="24" y="660">Immutable public-validation no-pass remains 621.3 MiB vs 512 MiB; consumed ranges were not used and can never be rerun.</text>',
            '<text class="note" x="24" y="688">Development-only decoder-memory evidence · not public validation, private holdout, independent reproduction, or state of the art</text>',
            '</svg>',
        ]
    )
    return "\n".join(output) + "\n"


def validate_publication_metadata(
    *,
    summary: dict[str, Any],
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_run_url: str,
    workflow_run_conclusion: str,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
) -> None:
    require_int(workflow_run_id, "workflow run ID", minimum=1)
    require_int(workflow_run_attempt, "workflow run attempt", minimum=1)
    require_int(artifact_id, "artifact ID", minimum=1)
    require_string(workflow_run_url, "workflow run URL")
    require_string(workflow_run_conclusion, "workflow run conclusion")
    require_string(artifact_name, "artifact name")
    require_string(artifact_digest, "artifact digest")
    expected_url = (
        "https://github.com/Atomics-hub/compression-lab/actions/runs/"
        f"{workflow_run_id}"
    )
    if workflow_run_url != expected_url:
        raise ValueError("workflow URL does not match the supplied run ID")
    expected_conclusion = "success" if summary["passed"] else "failure"
    if workflow_run_conclusion != expected_conclusion:
        raise ValueError(
            f"workflow conclusion must be {expected_conclusion} for this decision"
        )
    if artifact_name != f"jls2-context-reuse-{workflow_run_id}":
        raise ValueError("artifact name does not match the frozen workflow name")
    if ARTIFACT_DIGEST_PATTERN.fullmatch(artifact_digest) is None:
        raise ValueError("artifact digest must be a lowercase sha256: digest")


def publish(
    *,
    results_path: Path,
    provenance_path: Path,
    benchmark_log_path: Path,
    output: Path,
    candidate_commit: str,
    baseline_binary_sha256: str,
    candidate_binary_sha256: str,
    host_platform: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_run_url: str,
    workflow_run_conclusion: str,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
) -> dict[str, Any]:
    for path, label in (
        (results_path, "raw results"),
        (provenance_path, "runner provenance"),
        (benchmark_log_path, "benchmark log"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be a regular non-symlink file")
    if provenance_path.stat().st_size == 0 or benchmark_log_path.stat().st_size == 0:
        raise ValueError("runner provenance and benchmark log must be nonempty")
    if output.exists():
        raise ValueError("refusing to replace an existing publication directory")
    validate_ratio_context()
    results = load_json(results_path)
    summary, identities = validate_results(
        results,
        candidate_commit=candidate_commit,
        baseline_binary_sha256=baseline_binary_sha256,
        candidate_binary_sha256=candidate_binary_sha256,
        host_platform=host_platform,
    )
    validate_publication_metadata(
        summary=summary,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        workflow_run_url=workflow_run_url,
        workflow_run_conclusion=workflow_run_conclusion,
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        artifact_digest=artifact_digest,
    )
    comparison = comparison_payload(results, summary, identities)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".partial", dir=output.parent)
    )
    try:
        shutil.copyfile(results_path, staging / "results.json")
        shutil.copyfile(provenance_path, staging / "provenance.txt")
        shutil.copyfile(benchmark_log_path, staging / "benchmark.log")
        write_json(staging / "comparison.json", comparison)
        write_text(staging / "comparison.svg", render_svg(comparison))
        write_text(
            staging / "README.md",
            render_readme(
                comparison,
                workflow_run_id=workflow_run_id,
                workflow_run_attempt=workflow_run_attempt,
                workflow_run_url=workflow_run_url,
                workflow_run_conclusion=workflow_run_conclusion,
                artifact_id=artifact_id,
                artifact_name=artifact_name,
                artifact_digest=artifact_digest,
            ),
        )
        artifact_files = (
            "results.json",
            "provenance.txt",
            "benchmark.log",
            "comparison.json",
            "comparison.svg",
            "README.md",
        )
        artifacts = {name: sha256_file(staging / name) for name in artifact_files}
        receipt = {
            "schema_version": 1,
            "name": f"{PUBLISHER_NAME}-receipt",
            "decision": comparison["decision"],
            "selected_variant": comparison["selected_variant"],
            "retained_variant": comparison["retained_variant"],
            "baseline_commit": results["baseline_commit"],
            "candidate_commit": candidate_commit,
            "binaries": {
                "baseline_sha256": baseline_binary_sha256,
                "candidate_sha256": candidate_binary_sha256,
            },
            "host": results["host"],
            "workflow_run": {
                "run_id": workflow_run_id,
                "attempt": workflow_run_attempt,
                "url": workflow_run_url,
                "conclusion": workflow_run_conclusion,
            },
            "uploaded_artifact": {
                "id": artifact_id,
                "name": artifact_name,
                "digest": artifact_digest,
            },
            "source_inputs": {
                "results_sha256": sha256_file(results_path),
                "provenance_sha256": sha256_file(provenance_path),
                "benchmark_log_sha256": sha256_file(benchmark_log_path),
                "ratio_evidence_sha256": EXPECTED_RATIO_EVIDENCE_SHA256,
            },
            "verification": {
                "raw_schema_valid": True,
                "frozen_summary_recomputed": True,
                "trial_schedule_exact": True,
                "scheduled_trials": 64,
                "same_frame_identities": identities,
                "all_outputs_exact": True,
            },
            "publication_sources": {
                "benchmark": {
                    "path": BENCHMARK.relative_to(ROOT).as_posix(),
                    "sha256": sha256_file(BENCHMARK),
                },
                "protocol": {
                    "path": PROTOCOL.relative_to(ROOT).as_posix(),
                    "sha256": sha256_file(PROTOCOL),
                },
                "publisher": {
                    "path": Path(__file__).relative_to(ROOT).as_posix(),
                    "sha256": sha256_file(Path(__file__)),
                },
            },
            "artifacts": artifacts,
            "unchanged_ratio_context": RATIO_CONTEXT,
            "immutable_public_validation_boundary": PUBLIC_VALIDATION_BOUNDARY,
            "claim_ceiling": EXPECTED_RESULT_CLAIM_CEILING,
        }
        write_json(staging / "receipt.json", receipt)
        os.rename(staging, output)
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--benchmark-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--baseline-binary-sha256", required=True)
    parser.add_argument("--candidate-binary-sha256", required=True)
    parser.add_argument("--host-platform", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--workflow-run-url", required=True)
    parser.add_argument(
        "--workflow-run-conclusion", choices=("success", "failure"), required=True
    )
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-digest", required=True)
    args = parser.parse_args()
    publish(
        results_path=args.results.resolve(),
        provenance_path=args.provenance.resolve(),
        benchmark_log_path=args.benchmark_log.resolve(),
        output=args.output.resolve(),
        candidate_commit=args.candidate_commit,
        baseline_binary_sha256=args.baseline_binary_sha256,
        candidate_binary_sha256=args.candidate_binary_sha256,
        host_platform=args.host_platform,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        workflow_run_url=args.workflow_run_url,
        workflow_run_conclusion=args.workflow_run_conclusion,
        artifact_id=args.artifact_id,
        artifact_name=args.artifact_name,
        artifact_digest=args.artifact_digest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
