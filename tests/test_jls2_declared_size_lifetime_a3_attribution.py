from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit-jls2-declared-size-lifetime-a3.py"
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-19-jls2-declared-size-lifetime-a3-audit-protocol.md"
)
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "jls2-declared-size-lifetime-a3-attribution.yml"
)
VERIFIER = (
    ROOT / "scripts" / "verify-jls2-declared-size-lifetime-a3-attribution.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_a3_attribution", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load JLS2 A3 attribution runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_verifier():
    spec = importlib.util.spec_from_file_location("jls2_a3_verifier", VERIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load JLS2 A3 attribution verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_report(module) -> dict[str, object]:
    expected = module.EXPECTED_FRAMES["jls2-context-stress-256"]
    segment = {
        "segment_index": 0,
        "mode": "columnar",
        "encoded_frame_bytes": expected["encoded_bytes"] - 100,
        "encoded_frame_borrowed": True,
        "declared_output_bytes": expected["source_bytes"],
        "declared_skeleton_raw_bytes": 1_000,
        "declared_channel_raw_bytes": [2_000],
        "declared_live_working_bytes": expected["source_bytes"] + 3_000,
        "a2_batch_index": 0,
        "a2_batch_declared_live_working_bytes": expected["source_bytes"] + 3_000,
        "proposed_batch_index": 0,
        "proposed_batch_declared_live_working_bytes": expected["source_bytes"] + 3_000,
    }
    phases = [
        {
            "phase": phase,
            "batch_index": 0,
            "rss_bytes": 200_000_000,
            "allocator_in_use_bytes": 150_000_000,
            "allocator_free_arena_bytes": 10_000_000,
            "allocator_mmap_bytes": 100_000_000,
        }
        for phase in module.PHASES
    ]
    return {
        "schema_version": 1,
        "fixture_id": "jls2-context-stress-256",
        "encoded_bytes": expected["encoded_bytes"],
        "encoded_capacity_bytes": expected["encoded_bytes"],
        "encoded_sha256": expected["encoded_sha256"],
        "output_bytes": expected["source_bytes"],
        "output_sha256": "0" * 64,
        "segment_count": expected["segments"],
        "exact": True,
        "segments": [dict(segment, segment_index=index) for index in range(3)],
        "phase_snapshots": phases,
        "attribution": {
            "decoded_concurrency_potential_bytes": 120_000_000,
            "phase_correlated_rss_reduction_bytes": 110_000_000,
            "phase_correlated_allocator_release_bytes": 5_000_000,
            "credited_bytes": 110_000_000,
            "live_encoded_bytes_report_only": expected["encoded_bytes"],
            "live_declared_decoded_reassembly_bytes": 120_000_000,
            "allocator_in_use_not_represented_by_declared_buffers_bytes": 1,
            "free_allocator_arenas_or_mappings_retained_bytes": 2,
            "encoded_lifetime_authorization_credit_bytes": 0,
            "declared_values_are_observed_allocations": False,
            "unclassified_resident_bytes": 1,
        },
        "corruption_results": {
            "product_regression_suite": (
                "verified separately by frozen workflow before corpus access"
            )
        },
    }


def valid_result(module) -> dict[str, object]:
    reports = []
    template = valid_report(module)
    for fixture_id, expected in module.EXPECTED_FRAMES.items():
        report = copy.deepcopy(template)
        report.update(
            {
                "fixture_id": fixture_id,
                "encoded_bytes": expected["encoded_bytes"],
                "encoded_capacity_bytes": expected["encoded_bytes"],
                "encoded_sha256": expected["encoded_sha256"],
                "output_bytes": expected["source_bytes"],
                "segment_count": expected["segments"],
            }
        )
        segment = report["segments"][0]
        report["segments"] = [
            dict(segment, segment_index=index) for index in range(expected["segments"])
        ]
        reports.append(report)
    gates = {
        "exact_a2_commit": True,
        "exact_host_and_toolchain": True,
        "four_logical_cpus": True,
        "two_generation_topology_identical": True,
        "all_decodes_exact": True,
        "decoded_concurrency_potential_at_least_threshold": True,
        "phase_correlated_rss_reduction_at_least_threshold": True,
        "credited_attribution_at_least_threshold": True,
        "encoded_lifetime_credit_is_zero": True,
    }
    return {
        "schema_version": 1,
        "name": "jls2-declared-size-lifetime-a3-hosted-attribution-v1",
        "claim_scope": "development-only decoder-memory attribution",
        "a2_identity": {
            "commit": module.A2_COMMIT,
            "binary_sha256": module.A2_BINARY_SHA256,
            "baseline_peak_rss_bytes": module.A2_BASELINE_RSS_BYTES,
        },
        "hosted_identity": {
            "run_id": "123",
            "job_id": "456",
            "run_attempt": 1,
            "a2_commit": module.A2_COMMIT,
            "workflow_source_commit": "a" * 40,
            "workflow_sha256": "b" * 64,
            "runner_sha256": "c" * 64,
            "diagnostic_binary_sha256": "d" * 64,
            "a2_product_binary_sha256": module.A2_BINARY_SHA256,
            "artifact_name": "jls2-declared-size-lifetime-a3-attribution-123",
        },
        "host": {
            "platform": module.EXPECTED_PLATFORM,
            "logical_cpus": module.EXPECTED_LOGICAL_CPUS,
            "python": module.EXPECTED_PYTHON,
            "rustc": module.EXPECTED_RUSTC,
            "cargo": module.EXPECTED_CARGO,
            "glibc": module.EXPECTED_GLIBC,
            "allocator": module.EXPECTED_ALLOCATOR,
            "zstandard": module.EXPECTED_ZSTD,
        },
        "settings": {
            "attribution_threshold_bytes": module.ATTRIBUTION_THRESHOLD_BYTES,
            "a3_overage_bytes": module.A3_OVERAGE_BYTES,
            "proposed_batch_budget_bytes": module.PROPOSED_BATCH_BUDGET_BYTES,
            "a1_runner_sha256": module.A1_RUNNER_SHA256,
            "cargo_lock_sha256": module.EXPECTED_CARGO_LOCK_SHA256,
            "a2_protected_file_sha256": module.EXPECTED_A2_PROTECTED_SHA256,
            "development_fixtures_only": True,
            "validation_accessed": False,
            "holdout_accessed": False,
            "product_ab_authorized_before_this_result": False,
            "format_encoder_selector_changed": False,
        },
        "generations": [
            {"generation": 1, "reports": copy.deepcopy(reports)},
            {"generation": 2, "reports": copy.deepcopy(reports)},
        ],
        "summary": {
            "minimum_decoded_concurrency_potential_bytes": 120_000_000,
            "minimum_phase_correlated_rss_reduction_bytes": 110_000_000,
            "minimum_credited_bytes": 110_000_000,
            "gates": gates,
            "passed": True,
            "product_ab_authorized": True,
        },
    }


class JLS2DeclaredSizeLifetimeA3AttributionTests(unittest.TestCase):
    def test_frozen_identity_and_threshold(self) -> None:
        module = load_module()
        self.assertEqual(
            module.A2_COMMIT,
            "0f3377dff647e8a6d99b65d8f8a269687faa8ec6",
        )
        self.assertEqual(module.A2_BASELINE_RSS_BYTES, 657_682_432)
        self.assertEqual(module.ATTRIBUTION_THRESHOLD_BYTES, 105_202_484)
        self.assertEqual(module.PROPOSED_BATCH_BUDGET_BYTES, 32 * 1024 * 1024)
        self.assertEqual(module.EXPECTED_LOGICAL_CPUS, 4)
        self.assertEqual(module.EXPECTED_ZSTD["bundled-libzstd"], "1.5.7")
        self.assertEqual(len(module.EXPECTED_A2_PROTECTED_SHA256), 4)

    def test_report_schema_accepts_exact_complete_diagnostic(self) -> None:
        module = load_module()
        report = valid_report(module)
        module.validate_diagnostic_report(
            report,
            "jls2-context-stress-256",
            module.EXPECTED_FRAMES["jls2-context-stress-256"],
        )

    def test_report_rejects_encoded_lifetime_credit(self) -> None:
        module = load_module()
        report = valid_report(module)
        report["attribution"]["encoded_lifetime_authorization_credit_bytes"] = 1
        with self.assertRaisesRegex(ValueError, "encoded lifetime"):
            module.validate_diagnostic_report(
                report,
                "jls2-context-stress-256",
                module.EXPECTED_FRAMES["jls2-context-stress-256"],
            )

    def test_report_rejects_credit_above_frozen_minimum(self) -> None:
        module = load_module()
        report = valid_report(module)
        report["attribution"]["credited_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "frozen minimum"):
            module.validate_diagnostic_report(
                report,
                "jls2-context-stress-256",
                module.EXPECTED_FRAMES["jls2-context-stress-256"],
            )

    def test_protocol_and_workflow_preserve_no_ab_boundary(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("hosted_attribution_required", protocol)
        self.assertIn("105,202,484", protocol)
        self.assertIn("Encoded lifetime is report-only", protocol)
        self.assertIn("ubuntu-22.04", workflow)
        self.assertIn("--split development", workflow)
        self.assertNotIn("--split validation", workflow)
        self.assertNotIn("holdout", workflow.lower())
        self.assertIn("product A/B", protocol)
        self.assertNotIn("benchmark-jls2-declared-size", workflow)
        self.assertNotIn(
            'git merge-base --is-ancestor "$A2_COMMIT" HEAD', workflow
        )
        self.assertIn('git cat-file -e "$A2_COMMIT^{commit}"', workflow)
        self.assertIn('git worktree add --detach "$RUNNER_TEMP/a2-audit"', workflow)
        self.assertIn("intentionally not assumed to be an ancestor", workflow)

    def test_unrelated_lineage_cannot_weaken_protected_file_identity(self) -> None:
        module = load_module()
        module.validate_a2_protected_digests(
            dict(module.EXPECTED_A2_PROTECTED_SHA256)
        )
        changed = dict(module.EXPECTED_A2_PROTECTED_SHA256)
        changed["native/src/jls2.rs"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "ancestry is not accepted"):
            module.validate_a2_protected_digests(changed)

    def test_verifier_rejects_incomplete_hosted_identity(self) -> None:
        verifier = load_verifier()
        with self.assertRaisesRegex(ValueError, "result name"):
            verifier.validate_result({"schema_version": 1})

    def test_verifier_accepts_internally_complete_result(self) -> None:
        module = load_module()
        verifier = load_verifier()
        verifier.validate_result(valid_result(module))


if __name__ == "__main__":
    unittest.main()
