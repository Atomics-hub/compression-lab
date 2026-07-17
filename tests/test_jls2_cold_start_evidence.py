from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "jls2-cold-start-v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class JLS2ColdStartEvidenceTests(unittest.TestCase):
    def test_rejected_gate_is_complete_exact_and_machine_readable(self) -> None:
        result = json.loads((RUN / "results.json").read_text(encoding="utf-8"))
        summary = result["summary"]
        self.assertEqual(result["protocol"], "jls2-cold-start-v1")
        self.assertEqual(len(result["trials"]), 96)
        self.assertEqual(
            sum(not trial["warmup"] for trial in result["trials"]), 84
        )
        self.assertTrue(all(trial["exact"] for trial in result["trials"]))
        self.assertFalse(summary["candidate_qualifies"])
        self.assertTrue(summary["gates"]["encoded_identity"])
        self.assertEqual(
            {row["bytes"] for row in result["frames"].values()},
            {1_382_653, 738_259, 1_402_809},
        )

    def test_public_chart_retains_wins_losses_and_claim_boundary(self) -> None:
        report = (RUN / "README.md").read_text(encoding="utf-8")
        chart = (RUN / "cold-start-scorecard.svg").read_text(encoding="utf-8")
        root = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (
            "11.83%",
            "2/7",
            "3/7",
            "-8.10%",
            "71.00% faster",
            "immutable same-run 11-codec census remains",
            "unmaterialized and unopened",
            "not public validation",
        ):
            self.assertIn(text, report.lower())
        self.assertIn("candidate rejected", chart)
        self.assertIn("frozen target", chart)
        self.assertIn("standards census unchanged", chart)
        self.assertIn("jls2-cold-start-v1/README.md", root)

    def test_receipt_binds_artifacts_and_publication_sources(self) -> None:
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["decision"], "lazy-loading-retained-decode-gate-failed"
        )
        self.assertEqual(
            receipt["candidate_product_commit"],
            "604271cbc89a11c739848f68a7739ed523fb9a1b",
        )
        for relative, expected in receipt["artifacts"].items():
            self.assertEqual(sha256_file(ROOT / relative), expected)
        for relative, expected in receipt["publication_sources"].items():
            self.assertEqual(sha256_file(ROOT / relative), expected)


if __name__ == "__main__":
    unittest.main()
