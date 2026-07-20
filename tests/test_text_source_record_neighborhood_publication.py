import importlib.util
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPOSITORY / "scripts" / "publish-text-source-record-neighborhood-screen.py"
)
PUBLICATION = (
    REPOSITORY
    / "runs"
    / "text-source-record-neighborhood-screen-v1"
    / "publication"
)
BASELINE_EVIDENCE = (
    REPOSITORY
    / "runs"
    / "text-source-development-baseline-census-v1"
    / "publication"
    / "evidence.json"
)
SPEC = importlib.util.spec_from_file_location("record_neighborhood_publication", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import {SCRIPT}")
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


class RecordNeighborhoodPublicationTests(unittest.TestCase):
    def test_chart_keeps_all_standards_control_and_rejected_candidate(self) -> None:
        evidence = json.loads((PUBLICATION / "evidence.json").read_bytes())
        baseline = json.loads(BASELINE_EVIDENCE.read_bytes())
        comparison = publication.derive(
            evidence["results"],
            baseline["results"],
            evidence["structural_control_rows"],
            result_sha256=evidence["result_sha256"],
            receipts_sha256=evidence["raw_trial_receipts_manifest_sha256"],
            baseline_results_sha256=evidence["baseline_results_sha256"],
            baseline_public_evidence_sha256=evidence[
                "baseline_public_evidence_sha256"
            ],
            public_evidence_sha256=publication.sha256_file(
                PUBLICATION / "evidence.json"
            ),
        )
        self.assertEqual(len(comparison["tracks"]), 2)
        for track in comparison["tracks"]:
            practical = [
                row for row in track["rows"] if row["kind"] == "practical_baseline"
            ]
            controls = [
                row for row in track["rows"] if row["kind"] == "attribution_control"
            ]
            candidates = [
                row
                for row in track["rows"]
                if row["kind"] == "axiom_experimental_candidate"
            ]
            self.assertEqual(len(track["rows"]), 17)
            self.assertEqual(len(practical), 15)
            self.assertEqual(len(controls), 1)
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertTrue(candidate["exact"])
            self.assertTrue(candidate["deterministic"])
            self.assertLess(candidate["gain_vs_kanzi_percent"], 0)
            self.assertLess(candidate["gain_vs_structural_control_percent"], 0)
            self.assertEqual(
                next(row for row in practical if row["id"] == "kanzi-max")[
                    "axiom_beat"
                ],
                "no",
            )
            self.assertEqual(controls[0]["axiom_beat"], "no")
            self.assertTrue(any(row["axiom_beat"] == "yes" for row in practical))
        markdown = publication.render_markdown(comparison)
        svg = publication.render_svg(comparison)
        self.assertIn("earns no category win", markdown)
        self.assertIn("all 15 practical standards visible", svg)
        ElementTree.fromstring(svg)

    def test_public_evidence_is_bound_and_contains_no_local_path(self) -> None:
        evidence = json.loads((PUBLICATION / "evidence.json").read_bytes())
        publication.validate_public_evidence(evidence)
        self.assertEqual(len(evidence["trials"]), 8)
        self.assertEqual(len(evidence["structural_control_rows"]), 4)
        self.assertNotIn("/Users/", json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
