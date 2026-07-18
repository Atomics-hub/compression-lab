import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPOSITORY
    / "scripts"
    / "verify-text-source-record-neighborhood-publication.py"
)
PUBLICATION = (
    REPOSITORY
    / "runs"
    / "text-source-record-neighborhood-screen-v1"
    / "publication"
)
BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)
SPEC = importlib.util.spec_from_file_location(
    "record_neighborhood_publication_verifier", SCRIPT
)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import {SCRIPT}")
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class RecordNeighborhoodPublicationVerifierTests(unittest.TestCase):
    def test_checked_in_publication_reconstructs_offline(self) -> None:
        result = verifier.verify(PUBLICATION, BASELINE_PUBLICATION)
        self.assertTrue(result["verified"])
        self.assertEqual(result["trial_count"], 8)
        self.assertEqual(result["standards_per_track"], 15)
        self.assertEqual(result["candidates_per_track"], 1)
        self.assertFalse(result["axiom_prototype_admitted"])
        self.assertEqual(result["axiom_wins"], 0)

    def test_rewritten_receipt_cannot_bless_an_edited_chart(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            copied = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, copied)
            comparison_path = copied / "comparison.json"
            comparison = json.loads(comparison_path.read_bytes())
            comparison["tracks"][0]["rows"][-1]["axiom_beat"] = "fabricated win"
            comparison_path.write_bytes(verifier.PUBLICATION.json_bytes(comparison))
            receipt_path = copied / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["comparison.json"] = verifier.PUBLICATION.sha256_file(
                comparison_path
            )
            receipt_path.write_bytes(verifier.PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "comparison does not reconstruct"):
                verifier.verify(copied, BASELINE_PUBLICATION)

    def test_extra_file_and_noncanonical_evidence_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            copied = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, copied)
            (copied / "extra.txt").write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file roster"):
                verifier.verify(copied, BASELINE_PUBLICATION)
            (copied / "extra.txt").unlink()
            evidence = copied / "evidence.json"
            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not canonical"):
                verifier.verify(copied, BASELINE_PUBLICATION)


if __name__ == "__main__":
    unittest.main()
