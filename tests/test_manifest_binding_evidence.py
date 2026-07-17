import hashlib
import json
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
RUN = REPOSITORY / "runs" / "benchmark-manifest-binding-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManifestBindingEvidenceTests(unittest.TestCase):
    def test_receipt_is_complete_and_bound_to_current_sources(self):
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["gate"], "benchmark-manifest-binding-v1")
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["summary"], {"failed": 0, "passed": 9, "total": 9})
        self.assertEqual(len(receipt["checks"]), 9)
        self.assertTrue(all(row["status"] == "pass" for row in receipt["checks"]))

        identity = receipt["runner_identity"]
        self.assertEqual(identity["api_version"], 2)
        self.assertEqual(
            identity["source_sha256"],
            digest(REPOSITORY / "src" / "compresslab" / "benchmark_runner.py"),
        )
        self.assertEqual(
            identity["legacy_runner_source_sha256"],
            digest(REPOSITORY / "src" / "compresslab" / "runner.py"),
        )
        self.assertEqual(
            identity["corpus_loader_source_sha256"],
            digest(REPOSITORY / "src" / "compresslab" / "corpus.py"),
        )

    def test_public_chart_and_claim_ceiling_are_visible(self):
        report = (RUN / "README.md").read_text(encoding="utf-8")
        root_readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        self.assertIn("passed, 9/9 controls", report)
        self.assertIn("Previous behavior", report)
        self.assertIn("Hardened behavior", report)
        self.assertIn("does **not** prove", report)
        self.assertIn("benchmark-manifest-binding-v1/README.md", root_readme)


if __name__ == "__main__":
    unittest.main()
