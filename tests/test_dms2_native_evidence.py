import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
EVIDENCE = REPOSITORY / "runs" / "dms2-native-development-gate-v1.json"
DECISION = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-dms2-native-development-gate.md"
)


class DMS2NativeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_ratio_speed_and_exactness_gates_are_machine_readable(self):
        aggregate = self.evidence["aggregate"]
        self.assertEqual(aggregate["complete_bytes"], 189_738)
        self.assertEqual(aggregate["bz2_9_bytes"], 200_311)
        self.assertTrue(aggregate["ratio_gate_passed"])
        self.assertTrue(aggregate["compression_gate_passed"])
        self.assertTrue(aggregate["decompression_gate_passed"])
        self.assertTrue(
            aggregate["exact_deterministic_corruption_gates_passed"]
        )
        self.assertEqual(aggregate["families_with_five_percent_gain"], 2)

    def test_archived_development_chart_and_current_failure_are_visible(self):
        decision = DECISION.read_text(encoding="utf-8")
        readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        public = (
            REPOSITORY / "runs" / "dms2-public-validation-v1" / "README.md"
        ).read_text(encoding="utf-8")
        for row in self.evidence["standards"]:
            label = {
                "bz2-9": "bzip2-9",
                "7zip-9": "7-zip-9",
                "tbl1-stream-dense": "tbs1 stream-dense",
            }.get(row["codec_id"], row["codec_id"])
            self.assertIn(label, decision.lower())
        self.assertIn("189,738", decision)
        self.assertIn("11,937,137", public)
        self.assertIn("43.55%", public)
        self.assertIn("DMS2 vs Brotli-11", readme)
        self.assertIn("43.55% larger", readme)
        self.assertIn("dms2-public-validation-v1/README.md", readme)
        self.assertEqual(self.evidence["public_validation"], "unopened")
        self.assertEqual(self.evidence["private_holdout"], "sealed")
        self.assertGreater(len(self.evidence["remaining_gates"]), 0)


if __name__ == "__main__":
    unittest.main()
