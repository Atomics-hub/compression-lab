from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_PATH = ROOT / "scripts" / "publish-text-source-wk-c1-screen.py"
VERIFIER_PATH = ROOT / "scripts" / "verify-text-source-wk-c1-screen-publication.py"


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


PUBLISHER = load("wk_c1_publication_test", PUBLISHER_PATH)
VERIFIER = load("wk_c1_publication_verifier_test", VERIFIER_PATH)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def process(command: list[str], *, wall_ns: int = 10_000_000, peak: int = 100_000_000) -> dict[str, object]:
    return {
        "command": command,
        "returncode": 0,
        "timed_out": False,
        "wall_ns": wall_ns,
        "cpu_ns": wall_ns - 1,
        "peak_rss_bytes": peak,
        "stdout": "",
        "stderr": "",
    }


class TextSourceWkC1PublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.config_raw, self.config = PUBLISHER.read_canonical(PUBLISHER.CONFIG)

    def bindings(self) -> dict[str, str]:
        return {
            "repository_commit": "a" * 40,
            "config_sha256": PUBLISHER.sha256_bytes(self.config_raw),
            "transform_sha256": PUBLISHER.FROZEN_DEPENDENCIES[
                "scripts/text-source-wk-c1-transform.py"
            ],
            **self.config["bindings"],
        }

    def smoke_row(self, variant: str, item_id: str) -> dict[str, object]:
        source_sha = digest(f"source:{item_id}")
        commands = {
            "encode": ["python", "transform.py", "encode", variant],
            "backend_encode": ["kanzi", "--compress", "--level=9", "--block=1g", "--jobs=1"],
            "backend_decode": ["kanzi", "--decompress", "--jobs=1"],
            "decode": ["python", "transform.py", "decode"],
        }
        records = {key: process(command) for key, command in commands.items()}
        return {
            "variant": variant,
            "item_id": item_id,
            "source_bytes": 1_000_000,
            "source_sha256": source_sha,
            "transform_file_evidence": {"size_bytes": 1000, "sha256": digest(f"smoke:{variant}:{item_id}")},
            **records,
            "maximum_peak_rss_bytes": 100_000_000,
            "exact_roundtrip": True,
            "passed": True,
            "error": None,
        }

    def trial(self, variant: str, item_id: str, repetition: int, size: int) -> dict[str, object]:
        source_bytes = 1_000_000 if item_id == PUBLISHER.RUNNER.SCREEN_ITEMS[0] else 900_000
        source_sha = digest(f"source:{item_id}")
        artifact_sha = digest(f"artifact:{variant}:{item_id}")
        transform_sha = digest(f"transform:{variant}:{item_id}")
        encode = [
            process(["python", "transform.py", "encode", variant, "source", "transformed"]),
            process(["kanzi", "--compress", "--level=9", "--block=1g", "--jobs=1"]),
            process(["python", "runner.py", "wrap", variant]),
        ]
        decode = [
            process(["python", "runner.py", "unwrap", variant]),
            process(["kanzi", "--decompress", "--jobs=1"]),
            process(["python", "transform.py", "decode"]),
        ]
        transform_evidence = {
            "magic": "WKC1",
            "version": 1,
            "variant": variant,
            "source_bytes": source_bytes,
            "source_sha256": source_sha,
            "header_bytes": PUBLISHER.RUNNER.TRANSFORM.HEADER.size,
            "metadata_bytes": 500,
            "value_stream_bytes": 700,
            "complete_transform_bytes": PUBLISHER.RUNNER.TRANSFORM.HEADER.size + 1200,
            "template_count": 10,
            "field_count": 20,
            "sha256": transform_sha,
        }
        return {
            "schema_version": 1,
            "bindings": self.bindings(),
            "variant": variant,
            "item_id": item_id,
            "track": "english_wikimedia_wikitext",
            "repetition": repetition,
            "source_bytes": source_bytes,
            "source_sha256": source_sha,
            "transform_file_evidence": transform_evidence,
            "artifact_file_evidence": {"size_bytes": size, "sha256": artifact_sha},
            "artifact_bytes": size,
            "artifact_sha256": artifact_sha,
            "encode_processes": encode,
            "decode_processes": decode,
            "encode_totals": PUBLISHER.RUNNER.aggregate_processes(encode),
            "decode_totals": PUBLISHER.RUNNER.aggregate_processes(decode),
            "encode_peak_rss_bytes": 100_000_000,
            "decode_peak_rss_bytes": 100_000_000,
            "exact_roundtrip": True,
            "passed": True,
            "error": None,
        }

    def make_run(self, *, strong: bool) -> Path:
        run = self.work / ("strong-run" if strong else "rejected-run")
        sizes = (
            {
                PUBLISHER.RUNNER.VARIANTS[0]: (12_300_000, 11_300_000),
                PUBLISHER.RUNNER.VARIANTS[1]: (12_400_000, 11_400_000),
            }
            if strong
            else {
                PUBLISHER.RUNNER.VARIANTS[0]: (12_600_000, 11_500_000),
                PUBLISHER.RUNNER.VARIANTS[1]: (12_610_000, 11_510_000),
            }
        )
        trials = []
        paths = []
        for variant in PUBLISHER.RUNNER.VARIANTS:
            for item_index, item_id in enumerate(PUBLISHER.RUNNER.SCREEN_ITEMS):
                for repetition in range(2):
                    receipt = self.trial(variant, item_id, repetition, sizes[variant][item_index])
                    path = run / "trials" / variant / f"{item_id}.r{repetition}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(PUBLISHER.json_bytes(receipt))
                    paths.append(path)
                    trials.append(receipt)
        result = {
            "schema_version": 1,
            "name": "text-source-wk-c1-recursive-template-columnarization-screen-result-v1",
            "completed": True,
            "all_required_completed": True,
            "trial_count": 8,
            "trial_receipts_manifest_sha256": PUBLISHER.RUNNER.receipt_manifest(run, paths),
            "bindings": self.bindings(),
            "screen_boundary": self.config["splits"],
            "measurement": self.config["measurement"],
            "preflight": PUBLISHER.RUNNER.preflight(),
            "premeasurement_resource_smoke": [
                self.smoke_row(variant, item_id)
                for variant in PUBLISHER.RUNNER.VARIANTS
                for item_id in PUBLISHER.RUNNER.SCREEN_ITEMS
            ],
            "variants": self.config["variants"],
            "summary": PUBLISHER.RUNNER.summarize(trials, self.config),
            "claim_ceiling": self.config["claim_ceiling"],
            "public_validation_status": "sealed and unaccessed",
            "private_holdout_status": "sealed and unaccessed",
        }
        (run / "results.json").write_bytes(PUBLISHER.json_bytes(result))
        return run

    def publish(self, *, strong: bool) -> Path:
        run = self.make_run(strong=strong)
        provenance = self.work / "provenance.txt"
        benchmark_log = self.work / "benchmark.log"
        provenance.write_text("synthetic offline provenance\n", encoding="utf-8")
        benchmark_log.write_text("synthetic benchmark log\n", encoding="utf-8")
        output = self.work / ("strong-publication" if strong else "rejected-publication")
        PUBLISHER.publish(run=run, provenance=provenance, benchmark_log=benchmark_log, output=output)
        return output

    def test_publishes_and_verifies_strong_training_signal(self) -> None:
        output = self.publish(strong=True)
        verified = VERIFIER.verify(output)
        self.assertTrue(verified["full_strong_signal"])
        self.assertEqual(verified["axiom_wins"], 0)
        comparison = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual([row["id"] for row in comparison["controls"]], ["kanzi-max", "ts-h1"])
        self.assertEqual(len(comparison["schedule"]), 8)
        self.assertIn("training-only", comparison["claim_ceiling"].lower())
        readme = (output / "README.md").read_text(encoding="utf-8")
        self.assertIn("axiom_wins = 0", readme)
        self.assertIn("Public validation", readme)

    def test_rejection_is_explicit(self) -> None:
        output = self.publish(strong=False)
        verified = VERIFIER.verify(output)
        self.assertTrue(verified["rejected"])
        self.assertIn("is rejected", (output / "README.md").read_text(encoding="utf-8"))

    def test_refuses_result_summary_tampering_and_extra_keys(self) -> None:
        run = self.make_run(strong=True)
        result = json.loads((run / "results.json").read_text(encoding="utf-8"))
        result["summary"]["full_signal"] = False
        (run / "results.json").write_bytes(PUBLISHER.json_bytes(result))
        with self.assertRaisesRegex(ValueError, "summary differs"):
            PUBLISHER.collect_run(run)

        run = self.make_run(strong=False)
        result = json.loads((run / "results.json").read_text(encoding="utf-8"))
        result["unreviewed_extension"] = True
        (run / "results.json").write_bytes(PUBLISHER.json_bytes(result))
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            PUBLISHER.collect_run(run)

    def test_refuses_trial_extra_keys_and_determinism_tampering(self) -> None:
        run = self.make_run(strong=True)
        path = next((run / "trials").glob("*/*.json"))
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["unreviewed"] = True
        path.write_bytes(PUBLISHER.json_bytes(receipt))
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            PUBLISHER.collect_run(run)

        run = self.make_run(strong=False)
        paths = sorted((run / "trials" / PUBLISHER.RUNNER.VARIANTS[0]).glob("*.json"))
        receipt = json.loads(paths[0].read_text(encoding="utf-8"))
        receipt["artifact_sha256"] = digest("nondeterministic")
        receipt["artifact_file_evidence"]["sha256"] = receipt["artifact_sha256"]
        paths[0].write_bytes(PUBLISHER.json_bytes(receipt))
        with self.assertRaisesRegex(ValueError, "summary differs|manifest differs"):
            PUBLISHER.collect_run(run)

    def test_refuses_overwrite_and_detects_publication_mutation(self) -> None:
        output = self.publish(strong=True)
        run = self.make_run(strong=False)
        provenance = self.work / "another-provenance.txt"
        log = self.work / "another.log"
        provenance.write_text("p\n", encoding="utf-8")
        log.write_text("l\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            PUBLISHER.publish(run=run, provenance=provenance, benchmark_log=log, output=output)
        (output / "comparison.svg").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "artifact digest differs"):
            VERIFIER.verify(output)

    def test_frozen_dependency_hashes_are_current(self) -> None:
        PUBLISHER.validate_dependencies()
        self.assertEqual(
            set(PUBLISHER.FROZEN_DEPENDENCIES),
            {
                "config/text-source-wk-c1-screen-v1.json",
                "docs/benchmarks/2026-07-18-text-source-wk-c1-protocol.md",
                "scripts/benchmark-text-source-wk-c1-screen.py",
                "scripts/text-source-wk-c1-transform.py",
                "scripts/verify-text-source-wk-c1-screen-run.py",
            },
        )


if __name__ == "__main__":
    unittest.main()
