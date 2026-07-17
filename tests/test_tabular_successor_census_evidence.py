import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
RESULTS = (
    REPOSITORY
    / "runs"
    / "tabular-successor-development-census-v1"
    / "results.json"
)
DECISION = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-tabular-successor-development-census.md"
)


class TabularSuccessorCensusEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = json.loads(RESULTS.read_text(encoding="utf-8"))

    def test_complete_exact_roster_is_retained(self):
        expected = {
            "store",
            "lz4-1",
            "gzip-9",
            "bz2-9",
            "zstd-3",
            "zstd-9",
            "zstd-19",
            "brotli-11",
            "lzma-9",
            "7zip-9",
            "tbl1-stream-dense",
        }
        self.assertEqual({row["codec_id"] for row in self.results["summary"]}, expected)
        self.assertEqual(len(self.results["trials"]), 66)
        self.assertEqual(self.results["failures"], [])
        self.assertTrue(all(row["roundtrip_ok"] for row in self.results["trials"]))
        self.assertEqual(sum(item["size_bytes"] for item in self.results["corpus"]), 18_635_606)

    def test_chart_numbers_and_claim_boundary_are_visible(self):
        summary = {row["codec_id"]: row for row in self.results["summary"]}
        self.assertEqual(summary["tbl1-stream-dense"]["compressed_bytes"], 1_697_505)
        self.assertEqual(summary["bz2-9"]["compressed_bytes"], 1_650_170)
        self.assertEqual(summary["lzma-9"]["compressed_bytes"], 1_693_160)
        decision = DECISION.read_text(encoding="utf-8")
        readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        for text in (
            "2.87% larger",
            "0.26% larger",
            "59.88% larger",
            "one local development trial",
        ):
            self.assertIn(text, decision)
        self.assertIn("Fresh successor development checkpoint", readme)
        self.assertIn("2.87% larger", readme)
        self.assertIn("not validation", readme)


if __name__ == "__main__":
    unittest.main()
