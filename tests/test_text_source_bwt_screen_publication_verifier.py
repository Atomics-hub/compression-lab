import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify-text-source-bwt-screen-publication.py"
PUBLICATION = REPOSITORY / "runs" / "text-source-bwt-screen-v1" / "publication"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load_module("text_source_bwt_screen_publication_verifier", SCRIPT)


class TextSourceBwtScreenPublicationVerifierTests(unittest.TestCase):
    def test_checked_in_publication_reconstructs_entirely_offline(self) -> None:
        result = MODULE.verify(PUBLICATION)
        self.assertTrue(result["verified"])
        self.assertTrue(result["offline"])
        self.assertEqual(result["trial_count"], 32)
        self.assertEqual(result["track_count"], 2)
        self.assertEqual(result["comparison_rows_per_track"], 5)
        self.assertEqual(result["diagnostics_per_track"], 4)
        self.assertTrue(result["all_diagnostic_gains_negative"])
        self.assertEqual(result["axiom_wins"], 0)

    def test_rewritten_receipt_cannot_bless_an_edited_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            publication = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, publication)
            comparison_path = publication / "comparison.json"
            comparison = json.loads(comparison_path.read_bytes())
            comparison["tracks"][0]["rows"][1]["gain_vs_kanzi_percent"] = 1.0
            comparison_path.write_bytes(MODULE.PUBLICATION.json_bytes(comparison))
            receipt_path = publication / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["comparison.json"] = MODULE.PUBLICATION.sha256_file(
                comparison_path
            )
            receipt_path.write_bytes(MODULE.PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "comparison does not reconstruct"):
                MODULE.verify(publication)

    def test_rewritten_evidence_and_receipt_cannot_fabricate_a_win(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            publication = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, publication)
            evidence_path = publication / "evidence.json"
            evidence = json.loads(evidence_path.read_bytes())
            evidence["results"]["summary"]["axiom_wins"] = 1
            evidence_path.write_bytes(MODULE.PUBLICATION.json_bytes(evidence))
            receipt_path = publication / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["evidence.json"] = MODULE.PUBLICATION.sha256_file(
                evidence_path
            )
            receipt_path.write_bytes(MODULE.PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "evidence binding|identity or decision"):
                MODULE.verify(publication)

    def test_extra_file_and_noncanonical_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            publication = Path(raw) / "publication"
            shutil.copytree(PUBLICATION, publication)
            (publication / "extra.txt").write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file roster"):
                MODULE.verify(publication)
            (publication / "extra.txt").unlink()
            evidence = publication / "evidence.json"
            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(publication)


if __name__ == "__main__":
    unittest.main()
