#!/usr/bin/env python3
"""Strictly verify and publish the frozen JLS2 inline-single-worker A2 run."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "benchmark-jls2-context-reuse-inline-single-worker-a2.py"
RUNNER_SHA256 = "e5c538910b48afad74d930ce557fa6269f68e8e390c9bd6d02502c0f227ab6b4"
COMMON_PUBLISHER = ROOT / "scripts" / "publish-jls2-context-reuse.py"
COMMON_PUBLISHER_SHA256 = (
    "a83ec27bcce4c6b0a98866441b7fa01a1b37ff7a385111c02eedc70958579a76"
)
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-18-jls2-context-reuse-inline-single-worker-a2-protocol.md"
)
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "jls2-context-reuse-inline-single-worker-a2.yml"
)
PROTOCOL_SHA256 = "36edb0dc43cac1dd5917063fffcc4c744c4f4df141646d6e0c3550a68ce5b60e"
WORKFLOW_SHA256 = "aa9c1cb696750a6fd546da7c5767f97fc1726d721b42eedefb298f3f83884f27"
PUBLISHER_NAME = "jls2-context-reuse-inline-single-worker-a2-publication-v1"
EXPECTED_WORKFLOW_RUN_ID = 29_676_577_151
PRE_A1_PRODUCT_BASELINE_COMMIT = "7b081f6f11c2561c36289cfc57f7d3715ab8c594"
A1_CONTEXT = {
    "candidate_commit": "131547f35747cc0ff9dedbdef66d8a9516a7464f",
    "development_peak_rss_mib_display": 625.2,
    "frozen_peak_rss_limit_mib": 448.0,
    "decision": "rejected; the pre-A1 product baseline remained retained",
    "effect_on_a2": "A2 measures marginally against A1 but does not make A1 the product baseline",
}
EXPECTED_ITEM_IDS = (
    "clue-early-development",
    "clue-middle-development",
    "clue-late-development",
    "jls2-context-stress-256",
)
ARTIFACT_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


for frozen_path, expected_digest in (
    (COMMON_PUBLISHER, COMMON_PUBLISHER_SHA256),
    (RUNNER, RUNNER_SHA256),
    (PROTOCOL, PROTOCOL_SHA256),
    (WORKFLOW, WORKFLOW_SHA256),
):
    if sha256_file(frozen_path) != expected_digest:
        raise RuntimeError(f"frozen A2 publication dependency drifted: {frozen_path}")
COMMON = load_module(COMMON_PUBLISHER, "jls2_context_common_publication")
A2 = load_module(RUNNER, "jls2_context_inline_worker_a2")


def validate_host(host: dict[str, Any], expected_platform: str) -> None:
    COMMON.require_keys(
        host,
        {"platform", "python", "rustc", "logical_cpus", "load_average_after"},
        "host",
    )
    if COMMON.require_string(host["platform"], "host platform") != expected_platform:
        raise ValueError("supplied host platform does not match the raw A2 result")
    COMMON.require_string(host["python"], "host python")
    COMMON.require_string(host["rustc"], "host rustc")
    COMMON.require_int(host["logical_cpus"], "host logical CPUs", minimum=1)
    load = COMMON.require_list(host["load_average_after"], "host load average")
    if len(load) != 3:
        raise ValueError("host load average must contain exactly three values")
    for index, value in enumerate(load):
        COMMON.require_number(value, f"host load average {index}")


def validate_trial(
    trial: dict[str, Any], binaries: dict[str, Any], index: int
) -> tuple[int, bool, str, str]:
    label = f"trial {index}"
    COMMON.require_keys(
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
    variant = COMMON.require_string(trial["variant"], f"{label} variant")
    if variant not in A2.VARIANTS:
        raise ValueError(f"{label} has an unexpected variant")
    item_id = COMMON.require_string(trial["item_id"], f"{label} item ID")
    if item_id not in EXPECTED_ITEM_IDS:
        raise ValueError(f"{label} has an unexpected input")
    source_bytes = COMMON.require_int(
        trial["source_bytes"], f"{label} source bytes", minimum=1
    )
    COMMON.require_sha256(trial["source_sha256"], f"{label} source SHA-256")
    COMMON.require_int(trial["encoded_bytes"], f"{label} frame bytes", minimum=1)
    COMMON.require_sha256(trial["encoded_sha256"], f"{label} frame SHA-256")
    wall_ns = COMMON.require_int(trial["wall_ns"], f"{label} wall ns", minimum=1)
    mbps = COMMON.require_number(trial["mbps"], f"{label} MB/s", positive=True)
    if not math.isclose(
        mbps, source_bytes / wall_ns * 1000.0, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError(f"{label} MB/s does not match source bytes and wall time")
    COMMON.require_int(trial["peak_rss_bytes"], f"{label} peak RSS", minimum=1)
    if COMMON.require_int(trial["returncode"], f"{label} return code") != 0:
        raise ValueError(f"{label} did not exit successfully")
    COMMON.require_string(trial["stdout"], f"{label} stdout", nonempty=False)
    COMMON.require_string(trial["stderr"], f"{label} stderr", nonempty=False)
    if trial["exact"] is not True:
        raise ValueError(f"{label} restored output is not exact")
    round_number = COMMON.require_int(trial["round"], f"{label} round", minimum=0)
    if not isinstance(trial["warmup"], bool):
        raise ValueError(f"{label} warmup must be boolean")
    warmup = trial["warmup"]
    if warmup != (round_number == 0) or round_number > A2.ROUNDS:
        raise ValueError(f"{label} has inconsistent frozen round fields")
    command = COMMON.require_list(trial["command"], f"{label} command")
    if len(command) != 6 or not all(isinstance(part, str) and part for part in command):
        raise ValueError(f"{label} command must contain six nonempty strings")
    binary = COMMON.require_mapping(binaries[variant], f"{variant} binary")
    if command[:2] != [binary["path"], "decompress"]:
        raise ValueError(f"{label} command does not use the bound decoder")
    if command[3] != "-o" or command[5] != "--force":
        raise ValueError(f"{label} command interface drifted")
    return round_number, warmup, item_id, variant


def expected_schedule() -> list[tuple[int, bool, str, str]]:
    output = [
        (0, True, item_id, variant)
        for item_id in EXPECTED_ITEM_IDS
        for variant in A2.VARIANTS
    ]
    for round_number, rows in enumerate(
        A2.schedule(list(EXPECTED_ITEM_IDS), A2.ROUNDS), start=1
    ):
        output.extend(
            (round_number, False, item_id, variant) for item_id, variant in rows
        )
    return output


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
        source_bytes, source_sha, frame_bytes, frame_sha, frame_path = values.pop()
        identities.append(
            {
                "item_id": item_id,
                "source_bytes": source_bytes,
                "source_sha256": source_sha,
                "encoded_bytes": frame_bytes,
                "encoded_sha256": frame_sha,
                "frame_path_recorded": frame_path,
                "scheduled_decodes": len(rows),
                "same_frame_for_both_variants": True,
            }
        )
    return identities


def validate_settings(settings: dict[str, Any]) -> None:
    expected_support = {
        path.relative_to(ROOT).as_posix(): digest
        for path, digest in A2.FROZEN_SUPPORT_FILES.items()
    }
    COMMON.require_keys(
        settings,
        {
            "rounds",
            "warmups",
            "stress_id",
            "stress_records",
            "stress_rss_reduction_min_percent",
            "a1_runner_sha256",
            "frozen_support_sha256",
        },
        "settings",
    )
    observed = {
        "rounds": COMMON.require_int(settings["rounds"], "settings rounds", minimum=1),
        "warmups": COMMON.require_int(
            settings["warmups"], "settings warmups", minimum=1
        ),
        "stress_id": COMMON.require_string(settings["stress_id"], "settings stress ID"),
        "stress_records": COMMON.require_int(
            settings["stress_records"], "settings stress records", minimum=1
        ),
        "stress_rss_reduction_min_percent": COMMON.require_number(
            settings["stress_rss_reduction_min_percent"],
            "settings stress reduction",
            positive=True,
        ),
        "a1_runner_sha256": COMMON.require_sha256(
            settings["a1_runner_sha256"], "settings A1 runner SHA-256"
        ),
        "frozen_support_sha256": COMMON.require_mapping(
            settings["frozen_support_sha256"], "settings frozen support SHA-256"
        ),
    }
    expected = {
        "rounds": A2.ROUNDS,
        "warmups": 1,
        "stress_id": A2.STRESS_ID,
        "stress_records": A2.STRESS_RECORDS,
        "stress_rss_reduction_min_percent": A2.STRESS_RSS_REDUCTION_MIN_PERCENT,
        "a1_runner_sha256": A2.A1_RUNNER_SHA256,
        "frozen_support_sha256": expected_support,
    }
    if observed != expected:
        raise ValueError("frozen A2 settings or support hashes drifted")


def validate_results(
    results: dict[str, Any],
    *,
    candidate_commit: str,
    baseline_binary_sha256: str,
    candidate_binary_sha256: str,
    host_platform: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    COMMON.require_keys(
        results,
        {
            "schema_version",
            "name",
            "ablation",
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
        "A2 result",
    )
    if COMMON.require_int(results["schema_version"], "A2 schema version") != 1:
        raise ValueError("unexpected A2 schema version")
    if results["name"] != A2.RESULT_NAME:
        raise ValueError("unexpected A2 result identity")
    if results["ablation"] != "A1 reusable contexts plus inline execution when workers == 1":
        raise ValueError("A2 ablation identity drifted")
    if results["claim_scope"] != A2.CLAIM_SCOPE or results["claim_ceiling"] != A2.CLAIM_CEILING:
        raise ValueError("A2 claim boundary drifted")
    if results["baseline_commit"] != A2.BASELINE_COMMIT:
        raise ValueError("A2 result is not bound to exact A1")
    COMMON.require_int(results["created_at_epoch_seconds"], "A2 creation time", minimum=1)
    candidate = COMMON.require_mapping(results["candidate"], "candidate")
    COMMON.require_keys(candidate, {"commit", "dirty"}, "candidate")
    COMMON.require_git_commit(candidate_commit, "candidate commit")
    if candidate_commit == A2.BASELINE_COMMIT:
        raise ValueError("A2 candidate commit must differ from exact A1")
    if candidate != {"commit": candidate_commit, "dirty": False}:
        raise ValueError("supplied candidate commit does not match a clean raw A2 result")
    host = COMMON.require_mapping(results["host"], "host")
    validate_host(host, host_platform)
    binaries = COMMON.require_mapping(results["binaries"], "binaries")
    if set(binaries) != set(A2.VARIANTS):
        raise ValueError("A2 binary roster drifted")
    supplied_hashes = {
        "baseline": COMMON.require_sha256(
            baseline_binary_sha256, "A1 binary SHA-256"
        ),
        "candidate": COMMON.require_sha256(
            candidate_binary_sha256, "A2 binary SHA-256"
        ),
    }
    if supplied_hashes["baseline"] == supplied_hashes["candidate"]:
        raise ValueError("A1 and A2 binaries must have distinct SHA-256 digests")
    for variant, expected_hash in supplied_hashes.items():
        binary = COMMON.require_mapping(binaries[variant], f"{variant} binary")
        COMMON.require_keys(binary, {"path", "sha256"}, f"{variant} binary")
        COMMON.require_string(binary["path"], f"{variant} binary path")
        if COMMON.require_sha256(binary["sha256"], f"{variant} binary SHA-256") != expected_hash:
            raise ValueError(f"supplied {variant} binary digest does not match raw A2")
    validate_settings(COMMON.require_mapping(results["settings"], "settings"))
    raw_trials = COMMON.require_list(results["trials"], "trials")
    if len(raw_trials) != 64:
        raise ValueError("A2 result must contain exactly 64 trials")
    trials = [COMMON.require_mapping(row, f"trial {index}") for index, row in enumerate(raw_trials)]
    observed_schedule = [
        validate_trial(trial, binaries, index) for index, trial in enumerate(trials)
    ]
    if observed_schedule != expected_schedule():
        raise ValueError("A2 trial order does not match the frozen 64-trial schedule")
    identities = frame_identities(trials)
    recomputed = A2.summarize(trials, A2.ROUNDS)
    expected_gates = {
        "all_exact",
        "candidate_peak_rss_at_or_below_448_mib",
        "stress_peak_rss_reduction_at_least_5_percent",
        "no_clue_family_peak_rss_regression",
        "candidate_median_throughput_at_least_95_percent_of_baseline",
        "all_candidate_item_medians_at_or_above_250_mbps",
        "all_candidate_rounds_at_or_above_225_mbps",
        "candidate_cv_at_or_below_20_percent",
    }
    if set(recomputed["gates"]) != expected_gates:
        raise ValueError("frozen A2 gate roster drifted")
    if COMMON.require_mapping(results["summary"], "summary") != recomputed:
        raise ValueError("stored A2 summary does not match frozen recomputation")
    return recomputed, identities


def variant(summary: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in summary["variants"] if row["variant"] == name)


def validate_metadata(
    *,
    passed: bool,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_run_url: str,
    workflow_run_conclusion: str,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
) -> None:
    if COMMON.require_int(workflow_run_id, "workflow run ID", minimum=1) != EXPECTED_WORKFLOW_RUN_ID:
        raise ValueError("workflow run ID is not the frozen hosted A2 run")
    COMMON.require_int(workflow_run_attempt, "workflow run attempt", minimum=1)
    COMMON.require_int(artifact_id, "artifact ID", minimum=1)
    COMMON.require_string(workflow_run_url, "workflow run URL")
    COMMON.require_string(workflow_run_conclusion, "workflow conclusion")
    COMMON.require_string(artifact_name, "artifact name")
    COMMON.require_string(artifact_digest, "artifact digest")
    expected_url = f"https://github.com/Atomics-hub/compression-lab/actions/runs/{workflow_run_id}"
    if workflow_run_url != expected_url:
        raise ValueError("workflow URL does not match the frozen hosted A2 run")
    expected_conclusion = "success" if passed else "failure"
    if workflow_run_conclusion != expected_conclusion:
        raise ValueError(f"workflow conclusion must be {expected_conclusion} for this A2 decision")
    if artifact_name != f"jls2-context-reuse-inline-single-worker-a2-{workflow_run_id}":
        raise ValueError("artifact name does not match the frozen A2 workflow")
    if ARTIFACT_DIGEST_PATTERN.fullmatch(artifact_digest) is None:
        raise ValueError("artifact digest must be a lowercase sha256: digest")


def comparison_payload(
    results: dict[str, Any],
    summary: dict[str, Any],
    identities: list[dict[str, Any]],
    *,
    workflow: dict[str, Any],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    passed = summary["passed"]
    return {
        "schema_version": 1,
        "name": PUBLISHER_NAME,
        "decision": "passed" if passed else "rejected",
        "product_decision": (
            "combined_a1_a2_candidate_retained_for_fresh_validation_only"
            if passed
            else "pre_a1_product_baseline_retained"
        ),
        "selected_variant": "candidate" if passed else None,
        "retained_product_commit": None if passed else PRE_A1_PRODUCT_BASELINE_COMMIT,
        "pre_a1_product_baseline_commit": PRE_A1_PRODUCT_BASELINE_COMMIT,
        "a1_baseline_commit": A2.BASELINE_COMMIT,
        "candidate_commit": results["candidate"]["commit"],
        "claim_scope": A2.CLAIM_SCOPE,
        "claim_ceiling": A2.CLAIM_CEILING,
        "host": results["host"],
        "binaries": results["binaries"],
        "workflow_run": workflow,
        "uploaded_artifact": artifact,
        "schedule": {
            "total_trials": 64,
            "warmup_trials": 8,
            "measured_trials": 56,
            "rounds": A2.ROUNDS,
            "items": 4,
            "variants": list(A2.VARIANTS),
        },
        "frame_identities": identities,
        "summary": summary,
        "a1_context": A1_CONTEXT,
        "unchanged_ratio_context": COMMON.RATIO_CONTEXT,
        "immutable_public_validation_boundary": COMMON.PUBLIC_VALIDATION_BOUNDARY,
    }


def render_readme(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    baseline = variant(summary, "baseline")
    candidate = variant(summary, "candidate")
    passed = summary["passed"]
    if passed:
        outcome = (
            "**Outcome: A2 passed the frozen development gate.** The combined A1 "
            "context-reuse plus A2 inline-single-worker candidate is retained only "
            "for a separately frozen fresh validation gate. It does not rewrite the "
            "consumed public-validation result."
        )
    else:
        failed = [name for name, value in summary["gates"].items() if not value]
        outcome = (
            "**Outcome: A2 was rejected.** A1 had already failed its product gate; "
            "neither A1 nor A2 replaces the pre-A1 product baseline at `"
            f"{PRE_A1_PRODUCT_BASELINE_COMMIT}`. Failed A2 gates: "
            + ", ".join(f"`{name}`" for name in failed)
            + "."
        )
    lines = [
        "# JLS2 A2 inline-single-worker development result",
        "",
        outcome,
        "",
        "![A1 versus A2 comparison](comparison.svg)",
        "",
        "## Frozen paired result",
        "",
        "Both binaries decoded the exact same complete Linux-generated JLS2 frame for every input. Timing is cold-process parent wall time; restored output was verified by complete size and SHA-256.",
        "",
        "| Variant | Median aggregate | Minimum aggregate | CV | Peak RSS | Exact | Selected for fresh validation |",
        "| --- | ---: | ---: | ---: | ---: | :---: | :---: |",
    ]
    for row in (baseline, candidate):
        lines.append(
            "| {} | {:.2f} MB/s | {:.2f} MB/s | {:.2f}% | {:.1f} MiB | {} | {} |".format(
                "exact A1" if row["variant"] == "baseline" else "combined A1+A2",
                row["median_aggregate_mbps"],
                row["minimum_aggregate_mbps"],
                row["aggregate_cv_percent"],
                row["peak_rss_bytes"] / (1024 * 1024),
                "yes" if row["all_exact"] else "no",
                "yes" if passed and row["variant"] == "candidate" else "no",
            )
        )
    old_items = {row["item_id"]: row for row in baseline["item_rows"]}
    new_items = {row["item_id"]: row for row in candidate["item_rows"]}
    lines.extend(
        [
            "",
            "## Per-input memory",
            "",
            "| Input | Exact A1 peak | Combined A1+A2 peak | Change | A2 median |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item_id in EXPECTED_ITEM_IDS:
        old = old_items[item_id]
        new = new_items[item_id]
        change = (new["peak_rss_bytes"] / old["peak_rss_bytes"] - 1.0) * 100.0
        lines.append(
            f"| `{item_id}` | {old['peak_rss_bytes'] / (1024 * 1024):.1f} MiB | "
            f"{new['peak_rss_bytes'] / (1024 * 1024):.1f} MiB | {change:+.2f}% | "
            f"{new['median_mbps']:.2f} MB/s |"
        )
    lines.extend(["", "## Frozen A2 gates", ""])
    for name, value in summary["gates"].items():
        lines.append(f"- {'✅' if value else '❌'} `{name}`")
    public = comparison["immutable_public_validation_boundary"]
    ratio = comparison["unchanged_ratio_context"]
    workflow = comparison["workflow_run"]
    artifact = comparison["uploaded_artifact"]
    lines.extend(
        [
            "",
            "## Prior product boundaries",
            "",
            "A1 reusable contexts recorded **625.2 MiB** development peak RSS against its **448 MiB** frozen development limit, so A1 did not replace the pre-A1 product baseline. A2 uses exact A1 only as its attribution baseline.",
            "",
            f"The first public-validation result remains an immutable **no-pass** at **{public['standalone_decode_peak_rss_bytes'] / (1024 * 1024):.1f} MiB** versus the frozen **{public['frozen_peak_rss_limit_bytes'] / (1024 * 1024):.0f} MiB** product cap. Its ranges are consumed and can never be tuned on or rerun.",
            "",
            "## Unchanged compression context",
            "",
            f"This decoder-only A2 experiment changed no compression evidence. Immutable development JLS2 remains {ratio['jls2_bytes']:,} bytes ({ratio['jls2_ratio']:.2f}x), {ratio['gain_vs_strongest_standard_percent']:.2f}% smaller than {ratio['strongest_standard']}.",
            "",
            "## Provenance",
            "",
            f"- Pre-A1 product baseline: `{PRE_A1_PRODUCT_BASELINE_COMMIT}`",
            f"- Exact A1 attribution baseline: `{comparison['a1_baseline_commit']}`",
            f"- A2 candidate: `{comparison['candidate_commit']}`",
            f"- Host: `{comparison['host']['platform']}`; Python `{comparison['host']['python']}`; `{comparison['host']['rustc']}`",
            f"- Workflow: [run {workflow['run_id']}, attempt {workflow['attempt']}]({workflow['url']}) (`{workflow['conclusion']}`)",
            f"- Uploaded artifact: ID `{artifact['id']}`, `{artifact['name']}`, `{artifact['digest']}`",
            "- Schedule: 8 discarded warmups + 56 measured trials = 64 exact decodes",
            "",
            "## Evidence boundary",
            "",
            "Claim ceiling: **development-only A2 decoder-memory evidence.** This is not public validation, private-holdout evidence, independent reproduction, or a universal, market-leading, world-best, or state-of-the-art result.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    baseline = variant(summary, "baseline")
    candidate = variant(summary, "candidate")
    old_items = {row["item_id"]: row for row in baseline["item_rows"]}
    new_items = {row["item_id"]: row for row in candidate["item_rows"]}
    maximum = max(512 * 1024 * 1024, baseline["peak_rss_bytes"], candidate["peak_rss_bytes"])
    axis_mib = math.ceil(maximum / (1024 * 1024) / 64) * 64
    left, plot_width, top = 260, 830, 140
    gate_x = left + 448 / axis_mib * plot_width
    status = "PASSED" if summary["passed"] else "REJECTED"
    status_class = "pass" if summary["passed"] else "fail"
    output = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="760" viewBox="0 0 1240 760" role="img" aria-labelledby="title desc">',
        '<title id="title">JLS2 A1 versus inline-single-worker A2</title>',
        f'<desc id="desc">The frozen A2 development gate was {status.lower()}. Four input peak RSS comparisons are shown.</desc>',
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;fill:#24292f}.title{font-size:24px;font-weight:700}.sub,.axis,.note{font-size:13px;fill:#57606a}.section{font-size:17px;font-weight:600}.label{font-size:14px}.old{fill:#8c959f}.new{fill:#0969da}.pass{fill:#1a7f37}.fail{fill:#cf222e}.grid{stroke:#d0d7de}.gate{stroke:#bf8700;stroke-width:2;stroke-dasharray:6 5}.card{fill:#f6f8fa;stroke:#d0d7de}</style>",
        '<text class="title" x="24" y="38">JLS2 A2: exact A1 versus inline single worker</text>',
        f'<text class="{status_class}" x="1180" y="38" text-anchor="end" font-size="19" font-weight="700">{status}</text>',
        '<text class="sub" x="24" y="64">Cold standalone processes · identical Linux-generated frames · 64 scheduled exact decodes</text>',
        '<text class="section" x="24" y="108">Per-input peak RSS (MiB, lower is better)</text>',
    ]
    for tick in range(0, axis_mib + 1, 64):
        x = left + tick / axis_mib * plot_width
        output.extend(
            [
                f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + 300}"/>',
                f'<text class="axis" x="{x:.1f}" y="{top + 320}" text-anchor="middle">{tick}</text>',
            ]
        )
    output.extend(
        [
            f'<line class="gate" x1="{gate_x:.1f}" y1="{top - 12}" x2="{gate_x:.1f}" y2="{top + 300}"/>',
            f'<text class="axis" x="{gate_x:.1f}" y="{top - 18}" text-anchor="middle">448 MiB gate</text>',
        ]
    )
    for index, item_id in enumerate(EXPECTED_ITEM_IDS):
        y = top + index * 72 + 12
        old_mib = old_items[item_id]["peak_rss_bytes"] / (1024 * 1024)
        new_mib = new_items[item_id]["peak_rss_bytes"] / (1024 * 1024)
        output.extend(
            [
                f'<text class="label" x="24" y="{y + 21}">{html.escape(item_id)}</text>',
                f'<rect class="old" x="{left}" y="{y}" width="{old_mib / axis_mib * plot_width:.1f}" height="20" rx="3"/>',
                f'<text class="axis" x="{left + old_mib / axis_mib * plot_width + 8:.1f}" y="{y + 15}">{old_mib:.1f}</text>',
                f'<rect class="new" x="{left}" y="{y + 26}" width="{new_mib / axis_mib * plot_width:.1f}" height="20" rx="3"/>',
                f'<text class="axis" x="{left + new_mib / axis_mib * plot_width + 8:.1f}" y="{y + 41}">{new_mib:.1f}</text>',
            ]
        )
    cards = (
        ("Exact A1 median", f"{baseline['median_aggregate_mbps']:.2f} MB/s"),
        ("Combined A1+A2 median", f"{candidate['median_aggregate_mbps']:.2f} MB/s"),
        ("Stress RSS reduction", f"{summary['stress_peak_rss_reduction_percent']:.2f}%"),
        ("Frozen gates", f"{sum(summary['gates'].values())}/{len(summary['gates'])}"),
    )
    for index, (label, value) in enumerate(cards):
        x = 24 + index * 300
        output.extend(
            [
                f'<rect class="card" x="{x}" y="500" width="276" height="72" rx="6"/>',
                f'<text class="note" x="{x + 14}" y="525">{label}</text>',
                f'<text class="section" x="{x + 14}" y="552">{value}</text>',
            ]
        )
    output.extend(
        [
            '<text class="section" x="24" y="620">Prior boundaries</text>',
            '<text class="note" x="24" y="648">A1 context reuse: 625.2 MiB development peak vs 448 MiB gate; A1 did not replace the pre-A1 product.</text>',
            '<text class="note" x="24" y="676">Immutable public validation: 621.3 MiB vs 512 MiB no-pass; consumed ranges cannot be rerun.</text>',
            '<text class="note" x="24" y="716">Development-only A2 evidence · pass authorizes only a separately frozen fresh validation gate</text>',
            "</svg>",
        ]
    )
    return "\n".join(output) + "\n"


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
        (results_path, "raw A2 results"),
        (provenance_path, "A2 provenance"),
        (benchmark_log_path, "A2 benchmark log"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be a regular non-symlink file")
        if path.stat().st_size == 0:
            raise ValueError(f"{label} must be nonempty")
    if output.exists():
        raise ValueError("refusing to replace an existing A2 publication")
    COMMON.validate_ratio_context()
    results = COMMON.load_json(results_path)
    summary, identities = validate_results(
        results,
        candidate_commit=candidate_commit,
        baseline_binary_sha256=baseline_binary_sha256,
        candidate_binary_sha256=candidate_binary_sha256,
        host_platform=host_platform,
    )
    validate_metadata(
        passed=summary["passed"],
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        workflow_run_url=workflow_run_url,
        workflow_run_conclusion=workflow_run_conclusion,
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        artifact_digest=artifact_digest,
    )
    workflow = {
        "run_id": workflow_run_id,
        "attempt": workflow_run_attempt,
        "url": workflow_run_url,
        "conclusion": workflow_run_conclusion,
    }
    artifact = {"id": artifact_id, "name": artifact_name, "digest": artifact_digest}
    comparison = comparison_payload(
        results, summary, identities, workflow=workflow, artifact=artifact
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".partial", dir=output.parent)
    )
    try:
        shutil.copyfile(results_path, staging / "results.json")
        shutil.copyfile(provenance_path, staging / "provenance.txt")
        shutil.copyfile(benchmark_log_path, staging / "benchmark.log")
        COMMON.write_json(staging / "comparison.json", comparison)
        COMMON.write_text(staging / "comparison.svg", render_svg(comparison))
        COMMON.write_text(staging / "README.md", render_readme(comparison))
        artifact_files = (
            "results.json",
            "provenance.txt",
            "benchmark.log",
            "comparison.json",
            "comparison.svg",
            "README.md",
        )
        artifacts = {name: COMMON.sha256_file(staging / name) for name in artifact_files}
        receipt = {
            "schema_version": 1,
            "name": f"{PUBLISHER_NAME}-receipt",
            "decision": comparison["decision"],
            "product_decision": comparison["product_decision"],
            "pre_a1_product_baseline_commit": PRE_A1_PRODUCT_BASELINE_COMMIT,
            "a1_baseline_commit": A2.BASELINE_COMMIT,
            "candidate_commit": candidate_commit,
            "binaries": {
                "a1_sha256": baseline_binary_sha256,
                "a2_sha256": candidate_binary_sha256,
            },
            "host": results["host"],
            "workflow_run": workflow,
            "uploaded_artifact": artifact,
            "source_inputs": {
                "results_sha256": COMMON.sha256_file(results_path),
                "provenance_sha256": COMMON.sha256_file(provenance_path),
                "benchmark_log_sha256": COMMON.sha256_file(benchmark_log_path),
                "ratio_evidence_sha256": COMMON.EXPECTED_RATIO_EVIDENCE_SHA256,
            },
            "verification": {
                "strict_raw_schema_valid": True,
                "all_trial_fields_recomputed": True,
                "frozen_summary_and_gates_recomputed": True,
                "trial_schedule_exact": True,
                "scheduled_trials": 64,
                "same_frame_identities": identities,
                "all_outputs_exact": True,
            },
            "publication_sources": {
                "a2_runner": {
                    "path": RUNNER.relative_to(ROOT).as_posix(),
                    "sha256": RUNNER_SHA256,
                },
                "protocol": {
                    "path": PROTOCOL.relative_to(ROOT).as_posix(),
                    "sha256": PROTOCOL_SHA256,
                },
                "workflow": {
                    "path": WORKFLOW.relative_to(ROOT).as_posix(),
                    "sha256": WORKFLOW_SHA256,
                },
                "common_publisher": {
                    "path": COMMON_PUBLISHER.relative_to(ROOT).as_posix(),
                    "sha256": COMMON_PUBLISHER_SHA256,
                },
                "publisher": {
                    "path": Path(__file__).relative_to(ROOT).as_posix(),
                    "sha256": COMMON.sha256_file(Path(__file__)),
                },
            },
            "artifacts": artifacts,
            "a1_context": A1_CONTEXT,
            "unchanged_ratio_context": COMMON.RATIO_CONTEXT,
            "immutable_public_validation_boundary": COMMON.PUBLIC_VALIDATION_BOUNDARY,
            "claim_ceiling": A2.CLAIM_CEILING,
        }
        COMMON.write_json(staging / "receipt.json", receipt)
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
