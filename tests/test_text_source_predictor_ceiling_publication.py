import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "publish-text-source-predictor-ceiling.py"
SPEC = importlib.util.spec_from_file_location("predictor_ceiling_publication", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load predictor ceiling publication module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def predictor_fixture() -> dict:
    baseline = baseline_fixture()
    items = {item["id"]: item for item in baseline["items"]}
    tracks = []
    definitions = [
        (
            "source_code_bundles",
            ["cpython-3.14.6-source", "typescript-6.0.3-source"],
            ["rust-1.97.1-source", "llvm-22.1.8-source"],
            128_000,
            13.3,
        ),
        (
            "english_wikimedia_wikitext",
            ["enwikibooks-20260701", "enwikinews-20260701"],
            ["enwikiversity-20260701"],
            80_000,
            25.4,
        ),
    ]
    for track, training, evaluation, dictionary_bytes, dictionary_gain in definitions:
        source_bytes = sum(items[item_id]["source_bytes"] for item_id in evaluation)
        item_results = [
            {
                "item_id": item_id,
                "source_bytes": items[item_id]["source_bytes"],
                "source_sha256": items[item_id]["source_sha256"],
            }
            for item_id in evaluation
        ]
        tracks.append(
            {
                "track": track,
                "training_items": training,
                "evaluation_items": evaluation,
                "items": item_results,
                "dictionary": {
                    "bytes": dictionary_bytes,
                    "entry_count": 8192,
                    "sha256": "a" * 64,
                },
                "dictionary_gain_over_byte_previous_class_percent": dictionary_gain,
                "aggregates": [
                    {
                        "variant": variant,
                        "projected_complete_aggregate_bytes": int(
                            source_bytes * fraction
                        ),
                    }
                    for variant, fraction in zip(
                        MODULE.RUNNER.VARIANTS, (0.70, 0.62, 0.50)
                    )
                ],
                "decision": "reject_predictor_family_below_entropy_headroom_gate",
                "full_codec_build_admitted": False,
                "axiom_win": False,
            }
        )
    return {
        "schema_version": 1,
        "name": "text-source-predictor-entropy-ceiling-result-v1",
        "completed": True,
        "full_codec_build_admissions": 0,
        "axiom_wins": 0,
        "bindings": {"repository_commit": "b" * 40},
        "tracks": tracks,
        "claim_ceiling": (
            "Sampled development entropy-ceiling probe only. Estimated bytes are "
            "not a decodable artifact, codec result, baseline win, validation result, "
            "or state-of-the-art claim."
        ),
    }


def write_canonical(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MODULE.json_bytes(payload))


class TextSourcePredictorCeilingPublicationTests(unittest.TestCase):
    def test_chart_keeps_every_standard_and_ineligible_estimate_visible(self) -> None:
        comparison = MODULE.derive(predictor_fixture(), baseline_fixture())
        self.assertEqual(len(comparison["tracks"]), 2)
        for track in comparison["tracks"]:
            self.assertEqual(len(track["rows"]), 18)
            practical = [
                row for row in track["rows"] if row["kind"] == "practical_baseline"
            ]
            estimates = [
                row for row in track["rows"] if row["kind"] == "axiom_entropy_estimate"
            ]
            self.assertEqual(len(practical), 15)
            self.assertEqual(len(estimates), 3)
            self.assertTrue(all(row["exact"] for row in practical))
            self.assertTrue(
                all(
                    row["compression_mbps"] is None
                    and row["decompression_mbps"] is None
                    and row["compression_peak_rss_mib"] is None
                    and row["decompression_peak_rss_mib"] is None
                    and not row["exact"]
                    and not row["deterministic"]
                    and row["axiom_beat"] == "ineligible estimate"
                    and row["portability"] == "not an artifact"
                    for row in estimates
                )
            )

        comparison["result_sha256"] = "c" * 64
        comparison["public_evidence_sha256"] = "d" * 64
        markdown = MODULE.render_markdown(comparison)
        svg = MODULE.render_svg(comparison)
        self.assertIn("every tested practical standard", markdown.lower())
        self.assertIn("not decodable archives", markdown)
        self.assertIn("Axiom P2 mixed token/class estimate", markdown)
        self.assertIn("ineligible estimate", svg)
        self.assertIn("both successors are rejected", svg)
        ElementTree.fromstring(svg)

    def test_publication_is_deterministic_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result_path = root / "result.json"
            config_path = root / "config.json"
            baseline_path = root / "baseline" / "results.json"
            output = root / "publication"
            write_canonical(result_path, predictor_fixture())
            write_canonical(config_path, {"schema_version": 1, "name": "fixture"})
            write_canonical(baseline_path, baseline_fixture())
            verification = {
                "verified": True,
                "track_count": 2,
                "full_codec_build_admissions": 0,
                "axiom_wins": 0,
            }
            with (
                mock.patch.object(MODULE.RUNNER, "verify", return_value=verification),
                mock.patch.object(
                    MODULE.BASELINE_PUBLICATION,
                    "validate_trial_receipts",
                    return_value=None,
                ),
            ):
                MODULE.publish(result_path, config_path, baseline_path, output)
                first = {path.name: path.read_bytes() for path in output.iterdir()}
                MODULE.publish(result_path, config_path, baseline_path, output)
                second = {path.name: path.read_bytes() for path in output.iterdir()}
                self.assertEqual(first, second)
                self.assertEqual(
                    set(first),
                    {
                        "README.md",
                        "comparison.json",
                        "comparison.svg",
                        "evidence.json",
                        "receipt.json",
                    },
                )
                receipt = json.loads(first["receipt.json"])
                self.assertEqual(
                    set(receipt["artifacts"]),
                    {"README.md", "comparison.json", "comparison.svg", "evidence.json"},
                )
                (output / "README.md").write_text("tampered\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "artifact differs"):
                    MODULE.publish(result_path, config_path, baseline_path, output)

    def test_invalid_or_admitted_result_is_refused(self) -> None:
        result = predictor_fixture()
        result["full_codec_build_admissions"] = 1
        with self.assertRaisesRegex(ValueError, "identity or decision"):
            MODULE.derive(result, baseline_fixture())


if __name__ == "__main__":
    unittest.main()
