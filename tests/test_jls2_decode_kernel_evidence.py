import hashlib
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
RUN = REPOSITORY / "runs" / "jls2-decode-kernel-development-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class JLS2DecodeKernelEvidenceTests(unittest.TestCase):
    def test_receipt_binds_artifacts_and_current_sources(self):
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        ab = json.loads((RUN / "ab-result.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["gate"], "jls2-decode-kernel-development-v1")
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(ab["passed"])
        self.assertEqual(receipt["base_commit"], ab["base"]["commit"])
        self.assertEqual(receipt["candidate_commit"], ab["candidate"]["commit"])
        for name, expected in receipt["artifact_sha256"].items():
            self.assertEqual(digest(RUN / name), expected)
        self.assertEqual(
            receipt["publisher_sha256"],
            digest(REPOSITORY / "scripts" / "publish-jls2-decode-kernel.py"),
        )
        for relative, expected in ab["candidate"]["source_sha256"].items():
            self.assertEqual(digest(REPOSITORY / relative), expected)

    def test_exact_bytes_speed_gate_and_public_chart(self):
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        aggregate = receipt["aggregate_byte_api"]
        self.assertEqual(aggregate["candidate_rounds_at_or_above_250_mbps"], 7)
        self.assertGreater(aggregate["median_paired_improvement_percent"], 20)
        self.assertEqual(
            receipt["aggregate_product"]["encoded_bytes_unchanged"], 2_693_313
        )
        self.assertTrue(all(receipt["candidate_product_gates"].values()))

        report = (RUN / "README.md").read_text(encoding="utf-8")
        root = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        self.assertIn("21.66%", report)
        self.assertIn("7/7", report)
        self.assertIn("does not change the retained JLS2 public-validation failure", report)
        self.assertIn("jls2-decode-kernel-development-v1/README.md", root)
        self.assertIn("## Measured standings", root)
        self.assertNotIn("## Current limitations", root)


if __name__ == "__main__":
    unittest.main()
