import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
GATES_PATH = REPOSITORY / "config" / "dms2-public-validation-gates.json"
CORPUS_PATH = REPOSITORY / "config" / "tabular-successor-corpus-v1.json"
BENCHMARK = REPOSITORY / "scripts" / "benchmark-dms2-public-validation.py"
EVALUATOR = REPOSITORY / "scripts" / "evaluate-dms2-public-validation.py"
FETCHER = REPOSITORY / "scripts" / "fetch-dms2-public-validation.py"
WORKER = REPOSITORY / "scripts" / "dms2-validation-worker.py"
LOCK_PATH = REPOSITORY / "config" / "dms2-public-validation-lock.json"
LOCK_VERIFIER = REPOSITORY / "scripts" / "verify-dms2-public-validation-lock.py"
LOCK_RECEIPT = REPOSITORY / "runs" / "dms2-public-validation-lock-v1.json"
READINESS = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-dms2-public-validation-readiness.md"
)


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


def commit_object_present(commit: str) -> bool:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise AssertionError(f"invalid pinned commit: {commit!r}")
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=REPOSITORY,
        capture_output=True,
    )
    if present.returncode == 0:
        return True
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if shallow.returncode != 0 or shallow.stdout.strip() == "true":
        return False
    raise AssertionError(f"pinned commit is absent from a full-history checkout: {commit}")


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class DMS2PublicValidationTests(unittest.TestCase):
    def test_final_lock_pins_the_merged_readiness_surface(self):
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertRegex(lock["readiness_commit"], r"^[0-9a-f]{40}$")
        readiness = lock["readiness_commit"]
        if not commit_object_present(readiness):
            self.skipTest(
                f"readiness commit {readiness[:7]}... is not reachable from "
                "this checkout (shallow clone or source archive); "
                "the historical lock binding is verifiable only in clones "
                "retaining the object"
            )
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
        verifier = load_module("verify_dms2_final_lock", LOCK_VERIFIER)
        receipt = verifier.verify_historical_lock(LOCK_PATH)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["authorization"]["maximum_scored_attempts"], 1)
        self.assertEqual(
            receipt["authorization"]["expected_item_ids"],
            ["uci-gisette-train", "uci-madelon-train"],
        )

    def test_clean_tree_lock_receipt_is_bound_to_the_lock_commit(self):
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        receipt = json.loads(LOCK_RECEIPT.read_text(encoding="utf-8"))
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["tracked_status"], "")
        self.assertEqual(
            receipt["head_commit"],
            "f4d17f4658cf18dd6d16d84c6adb0220809c7884",
        )
        self.assertEqual(receipt["readiness_commit"], lock["readiness_commit"])
        self.assertEqual(receipt["lock_sha256"], digest(LOCK_PATH))
        self.assertEqual(receipt["verified_paths"], lock["locked_paths"])

    def test_explicit_acquisition_still_refuses_a_drifted_lock(self):
        fetcher = load_module("fetch_dms2_drifted_lock", FETCHER)
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        readiness = lock["readiness_commit"]
        if not commit_object_present(readiness):
            self.skipTest(
                f"readiness commit {readiness[:7]}... is not reachable from "
                "this checkout (shallow clone or source archive); "
                "the drift refusal is distinguishable from the ancestor "
                "refusal only in clones retaining the object"
            )
        lock["locked_paths"]["config/dms2-public-validation-gates.json"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            drifted = root / "drifted-lock.json"
            drifted.write_text(json.dumps(lock), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "requires a clean tracked tree|digest mismatch|locked working path drifted",
            ):
                fetcher.acquire(
                    config=CORPUS_PATH,
                    lock=drifted,
                    output=root / "output",
                    cache=root / "cache",
                    allow_public_validation=True,
                )
            self.assertFalse((root / "output").exists())
            self.assertFalse((root / "cache").exists())

    def test_candidate_and_development_evidence_are_frozen(self):
        gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        benchmark = load_module("benchmark_dms2_validation", BENCHMARK)
        candidate = gates["candidate"]
        self.assertTrue(
            any(
                digest(REPOSITORY / relative) != expected
                for relative, expected in candidate["frozen_paths"].items()
            )
        )
        evidence = gates["development_evidence"]
        self.assertEqual(
            benchmark.verify_development_evidence(gates),
            {
                evidence["speed_ratio_path"]: evidence["speed_ratio_sha256"],
                evidence["operational_path"]: evidence["operational_sha256"],
                evidence["cross_platform_path"]: evidence[
                    "cross_platform_sha256"
                ],
            },
        )
        self.assertEqual(candidate["selector_sample_bytes"], 65536)
        self.assertEqual(candidate["direct_fallback_level"], 1)
        frozen_base = candidate["frozen_base_commit"]
        if not commit_object_present(frozen_base):
            self.skipTest(
                f"frozen base commit {frozen_base[:7]}... is not reachable "
                "from this checkout (shallow clone or source archive); the "
                "historical candidate binding is verifiable only "
                "in clones retaining the object"
            )
        for relative, expected in candidate["frozen_paths"].items():
            self.assertEqual(
                digest_at_commit(candidate["frozen_base_commit"], relative),
                expected,
            )
        with self.assertRaisesRegex(ValueError, "working candidate path drifted"):
            benchmark.verify_frozen_candidate(candidate)

    def test_validation_is_unopened_and_both_families_must_win(self):
        gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        validation = corpus["public_validation"]
        expected_ids = [row["id"] for row in gates["validation"]["expected_items"]]
        self.assertEqual(expected_ids, ["uci-gisette-train", "uci-madelon-train"])
        selected = [row for row in validation if row["id"] in expected_ids]
        self.assertEqual([row["id"] for row in selected], expected_ids)
        self.assertTrue(all(row["archive_sha256"] is None for row in selected))
        self.assertTrue(all(row["selected_item_sha256"] is None for row in selected))
        self.assertEqual(
            gates["requirements"][
                "minimum_families_with_five_percent_gain_vs_strongest_complete_exact_byte_baseline"
            ],
            2,
        )
        self.assertEqual(gates["validation"]["corpus_config_sha256"], digest(CORPUS_PATH))
        self.assertEqual(gates["private_holdout"]["status"], "sealed")
        readiness = READINESS.read_text(encoding="utf-8")
        self.assertIn("Ready to lock; validation remains unopened", readiness)
        self.assertIn("both Gisette and Madelon at least 5% smaller", readiness)
        self.assertIn("explicitly contextual rather than paired", readiness)

    def test_acquisition_refuses_before_explicit_authorization(self):
        fetcher = load_module("fetch_dms2_validation", FETCHER)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(ValueError, "refusing to acquire"):
                fetcher.acquire(
                    config=CORPUS_PATH,
                    lock=root / "missing-lock.json",
                    output=root / "output",
                    cache=root / "cache",
                    allow_public_validation=False,
                )
            self.assertFalse((root / "output").exists())
            self.assertFalse((root / "cache").exists())

    def test_worker_stream_is_exact_deterministic_safe_and_bounded(self):
        worker = load_module("dms2_validation_worker", WORKER)
        benchmark = load_module("benchmark_dms2_worker_proof", BENCHMARK)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "matrix.txt"
            first = root / "first.dss1"
            second = root / "second.dss1"
            restored = root / "restored.txt"
            source.write_bytes(
                b"\n".join(
                    b" ".join(str((row + column) % 17).encode() for column in range(64))
                    for row in range(2000)
                )
                + b"\n"
            )
            first_meta = worker.run(
                "compress",
                source,
                first,
                segment_size=16 * 1024,
                level=19,
                max_output_size=source.stat().st_size,
            )
            worker.run(
                "compress",
                source,
                second,
                segment_size=16 * 1024,
                level=19,
                max_output_size=source.stat().st_size,
            )
            worker.run(
                "decompress",
                first,
                restored,
                segment_size=16 * 1024,
                level=19,
                max_output_size=source.stat().st_size,
            )
            self.assertEqual(restored.read_bytes(), source.read_bytes())
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertGreater(first_meta["segments"], 1)
            safety = benchmark.verify_stream_safety(source, first)
            self.assertTrue(safety["passed"])
            self.assertLessEqual(safety["maximum_regression_bytes"], 0)

    def test_evaluator_enforces_ratio_speed_memory_integrity_and_chart(self):
        gates = json.loads(GATES_PATH.read_text(encoding="utf-8"))
        expected = gates["validation"]["expected_items"]
        baseline_ids = gates["baselines"]["codec_ids"]
        corpus = [
            {
                "id": item["id"],
                "family": item["family"],
                "sha256": hashlib.sha256(item["id"].encode()).hexdigest(),
                "size_bytes": 1000,
                "split": "validation",
                "license_spdx": "CC-BY-4.0",
            }
            for item in expected
        ]
        baseline_medians = []
        baseline_summaries = []
        baseline_trials = []
        for codec_index, codec_id in enumerate(baseline_ids):
            compressed = 100 + codec_index
            for item in corpus:
                baseline_medians.append(
                    {
                        "item_id": item["id"],
                        "codec_id": codec_id,
                        "original_bytes": 1000,
                        "compressed_bytes": compressed,
                    }
                )
                baseline_trials.append(
                    {
                        "item_id": item["id"],
                        "codec_id": codec_id,
                        "roundtrip_ok": True,
                        "source_sha256": item["sha256"],
                        "restored_sha256": item["sha256"],
                    }
                )
            baseline_summaries.append(
                {
                    "codec_id": codec_id,
                    "compressed_bytes": compressed * len(corpus),
                    "compression_mbps": 20.0,
                    "decompression_mbps": 100.0,
                    "compression_peak_rss_bytes": 96 * 1024 * 1024,
                    "decompression_peak_rss_bytes": 80 * 1024 * 1024,
                    "roundtrip_failures": 0,
                }
            )
        candidate_trials = []
        for repetition in range(1, 6):
            for item in corpus:
                candidate_trials.append(
                    {
                        "item_id": item["id"],
                        "repetition": repetition,
                        "original_bytes": 1000,
                        "compressed_bytes": 70,
                        "compression_ns": 10_000,
                        "decompression_ns": 2_000,
                        "roundtrip_ok": True,
                        "source_sha256": item["sha256"],
                        "restored_sha256": item["sha256"],
                    }
                )
        candidate_medians = [
            {
                "item_id": item["id"],
                "codec_id": "dms2-stream",
                "original_bytes": 1000,
                "compressed_bytes": 70,
                "compression_ns": 10_000,
                "decompression_ns": 2_000,
            }
            for item in corpus
        ]
        candidate_summary = {
            "codec_id": "dms2-stream",
            "original_bytes": 2000,
            "compressed_bytes": 140,
            "compression_mbps": 100.0,
            "decompression_mbps": 500.0,
            "roundtrip_failures": 0,
        }
        baseline = {
            "codecs": [{"id": codec_id} for codec_id in baseline_ids],
            "corpus": corpus,
            "config": {
                "repetitions": 5,
                "warmups": 1,
                "execution_mode": "persistent-worker",
            },
            "failures": [],
            "medians": baseline_medians,
            "summary": baseline_summaries,
            "trials": baseline_trials,
        }
        baseline_memory = {
            "corpus": corpus,
            "config": {"execution_mode": "cold-process"},
            "failures": [],
            "summary": baseline_summaries,
            "trials": baseline_trials,
        }
        candidate = {
            "corpus": corpus,
            "config": {
                "repetitions": 5,
                "warmups": 1,
                "execution_mode": "persistent-dms2-worker",
                "order_seed": 20260717,
            },
            "failures": [],
            "medians": candidate_medians,
            "summary": candidate_summary,
            "trials": candidate_trials,
        }
        candidate_memory = {
            "config": {"execution_mode": "cold-process"},
            "summary": {
                "codec_id": "dms2-stream",
                "compression_peak_rss_bytes": 128 * 1024 * 1024,
                "decompression_peak_rss_bytes": 96 * 1024 * 1024,
                "roundtrip_failures": 0,
            },
            "trials": [
                {"item_id": item["id"], "roundtrip_ok": True} for item in corpus
            ],
        }
        proof = [
            {
                "id": item["id"],
                "exact_roundtrip": True,
                "deterministic": True,
                "corruption_rejected": True,
                "fallback_safety": {
                    "passed": True,
                    "maximum_regression_bytes": 0,
                },
            }
            for item in corpus
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paths = {
                "baseline_performance": root / "baseline.json",
                "baseline_memory": root / "baseline-memory.json",
                "candidate_performance": root / "candidate.json",
                "candidate_memory": root / "candidate-memory.json",
            }
            payloads = {
                "baseline_performance": baseline,
                "baseline_memory": baseline_memory,
                "candidate_performance": candidate,
                "candidate_memory": candidate_memory,
            }
            for name, path in paths.items():
                path.write_text(json.dumps(payloads[name]), encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"items": corpus}), encoding="utf-8")
            receipt_path = root / "receipt.json"
            decision_path = root / "decision.json"
            evidence = gates["development_evidence"]
            receipt = {
                "first_score": True,
                "completed": True,
                "repository": {"tracked_status": ""},
                "normalized_preflight_load_1m": 0.1,
                "manifest_path": str(manifest),
                "manifest_sha256": digest(manifest),
                "gates_sha256": digest(GATES_PATH),
                "lock_receipt": {"passed": True},
                "frozen_candidate_paths": gates["candidate"]["frozen_paths"],
                "development_evidence_paths": {
                    evidence["speed_ratio_path"]: evidence["speed_ratio_sha256"],
                    evidence["operational_path"]: evidence["operational_sha256"],
                    evidence["cross_platform_path"]: evidence[
                        "cross_platform_sha256"
                    ],
                },
                "baseline_performance_results": paths[
                    "baseline_performance"
                ].name,
                "baseline_performance_sha256": digest(
                    paths["baseline_performance"]
                ),
                "baseline_memory_results": paths["baseline_memory"].name,
                "baseline_memory_sha256": digest(paths["baseline_memory"]),
                "candidate_performance_results": paths[
                    "candidate_performance"
                ].name,
                "candidate_performance_sha256": digest(
                    paths["candidate_performance"]
                ),
                "candidate_memory_results": paths["candidate_memory"].name,
                "candidate_memory_sha256": digest(paths["candidate_memory"]),
                "deterministic_integrity_fallback_proof": proof,
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
                str(decision_path),
            ]
            passed = subprocess.run(
                command,
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            decision = json.loads(decision_path.read_text())
            self.assertTrue(decision["passed"])
            self.assertEqual(len(decision["comparison_chart"]), 11)
            self.assertIn("contextual", decision["runner_comparability"]["speed"])

            for row in candidate["medians"]:
                row["compressed_bytes"] = 99
            candidate["summary"]["compressed_bytes"] = 198
            paths["candidate_performance"].write_text(
                json.dumps(candidate), encoding="utf-8"
            )
            receipt["candidate_performance_sha256"] = digest(
                paths["candidate_performance"]
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            failed = subprocess.run(
                command,
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 2, failed.stderr)
            decision = json.loads(decision_path.read_text())
            self.assertFalse(decision["gate_results"]["aggregate_ratio"])
            self.assertFalse(decision["gate_results"]["family_ratio_count"])


if __name__ == "__main__":
    unittest.main()
