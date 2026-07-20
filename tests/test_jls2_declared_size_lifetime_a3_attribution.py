from __future__ import annotations

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


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_a3_attribution", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load JLS2 A3 attribution runner")
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
            "encoded_lifetime_authorization_credit_bytes": 0,
            "unclassified_resident_bytes": 1,
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


if __name__ == "__main__":
    unittest.main()
