import importlib.util
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "publish-text-source-long-range-screen.py"
SPEC = importlib.util.spec_from_file_location("long_range_screen_publication", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load long-range screen publication module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PUBLICATION = (
    REPOSITORY / "runs" / "text-source-long-range-screen-v1" / "publication"
)
BASELINE_EVIDENCE = (
    REPOSITORY
    / "runs"
    / "text-source-development-baseline-census-v1"
    / "publication"
    / "evidence.json"
)


class TextSourceLongRangeScreenPublicationTests(unittest.TestCase):
    def test_chart_keeps_every_standard_diagnostic_and_empty_axiom_row(self) -> None:
        evidence = json.loads((PUBLICATION / "evidence.json").read_bytes())
        baseline = json.loads(BASELINE_EVIDENCE.read_bytes())
        comparison = MODULE.derive(
            evidence["results"],
            baseline["results"],
            result_sha256=evidence["result_sha256"],
            receipts_sha256=evidence["raw_trial_receipts_manifest_sha256"],
            baseline_results_sha256=evidence["baseline_results_sha256"],
            baseline_public_evidence_sha256=evidence[
                "baseline_public_evidence_sha256"
            ],
            public_evidence_sha256=MODULE.sha256_file(PUBLICATION / "evidence.json"),
        )
        self.assertEqual(len(comparison["tracks"]), 2)
        for track in comparison["tracks"]:
            self.assertEqual(len(track["rows"]), 19)
            practical = [row for row in track["rows"] if row["kind"] == "practical_baseline"]
            diagnostics = [row for row in track["rows"] if row["kind"] == "competitor_diagnostic"]
            axiom = [row for row in track["rows"] if row["kind"] == "axiom_unbuilt"]
            self.assertEqual(len(practical), 15)
            self.assertEqual(len(diagnostics), 3)
            self.assertEqual(len(axiom), 1)
            self.assertTrue(all(row["exact"] and row["deterministic"] for row in diagnostics))
            self.assertTrue(all(row["gain_vs_kanzi_percent"] < 0 for row in diagnostics))
            self.assertIsNone(axiom[0]["complete_bytes"])
            self.assertFalse(axiom[0]["exact"])
            self.assertEqual(axiom[0]["axiom_beat"], "no artifact; no win")
        markdown = MODULE.render_markdown(comparison)
        svg = MODULE.render_svg(comparison)
        self.assertIn("No Axiom codec was built", markdown)
        self.assertIn("all 15 practical standards visible", svg)
        ElementTree.fromstring(svg)

    def test_checked_in_public_evidence_has_no_local_path(self) -> None:
        evidence = json.loads((PUBLICATION / "evidence.json").read_bytes())
        MODULE.validate_public_evidence(evidence)
        encoded = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("/Users/", encoded)
        self.assertEqual(len(evidence["trials"]), 24)


if __name__ == "__main__":
    unittest.main()
