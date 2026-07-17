from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "config" / "log-competitor-reproduction-v1.json"
PORTFOLIO = ROOT / "config" / "compression-category-matrix.json"


class LogCompetitorAuditTests(unittest.TestCase):
    def test_current_standards_and_emerging_specialists_are_visible(self) -> None:
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(audit["schema_version"], 2)
        self.assertEqual(audit["audited_at"], "2026-07-17")
        standards = {
            row["codec_id"]: row["version"]
            for row in audit["current_standard_roster"]
        }
        self.assertEqual(standards["zstd-3/zstd-9/zstd-19"], "1.5.7")
        self.assertEqual(standards["brotli-11"], "1.2.0")
        self.assertEqual(standards["lz4-1"], "1.10.0")
        self.assertEqual(standards["7zip-9"], "26.02")
        competitors = {row["name"]: row for row in audit["competitors"]}
        self.assertEqual(
            competitors["LogFold"]["commit"],
            "1832f4f380e360dd12d098d987e8c0f6dcc1f3cf",
        )
        self.assertIn("only LICENSE and README.md", competitors["LogFold"]["local_status"])
        self.assertIsNone(competitors["LogPrism"]["commit"])
        self.assertIn("repository is empty", competitors["LogPrism"]["local_status"])
        self.assertTrue(audit["eligibility_policy"]["unavailable_is_not_a_win"])
        self.assertEqual(
            set(audit["eligibility_policy"]["recheck_before_public_validation"]),
            {"LogFold", "LogPrism", "LogLite", "DeLog"},
        )

    def test_json_log_portfolio_advances_only_the_development_product_gate(self) -> None:
        portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        category = next(
            row for row in portfolio["categories"] if row["id"] == "json_logs"
        )
        self.assertEqual(category["status"], "public-validation-partial")
        self.assertIn("standalone decoder", category["current_result"].lower())
        self.assertIn("remain sealed", category["current_result"].lower())
        self.assertIn("maximum of one scored attempt", category["next_gate"])
        self.assertIn("7-Zip-9", category["tested_standards"])


if __name__ == "__main__":
    unittest.main()
