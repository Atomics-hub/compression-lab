#!/usr/bin/env python3
"""Publish the immutable rejected JLS2 A3 hosted-attribution result offline."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_VERIFIER = (
    ROOT / "scripts" / "verify-jls2-declared-size-lifetime-a3-attribution.py"
)
RAW_VERIFIER_SHA256 = (
    "6d7424085ed774fe85cb898c0d63db45bbca19d16d822e8a584aa8eeff966c6d"
)
RAW_CONTRACT = ROOT / "scripts" / "audit-jls2-declared-size-lifetime-a3.py"
RAW_CONTRACT_SHA256 = (
    "e8f15c2fb820540da386a1994daf7ecc7f498669ac7c15ac8671aec7807e7b86"
)
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-19-jls2-declared-size-lifetime-a3-audit-protocol.md"
)
PROTOCOL_SHA256 = "68b4e9e30d81f8d7dd4336a186dde842aa67a36ef0859d2a9693cc97133303e1"
PUBLISHER_NAME = "jls2-declared-size-lifetime-a3-attribution-publication-v1"
EXPECTED_RUN_ID = 29_765_080_842
EXPECTED_JOB_ID = 88_429_200_694
EXPECTED_RUN_ATTEMPT = 1
EXPECTED_RUN_CONCLUSION = "failure"
EXPECTED_ARTIFACT_ID = 8_470_661_511
EXPECTED_ARTIFACT_NAME = (
    "jls2-declared-size-lifetime-a3-attribution-29765080842"
)
EXPECTED_ARTIFACT_DIGEST = (
    "sha256:42ae14e5a0cdd63f8673fe5f4256e0f1dda16f4cc86e80acb3570e66407d3a05"
)
EXPECTED_WORKFLOW_HEAD = "41d2aaea12e5126bb83106792bfd575dc12e7440"
EXPECTED_EMBEDDED_WORKFLOW_COMMIT = "3cfd54e798056bd419dbbd3daec4359be873a87b"
EXPECTED_EMBEDDED_WORKFLOW_SHA256 = (
    "3b052fc0b38588c1e29b1d703e05c2b4063b4d55b0a47b770abe0194d0946dbd"
)
EXPECTED_EMBEDDED_RUNNER_SHA256 = (
    "e8f15c2fb820540da386a1994daf7ecc7f498669ac7c15ac8671aec7807e7b86"
)
EXPECTED_DIAGNOSTIC_BINARY_SHA256 = (
    "a01b3ef1a4aecfd6dea2383bb03b3372f363e06a6cf60b39e9a0ec724433b724"
)
EXPECTED_A2_COMMIT = "0f3377dff647e8a6d99b65d8f8a269687faa8ec6"
EXPECTED_A2_BINARY = "c67e9c9b1902414c2b2e67991631d4cd065041242e6dd39392d673da2ca752fd"
EXPECTED_THRESHOLD = 105_202_484
EXPECTED_INPUT_SHA256 = {
    "attribution.log": (
        "414337cc13414b3a6dc6b56e5668754a40a396f7b91da176951709b21fd28227"
    ),
    "provenance.txt": (
        "9a23b6df9879225d063c11dd18d078f3ce65b89da2718ca46ac2d9ddcff7ef23"
    ),
    "results.json": (
        "e771ffe8ae239f381134e5c626f596b84f256ba0d14e7c6cdf5f036841b1ea82"
    ),
    "results.sha256": (
        "ef7c10ffe7d0c5ce2f8c25930058ce25db3874c1d0291b5107688642dc0cb86c"
    ),
}
PUBLICATION_ROSTER = {
    "README.md",
    "attribution.log",
    "comparison.json",
    "comparison.svg",
    "provenance.txt",
    "receipt.json",
    "results.json",
    "results.sha256",
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


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


for frozen_path, expected in (
    (RAW_VERIFIER, RAW_VERIFIER_SHA256),
    (RAW_CONTRACT, RAW_CONTRACT_SHA256),
    (PROTOCOL, PROTOCOL_SHA256),
):
    if sha256_file(frozen_path) != expected:
        raise RuntimeError(f"frozen A3 publication dependency drifted: {frozen_path}")
RAW = load_module(RAW_VERIFIER, "jls2_a3_raw_verifier")


def require_exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        missing = sorted(keys - set(value)) if isinstance(value, dict) else sorted(keys)
        extra = sorted(set(value) - keys) if isinstance(value, dict) else []
        raise ValueError(f"{label} keys mismatch; missing={missing}, extra={extra}")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value: dict[str, Any]) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_source(artifact_dir: Path) -> dict[str, Any]:
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError("artifact directory must be a regular non-symlink directory")
    observed = {entry.name for entry in artifact_dir.iterdir()}
    if observed != set(EXPECTED_INPUT_SHA256):
        raise ValueError(
            "artifact roster mismatch; "
            f"missing={sorted(set(EXPECTED_INPUT_SHA256) - observed)}, "
            f"extra={sorted(observed - set(EXPECTED_INPUT_SHA256))}"
        )
    for name, expected in EXPECTED_INPUT_SHA256.items():
        path = artifact_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"artifact member must be a regular non-symlink file: {name}")
        observed_digest = sha256_file(path)
        if observed_digest != expected:
            raise ValueError(
                f"artifact member digest mismatch: {name}; "
                f"expected {expected}, observed {observed_digest}"
            )
    result = json.loads((artifact_dir / "results.json").read_text(encoding="utf-8"))
    RAW.validate_result(result)
    return result


def recompute(result: dict[str, Any]) -> dict[str, Any]:
    identity = result["hosted_identity"]
    if identity["run_id"] != str(EXPECTED_RUN_ID):
        raise ValueError("embedded run ID mismatch")
    if identity["job_id"] != str(EXPECTED_JOB_ID):
        raise ValueError("embedded job ID mismatch")
    if identity["run_attempt"] != EXPECTED_RUN_ATTEMPT:
        raise ValueError("embedded run attempt mismatch")
    if identity["artifact_name"] != EXPECTED_ARTIFACT_NAME:
        raise ValueError("embedded artifact name mismatch")
    if identity["workflow_source_commit"] != EXPECTED_EMBEDDED_WORKFLOW_COMMIT:
        raise ValueError("embedded PR merge-workflow commit mismatch")
    if identity["workflow_sha256"] != EXPECTED_EMBEDDED_WORKFLOW_SHA256:
        raise ValueError("embedded workflow SHA-256 mismatch")
    if identity["runner_sha256"] != EXPECTED_EMBEDDED_RUNNER_SHA256:
        raise ValueError("embedded runner SHA-256 mismatch")
    if identity["diagnostic_binary_sha256"] != EXPECTED_DIAGNOSTIC_BINARY_SHA256:
        raise ValueError("embedded diagnostic binary SHA-256 mismatch")
    if identity["a2_commit"] != EXPECTED_A2_COMMIT:
        raise ValueError("embedded A2 commit mismatch")
    if identity["a2_product_binary_sha256"] != EXPECTED_A2_BINARY:
        raise ValueError("embedded A2 binary mismatch")
    if result["a2_identity"] != {
        "baseline_peak_rss_bytes": 657_682_432,
        "binary_sha256": EXPECTED_A2_BINARY,
        "commit": EXPECTED_A2_COMMIT,
    }:
        raise ValueError("A2 identity block mismatch")
    settings = result["settings"]
    if settings["attribution_threshold_bytes"] != EXPECTED_THRESHOLD:
        raise ValueError("attribution threshold mismatch")
    if not settings["development_fixtures_only"]:
        raise ValueError("result is not development-only")
    if settings["validation_accessed"] or settings["holdout_accessed"]:
        raise ValueError("validation or holdout access is forbidden")
    if settings["product_ab_authorized_before_this_result"]:
        raise ValueError("result improperly began with product A/B authorization")
    reports = [
        report
        for generation in result["generations"]
        for report in generation["reports"]
    ]
    potential = min(
        report["attribution"]["decoded_concurrency_potential_bytes"]
        for report in reports
    )
    rss = min(
        report["attribution"]["phase_correlated_rss_reduction_bytes"]
        for report in reports
    )
    credited = min(
        report["attribution"]["credited_bytes"] for report in reports
    )
    encoded_zero = all(
        report["attribution"]["encoded_lifetime_authorization_credit_bytes"] == 0
        for report in reports
    )
    all_exact = all(report["exact"] for report in reports)
    by_generation = [
        {report["fixture_id"]: report for report in generation["reports"]}
        for generation in result["generations"]
    ]
    topology_identical = all(
        RAW.load_contract().topology_key(by_generation[0][fixture_id])
        == RAW.load_contract().topology_key(by_generation[1][fixture_id])
        for fixture_id in by_generation[0]
    )
    gates = {
        "exact_a2_commit": result["a2_identity"]["commit"] == EXPECTED_A2_COMMIT,
        "exact_host_and_toolchain": True,
        "four_logical_cpus": result["host"]["logical_cpus"] == 4,
        "two_generation_topology_identical": topology_identical,
        "all_decodes_exact": all_exact,
        "decoded_concurrency_potential_at_least_threshold": potential
        >= EXPECTED_THRESHOLD,
        "phase_correlated_rss_reduction_at_least_threshold": rss
        >= EXPECTED_THRESHOLD,
        "credited_attribution_at_least_threshold": credited >= EXPECTED_THRESHOLD,
        "encoded_lifetime_credit_is_zero": encoded_zero,
    }
    passed = all(gates.values())
    summary = {
        "minimum_decoded_concurrency_potential_bytes": potential,
        "minimum_phase_correlated_rss_reduction_bytes": rss,
        "minimum_credited_bytes": credited,
        "gates": gates,
        "passed": passed,
        "product_ab_authorized": passed,
    }
    if summary != result["summary"]:
        raise ValueError("raw summary or gate decision does not recompute exactly")
    if passed:
        raise ValueError("immutable A3 artifact unexpectedly passes")
    return summary


def build_comparison(result: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    threshold = result["settings"]["attribution_threshold_bytes"]
    metrics = [
        ("decoded_concurrency_potential", summary["minimum_decoded_concurrency_potential_bytes"]),
        ("phase_correlated_rss_reduction", summary["minimum_phase_correlated_rss_reduction_bytes"]),
        ("credited_attribution", summary["minimum_credited_bytes"]),
    ]
    rows = [
        {
            "metric": name,
            "observed_bytes": value,
            "threshold_bytes": threshold,
            "shortfall_bytes": max(0, threshold - value),
            "percent_of_threshold": value / threshold * 100.0,
            "gate_passed": value >= threshold,
        }
        for name, value in metrics
    ]
    fixture_rows = []
    fixture_ids = [
        report["fixture_id"] for report in result["generations"][0]["reports"]
    ]
    for fixture_id in fixture_ids:
        reports = [
            report
            for generation in result["generations"]
            for report in generation["reports"]
            if report["fixture_id"] == fixture_id
        ]
        fixture_rows.append(
            {
                "fixture_id": fixture_id,
                "minimum_potential_bytes": min(
                    report["attribution"]["decoded_concurrency_potential_bytes"]
                    for report in reports
                ),
                "minimum_rss_reduction_bytes": min(
                    report["attribution"]["phase_correlated_rss_reduction_bytes"]
                    for report in reports
                ),
                "minimum_credited_bytes": min(
                    report["attribution"]["credited_bytes"] for report in reports
                ),
            }
        )
    return {
        "schema_version": 1,
        "name": "jls2-a3-attribution-rejection-comparison-v1",
        "decision": "rejected",
        "product_ab_authorized": False,
        "claim_scope": result["claim_scope"],
        "claim_ceiling": result["claim_ceiling"],
        "threshold_bytes": threshold,
        "metric_rows": rows,
        "fixture_rows": fixture_rows,
        "integrity": {
            "all_decodes_exact": summary["gates"]["all_decodes_exact"],
            "two_generation_topology_identical": summary["gates"][
                "two_generation_topology_identical"
            ],
            "encoded_lifetime_credit_bytes": 0,
            "format_encoder_selector_changed": False,
        },
        "evidence_level": "development-only hosted attribution",
        "runner_comparability": (
            "Exact A2 Ubuntu 22.04 runner-image, four logical CPUs, glibc 2.35, "
            "Rust 1.97.0, and A2 product binary identity."
        ),
    }


def render_svg(comparison: dict[str, Any]) -> str:
    width = 920
    height = 310
    left = 290
    chart_width = 560
    rows = comparison["metric_rows"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1020"/>',
        '<text x="32" y="38" fill="#f8fafc" font-family="system-ui,sans-serif" font-size="22" font-weight="700">JLS2 A3 attribution gate — rejected</text>',
        '<text x="32" y="64" fill="#94a3b8" font-family="system-ui,sans-serif" font-size="13">Development-only; bars must reach the 105,202,484-byte threshold.</text>',
    ]
    for index, row in enumerate(rows):
        y = 102 + index * 62
        fraction = min(row["observed_bytes"] / row["threshold_bytes"], 1.0)
        bar = chart_width * fraction
        label = row["metric"].replace("_", " ")
        observed_mib = row["observed_bytes"] / (1024 * 1024)
        threshold_mib = row["threshold_bytes"] / (1024 * 1024)
        parts.extend(
            [
                f'<text x="32" y="{y + 19}" fill="#e2e8f0" font-family="system-ui,sans-serif" font-size="13">{html.escape(label)}</text>',
                f'<rect x="{left}" y="{y}" width="{chart_width}" height="24" rx="4" fill="#273449"/>',
                f'<rect x="{left}" y="{y}" width="{bar:.2f}" height="24" rx="4" fill="#ef4444"/>',
                f'<line x1="{left + chart_width}" y1="{y - 4}" x2="{left + chart_width}" y2="{y + 28}" stroke="#f8fafc" stroke-width="2"/>',
                f'<text x="{left + 8}" y="{y + 17}" fill="#fff" font-family="ui-monospace,monospace" font-size="12">{observed_mib:.2f} / {threshold_mib:.2f} MiB</text>',
            ]
        )
    parts.extend(
        [
            '<text x="32" y="294" fill="#fca5a5" font-family="system-ui,sans-serif" font-size="13" font-weight="600">No A3 product candidate or product A/B is authorized.</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def render_readme(comparison: dict[str, Any]) -> str:
    rows = comparison["metric_rows"]
    by_metric = {row["metric"]: row for row in rows}
    potential = by_metric["decoded_concurrency_potential"]["observed_bytes"]
    rss = by_metric["phase_correlated_rss_reduction"]["observed_bytes"]
    threshold = comparison["threshold_bytes"]
    table = [
        "| Frozen gate | Observed | Required | Shortfall | Passed? |",
        "|---|---:|---:|---:|:---:|",
    ]
    for row in rows:
        table.append(
            "| "
            + row["metric"].replace("_", " ")
            + f" | {row['observed_bytes']:,} B | {row['threshold_bytes']:,} B"
            + f" | {row['shortfall_bytes']:,} B | {'yes' if row['gate_passed'] else 'no'} |"
        )
    return "\n".join(
        [
            "# JLS2 A3 hosted attribution — rejected",
            "",
            "![JLS2 A3 attribution gate](comparison.svg)",
            "",
            "The immutable development-only hosted preflight rejected A3 before any product candidate or product A/B. "
            f"The minimum decoded-concurrency potential and credited attribution were {potential:,} bytes; "
            f"the minimum observed phase-correlated RSS reduction was {rss:,} bytes. "
            f"Each was required to reach {threshold:,} bytes.",
            "",
            *table,
            "",
            "All eight diagnostic decodes were exact, both generated topologies matched, and encoded lifetime received zero authorization credit. Those integrity passes do not override the failed attribution gates.",
            "",
            "## Decision and claim ceiling",
            "",
            "A3 is killed at preflight. No A3 implementation, product A/B, validation run, holdout run, product replacement, market-leading claim, world-best claim, or state-of-the-art claim is authorized. The pre-A1 product remains retained; exact A2 remains attribution-only.",
            "",
            "This evidence is development-only. No validation or private-holdout bytes were accessed.",
            "",
            "## Immutable hosted identity",
            "",
            f"- Run `{EXPECTED_RUN_ID}`, job `{EXPECTED_JOB_ID}`, attempt `{EXPECTED_RUN_ATTEMPT}`, conclusion `{EXPECTED_RUN_CONCLUSION}`.",
            f"- Artifact `{EXPECTED_ARTIFACT_ID}` / `{EXPECTED_ARTIFACT_NAME}` / `{EXPECTED_ARTIFACT_DIGEST}`.",
            f"- GitHub workflow head `{EXPECTED_WORKFLOW_HEAD}`; embedded PR merge-workflow commit `{EXPECTED_EMBEDDED_WORKFLOW_COMMIT}`.",
            f"- Exact A2 commit `{EXPECTED_A2_COMMIT}` and product binary `{EXPECTED_A2_BINARY}`.",
            "- The raw result, detached result digest, log, provenance, comparison, chart, and receipt are retained together here.",
            "",
        ]
    )


def publish(artifact_dir: Path, output: Path) -> dict[str, Any]:
    if artifact_dir.is_symlink():
        raise ValueError("artifact directory cannot be a symlink")
    artifact_dir = artifact_dir.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"publication output already exists: {output}")
    if not output.parent.exists() or output.parent.is_symlink():
        raise ValueError("publication parent must be an existing non-symlink directory")
    result = read_source(artifact_dir)
    summary = recompute(result)
    comparison = build_comparison(result, summary)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for name in EXPECTED_INPUT_SHA256:
            shutil.copyfile(artifact_dir / name, staging / name)
        write_json(staging / "comparison.json", comparison)
        write_text(staging / "comparison.svg", render_svg(comparison))
        write_text(staging / "README.md", render_readme(comparison))
        files = {
            name: sha256_file(staging / name)
            for name in sorted(PUBLICATION_ROSTER - {"receipt.json"})
        }
        receipt = {
            "schema_version": 1,
            "name": f"{PUBLISHER_NAME}-receipt",
            "decision": "rejected",
            "product_ab_authorized": False,
            "claim_ceiling": result["claim_ceiling"],
            "source_artifact": {
                "run_id": EXPECTED_RUN_ID,
                "job_id": EXPECTED_JOB_ID,
                "run_attempt": EXPECTED_RUN_ATTEMPT,
                "run_conclusion": EXPECTED_RUN_CONCLUSION,
                "artifact_id": EXPECTED_ARTIFACT_ID,
                "artifact_name": EXPECTED_ARTIFACT_NAME,
                "artifact_digest": EXPECTED_ARTIFACT_DIGEST,
                "workflow_head": EXPECTED_WORKFLOW_HEAD,
                "embedded_workflow_commit": EXPECTED_EMBEDDED_WORKFLOW_COMMIT,
                "input_roster_sha256": EXPECTED_INPUT_SHA256,
            },
            "a2_identity": result["a2_identity"],
            "summary": summary,
            "publication_dependencies_sha256": {
                "publisher": sha256_file(Path(__file__).resolve()),
                "raw_verifier": RAW_VERIFIER_SHA256,
                "raw_contract": RAW_CONTRACT_SHA256,
                "protocol": PROTOCOL_SHA256,
            },
            "publication_files_sha256": files,
            "validation_accessed": False,
            "holdout_accessed": False,
        }
        write_json(staging / "receipt.json", receipt)
        if {entry.name for entry in staging.iterdir()} != PUBLICATION_ROSTER:
            raise RuntimeError("internal publication roster mismatch")
        os.replace(staging, output)
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = publish(args.artifact_dir, args.output)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
