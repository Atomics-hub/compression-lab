from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "config" / "compression-category-matrix.json"
STATUS = ROOT / "docs" / "benchmarks" / "2026-07-16-category-portfolio-status.md"
STATUS_LABELS = {
    "json_logs": "JSON and machine logs",
    "source_code_bundles": "Source-code bundles",
    "english_wikimedia_wikitext": "English Wikimedia wikitext",
    "tabular_csv": "Tabular CSV",
    "numeric_timeseries": "Dense numeric matrices and time series",
    "general_binary_archive": "General binary/archive",
    "incompressible_precompressed": "Incompressible/already compressed",
}


class CategoryCompletionScorecardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))

    def test_every_category_uses_the_same_ten_binary_gates(self) -> None:
        definitions = self.portfolio["completion_gate_definitions"]
        gate_ids = [row["id"] for row in definitions]
        self.assertEqual(len(gate_ids), 10)
        self.assertEqual(len(set(gate_ids)), 10)
        self.assertEqual(sum(row["weight_percent"] for row in definitions), 100)
        for category in self.portfolio["categories"]:
            gates = category["completion_gates"]
            self.assertEqual(set(gates), set(gate_ids))
            self.assertTrue(all(type(value) is bool for value in gates.values()))
            self.assertEqual(
                category["readiness_percent"],
                sum(row["weight_percent"] for row in definitions if gates[row["id"]]),
            )
        average = sum(
            row["readiness_percent"] for row in self.portfolio["categories"]
        ) / len(self.portfolio["categories"])
        self.assertAlmostEqual(
            self.portfolio["category_evidence_completion_percent"],
            average,
            places=2,
        )

    def test_one_hundred_percent_requires_holdout_and_independent_reproduction(
        self,
    ) -> None:
        policy = self.portfolio["completion_policy"].lower()
        self.assertIn("private holdout", policy)
        self.assertIn("independent reproduction", policy)
        for category in self.portfolio["categories"]:
            if category["readiness_percent"] == 100:
                self.assertTrue(category["completion_gates"]["private_holdout_pass"])
                self.assertTrue(
                    category["completion_gates"]["independent_reproduction"]
                )

    def test_failed_public_validation_never_receives_complete_pass_credit(self) -> None:
        categories = {row["id"]: row for row in self.portfolio["categories"]}
        for category_id in ("json_logs", "tabular_csv", "numeric_timeseries"):
            category = categories[category_id]
            self.assertEqual(category["status"], "public-validation-partial")
            self.assertFalse(
                category["completion_gates"]["public_validation_complete_pass"]
            )
        self.assertEqual(categories["json_logs"]["readiness_percent"], 50)

    def test_no_category_is_currently_mislabeled_complete(self) -> None:
        for category in self.portfolio["categories"]:
            self.assertLess(category["readiness_percent"], 100)
            self.assertFalse(category["completion_gates"]["private_holdout_pass"])
            self.assertFalse(category["completion_gates"]["independent_reproduction"])

    def test_human_readable_portfolio_matches_machine_percentages(self) -> None:
        status = STATUS.read_text(encoding="utf-8")
        self.assertIn(
            f"**{self.portfolio['category_evidence_completion_percent']:.2f}%**",
            status,
        )
        for category in self.portfolio["categories"]:
            row = re.escape(
                f"| {STATUS_LABELS[category['id']]} | "
                f"**{category['readiness_percent']}%** |"
            )
            self.assertRegex(status, row)


if __name__ == "__main__":
    unittest.main()
