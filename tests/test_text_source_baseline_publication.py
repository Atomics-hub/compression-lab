import importlib.util
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "publish-text-source-baseline-census.py"
SPEC = importlib.util.spec_from_file_location(
    "text_source_baseline_publication", SCRIPT
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load text/source baseline publication module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture() -> dict:
    items = [
        {
            "id": item_id,
            "track": track,
            "format": (
                "source-bundle-v1"
                if track == "source_code_bundles"
                else "wikimedia-revision-text-v1"
            ),
            "source_bytes": 10_000 + item_index * 1_000,
            "source_sha256": hashlib.sha256(item_id.encode()).hexdigest(),
        }
        for item_index, (item_id, track) in enumerate(MODULE.EXPECTED_ITEMS)
    ]
    item_rows = []
    tracks = {}
    for item_index, item in enumerate(items):
        for codec_index, codec_id in enumerate(MODULE.EXPECTED_CODECS):
            artifact = 1_000 + item_index * 100 + codec_index * 10
            item_rows.append(
                {
                    "codec_id": codec_id,
                    "item_id": item["id"],
                    "track": item["track"],
                    "source_bytes": item["source_bytes"],
                    "artifact_bytes": artifact,
                    "artifact_sha256": hashlib.sha256(
                        f"{codec_id}/{item['id']}".encode()
                    ).hexdigest(),
                    "median_compression_ns": 1_000_000 + item_index * 1_000,
                    "median_decompression_ns": 500_000 + item_index * 1_000,
                    "compression_peak_rss_bytes": (10 + item_index) * 1024 * 1024,
                    "decompression_peak_rss_bytes": (8 + item_index) * 1024 * 1024,
                    "exact_roundtrip": True,
                    "deterministic_artifact": True,
                    "passed": True,
                    "errors": [],
                }
            )
    for track_id in MODULE.TRACK_LABELS:
        track_items = [row for row in items if row["track"] == track_id]
        source_bytes = sum(item["source_bytes"] for item in track_items)
        codecs = []
        for codec_id in MODULE.EXPECTED_CODECS:
            selected = [
                row
                for row in item_rows
                if row["track"] == track_id and row["codec_id"] == codec_id
            ]
            artifact = sum(row["artifact_bytes"] for row in selected)
            compression_ns = sum(row["median_compression_ns"] for row in selected)
            decompression_ns = sum(row["median_decompression_ns"] for row in selected)
            codecs.append(
                {
                    "codec_id": codec_id,
                    "source_bytes": source_bytes,
                    "artifact_bytes": artifact,
                    "ratio_percent": artifact / source_bytes * 100,
                    "compression_mbps": source_bytes / compression_ns * 1000,
                    "decompression_mbps": source_bytes / decompression_ns * 1000,
                    "compression_peak_rss_bytes": max(
                        row["compression_peak_rss_bytes"] for row in selected
                    ),
                    "decompression_peak_rss_bytes": max(
                        row["decompression_peak_rss_bytes"] for row in selected
                    ),
                    "complete": True,
                }
            )
        tracks[track_id] = {
            "source_bytes": source_bytes,
            "leader": codecs[0],
            "codecs": codecs,
        }
    return {
        "schema_version": 1,
        "name": "text-source-development-baseline-census-v1",
        "completed": True,
        "all_required_completed": True,
        "trial_count": 630,
        "bindings": {
            "repository_commit": "c" * 40,
            "config_sha256": "d" * 64,
            "manifest_sha256": "e" * 64,
        },
        "repository": {"commit": "c" * 40, "tracked_status": ""},
        "config_path": "config/text-source-baseline-toolchain-v1.json",
        "manifest_path": "corpora/text-source-development-v1/manifest.json",
        "host": {
            "platform": "fixture",
            "machine": "test",
            "python": "3.12",
            "logical_cpus": 1,
        },
        "tools": {
            tool_id: {
                "binary_sha256": hashlib.sha256(tool_id.encode()).hexdigest(),
                "binary_size_bytes": 1,
                "version": "fixture",
            }
            | ({"commit": hashlib.sha1(tool_id.encode()).hexdigest()} if tool_id in {"kanzi", "libbsc"} else {})
            for tool_id in MODULE.EXPECTED_TOOLS
        },
        "codec_ids": list(MODULE.EXPECTED_CODECS),
        "preflight": [
            {
                "codec_id": codec_id,
                "source_bytes": 1_000,
                "artifact_bytes": 500,
                "artifact_sha256": hashlib.sha256(codec_id.encode()).hexdigest(),
                "exact_roundtrip": True,
            }
            for codec_id in MODULE.EXPECTED_CODECS
        ],
        "items": items,
        "summary": {"item_codec_rows": item_rows, "tracks": tracks},
    }


def write_trial_receipts(root: Path, results: dict) -> None:
    item_map = {item["id"]: item for item in results["items"]}
    for summary in results["summary"]["item_codec_rows"]:
        item = item_map[summary["item_id"]]
        commands = MODULE.expected_commands(summary["codec_id"], item)
        for repetition in range(MODULE.WARMUPS + MODULE.MEASURED_REPETITIONS):
            path = (
                root
                / "trials"
                / summary["codec_id"]
                / f"{summary['item_id']}.r{repetition}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            process = {
                "command": commands["compression"],
                "returncode": 0,
                "timed_out": False,
                "wall_ns": summary["median_compression_ns"],
                "cpu_ns": summary["median_compression_ns"],
                "peak_rss_bytes": summary["compression_peak_rss_bytes"],
                "stdout": "",
                "stderr": "",
            }
            decompression = process | {
                "command": commands["decompression"],
                "wall_ns": summary["median_decompression_ns"],
                "cpu_ns": summary["median_decompression_ns"],
                "peak_rss_bytes": summary["decompression_peak_rss_bytes"],
            }
            receipt = {
                "schema_version": 1,
                "bindings": results["bindings"],
                "codec_id": summary["codec_id"],
                "item_id": summary["item_id"],
                "track": item["track"],
                "repetition": repetition,
                "warmup": repetition == 0,
                "source_bytes": item["source_bytes"],
                "source_sha256": item["source_sha256"],
                "artifact_bytes": summary["artifact_bytes"],
                "artifact_sha256": summary["artifact_sha256"],
                "compression": process,
                "decompression": decompression,
                "exact_roundtrip": True,
                "passed": True,
                "error": None,
            }
            path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )


