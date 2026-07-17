from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
RUN = REPOSITORY / "runs" / "clue-jls2-decode-scheduling-v1"


class ClueJls2DecodeSchedulingEvidenceTests(unittest.TestCase):
    def test_rejected_topology_result_is_complete_and_bound(self) -> None:
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        results = json.loads((RUN / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "rejected")
        self.assertIsNone(receipt["selected_variant"])
        self.assertEqual(receipt["retained_variant"], "outer2-innerauto")
        self.assertGreater(receipt["baseline_parent_median_mbps"], 250)
        self.assertGreater(receipt["baseline_worker_minimum_mbps"], 250)
        self.assertFalse(results["git"]["dirty"])
        self.assertEqual(len(results["trials"]), 96)
        self.assertTrue(all(trial["exact"] for trial in results["trials"]))
        self.assertIsNone(results["summary"]["selected_variant"])
        for name, expected in receipt["artifacts"].items():
            self.assertEqual(
                hashlib.sha256((RUN / name).read_bytes()).hexdigest(), expected
            )

    def test_public_chart_and_claim_boundary_are_visible(self) -> None:
        report = (RUN / "README.md").read_text(encoding="utf-8")
        root = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        for value in ("330.40", "604.37", "380.60", "267.04"):
            self.assertIn(value, report)
        self.assertIn("scheduling hypothesis rejected", report)
        self.assertIn("public-validation ranges remain unmaterialized", report)
        self.assertIn("clue-jls2-decode-scheduling-v1/README.md", root)


if __name__ == "__main__":
    unittest.main()
