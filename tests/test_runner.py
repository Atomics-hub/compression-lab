import json
import tempfile
import unittest
from pathlib import Path

from compresslab.codecs import resolve_codecs
from compresslab.corpus import generate_corpus
from compresslab.runner import run_benchmark


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
                    ["store", "adaptive-v0", "adaptive-v1", "adaptive-v2", "gzip-1"]
                ),
                repetitions=1,
                warmups=0,
                bandwidths_mbps=[100.0],
                timeout_seconds=30.0,
            )
            self.assertFalse(run.failures)
            self.assertEqual(len(run.trials), 40)
            self.assertTrue((output / "results.json").is_file())
            self.assertTrue((output / "summary.csv").is_file())
            self.assertTrue((output / "report.md").is_file())
            payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["config"]["order_seed"], 20260715)
            self.assertIn("per_codec", payload["stability"])
            self.assertEqual(len(payload["summary"]), 5)
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
            )
            self.assertFalse(run.failures)
            self.assertEqual(run.config["execution_mode"], "persistent-worker")
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


if __name__ == "__main__":
    unittest.main()
