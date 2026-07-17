import hashlib
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
RUN = REPOSITORY / "runs" / "clue-json-log-development-census-v1"
CONFIG = REPOSITORY / "config" / "clue-json-log-corpus-v1.json"
PUBLISHER = REPOSITORY / "scripts" / "publish-clue-json-log-census.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ClueJsonCensusEvidenceTests(unittest.TestCase):
    def test_chart_is_complete_exact_and_bound(self):
        comparison = json.loads((RUN / "comparison.json").read_text(encoding="utf-8"))
        results = RUN / "results.json"
        self.assertEqual(comparison["source"]["results_sha256"], sha256(results))
        self.assertEqual(len(comparison["comparison_rows"]), 11)
        self.assertTrue(comparison["gate_results"]["all_99_roundtrips"])
        self.assertTrue(
            all(row["roundtrip_verified"] for row in comparison["comparison_rows"])
        )
        self.assertEqual(comparison["strongest_standard"]["codec_id"], "brotli-11")
        self.assertAlmostEqual(
            comparison["strongest_standard"]["jls2_gain_percent"],
            18.08268074032711,
        )
        self.assertTrue(comparison["gate_results"]["jls2_smallest_every_family"])

    def test_failed_decode_gate_and_claim_boundary_are_visible(self):
        comparison = json.loads((RUN / "comparison.json").read_text(encoding="utf-8"))
        readme = (RUN / "README.md").read_text(encoding="utf-8")
        self.assertEqual(comparison["result"], "not_passed")
        self.assertFalse(comparison["category_gate_passed"])
        self.assertFalse(
            comparison["gate_results"]["minimum_250_mbps_aggregate_decompression"]
        )
        self.assertIn("complete category gate not passed", readme)
        self.assertIn("development evidence only", comparison["claim_ceiling"])
        for row in comparison["comparison_rows"]:
            self.assertIn(row["codec_id"], readme)

    def test_validation_stays_unopened_and_receipt_hashes_every_artifact(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        for row in config["selection"]["public_validation"]:
            self.assertIsNone(row["size_bytes"])
            self.assertIsNone(row["sha256"])
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        for name, digest in receipt["artifacts"].items():
            self.assertEqual(digest, sha256(RUN / name))
        self.assertEqual(receipt["publisher_source_sha256"], sha256(PUBLISHER))


if __name__ == "__main__":
    unittest.main()
