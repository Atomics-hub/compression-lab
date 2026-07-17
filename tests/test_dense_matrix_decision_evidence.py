import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
EVIDENCE = REPOSITORY / "runs" / "dense-matrix-representation-development-decision-v1.json"
DECISION = REPOSITORY / "docs" / "benchmarks" / "2026-07-17-dense-matrix-representation-decision.md"


class DenseMatrixDecisionEvidenceTests(unittest.TestCase):
    def test_ratio_pass_and_operational_failure_are_both_visible(self):
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        selector = next(row for row in evidence["hypotheses"] if row["id"] == "DMS1")
        self.assertEqual(selector["aggregate_bytes"], 177_434)
        self.assertEqual(selector["families_with_five_percent_gain"], 2)
        self.assertTrue(selector["ratio_gate_passed"])
        self.assertFalse(selector["operational_gate_passed"])
        self.assertEqual(evidence["corpus"]["public_validation"], "unopened")

    def test_chart_and_claim_ceiling_are_synchronized(self):
        decision = DECISION.read_text(encoding="utf-8")
        self.assertIn("11.42% smaller", decision)
        self.assertIn("The product candidate does not yet pass", decision)
        self.assertIn("Public validation remains unopened", decision)
        self.assertIn("no category-best", decision)


if __name__ == "__main__":
    unittest.main()