class TextSourceBaselinePublicationTests(unittest.TestCase):
    def test_wikimedia_commands_use_the_frozen_axwkt_extension(self) -> None:
        item = {
            "id": "enwikibooks-20260701",
            "format": "wikimedia-revision-text-v1",
        }
        commands = MODULE.expected_commands("7zip-lzma2-9", item)
        self.assertEqual(
            commands["compression"][-1],
            "$REPOSITORY/corpora/text-source-development-v1/"
            "enwikibooks-20260701.axwkt",
        )
        self.assertNotIn("axwiki", " ".join(commands["compression"]))

    def test_publication_exposes_every_metric_and_honest_candidate_status(self) -> None:
        comparison = MODULE.derive(fixture(), source_sha256="f" * 64)
        markdown = MODULE.render_markdown(comparison)
        svg = MODULE.render_svg(comparison)
        self.assertEqual(len(comparison["tracks"]), 2)
        self.assertEqual(len(comparison["tracks"][0]["codecs"]), 15)
        self.assertIn("Compress MB/s", markdown)
        self.assertIn("Peak RSS C / D MiB", markdown)
        self.assertIn("Axiom status: untested", markdown)
        self.assertIn("Research-ceiling tier still pending", markdown)
        self.assertIn("Axiom text/source specialist: UNTESTED", svg)
        self.assertIn("Exact / deterministic", svg)
        self.assertIn("Peak RSS C / D MiB", svg)
        ElementTree.fromstring(svg)

    def test_incomplete_results_are_refused(self) -> None:
        results = fixture()
        results["all_required_completed"] = False
        with self.assertRaisesRegex(ValueError, "incomplete"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_invalid_evidence_digest_is_refused(self) -> None:
        results = fixture()
        results["bindings"]["manifest_sha256"] = "z" * 64
        with self.assertRaisesRegex(ValueError, "invalid digest"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_invalid_tool_identity_is_refused(self) -> None:
        results = fixture()
        results["tools"]["kanzi"]["binary_sha256"] = "x" * 64
        with self.assertRaisesRegex(ValueError, "tool identity is invalid"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_failed_preflight_is_refused(self) -> None:
        results = fixture()
        results["preflight"][0]["exact_roundtrip"] = False
        with self.assertRaisesRegex(ValueError, "preflight evidence is incomplete"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_invalid_summary_digest_is_refused(self) -> None:
        results = fixture()
        results["summary"]["item_codec_rows"][0]["artifact_sha256"] = "G" * 64
        with self.assertRaisesRegex(ValueError, "incomplete or contains a failed"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_nonfinite_rate_is_refused(self) -> None:
        results = fixture()
        results["summary"]["tracks"]["source_code_bundles"]["codecs"][0][
            "ratio_percent"
        ] = math.nan
        with self.assertRaisesRegex(ValueError, "rate is inconsistent"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_boolean_schema_version_is_refused(self) -> None:
        results = fixture()
        results["schema_version"] = True
        with self.assertRaisesRegex(ValueError, "schema version"):
            MODULE.derive(results, source_sha256="f" * 64)

    def test_publication_is_deterministic_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(fixture(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, fixture())
            output = root / "publication"
            MODULE.publish(results_path, output)
            first = {path.name: path.read_bytes() for path in output.iterdir()}
            MODULE.publish(results_path, output)
            second = {path.name: path.read_bytes() for path in output.iterdir()}
            self.assertEqual(first, second)
            receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(receipt["artifacts"]),
                {"README.md", "comparison.json", "comparison.svg", "evidence.json"},
            )
            for name, digest in receipt["artifacts"].items():
                self.assertEqual(MODULE.sha256_file(output / name), digest)
            (output / "README.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                MODULE.publish(results_path, output)

    def test_publication_refuses_extra_or_symlinked_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results_path = root / "results.json"
            results = fixture()
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            output = root / "publication"
            MODULE.publish(results_path, output)
            (output / "extra.txt").write_text("not evidence\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differing roster"):
                MODULE.publish(results_path, output)
            (output / "extra.txt").unlink()
            readme = output / "README.md"
            original = root / "README.original"
            readme.replace(original)
            readme.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "differing publication artifact"):
                MODULE.publish(results_path, output)

    def test_public_evidence_retains_decision_fields_without_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results = fixture()
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            receipt_path = next((root / "trials" / "libbsc-max").glob("*.r1.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            private_stream = "/Users/example/project source\n"
            receipt["compression"]["stdout"] = private_stream
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            artifacts = MODULE.build_artifacts(results_path)
            evidence_raw = artifacts["evidence.json"]
            evidence = json.loads(evidence_raw)
            self.assertEqual(len(evidence["trials"]), 630)
            self.assertNotIn(b"/Users/", evidence_raw)
            public_receipt = next(
                row["receipt"]
                for row in evidence["trials"]
                if row["path"] == receipt_path.relative_to(root / "trials").as_posix()
            )
            commitment = public_receipt["compression"]["stdout_commitment"]
            self.assertEqual(commitment["classification"], "redacted")
            self.assertEqual(commitment["utf8_bytes"], len(private_stream.encode()))
            self.assertEqual(
                commitment["sha256"],
                hashlib.sha256(private_stream.encode()).hexdigest(),
            )
            self.assertEqual(public_receipt["artifact_bytes"], receipt["artifact_bytes"])
            self.assertNotIn("stdout", public_receipt["compression"])
            public_receipt["artifact_bytes"] += 1
            evidence["public_trial_receipts_manifest_sha256"] = (
                MODULE.public_receipts_manifest_sha256(evidence["trials"])
            )
            with self.assertRaisesRegex(ValueError, "do not reproduce summary row"):
                MODULE.validate_public_evidence(evidence)

    def test_publication_refuses_missing_or_corrupt_trial_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results = fixture()
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            receipt = next((root / "trials").glob("*/*.r1.json"))
            receipt.unlink()
            with self.assertRaisesRegex(ValueError, "1 missing"):
                MODULE.publish(results_path, root / "publication")

    def test_publication_refuses_weak_process_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results = fixture()
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            receipt_path = next((root / "trials").glob("*/*.r1.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            del receipt["compression"]["cpu_ns"]
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "compression record is invalid"):
                MODULE.publish(results_path, root / "publication")

    def test_publication_refuses_changed_codec_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results = fixture()
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            receipt_path = next((root / "trials" / "zstd-19").glob("*.r1.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["compression"]["command"][3] = "-18"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "command differs"):
                MODULE.publish(results_path, root / "publication")

    def test_publication_refuses_noncanonical_duplicate_key_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results = fixture()
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            receipt_path = next((root / "trials").glob("*/*.r1.json"))
            payload = receipt_path.read_bytes().replace(
                b'{\n  "artifact_bytes"',
                b'{\n  "schema_version": 1,\n  "artifact_bytes"',
                1,
            )
            receipt_path.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.publish(results_path, root / "publication")

    def test_publication_refuses_boolean_trial_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            results = fixture()
            results_path = root / "results.json"
            results_path.write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_trial_receipts(root, results)
            receipt_path = next((root / "trials").glob("*/*.r1.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["repetition"] = True
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "identity or integrity failed"):
                MODULE.publish(results_path, root / "publication")


if __name__ == "__main__":
    unittest.main()
