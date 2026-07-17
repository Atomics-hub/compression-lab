import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "runs" / "tbl1-dense-development-decision-v1.json"


class Tbl1DenseEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_point_metrics_pass_without_overstating_complete_gate(self) -> None:
        self.assertNotEqual(self.result["overall_gate"], "passed")
        self.assertTrue(self.result["point_metrics_pass"])
        candidate = self.result["candidate_result"]
        self.assertEqual(candidate["complete_bytes"], 12_012_933)
        self.assertEqual(candidate["repetitions"], 5)
        self.assertEqual(candidate["exact_roundtrips"], 20)
        self.assertGreaterEqual(candidate["compression_mbps"], 50)
        self.assertGreaterEqual(candidate["decompression_mbps"], 250)
        self.assertLessEqual(candidate["compression_peak_rss_mib"], 512)
        self.assertEqual(
            sum(family["family_gate_pass"] for family in self.result["families"]),
            3,
        )

    def test_open_gates_remain_machine_readable(self) -> None:
        gates = self.result["gates"]
        self.assertFalse(gates["stable_margin_pass"])
        self.assertFalse(gates["bounded_streaming_pass"])
        self.assertFalse(gates["large_file_pass"])
        self.assertFalse(gates["public_validation_pass"])
        self.assertFalse(gates["independent_reproduction_pass"])
        self.assertFalse(self.result["corpus"]["public_validation_opened"])

    def test_public_summary_names_each_compared_standard(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        decision = (
            ROOT
            / "docs"
            / "benchmarks"
            / "2026-07-16-tbl1-dense-development-decision.md"
        ).read_text(encoding="utf-8")
        for standard in (
            "Brotli-11",
            "LZMA-9",
            "7-Zip-9",
            "zstd-19",
            "bzip2-9",
            "zstd-9",
            "gzip-9",
            "zstd-3",
            "LZ4-1",
            "store",
        ):
            self.assertIn(standard, readme)
            self.assertIn(standard, decision)
        self.assertIn("category is **not\npassed**", readme)


if __name__ == "__main__":
    unittest.main()
