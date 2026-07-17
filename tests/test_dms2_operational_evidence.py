import hashlib
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SPEED = REPOSITORY / "runs" / "dms2-safe-selector-development-gate-v2.json"
OPERATIONAL = REPOSITORY / "runs" / "dms2-operational-development-gate-v1.json"
CROSS_PLATFORM = REPOSITORY / "runs" / "dms2-cross-platform-ci-receipt-v1.json"
DECISION = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-dms2-native-development-gate.md"
)


class DMS2OperationalEvidenceTests(unittest.TestCase):
    def test_all_local_gates_pass_without_opening_validation(self):
        speed = json.loads(SPEED.read_text(encoding="utf-8"))
        operational = json.loads(OPERATIONAL.read_text(encoding="utf-8"))
        self.assertTrue(operational["gate_results"]["all_passed"])
        self.assertTrue(speed["aggregate"]["ratio_gate_passed"])
        self.assertTrue(speed["aggregate"]["compression_gate_passed"])
        self.assertTrue(speed["aggregate"]["decompression_gate_passed"])
        self.assertEqual(
            speed["remaining_gates"],
            ["portable wheel verification on Linux and Windows"],
        )
        self.assertEqual(speed["public_validation"], "unopened")
        self.assertEqual(speed["private_holdout"], "sealed")

    def test_operational_receipt_is_bound_and_complete(self):
        speed = json.loads(SPEED.read_text(encoding="utf-8"))
        digest = hashlib.sha256(OPERATIONAL.read_bytes()).hexdigest()
        self.assertEqual(speed["operational_evidence_sha256"], digest)
        operational = json.loads(OPERATIONAL.read_text(encoding="utf-8"))
        self.assertEqual(
            operational["record_table_regression"]["regression_percent"], 0.0
        )
        self.assertTrue(
            all(
                row["oracle_selected"] and row["no_expansion_vs_direct"]
                for row in operational["selector"]["rows"]
            )
        )
        self.assertLess(
            max(
                row[operation]["maximum_resident_set_bytes"]
                for row in operational["frame_memory"]
                for operation in ("compression", "decompression")
            ),
            operational["memory_ceiling_bytes"],
        )

    def test_public_chart_matches_machine_readable_evidence(self):
        speed = json.loads(SPEED.read_text(encoding="utf-8"))
        decision = DECISION.read_text(encoding="utf-8")
        readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        self.assertEqual(speed["aggregate"]["complete_bytes"], 189_738)
        for text in (decision, readme):
            self.assertIn("54.85", text)
            self.assertIn("268.18", text)
            self.assertIn("5.28% smaller", text)
            self.assertIn("not a world-best claim", text)

    def test_cross_platform_receipt_binds_green_jobs_and_source(self):
        receipt = json.loads(CROSS_PLATFORM.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["tested_commit"],
            "4e816ca37b7e9d7b639b474d7dedc4ac077df8b4",
        )
        self.assertEqual(
            {run["event"] for run in receipt["successful_runs"]},
            {"push", "pull_request"},
        )
        self.assertEqual(
            set(receipt["platform_jobs"]), {"linux", "macos", "windows"}
        )
        self.assertTrue(
            all(
                jobs["full_suite"]["conclusion"] == "success"
                and jobs["native_wheel"]["conclusion"] == "success"
                for jobs in receipt["platform_jobs"].values()
            )
        )
        for path, expected in receipt["source_sha256"].items():
            self.assertEqual(
                hashlib.sha256((REPOSITORY / path).read_bytes()).hexdigest(),
                expected,
            )


if __name__ == "__main__":
    unittest.main()
