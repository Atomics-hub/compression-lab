import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify-text-source-long-range-screen-publication.py"
SPEC = importlib.util.spec_from_file_location(
    "long_range_screen_publication_verifier", SCRIPT
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load long-range screen publication verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PUBLICATION = (
    REPOSITORY / "runs" / "text-source-long-range-screen-v1" / "publication"
)
BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)


class TextSourceLongRangeScreenPublicationVerifierTests(unittest.TestCase):
    def test_checked_in_publication_reconstructs_without_private_run(self) -> None:
        result = MODULE.verify(PUBLICATION, BASELINE_PUBLICATION)
        self.assertTrue(result["verified"])
        self.assertEqual(result["trial_count"], 24)
        self.assertEqual(result["standards_per_track"], 15)
        self.assertEqual(result["diagnostics_per_track"], 3)
        self.assertFalse(result["axiom_prototype_admitted"])
        self.assertEqual(result["axiom_wins"], 0)

    def test_rewritten_receipt_cannot_bless_an_edited_chart(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            publication = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, publication)
            comparison_path = publication / "comparison.json"
            comparison = json.loads(comparison_path.read_bytes())
            comparison["tracks"][0]["rows"][-1]["axiom_beat"] = "fabricated win"
            comparison_path.write_bytes(MODULE.PUBLICATION.json_bytes(comparison))
            receipt_path = publication / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["comparison.json"] = MODULE.PUBLICATION.sha256_file(
                comparison_path
            )
            receipt_path.write_bytes(MODULE.PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(
                ValueError, "comparison does not reconstruct"
            ):
                MODULE.verify(publication, BASELINE_PUBLICATION)

    def test_extra_file_and_noncanonical_evidence_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            publication = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, publication)
            (publication / "extra.txt").write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file roster"):
                MODULE.verify(publication, BASELINE_PUBLICATION)
            (publication / "extra.txt").unlink()
            evidence = publication / "evidence.json"
            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(publication, BASELINE_PUBLICATION)


if __name__ == "__main__":
    unittest.main()
