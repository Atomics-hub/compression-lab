import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
GATES_PATH = REPOSITORY / "config" / "tbl1-public-validation-gates.json"
CORPUS_PATH = REPOSITORY / "config" / "tabular-corpus-v1.json"
EVALUATOR = REPOSITORY / "scripts" / "evaluate-tbl1-public-validation.py"
BENCHMARK = REPOSITORY / "scripts" / "benchmark-tbl1-public-validation.py"
LOCK_PATH = REPOSITORY / "config" / "tbl1-public-validation-lock.json"
LOCK_VERIFIER = REPOSITORY / "scripts" / "verify-tbl1-public-validation-lock.py"
GIT_ATTRIBUTES = REPOSITORY / ".gitattributes"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_at_commit(commit: str, path: str) -> str:
    content = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def load_benchmark_module():
    specification = importlib.util.spec_from_file_location(
        "benchmark_tbl1_public_validation",
        BENCHMARK,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("unable to load TBL1 validation benchmark")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class TBL1PublicValidationTests(unittest.TestCase):
    def test_final_lock_pins_merged_readiness_controls(self):
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertRegex(lock["readiness_commit"], r"^[0-9a-f]{40}$")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", lock["readiness_commit"], "HEAD"],
            cwd=REPOSITORY,
            check=False,
        )
        self.assertEqual(ancestor.returncode, 0)
        for relative, expected in lock["locked_paths"].items():
            committed = subprocess.run(
                ["git", "show", f"{lock['readiness_commit']}:{relative}"],
                cwd=REPOSITORY,
                check=True,
                capture_output=True,
            ).stdout
            self.assertEqual(hashlib.sha256(committed).hexdigest(), expected)
            self.assertEqual(digest(REPOSITORY / relative), expected)

        specification = importlib.util.spec_from_file_location(
            "verify_tbl1_public_validation_lock",
            LOCK_VERIFIER,
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader if specification else None)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        receipt = module.verify_lock(LOCK_PATH, require_clean=False)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["readiness_commit"], lock["readiness_commit"])

    def test_segment_fallback_proof_recomputes_equally_framed_route(self):
        module = load_benchmark_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.csv"
            frame = root / "source.tbs1"
            source.write_bytes((b"kind,value\nalpha,1\nbeta,2\n" * 1000))
            module.compress_stream(source, frame, segment_size=4096, record_slack=256)
            proof = module.verify_stream_safety(source, frame)
            self.assertTrue(proof["passed"])
            self.assertGreater(proof["segments"], 1)
            self.assertLessEqual(proof["maximum_regression_bytes"], 0)

    def test_declared_candidate_hashes_match_frozen_base_commit(self):
        gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        candidate = gates["candidate"]
        for relative, expected in candidate["frozen_paths"].items():
            self.assertEqual(
                digest_at_commit(candidate["frozen_base_commit"], relative),
                expected,
            )
        module = load_benchmark_module()
        with self.assertRaisesRegex(
            ValueError, "working candidate path differs from frozen digest"
        ):
            module.verify_frozen_candidate(candidate)

    def test_validation_is_unopened_and_provenance_is_frozen(self):
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        validation = corpus["public_validation"]
        self.assertEqual(len(validation), 4)
        self.assertTrue(all(item["archive_sha256"] is None for item in validation))
        self.assertTrue(
            all(item["selected_item_sha256"] is None for item in validation)
        )
        oulad = next(item for item in validation if item["dataset_id"] == 349)
        self.assertIn("open%2Buniversity", oulad["page_url"])
        self.assertNotIn("tennis", oulad["page_url"])
        self.assertEqual(gates["validation"]["corpus_config_sha256"], digest(CORPUS_PATH))
        self.assertRegex(gates["candidate"]["frozen_base_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            gates["candidate"]["codec_id"],
            "tbl1-stream-dense",
        )
        self.assertEqual(len(gates["baselines"]["codec_ids"]), 10)
        self.assertEqual(
            gates["private_holdout"]["status"],
            "sealed",
        )
        self.assertIn(
            "* text=auto eol=lf",
            GIT_ATTRIBUTES.read_text(encoding="utf-8"),
        )

    def test_evaluator_enforces_ratio_speed_memory_and_proof_gates(self):
        gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        candidate_id = gates["candidate"]["codec_id"]
        baseline_ids = gates["baselines"]["codec_ids"]
        codec_ids = [candidate_id, *baseline_ids]
        expected = gates["validation"]["expected_items"]
        corpus = [
            {
                "id": item["id"],
                "sha256": item["id"].ljust(64, "0")[:64],
                "size_bytes": 1000,
                "split": "validation",
                "license_spdx": "CC-BY-4.0",
            }
            for item in expected
        ]
        medians = []
        summaries = []
        for codec_index, codec_id in enumerate(codec_ids):
            per_item = 70 if codec_id == candidate_id else 100 + codec_index
            for item in expected:
                medians.append(
                    {
                        "item_id": item["id"],
                        "codec_id": codec_id,
                        "original_bytes": 1000,
                        "compressed_bytes": per_item,
                    }
                )
            summaries.append(
                {
                    "codec_id": codec_id,
                    "compressed_bytes": per_item * len(expected),
                    "compression_mbps": 60.0 if codec_id == candidate_id else 10.0,
                    "decompression_mbps": 300.0 if codec_id == candidate_id else 100.0,
                    "compression_peak_rss_bytes": 128 * 1024 * 1024,
                    "decompression_peak_rss_bytes": 96 * 1024 * 1024,
                    "roundtrip_failures": 0,
                }
            )
        trials = []
        for repetition in range(1, 6):
            for item in corpus:
                trials.append(
                    {
                        "item_id": item["id"],
                        "codec_id": candidate_id,
                        "repetition": repetition,
                        "original_bytes": 1000,
                        "compression_ns": 10000,
                        "decompression_ns": 2000,
                        "roundtrip_ok": True,
                        "source_sha256": item["sha256"],
                        "restored_sha256": item["sha256"],
                    }
                )
        for codec_id in baseline_ids:
            for item in corpus:
                trials.append(
                    {
                        "item_id": item["id"],
                        "codec_id": codec_id,
                        "repetition": 1,
                        "original_bytes": 1000,
                        "compression_ns": 10000,
                        "decompression_ns": 2000,
                        "roundtrip_ok": True,
                        "source_sha256": item["sha256"],
                        "restored_sha256": item["sha256"],
                    }
                )
        performance = {
            "codecs": [{"id": codec_id} for codec_id in codec_ids],
            "corpus": corpus,
            "config": {
                "repetitions": 5,
                "warmups": 1,
                "execution_mode": "persistent-worker",
                "order_seed": 20260717,
                "splits": ["validation"],
            },
            "failures": [],
            "summary": summaries,
            "medians": medians,
            "trials": trials,
        }
        memory = {
            "codecs": [{"id": candidate_id}],
            "corpus": corpus,
            "config": {
                "repetitions": 1,
                "warmups": 0,
                "execution_mode": "cold-process",
                "order_seed": 20260717,
                "splits": ["validation"],
            },
            "failures": [],
            "summary": [summaries[0]],
            "medians": [row for row in medians if row["codec_id"] == candidate_id],
            "trials": [row for row in trials if row["codec_id"] == candidate_id][:4],
        }
        proof = [
            {
                "id": item["id"],
                "exact_roundtrip": True,
                "deterministic": True,
                "first_metadata": {"segment_count": 1},
                "fallback_safety": {
                    "segments": 1,
                    "maximum_regression_bytes": 0,
                    "passed": True,
                },
            }
            for item in expected
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            performance_dir = root / "performance"
            memory_dir = root / "memory"
            performance_dir.mkdir()
            memory_dir.mkdir()
            performance_path = performance_dir / "results.json"
            memory_path = memory_dir / "results.json"
            receipt_path = root / "receipt.json"
            manifest_path = root / "manifest.json"
            output_path = root / "decision.json"
            performance_path.write_text(json.dumps(performance), encoding="utf-8")
            memory_path.write_text(json.dumps(memory), encoding="utf-8")
            manifest_path.write_text(json.dumps({"items": corpus}), encoding="utf-8")
            receipt = {
                "first_score": True,
                "completed": True,
                "repository": {"tracked_status": ""},
                "normalized_preflight_load_1m": 0.1,
                "gates_sha256": digest(GATES_PATH),
                "manifest_path": str(manifest_path),
                "manifest_sha256": digest(manifest_path),
                "frozen_candidate_paths": gates["candidate"]["frozen_paths"],
                "performance_results": "performance/results.json",
                "performance_results_sha256": digest(performance_path),
                "memory_results": "memory/results.json",
                "memory_results_sha256": digest(memory_path),
                "deterministic_proof": proof,
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            command = [
                sys.executable,
                str(EVALUATOR),
                "--receipt",
                str(receipt_path),
                "--gates",
                str(GATES_PATH),
                "--output",
                str(output_path),
            ]
            passed = subprocess.run(
                command,
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertTrue(json.loads(output_path.read_text())["passed"])

            for row in performance["medians"]:
                if row["codec_id"] == candidate_id:
                    row["compressed_bytes"] = 99
            performance["summary"][0]["compressed_bytes"] = 396
            performance_path.write_text(json.dumps(performance), encoding="utf-8")
            receipt["performance_results_sha256"] = digest(performance_path)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            failed = subprocess.run(
                command,
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 2, failed.stderr)
            decision = json.loads(output_path.read_text())
            self.assertFalse(decision["passed"])
            self.assertFalse(decision["gate_results"]["aggregate_ratio"])
            self.assertFalse(decision["gate_results"]["family_ratio_count"])


if __name__ == "__main__":
    unittest.main()
