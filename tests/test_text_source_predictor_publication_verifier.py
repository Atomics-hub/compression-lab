import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.test_text_source_baseline_publication import (
    fixture as baseline_fixture,
    write_trial_receipts,
)
from tests.test_text_source_predictor_ceiling_publication import (
    MODULE as PUBLICATION,
    predictor_fixture,
    write_canonical,
)


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify-text-source-predictor-publication.py"
SPEC = importlib.util.spec_from_file_location("predictor_publication_verifier", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load predictor publication verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourcePredictorPublicationVerifierTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        result_path = root / "result.json"
        config_path = root / "config.json"
        baseline_path = root / "baseline" / "results.json"
        output = root / "publication"
        write_canonical(result_path, predictor_fixture())
        write_canonical(config_path, {"schema_version": 1, "name": "fixture"})
        baseline = baseline_fixture()
        write_canonical(baseline_path, baseline)
        write_trial_receipts(baseline_path.parent, baseline)
        verification = {
            "verified": True,
            "track_count": 2,
            "full_codec_build_admissions": 0,
            "axiom_wins": 0,
        }
        with mock.patch.object(
            PUBLICATION.RUNNER, "verify", return_value=verification
        ):
            PUBLICATION.publish(result_path, config_path, baseline_path, output)
        return output, baseline_path

    def test_verifier_reconstructs_bundle_without_predictor_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output, baseline_path = self.prepare(Path(raw))
            result = MODULE.verify(output, baseline_path)
            self.assertTrue(result["verified"])
            self.assertEqual(result["track_count"], 2)
            self.assertEqual(result["axiom_wins"], 0)

    def test_recomputed_receipt_cannot_bless_an_edited_chart(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output, baseline_path = self.prepare(Path(raw))
            comparison_path = output / "comparison.json"
            comparison = json.loads(comparison_path.read_bytes())
            comparison["tracks"][0]["rows"][0]["axiom_beat"] = "yes"
            comparison_path.write_bytes(PUBLICATION.json_bytes(comparison))
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["artifacts"]["comparison.json"] = PUBLICATION.sha256_bytes(
                comparison_path.read_bytes()
            )
            receipt_path.write_bytes(PUBLICATION.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                MODULE.verify(output, baseline_path)

    def test_noncanonical_evidence_and_extra_files_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output, baseline_path = self.prepare(Path(raw))
            evidence = output / "evidence.json"
            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(output, baseline_path)
        with tempfile.TemporaryDirectory() as raw:
            output, baseline_path = self.prepare(Path(raw))
            (output / "extra.txt").write_text("extra\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file roster"):
                MODULE.verify(output, baseline_path)


if __name__ == "__main__":
    unittest.main()
