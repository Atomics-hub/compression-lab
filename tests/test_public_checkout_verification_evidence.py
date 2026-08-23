from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
RUN = REPOSITORY / "runs" / "public-checkout-verification-v1"
AUDIT = REPOSITORY / "scripts" / "audit-public-checkout-verification.py"
GUARDED_TESTS = (
    "tests/test_clue_jls2_validation_lock.py",
    "tests/test_dms2_public_validation.py",
    "tests/test_tbl1_public_validation.py",
    "tests/test_text_source_development_evidence.py",
    "tests/test_jls2_native_decoder_evidence.py",
    "tests/test_jls2_cold_start_evidence.py",
)
NUMERIC_TEST = "tests/test_numeric_ar5_numr_prototype.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicCheckoutVerificationEvidenceTests(unittest.TestCase):
    def test_receipt_is_complete_and_bound_to_current_sources(self) -> None:
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["gate"], "public-checkout-verification-v1")
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(
            receipt["summary"], {"failed": 0, "passed": 18, "total": 18}
        )
        self.assertEqual(len(receipt["checks"]), 18)
        self.assertTrue(all(row["status"] == "pass" for row in receipt["checks"]))

        identity = receipt["runner_identity"]
        self.assertEqual(identity["audit_script_sha256"], digest(AUDIT))
        self.assertEqual(
            identity["guarded_test_sha256"],
            {
                relative: digest(REPOSITORY / relative)
                for relative in GUARDED_TESTS
            },
        )
        self.assertEqual(
            identity["numeric_test_sha256"], digest(REPOSITORY / NUMERIC_TEST)
        )

    def test_public_record_and_claim_ceiling_are_visible(self) -> None:
        report = (RUN / "README.md").read_text(encoding="utf-8")
        root_readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        self.assertIn("passed, 18/18 controls", report)
        self.assertIn("does **not** prove", report)
        self.assertIn("public-checkout-verification-v1/README.md", root_readme)


if __name__ == "__main__":
    unittest.main()
