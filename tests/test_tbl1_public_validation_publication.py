import hashlib
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
BUNDLE = REPOSITORY / "runs" / "tbl1-public-validation-v1"
DECISION = BUNDLE / "decision.json"
RECEIPT = BUNDLE / "receipt.json"
MANIFEST = BUNDLE / "manifest.json"
PERFORMANCE = BUNDLE / "performance" / "results.json"
MEMORY = BUNDLE / "memory" / "results.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TBL1PublicValidationPublicationTests(unittest.TestCase):
    def test_immutable_first_score_bundle_and_decision(self):
        self.assertEqual(
            digest(DECISION),
            "baf0cd9421e726bf0b51a29fbe3a57f84f109b0907d695b53f86ca0dbfe0b7a5",
        )
        self.assertEqual(
            digest(RECEIPT),
            "16656332e6d5ecadaee3e555122a8540037e6b9dcefc91e5ef15fc0115bea5d8",
        )
        self.assertEqual(
            digest(MANIFEST),
            "cf1c045f8c8ddbc19e2ca3d729a55e305263bc35eb03a4e2f2c8b7fc4e763f99",
        )

        decision = json.loads(DECISION.read_text(encoding="utf-8"))
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        performance = json.loads(PERFORMANCE.read_text(encoding="utf-8"))
        memory = json.loads(MEMORY.read_text(encoding="utf-8"))

        self.assertFalse(decision["passed"])
        self.assertEqual(decision["status"], "not_passed")
        self.assertFalse(decision["gate_results"]["aggregate_ratio"])
        self.assertTrue(decision["gate_results"]["family_ratio_count"])
        self.assertFalse(
            decision["gate_results"]["minimum_repetition_decompression_speed"]
        )
        self.assertEqual(len(decision["comparison_chart"]), 11)
        self.assertEqual(len(decision["families"]), 4)
        self.assertEqual(sum(row["passed"] for row in decision["families"]), 3)

        self.assertTrue(receipt["completed"])
        self.assertEqual(receipt["performance_results_sha256"], digest(PERFORMANCE))
        self.assertEqual(receipt["memory_results_sha256"], digest(MEMORY))
        self.assertEqual(len(receipt["deterministic_proof"]), 4)
        self.assertEqual(len(performance["trials"]), 220)
        self.assertEqual(performance["failures"], [])
        self.assertEqual(len(memory["trials"]), 4)
        self.assertEqual(memory["failures"], [])


if __name__ == "__main__":
    unittest.main()
