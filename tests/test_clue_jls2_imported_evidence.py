from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "runs" / "clue-jls2-public-validation-v1"
PUBLICATION = EVIDENCE / "publication"
IMPORT_RECEIPT = ROOT / "runs" / "clue-jls2-public-validation-v1-import.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ClueJLS2ImportedEvidenceTests(unittest.TestCase):
    def test_import_receipt_binds_the_exact_github_artifact(self) -> None:
        receipt = json.loads(IMPORT_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(receipt["workflow_run_id"], 29606109504)
        self.assertEqual(receipt["artifact_id"], 8418445259)
        self.assertEqual(
            receipt["artifact_digest"],
            "sha256:03d39e93c037b25397fa6750d2d4d30da08eedafcc9ef7b8f0c66b140b6047a3",
        )
        self.assertEqual(
            receipt["workflow_head_sha"],
            "b9cdc9e797b36709ba4c17c23a4c6585670254e3",
        )
        self.assertEqual(receipt["result"], "not_passed")
        self.assertFalse(receipt["category_gate_passed"])
        self.assertEqual(receipt["file_count_excluding_sha256sums"], 42)
        self.assertEqual(receipt["decision_sha256"], digest(EVIDENCE / "decision.json"))

    def test_all_imported_files_match_the_retained_checksum_manifest(self) -> None:
        expected: dict[str, str] = {}
        for line in (EVIDENCE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            checksum, relative = line.split("  ./", 1)
            self.assertNotIn(relative, expected)
            expected[relative] = checksum
        observed = {
            path.relative_to(EVIDENCE).as_posix()
            for path in EVIDENCE.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        }
        self.assertEqual(set(expected), observed)
        for relative, checksum in expected.items():
            self.assertEqual(digest(EVIDENCE / relative), checksum, relative)

    def test_publication_and_live_claims_match_the_frozen_no_pass(self) -> None:
        decision = json.loads((PUBLICATION / "decision.json").read_text(encoding="utf-8"))
        aggregate = decision["aggregate"]
        self.assertEqual(aggregate["original_bytes"], 96_934_483)
        self.assertEqual(aggregate["candidate_bytes"], 489_591)
        self.assertEqual(aggregate["strongest_eligible_codec"], "brotli-11")
        self.assertEqual(aggregate["strongest_eligible_bytes"], 1_040_990)
        self.assertAlmostEqual(aggregate["gain_vs_strongest_eligible_percent"], 52.9687, places=4)
        self.assertFalse(decision["gate_results"]["decompression_memory"])
        self.assertTrue(
            all(
                passed
                for gate, passed in decision["gate_results"].items()
                if gate != "decompression_memory"
            )
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("52.97% smaller", readme)
        self.assertIn("621.3 MiB", readme)
        self.assertIn("only miss", readme)
        self.assertIn("overall product gate is still an honest **no-pass**", readme)


if __name__ == "__main__":
    unittest.main()
