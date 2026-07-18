import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

from tests.test_text_source_baseline_publication import (
    fixture as baseline_fixture,
    write_trial_receipts as write_baseline_receipts,
)


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "publish-text-source-structural-transform.py"
SPEC = importlib.util.spec_from_file_location("structural_publication", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load structural publication module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def process(*, command: list[str], wall_ns: int, peak_rss_bytes: int) -> dict:
    return {
        "command": command,
        "returncode": 0,
        "timed_out": False,
        "wall_ns": wall_ns,
        "cpu_ns": wall_ns,
        "peak_rss_bytes": peak_rss_bytes,
        "stdout": "",
        "stderr": "",
    }


def structural_fixture(baseline: dict, baseline_sha256: str) -> tuple[dict, list[dict]]:
    baseline_rows = {
        row["item_id"]: row
        for row in baseline["summary"]["item_codec_rows"]
        if row["codec_id"] == "kanzi-max"
    }
    metadata = {
        item_id: (format_name, track)
        for item_id, format_name, track in MODULE.EXPECTED_ITEMS
    }
    items = []
    for item in baseline["items"]:
        row = baseline_rows[item["id"]]
        format_name, track = metadata[item["id"]]
        items.append(
            {
                "id": item["id"],
                "format": format_name,
                "track": track,
                "source_bytes": item["source_bytes"],
                "source_sha256": item["source_sha256"],
                "baseline_bytes": row["artifact_bytes"],
                "baseline_compression_peak_rss_bytes": row[
                    "compression_peak_rss_bytes"
                ],
                "baseline_decompression_peak_rss_bytes": row[
                    "decompression_peak_rss_bytes"
                ],
            }
        )
    bindings = {
        "repository_commit": "a" * 40,
        "baseline_results_sha256": baseline_sha256,
        "corpus_manifest_sha256": "b" * 64,
        "kanzi_binary_sha256": "c" * 64,
    }
    trials = []
    for item in items:
        for variant in MODULE.STRUCTURAL.variants_for(item):
            commands = MODULE.expected_process_commands(item, variant)
            reduction = 0.04 if variant == "ts-h2-extension-lanes" else 0.01
            candidate_bytes = int(item["baseline_bytes"] * (1.0 - reduction))
            payload_bytes = candidate_bytes - MODULE.STRUCTURAL.FRAME_HEADER.size
            digest = hashlib.sha256(f"{variant}/{item['id']}".encode()).hexdigest()
            for repetition in range(3):
                compression = [
                    process(
                        command=commands["compression"][index],
                        wall_ns=value,
                        peak_rss_bytes=value * 1024,
                    )
                    for index, value in enumerate((10, 20, 30))
                ]
                decompression = [
                    process(
                        command=commands["decompression"][index],
                        wall_ns=value,
                        peak_rss_bytes=value * 1024,
                    )
                    for index, value in enumerate((5, 10, 15))
                ]
                trials.append(
                    {
                        "schema_version": 1,
                        "bindings": bindings,
                        "variant": variant,
                        "item_id": item["id"],
                        "track": item["track"],
                        "repetition": repetition,
                        "warmup": repetition == 0,
                        "source_bytes": item["source_bytes"],
                        "source_sha256": item["source_sha256"],
                        "baseline_codec": "kanzi-max",
                        "baseline_bytes": item["baseline_bytes"],
                        "transformed_bytes": item["source_bytes"],
                        "backend_payload_bytes": payload_bytes,
                        "candidate_bytes": candidate_bytes,
                        "candidate_sha256": digest,
                        "compression_wall_ns": 60,
                        "decompression_wall_ns": 30,
                        "compression_peak_rss_bytes": 30 * 1024,
                        "decompression_peak_rss_bytes": 15 * 1024,
                        "processes": {
                            "compression": compression,
                            "decompression": decompression,
                        },
                        "exact_roundtrip": True,
                        "passed": True,
                        "error": None,
                    }
                )
    summary = MODULE.STRUCTURAL.summarize(trials, items)
    results = {
        "schema_version": 1,
        "name": "text-source-structural-transform-development-v1",
        "completed": True,
        "all_required_completed": all(row["passed"] for row in summary["item_rows"]),
        "trial_count": 33,
        "bindings": bindings,
        "baseline_commit": baseline["bindings"]["repository_commit"],
        "backend": "kanzi-max",
        "backend_setting": ["--level=9", "--block=1g", "--jobs=1"],
        "repetitions": 2,
        "warmups": 1,
        "order_seed": 20260718,
        "items": items,
        "claim_ceiling": "fixture",
        "summary": summary,
    }
    return results, trials


def write_structural_receipts(root: Path, trials: list[dict]) -> None:
    for receipt in trials:
        path = (
            root
            / "trials"
            / receipt["variant"]
            / f"{receipt['item_id']}.r{receipt['repetition']}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


class TextSourceStructuralTransformPublicationTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        baseline = baseline_fixture()
        baseline_path = root / "baseline" / "results.json"
        baseline_path.parent.mkdir(parents=True)
        baseline_path.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_baseline_receipts(baseline_path.parent, baseline)
        structural, trials = structural_fixture(
            baseline, MODULE.sha256_file(baseline_path)
        )
        structural_path = root / "structural" / "results.json"
        structural_path.parent.mkdir(parents=True)
        structural_path.write_text(
            json.dumps(structural, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_structural_receipts(structural_path.parent, trials)
        return structural_path, baseline_path

    def test_publication_keeps_every_standard_and_candidate_visible(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            artifacts = MODULE.build_artifacts(structural_path, baseline_path)
            comparison = json.loads(artifacts["comparison.json"])
            source, wiki = comparison["tracks"]
            self.assertEqual(len(source["rows"]), 17)
            self.assertEqual(len(wiki["rows"]), 16)
            baseline_statuses = {
                row["axiom_beaten_status"]
                for row in source["rows"]
                if row["kind"] == "practical_baseline"
            }
            self.assertEqual(baseline_statuses, {"yes", "no"})
            markdown = artifacts["README.md"].decode()
            svg = artifacts["comparison.svg"].decode()
            self.assertIn("Axiom TS-H1 demux", markdown)
            self.assertIn("Axiom TS-H2 extension lanes", markdown)
            self.assertIn("Peak RSS C / D MiB", markdown)
            self.assertIn("Portability", markdown)
            self.assertIn("Axiom beat?", markdown)
            self.assertIn("Runner comparability (size)", markdown)
            self.assertIn("Runner comparability (speed/memory)", markdown)
            self.assertIn("Corruption preflight: AXTP2", markdown)
            self.assertTrue(
                comparison["integrity"][
                    "axtp2_payload_sha256_verified_before_backend_decode"
                ]
            )
            self.assertEqual(
                comparison["integrity"][
                    "axtp2_fixed_header_one_bit_mutations_rejected"
                ],
                MODULE.STRUCTURAL.FRAME_HEADER.size * 8,
            )
            self.assertEqual(
                comparison["integrity"]["axtp2_truncated_header_lengths_rejected"],
                MODULE.STRUCTURAL.FRAME_HEADER.size,
            )
            self.assertTrue(
                comparison["integrity"][
                    "axtp2_truncated_and_appended_payloads_rejected"
                ]
            )
            self.assertTrue(comparison["integrity"]["axtp2_transactional_extraction"])
            self.assertTrue(
                comparison["integrity"][
                    "transform_output_bound_checked_before_reconstruction"
                ]
            )
            self.assertTrue(
                comparison["integrity"][
                    "transform_record_count_bounded_before_iteration"
                ]
            )
            self.assertTrue(
                comparison["integrity"][
                    "transform_encoder_decoder_format_bounds_symmetric"
                ]
            )
            self.assertTrue(
                comparison["integrity"]["transform_extension_lane_roster_canonical"]
            )
            self.assertTrue(
                comparison["integrity"]["transform_front_coding_maximal_and_canonical"]
            )
            self.assertIn("Research-ceiling rows remain pending", markdown)
            self.assertIn("All 15 practical standards remain visible", svg)
            self.assertIn("Portability", svg)
            self.assertIn("Axiom beat?", svg)
            ElementTree.fromstring(svg)

    def test_publication_is_deterministic_immutable_and_receipt_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            structural_path, baseline_path = self.prepare(root)
            output = root / "publication"
            MODULE.publish(structural_path, baseline_path, output)
            first = {path.name: path.read_bytes() for path in output.iterdir()}
            MODULE.publish(structural_path, baseline_path, output)
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
            missing = next((structural_path.parent / "trials").glob("*/*.r1.json"))
            missing.unlink()
            with self.assertRaisesRegex(ValueError, "1 missing"):
                MODULE.build_artifacts(structural_path, baseline_path)

    def test_publication_refuses_extra_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            structural_path, baseline_path = self.prepare(root)
            output = root / "publication"
            MODULE.publish(structural_path, baseline_path, output)
            (output / "extra.txt").write_text("not evidence\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differing roster"):
                MODULE.publish(structural_path, baseline_path, output)

    def test_public_evidence_redacts_streams_and_binds_baseline_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            receipt_path = next(
                (structural_path.parent / "trials").glob("*/*.r1.json")
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            private_stream = "/private/var/folders/example worker output\n"
            receipt["processes"]["compression"][0]["stdout"] = private_stream
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            artifacts = MODULE.build_artifacts(structural_path, baseline_path)
            evidence_raw = artifacts["evidence.json"]
            evidence = json.loads(evidence_raw)
            self.assertEqual(len(evidence["trials"]), 33)
            self.assertNotIn(b"/private/var/", evidence_raw)
            self.assertEqual(len(evidence["baseline_public_evidence_sha256"]), 64)
            public_receipt = next(
                row["receipt"]
                for row in evidence["trials"]
                if row["path"]
                == receipt_path.relative_to(structural_path.parent / "trials").as_posix()
            )
            commitment = public_receipt["processes"]["compression"][0][
                "stdout_commitment"
            ]
            self.assertEqual(commitment["classification"], "redacted")
            self.assertEqual(
                commitment["sha256"],
                hashlib.sha256(private_stream.encode()).hexdigest(),
            )
            self.assertNotIn(
                "stdout", public_receipt["processes"]["compression"][0]
            )
            public_process = public_receipt["processes"]["compression"][0]
            public_process["wall_ns"] += 10
            public_receipt["compression_wall_ns"] += 10
            evidence["public_structural_trial_receipts_manifest_sha256"] = (
                MODULE.BASELINE_PUBLICATION.public_receipts_manifest_sha256(
                    evidence["trials"]
                )
            )
            with self.assertRaisesRegex(ValueError, "do not reconstruct results summary"):
                MODULE.validate_public_evidence(evidence)

    def test_exactness_failure_is_published_as_negative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            failed_path = next(
                (structural_path.parent / "trials" / "ts-h1-demux").glob("*.r1.json")
            )
            failed = json.loads(failed_path.read_text(encoding="utf-8"))
            failed["exact_roundtrip"] = False
            failed["passed"] = False
            failed["error"] = "restored bytes differ from source"
            failed_path.write_text(
                json.dumps(failed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            results = json.loads(structural_path.read_text(encoding="utf-8"))
            trials = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (structural_path.parent / "trials").glob("*/*.json")
            ]
            summary = MODULE.STRUCTURAL.summarize(trials, results["items"])
            results["summary"] = summary
            results["all_required_completed"] = all(
                row["passed"] for row in summary["item_rows"]
            )
            structural_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            artifacts = MODULE.build_artifacts(structural_path, baseline_path)
            comparison = json.loads(artifacts["comparison.json"])
            self.assertEqual(comparison["integrity"]["failed_trial_count"], 1)
            self.assertFalse(comparison["integrity"]["all_roundtrips_exact"])
            self.assertFalse(comparison["integrity"]["all_required_completed"])
            self.assertIn(
                "Failed structural trials: **1**", artifacts["README.md"].decode()
            )

    def test_publication_refuses_structural_item_baseline_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            structural = json.loads(structural_path.read_text(encoding="utf-8"))
            structural["items"][0]["baseline_compression_peak_rss_bytes"] += 1
            structural_path.write_text(
                json.dumps(structural, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "disagrees with bound baseline"):
                MODULE.build_artifacts(structural_path, baseline_path)

    def test_publication_refuses_boolean_process_metric(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            receipt_path = next(
                (structural_path.parent / "trials").glob("*/*.r1.json")
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["processes"]["compression"][0]["cpu_ns"] = False
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "process is invalid"):
                MODULE.build_artifacts(structural_path, baseline_path)

    def test_publication_refuses_noncanonical_structural_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            payload = structural_path.read_bytes().replace(
                b'{\n  "all_required_completed"',
                b'{\n  "schema_version": 1,\n  "all_required_completed"',
                1,
            )
            structural_path.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.build_artifacts(structural_path, baseline_path)

    def test_publication_refuses_invalid_structural_binding_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            structural_path, baseline_path = self.prepare(Path(raw))
            structural = json.loads(structural_path.read_text(encoding="utf-8"))
            structural["bindings"]["kanzi_binary_sha256"] = "Z" * 64
            structural_path.write_text(
                json.dumps(structural, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid digest"):
                MODULE.build_artifacts(structural_path, baseline_path)


if __name__ == "__main__":
    unittest.main()
