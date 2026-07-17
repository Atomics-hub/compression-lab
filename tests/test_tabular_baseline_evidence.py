import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SUMMARY = REPOSITORY / "runs" / "tabular-development-baseline-census.json"
DECISION = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-16-tabular-baseline-census.md"
)


class TabularBaselineEvidenceTests(unittest.TestCase):
    def test_discovery_boundary_and_complete_baseline_roster_are_visible(self):
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        self.assertEqual(summary["stage"], "development-baseline-census")
        self.assertEqual(summary["overall_gate"], "unscored")
        self.assertIsNone(summary["candidate"])
        self.assertTrue(summary["evidence"]["git_dirty"])
        self.assertEqual(summary["evidence"]["roundtrip_failures"], 0)
        self.assertEqual(len(summary["standards"]), 10)
        self.assertEqual(summary["corpus"]["public_validation"], "unopened")
        self.assertEqual(summary["corpus"]["private_holdout"], "sealed")

    def test_markdown_contains_every_committed_standard_result(self):
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        decision = DECISION.read_text(encoding="utf-8")
        for standard in summary["standards"]:
            self.assertIn(f"{standard['complete_bytes']:,}", decision)
        self.assertIn(summary["evidence"]["source_results_sha256"], decision)
        self.assertIn(summary["corpus"]["manifest_sha256"], decision)


if __name__ == "__main__":
    unittest.main()
