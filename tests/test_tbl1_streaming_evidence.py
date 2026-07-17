import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "runs" / "tbl1-streaming-development-decision-v1.json"


class Tbl1StreamingEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_streaming_gate_pass_does_not_overstate_category(self) -> None:
        self.assertEqual(self.result["development_streaming_gate"], "passed")
        self.assertNotEqual(self.result["overall_category_gate"], "passed")
        candidate = self.result["candidate_result"]
        self.assertEqual(candidate["complete_bytes"], 12_134_137)
        self.assertLessEqual(
            candidate["size_regression_vs_whole_file_percent"], 2.0
        )
        self.assertGreaterEqual(candidate["compression_mbps"], 50.0)
        self.assertGreaterEqual(candidate["decompression_mbps"], 250.0)
        self.assertGreaterEqual(
            candidate["minimum_repetition_compression_mbps"], 50.0
        )
        self.assertGreaterEqual(
            candidate["minimum_repetition_decompression_mbps"], 250.0
        )
        self.assertLessEqual(candidate["cold_compression_peak_rss_mib"], 512.0)
        self.assertEqual(candidate["repetitions"], 5)
        self.assertEqual(candidate["exact_roundtrips"], 20)
        self.assertEqual(
            sum(family["family_gate_pass"] for family in self.result["families"]),
            3,
        )

    def test_large_file_and_open_gates_are_explicit(self) -> None:
        large = self.result["large_file"]
        self.assertGreaterEqual(large["source_bytes"], 1024 * 1024 * 1024)
        self.assertTrue(large["exact_roundtrip"])
        self.assertLessEqual(large["compression_peak_rss_mib"], 512.0)
        self.assertLessEqual(large["decompression_peak_rss_mib"], 512.0)
        gates = self.result["gates"]
        self.assertTrue(gates["large_file_pass"])
        self.assertTrue(gates["portable_reference_decoder_pass"])
        self.assertTrue(gates["enforced_direct_store_fallback_pass"])
        self.assertFalse(gates["public_validation_pass"])
        self.assertFalse(gates["independent_reproduction_pass"])
        self.assertFalse(self.result["corpus"]["public_validation_opened"])

    def test_public_chart_lists_every_comparison(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        decision = (
            ROOT
            / "docs"
            / "benchmarks"
            / "2026-07-16-tbl1-streaming-development-decision.md"
        ).read_text(encoding="utf-8")
        public_standards = (
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
        )
        for standard in public_standards:
            self.assertIn(standard, readme)
            self.assertIn(standard, decision)
        self.assertIn("TBL1-dense whole-file", decision)
        self.assertIn("overall frozen gate was **not passed**", readme)
        self.assertIn("268,432,956 previously unseen UCI table bytes", readme)


if __name__ == "__main__":
    unittest.main()
