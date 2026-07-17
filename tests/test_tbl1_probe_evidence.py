import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class TBL1ProbeEvidenceTests(unittest.TestCase):
    def test_probe_result_retains_strict_claim_boundary(self):
        result = json.loads(
            (
                REPOSITORY / "runs" / "tbl1-column-transpose-probe-v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(result["stage"], "development-probe")
        self.assertTrue(result["evidence"]["git_dirty"])
        self.assertEqual(result["aggregate"]["families_with_size_win"], 3)
        self.assertTrue(result["aggregate"]["exact_roundtrip"])
        self.assertGreater(
            result["aggregate"]["gain_vs_direct_zstd19_percent"], 20.0
        )
        self.assertEqual(result["families"][-1]["backend"], "direct-zstd")
        self.assertIn("product", result["claim_ceiling"])
        self.assertIn("not a full-corpus", result["claim_ceiling"])


if __name__ == "__main__":
    unittest.main()
