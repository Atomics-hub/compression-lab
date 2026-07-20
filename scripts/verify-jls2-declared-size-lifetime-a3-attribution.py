#!/usr/bin/env python3
"""Verify a frozen JLS2 A3 hosted attribution result without corpus access."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "audit-jls2-declared-size-lifetime-a3.py"


def load_contract() -> Any:
    spec = importlib.util.spec_from_file_location("jls2_a3_contract", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen A3 attribution contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_result(result: dict[str, Any]) -> None:
    contract = load_contract()
    if result.get("schema_version") != 1:
        raise ValueError("result schema version mismatch")
    if result.get("name") != "jls2-declared-size-lifetime-a3-hosted-attribution-v1":
        raise ValueError("result name mismatch")
    if result.get("claim_scope") != "development-only decoder-memory attribution":
        raise ValueError("result claim scope mismatch")
    a2 = result.get("a2_identity", {})
    if a2 != {
        "commit": contract.A2_COMMIT,
        "binary_sha256": contract.A2_BINARY_SHA256,
        "baseline_peak_rss_bytes": contract.A2_BASELINE_RSS_BYTES,
    }:
        raise ValueError("exact A2 identity mismatch")
    hosted = result.get("hosted_identity", {})
    for field in ("run_id", "job_id"):
        if not isinstance(hosted.get(field), str) or not hosted[field].isdigit():
            raise ValueError(f"hosted {field} is invalid")
    if not isinstance(hosted.get("run_attempt"), int) or hosted["run_attempt"] < 1:
        raise ValueError("hosted run attempt is invalid")
    if hosted.get("a2_commit") != contract.A2_COMMIT:
        raise ValueError("hosted A2 commit mismatch")
    if hosted.get("a2_product_binary_sha256") != contract.A2_BINARY_SHA256:
        raise ValueError("hosted A2 product binary mismatch")
    commit = hosted.get("workflow_source_commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise ValueError("hosted workflow source commit is invalid")
    for field in (
        "workflow_sha256",
        "runner_sha256",
        "diagnostic_binary_sha256",
    ):
        value = hosted.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"hosted {field} is invalid")
    if hosted.get("artifact_name") != (
        "jls2-declared-size-lifetime-a3-attribution-" + hosted["run_id"]
    ):
        raise ValueError("artifact name is not bound to run ID")
    expected_host = {
        "platform": contract.EXPECTED_PLATFORM,
        "logical_cpus": contract.EXPECTED_LOGICAL_CPUS,
        "python": contract.EXPECTED_PYTHON,
        "rustc": contract.EXPECTED_RUSTC,
        "cargo": contract.EXPECTED_CARGO,
        "glibc": contract.EXPECTED_GLIBC,
        "allocator": contract.EXPECTED_ALLOCATOR,
        "zstandard": contract.EXPECTED_ZSTD,
    }
    if result.get("host") != expected_host:
        raise ValueError("frozen host/toolchain identity mismatch")
    settings = result.get("settings", {})
    expected_settings = {
        "attribution_threshold_bytes": contract.ATTRIBUTION_THRESHOLD_BYTES,
        "a3_overage_bytes": contract.A3_OVERAGE_BYTES,
        "proposed_batch_budget_bytes": contract.PROPOSED_BATCH_BUDGET_BYTES,
        "a1_runner_sha256": contract.A1_RUNNER_SHA256,
        "cargo_lock_sha256": contract.EXPECTED_CARGO_LOCK_SHA256,
        "a2_protected_file_sha256": contract.EXPECTED_A2_PROTECTED_SHA256,
        "development_fixtures_only": True,
        "validation_accessed": False,
        "holdout_accessed": False,
        "product_ab_authorized_before_this_result": False,
        "format_encoder_selector_changed": False,
    }
    if settings != expected_settings:
        raise ValueError("frozen settings mismatch")
    generations = result.get("generations")
    if not isinstance(generations, list) or len(generations) != 2:
        raise ValueError("exactly two generations are required")
    by_generation = []
    potentials = []
    rss_reductions = []
    credits = []
    for expected_generation, generation in enumerate(generations, start=1):
        if generation.get("generation") != expected_generation:
            raise ValueError("generation order mismatch")
        reports = generation.get("reports")
        if not isinstance(reports, list):
            raise ValueError("generation reports are missing")
        by_id = {report.get("fixture_id"): report for report in reports}
        if set(by_id) != set(contract.EXPECTED_FRAMES):
            raise ValueError("generation fixture set mismatch")
        for fixture_id, expected in contract.EXPECTED_FRAMES.items():
            report = by_id[fixture_id]
            contract.validate_diagnostic_report(report, fixture_id, expected)
            attribution = report["attribution"]
            potentials.append(attribution["decoded_concurrency_potential_bytes"])
            rss_reductions.append(
                attribution["phase_correlated_rss_reduction_bytes"]
            )
            credits.append(attribution["credited_bytes"])
        by_generation.append(by_id)
    for fixture_id in contract.EXPECTED_FRAMES:
        if contract.topology_key(by_generation[0][fixture_id]) != contract.topology_key(
            by_generation[1][fixture_id]
        ):
            raise ValueError("two-generation topology mismatch")
    minimum_potential = min(potentials)
    minimum_rss = min(rss_reductions)
    minimum_credit = min(credits)
    threshold = contract.ATTRIBUTION_THRESHOLD_BYTES
    gates = {
        "exact_a2_commit": True,
        "exact_host_and_toolchain": True,
        "four_logical_cpus": result.get("host", {}).get("logical_cpus")
        == contract.EXPECTED_LOGICAL_CPUS,
        "two_generation_topology_identical": True,
        "all_decodes_exact": True,
        "decoded_concurrency_potential_at_least_threshold": minimum_potential
        >= threshold,
        "phase_correlated_rss_reduction_at_least_threshold": minimum_rss
        >= threshold,
        "credited_attribution_at_least_threshold": minimum_credit >= threshold,
        "encoded_lifetime_credit_is_zero": True,
    }
    summary = result.get("summary", {})
    if summary.get("minimum_decoded_concurrency_potential_bytes") != minimum_potential:
        raise ValueError("minimum decoded-concurrency potential mismatch")
    if summary.get("minimum_phase_correlated_rss_reduction_bytes") != minimum_rss:
        raise ValueError("minimum phase RSS reduction mismatch")
    if summary.get("minimum_credited_bytes") != minimum_credit:
        raise ValueError("minimum credited attribution mismatch")
    if summary.get("gates") != gates:
        raise ValueError("selection gates mismatch")
    passed = all(gates.values())
    if summary.get("passed") is not passed:
        raise ValueError("result pass decision mismatch")
    if summary.get("product_ab_authorized") is not passed:
        raise ValueError("product A/B authorization mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    with args.result.open(encoding="utf-8") as source:
        result = json.load(source)
    validate_result(result)
    print(f"verified {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
