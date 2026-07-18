import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_baseline_publication import (
    MODULE as PUBLICATION,
    fixture,
    write_trial_receipts,
)


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify-text-source-baseline-publication.py"
SPEC = importlib.util.spec_from_file_location("baseline_publication_verifier", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load baseline publication verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourceBaselinePublicationVerifierTests(unittest.TestCase):
    def publish_fixture(self, root: Path) -> Path:
        results = fixture()
        results_path = root / "private" / "results.json"
        results_path.parent.mkdir()
        results_path.write_bytes(PUBLICATION.json_bytes(results))
        write_trial_receipts(results_path.parent, results)
        output = root / "checked-in-publication"
        PUBLICATION.publish(results_path, output)
        return output

    def test_verifier_recalculates_checked_in_evidence_without_private_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = self.publish_fixture(root)
            result = MODULE.verify(output)
            self.assertTrue(result["verified"])
            self.assertEqual(result["trial_count"], 630)

            evidence = output / "evidence.json"
            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(output)

    def test_recomputed_receipt_cannot_bless_an_edited_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = self.publish_fixture(Path(raw))
            comparison_path = output / "comparison.json"
            comparison = json.loads(comparison_path.read_bytes())
            comparison["tracks"][0]["ratio_leader"] = "Fabricated leader"
            comparison_path.write_bytes(PUBLICATION.json_bytes(comparison))
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["comparison.json"] = PUBLICATION.sha256_file(
                comparison_path
            )
            receipt_path.write_bytes(PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "comparison does not reconstruct"):
                MODULE.verify(output)

    def test_recomputed_receipt_cannot_bless_edited_presentation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = self.publish_fixture(Path(raw))
            readme = output / "README.md"
            readme.write_text("# Fabricated claim\n", encoding="utf-8")
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["README.md"] = PUBLICATION.sha256_file(readme)
            receipt_path.write_bytes(PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "presentation does not reconstruct"):
                MODULE.verify(output)

    def test_verifier_rejects_a_rewritten_receipt_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = self.publish_fixture(Path(raw))
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["unbound_note"] = "not part of the frozen receipt"
            receipt_path.write_bytes(PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "receipt does not reconstruct"):
                MODULE.verify(output)


if __name__ == "__main__":
    unittest.main()
