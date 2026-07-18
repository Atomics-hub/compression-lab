import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_structural_transform_publication import (
    MODULE as PUBLICATION,
    TextSourceStructuralTransformPublicationTests as FixtureHelper,
)


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify-text-source-structural-publication.py"
SPEC = importlib.util.spec_from_file_location("structural_publication_verifier", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load structural publication verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourceStructuralPublicationVerifierTests(unittest.TestCase):
    def publish_fixture(self, root: Path) -> tuple[Path, Path]:
        helper = FixtureHelper()
        structural_path, baseline_path = helper.prepare(root)
        baseline_publication = root / "baseline-publication"
        PUBLICATION.BASELINE_PUBLICATION.publish(
            baseline_path, baseline_publication
        )
        output = root / "checked-in-publication"
        PUBLICATION.publish(structural_path, baseline_path, output)
        return output, baseline_publication

    def test_verifier_recalculates_structural_evidence_without_private_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output, baseline_publication = self.publish_fixture(root)
            result = MODULE.verify(output, baseline_publication)
            self.assertTrue(result["verified"])
            self.assertEqual(result["trial_count"], 33)

            evidence = output / "evidence.json"
            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(output, baseline_publication)

    def test_recomputed_receipt_cannot_bless_an_edited_structural_chart(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output, baseline_publication = self.publish_fixture(Path(raw))
            comparison_path = output / "comparison.json"
            comparison = json.loads(comparison_path.read_bytes())
            comparison["tracks"][0]["practical_leader"] = "Fabricated leader"
            comparison_path.write_bytes(PUBLICATION.json_bytes(comparison))
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["comparison.json"] = PUBLICATION.sha256_file(
                comparison_path
            )
            receipt_path.write_bytes(PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "comparison does not reconstruct"):
                MODULE.verify(output, baseline_publication)


if __name__ == "__main__":
    unittest.main()
