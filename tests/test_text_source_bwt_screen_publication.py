import importlib.util
import json
from pathlib import Path
import unittest
from xml.etree import ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "publish-text-source-bwt-screen.py"
PUBLICATION = REPOSITORY / "runs" / "text-source-bwt-screen-v1" / "publication"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load_module("text_source_bwt_screen_publication", SCRIPT)


class TextSourceBwtScreenPublicationTests(unittest.TestCase):
    def test_chart_shows_kanzi_and_all_four_negative_diagnostics_per_track(self) -> None:
        comparison = json.loads((PUBLICATION / "comparison.json").read_bytes())
        self.assertEqual(len(comparison["tracks"]), 2)
        for track in comparison["tracks"]:
            self.assertEqual(len(track["rows"]), 5)
            baseline = [row for row in track["rows"] if row["kind"] == "practical_baseline"]
            diagnostics = [
                row for row in track["rows"] if row["kind"] == "competitor_diagnostic"
            ]
            self.assertEqual([row["id"] for row in baseline], ["kanzi-max"])
            self.assertEqual([row["id"] for row in diagnostics], list(MODULE.RUNNER.VARIANTS))
            self.assertTrue(
                all(row["gain_vs_kanzi_percent"] < 0 for row in diagnostics)
            )
            self.assertTrue(all(row["exact"] and row["deterministic"] for row in diagnostics))
            self.assertTrue(all(row["resource_limit_passed"] for row in diagnostics))
            self.assertTrue(all(row["compression_mbps"] > 0 for row in diagnostics))
            self.assertTrue(all(row["decompression_mbps"] > 0 for row in diagnostics))
            self.assertIsNone(baseline[0]["compression_mbps"])
            self.assertEqual(
                baseline[0]["speed_memory_availability"],
                "not copied into this diagnostic result",
            )
            self.assertEqual(
                track["track_decision"], "reject_raw_bwt_direction_for_track"
            )
        self.assertEqual(comparison["axiom_wins"], 0)
        self.assertEqual(comparison["integrity"]["axiom_artifact_count"], 0)

    def test_presentation_is_explicit_and_svg_is_valid(self) -> None:
        comparison = json.loads((PUBLICATION / "comparison.json").read_bytes())
        markdown = MODULE.render_markdown(comparison)
        svg = MODULE.render_svg(comparison)
        self.assertIn("All 32 retained trials decoded exactly", markdown)
        self.assertIn("Every custom BWT chain was larger", markdown)
        self.assertIn("Baseline speed/RSS", markdown)
        self.assertIn("`axiom_wins` remains 0", markdown)
        self.assertIn("four deterministic BWT diagnostics", svg)
        self.assertIn("no Axiom artifact or win", svg)
        ElementTree.fromstring(svg)

    def test_public_evidence_reconstructs_offline_and_has_no_local_path(self) -> None:
        evidence = json.loads((PUBLICATION / "evidence.json").read_bytes())
        MODULE.validate_public_evidence(evidence)
        verification = MODULE.reconstruct_run_verification(evidence)
        self.assertEqual(evidence["run_verification"], verification)
        self.assertTrue(verification["offline"])
        self.assertEqual(verification["trial_count"], 32)
        self.assertEqual(verification["exact_deterministic_item_variant_count"], 16)
        self.assertEqual(verification["axiom_wins"], 0)
        encoded = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn(str(REPOSITORY), encoded)


if __name__ == "__main__":
    unittest.main()
