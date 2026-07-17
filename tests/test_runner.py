import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from compresslab.codecs import resolve_codecs
from compresslab.cli import build_parser
from compresslab.corpus import generate_corpus
from compresslab.benchmark_runner import run_benchmark


class RunnerTests(unittest.TestCase):
    def test_smoke_roundtrip_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus"
            output = root / "run"
            generate_corpus(corpus, size_scale=0.125)
            run = run_benchmark(
                corpus,
                output,
                resolve_codecs(
                    [
                        "store",
                        "adaptive-v0",
                        "adaptive-v1",
                        "adaptive-v2",
                        "adaptive-v3",
                        "gzip-1",
                    ]
                ),
                repetitions=1,
                warmups=0,
                bandwidths_mbps=[100.0],
                timeout_seconds=30.0,
            )
            self.assertFalse(run.failures)
            self.assertEqual(len(run.trials), 48)
            self.assertTrue((output / "results.json").is_file())
            self.assertTrue((output / "summary.csv").is_file())
            self.assertTrue((output / "report.md").is_file())
            payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 5)
            self.assertIn("commit", payload["system"]["git"])
            self.assertEqual(payload["config"]["order_seed"], 20260715)
            self.assertEqual(payload["config"]["runner"]["api_version"], 2)
            self.assertEqual(
                payload["config"]["corpus_manifest"]["selected_item_count"], 8
            )
            self.assertEqual(
                payload["config"]["corpus_manifest"]["sha256"],
                hashlib.sha256((corpus / "manifest.json").read_bytes()).hexdigest(),
            )
            self.assertIn("per_codec", payload["stability"])
            self.assertEqual(len(payload["summary"]), 6)
            adaptive = next(
                row for row in payload["summary"] if row["codec_id"] == "adaptive-v0"
            )
            self.assertEqual(adaptive["roundtrip_failures"], 0)
            adaptive_medians = [
                row for row in payload["medians"] if row["codec_id"] == "adaptive-v0"
            ]
            self.assertEqual(len(adaptive_medians), 8)
            for row in adaptive_medians:
                if row["item_category"] in {"incompressible", "already-compressed"}:
                    self.assertEqual(row["selected_backend"], "store")
                    self.assertLessEqual(
                        row["compressed_bytes"], row["original_bytes"] + 46
                    )
            self.assertIn("by_bandwidth", payload["oracle"])
            adaptive_v1 = [
                row for row in payload["medians"] if row["codec_id"] == "adaptive-v1"
            ]
            self.assertTrue(
                any(
                    row["selected_backend"] == "delta-transpose+gzip-1"
                    for row in adaptive_v1
                )
            )
            adaptive_v2 = [
                row for row in payload["medians"] if row["codec_id"] == "adaptive-v2"
            ]
            self.assertEqual(len(adaptive_v2), 8)
            self.assertTrue(all(row["roundtrip_ok"] for row in adaptive_v2))
            adaptive_v3 = [
                row for row in payload["medians"] if row["codec_id"] == "adaptive-v3"
            ]
            self.assertEqual(len(adaptive_v3), 8)
            self.assertTrue(all(row["roundtrip_ok"] for row in adaptive_v3))
            self.assertTrue(
                any(row["transformed_segments"] > 0 for row in adaptive_v3)
            )

    def test_persistent_workers_and_shuffled_repetition_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus"
            output = root / "run"
            generate_corpus(corpus, size_scale=0.03125)
            run = run_benchmark(
                corpus,
                output,
                resolve_codecs(["store", "gzip-1"]),
                repetitions=2,
                warmups=0,
                bandwidths_mbps=[100.0],
                timeout_seconds=30.0,
                execution_mode="persistent-worker",
                order_seed=17,
                bootstrap_samples=100,
                minimum_trial_time_ms=5.0,
                max_batch_iterations=4096,
            )
            self.assertFalse(run.failures)
            self.assertEqual(run.config["execution_mode"], "persistent-worker")
            self.assertEqual(run.config["minimum_trial_time_ms"], 5.0)
            self.assertTrue(
                any(row["compression_batch_iterations"] > 1 for row in run.trials)
            )
            self.assertTrue(
                any(row["decompression_batch_iterations"] > 1 for row in run.trials)
            )
            self.assertTrue(
                all(row["compression_batch_target_met"] for row in run.trials)
            )
            self.assertTrue(
                all(row["decompression_batch_target_met"] for row in run.trials)
            )
            for codec_id in ("store", "gzip-1"):
                codec_trials = [row for row in run.trials if row["codec_id"] == codec_id]
                pids = {
                    row["compression_worker_pid"] for row in codec_trials
                } | {row["decompression_worker_pid"] for row in codec_trials}
                self.assertEqual(len(pids), 1)
                self.assertNotIn(0, pids)
            orders = []
            for repetition in (1, 2):
                rows = sorted(
                    (row for row in run.trials if row["repetition"] == repetition),
                    key=lambda row: row["order_index"],
                )
                self.assertEqual(
                    [row["order_index"] for row in rows],
                    list(range(1, len(rows) + 1)),
                )
                orders.append([(row["item_id"], row["codec_id"]) for row in rows])
            self.assertNotEqual(orders[0], orders[1])

    def test_explicit_manifest_ignores_disagreeing_sibling_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus"
            output = root / "run"
            default_manifest = generate_corpus(corpus, size_scale=0.03125)
            payload = json.loads(default_manifest.read_text(encoding="utf-8"))
            selected_item = payload["items"][3]
            projected_manifest = corpus / "scoring-manifest.json"
            projected_manifest.write_text(
                json.dumps(
                    {**payload, "items": [selected_item]},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            run = run_benchmark(
                corpus,
                output,
                resolve_codecs(["store"]),
                repetitions=1,
                warmups=0,
                bandwidths_mbps=[100.0],
                timeout_seconds=30.0,
                manifest_path=projected_manifest,
            )

            self.assertEqual([row["id"] for row in run.corpus], [selected_item["id"]])
            self.assertEqual(len(run.trials), 1)
            identity = run.config["corpus_manifest"]
            self.assertEqual(identity["path"], str(projected_manifest.resolve()))
            self.assertEqual(
                identity["sha256"],
                hashlib.sha256(projected_manifest.read_bytes()).hexdigest(),
            )
            self.assertEqual(identity["selected_item_ids"], [selected_item["id"]])
            self.assertEqual(len(payload["items"]), 8)

    def test_invalid_explicit_manifest_refuses_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus"
            output = root / "run"
            default_manifest = generate_corpus(corpus, size_scale=0.03125)
            payload = json.loads(default_manifest.read_text(encoding="utf-8"))
            payload["items"][0]["sha256"] = "0" * 64
            invalid_manifest = corpus / "invalid-manifest.json"
            invalid_manifest.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Corpus integrity check failed"):
                run_benchmark(
                    corpus,
                    output,
                    resolve_codecs(["store"]),
                    repetitions=1,
                    warmups=0,
                    manifest_path=invalid_manifest,
                )
            self.assertFalse(output.exists())

    def test_cli_accepts_an_explicit_manifest(self):
        manifest = Path("corpus/scoring-manifest.json")
        args = build_parser().parse_args(
            [
                "run",
                "--corpus",
                "corpus",
                "--manifest",
                str(manifest),
                "--output",
                "run",
            ]
        )
        self.assertEqual(args.manifest, manifest)


if __name__ == "__main__":
    unittest.main()
