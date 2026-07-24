from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "config" / "clue-jls2-public-validation-v2-gates.json"
CORPUS = ROOT / "config" / "clue-json-log-corpus-v2.json"
FETCHER = ROOT / "scripts" / "fetch-clue-json-corpus-v2.py"
VERIFIER = ROOT / "scripts" / "verify-clue-jls2-public-validation-v2-lock.py"
BENCHMARK = ROOT / "scripts" / "benchmark-clue-jls2-public-validation-v2.py"
EVALUATOR = ROOT / "scripts" / "evaluate-clue-jls2-public-validation-v2.py"
PBC_GATES = ROOT / "config" / "clue-pbc-public-validation-v2-gates.json"
READINESS = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-23-clue-jls2-public-validation-v2-readiness.md"
)
MIB = 1024 * 1024


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_at_commit(commit: str, relative: str) -> str:
    content = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def build_valid_inputs(gates: dict):
    candidate_id = gates["candidate"]["codec_id"]
    codec_ids = [candidate_id, *gates["baselines"]["standard_codec_ids"]]
    expected = gates["validation"]["expected_items"]
    medians = []
    trials = []
    summaries = []
    for codec_index, codec_id in enumerate(codec_ids):
        compressed = 100 if codec_id == candidate_id else 120 + codec_index
        summaries.append(
            {
                "codec_id": codec_id,
                "original_bytes": 2000,
                "compressed_bytes": compressed,
                "compression_mbps": 120.0 if codec_id == candidate_id else 80.0,
                "decompression_mbps": 400.0,
                "compression_peak_rss_bytes": 128 * MIB,
                "decompression_peak_rss_bytes": 96 * MIB,
                "roundtrip_failures": 0,
            }
        )
        for item in expected:
            source_sha256 = hashlib.sha256(item["id"].encode()).hexdigest()
            medians.append(
                {
                    "item_id": item["id"],
                    "codec_id": codec_id,
                    "original_bytes": 1000,
                    "compressed_bytes": 50
                    if codec_id == candidate_id
                    else 60 + codec_index,
                    "source_sha256": source_sha256,
                }
            )
            trials.append(
                {
                    "item_id": item["id"],
                    "codec_id": codec_id,
                    "compression_mbps": 110.0,
                    "roundtrip_ok": True,
                }
            )
    proof_rows = [
        {
            "id": item["id"],
            "family": item["family"],
            "deterministic": True,
            "corruption_rejected": True,
            "fallback_safety": {
                "maximum_regression_bytes": 0,
                "stream_bytes": 100,
                "accounted_stream_bytes": 100,
                "complete_frame_accounting": True,
                "passed": True,
            },
        }
        for item in expected
    ]
    compression_rss_rows = [
        {
            "item_id": item["id"],
            "family": item["family"],
            "source_bytes": 1000,
            "maxrss_bytes": 128 * MIB,
            "shim_maxrss_bytes": 8 * MIB,
            "shim_floor_eligible": True,
        }
        for item in expected
    ]
    decode_trials = [
        {
            "item_id": item["id"],
            "family": item["family"],
            "round": repetition + 1,
            "warmup": False,
            "mbps": 300.0,
            "exact": True,
            "peak_rss_bytes": 96 * MIB,
            "shim_maxrss_bytes": 8 * MIB,
            "shim_floor_eligible": True,
        }
        for repetition in range(5)
        for item in expected
    ]
    receipt = {
        "first_score": True,
        "completed": True,
        "frozen_candidate_paths": gates["candidate"]["frozen_paths"],
        "verified_development_evidence": {"a": "1", "b": "2", "c": "3"},
        "candidate_proof": {
            "deterministic_rows": proof_rows,
            "compression_rss_rows": compression_rss_rows,
            "compression_rss_summary": {
                "peak_rss_bytes": 128 * MIB,
                "worst_shim_maxrss_bytes": 8 * MIB,
                "all_shim_floor_eligible": True,
            },
            "standalone_decode_trials": decode_trials,
            "standalone_decode_summary": {
                "median_aggregate_mbps": 300.0,
                "minimum_aggregate_mbps": 300.0,
                "peak_rss_bytes": 96 * MIB,
                "worst_shim_maxrss_bytes": 8 * MIB,
                "all_exact": True,
                "all_shim_floor_eligible": True,
            },
        },
    }
    performance = {
        "schema_version": 5,
        "failures": [],
        "codecs": [{"id": codec_id} for codec_id in codec_ids],
        "summary": summaries,
        "medians": medians,
        "trials": trials,
    }
    pbc_rows = [
        {
            "family": item["family"],
            "method": "pbc_only",
            "original_bytes": 1000,
            "source_sha256": hashlib.sha256(item["id"].encode()).hexdigest(),
            "archive_bytes": 75,
        }
        for item in expected
    ]
    pbc = {
        "passed": True,
        "rows": pbc_rows,
        "aggregates": {
            "pbc_only": {
                "original_bytes": 2000,
                "archive_bytes": 150,
                "complete_compression_mbps": 10.0,
                "decompression_mbps": 50.0,
            }
        },
        "decision": {"primary_method": "pbc_only"},
    }
    return receipt, performance, pbc


class ClueJLS2V2ValidationReadinessTests(unittest.TestCase):
    def test_candidate_and_development_evidence_are_frozen(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        candidate = gates["candidate"]
        self.assertEqual(gates["public_brand"], "Atompress")
        self.assertEqual(gates["technical_codec"], "JLS2")
        self.assertEqual(gates["prior_score"]["result"], "not_passed")
        self.assertTrue(gates["prior_score"]["immutable"])
        for relative, expected in candidate["frozen_paths"].items():
            self.assertEqual(
                digest_at_commit(candidate["frozen_implementation_commit"], relative),
                expected,
            )
        self.assertEqual(
            candidate["frozen_paths"]["native/src/jls2.rs"],
            digest(ROOT / "native" / "src" / "jls2.rs"),
        )
        evidence = gates["development_evidence"]
        for prefix in ("ratio_census", "standalone_local", "standalone_hosted"):
            self.assertEqual(
                digest(ROOT / evidence[f"{prefix}_path"]),
                evidence[f"{prefix}_sha256"],
            )

    def test_instrument_and_ranges_are_pinned(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        instrument = gates["instrument"]
        self.assertEqual(
            instrument["clean_rss_sha256"],
            digest(ROOT / instrument["clean_rss_path"]),
        )
        self.assertEqual(
            instrument["clean_rss_sha256"],
            "805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306",
        )
        self.assertEqual(
            instrument["candidate_compress_driver_sha256"],
            digest(ROOT / instrument["candidate_compress_driver_path"]),
        )
        self.assertEqual(gates["validation"]["corpus_config_sha256"], digest(CORPUS))
        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        expected = gates["validation"]["expected_items"]
        sealed = corpus["selection"]["public_validation"]
        self.assertEqual([row["id"] for row in expected], [row["id"] for row in sealed])
        self.assertEqual(
            [(r["first_record_id"], r["last_record_id"]) for r in expected],
            [(28_000_001, 28_250_000), (40_000_001, 40_250_000)],
        )
        self.assertTrue(all(row["size_bytes"] is None for row in sealed))

    def test_thresholds_and_authorization(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        requirements = gates["requirements"]
        self.assertEqual(
            requirements["maximum_cold_decompression_peak_rss_bytes"], 536_870_912
        )
        self.assertEqual(
            requirements["maximum_cold_compression_peak_rss_bytes"], 536_870_912
        )
        self.assertEqual(requirements["maximum_shim_floor_bytes"], 67_108_864)
        self.assertEqual(requirements["maximum_shim_fraction_of_maxrss"], 0.25)
        self.assertTrue(requirements["require_shim_floor_eligibility"])
        self.assertEqual(requirements["minimum_families_passing_ratio_gate"], 2)
        self.assertEqual(requirements["minimum_aggregate_compression_mbps"], 100.0)
        self.assertEqual(
            requirements["minimum_aggregate_standalone_decompression_mbps"], 250.0
        )
        self.assertFalse(gates["authorization"]["validation_currently_authorized"])
        self.assertEqual(gates["authorization"]["maximum_acquisitions"], 1)
        self.assertEqual(gates["authorization"]["maximum_scored_attempts"], 1)
        self.assertEqual(gates["runner_class"]["hosted_label"], "ubuntu-22.04")
        self.assertEqual(gates["runner_class"]["vcpus"], 4)
        self.assertEqual(gates["private_holdout"]["status"], "sealed")

    def test_complete_roster_and_unavailable_markers(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        self.assertEqual(len(gates["baselines"]["standard_codec_ids"]), 10)
        self.assertEqual(gates["baselines"]["specialist"]["name"], "PBC-only")
        self.assertEqual(
            gates["baselines"]["specialist"]["gates_sha256"], digest(PBC_GATES)
        )
        pbc = json.loads(PBC_GATES.read_text(encoding="utf-8"))
        self.assertEqual(
            pbc["requirements"]["expected_families"],
            ["clue_validation_v2_c", "clue_validation_v2_d"],
        )
        self.assertEqual(
            set(gates["baselines"]["unavailable_context"]),
            {"LogFold", "LogPrism", "LogLite", "DeLog"},
        )
        self.assertEqual(
            gates["baselines"]["eligibility_audit_sha256"],
            digest(ROOT / gates["baselines"]["eligibility_audit_path"]),
        )
        text = READINESS.read_text(encoding="utf-8")
        self.assertIn("validation remains unopened and unauthorized", text.lower())
        self.assertIn("absence is not a JLS2 win", text)
        self.assertIn("each of the two families", text.lower())

    def test_validation_refuses_without_final_lock(self) -> None:
        fetcher = load_module("fetch_clue_v2_without_final_lock", FETCHER)
        verifier = load_module("verify_clue_v2_missing_lock", VERIFIER)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = root / "missing-lock.json"
            with self.assertRaisesRegex(ValueError, "readiness lock is missing"):
                verifier.verify_lock(missing, require_clean=False)
            with self.assertRaisesRegex(ValueError, "valid final readiness lock"):
                fetcher.build(
                    CORPUS,
                    "public-validation",
                    root / "output",
                    root / "cache",
                    allow_public_validation=True,
                    validation_lock=missing,
                )
            self.assertFalse((root / "output").exists())
            self.assertFalse((root / "cache").exists())

    def test_pbc_projection_uses_identical_bytes(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        benchmark = load_module("benchmark_clue_v2_projection", BENCHMARK)
        items = []
        medians = []
        for index, expected in enumerate(gates["validation"]["expected_items"]):
            digest_value = hashlib.sha256(expected["id"].encode()).hexdigest()
            items.append(
                {
                    **expected,
                    "size_bytes": 1000,
                    "sha256": digest_value,
                    "path": f"{expected['id']}.jsonl",
                }
            )
            medians.extend(
                [
                    {
                        "item_id": expected["id"],
                        "codec_id": "jls2",
                        "source_sha256": digest_value,
                        "compressed_bytes": 100 + index,
                    },
                    {
                        "item_id": expected["id"],
                        "codec_id": "zstd-9",
                        "source_sha256": digest_value,
                        "compressed_bytes": 150 + index,
                    },
                ]
            )
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "accepted.json"
            results = Path(raw) / "results.json"
            results.write_text(json.dumps({"medians": medians}), encoding="utf-8")
            benchmark.write_pbc_accepted(results, items, output)
            accepted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            [row["family"] for row in accepted["rows"]],
            ["clue_validation_v2_c", "clue_validation_v2_d"],
        )
        self.assertEqual([row["encoded_bytes"] for row in accepted["rows"]], [100, 101])

    def test_evaluator_passes_and_enforces_gates(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        evaluator = load_module("evaluate_clue_v2_first_score", EVALUATOR)
        receipt, performance, pbc = build_valid_inputs(gates)
        result = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertTrue(result["category_gate_passed"])
        self.assertTrue(all(result["gate_results"].values()))
        self.assertEqual(len(result["comparison_rows"]), 16)
        self.assertEqual(
            sum(row["compressed_bytes"] is None for row in result["comparison_rows"]),
            4,
        )
        self.assertEqual(result["prior_score"]["result"], "not_passed")

    def test_evaluator_fails_on_ratio_boundary(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        evaluator = load_module("evaluate_clue_v2_ratio", EVALUATOR)
        candidate_id = gates["candidate"]["codec_id"]
        receipt, performance, pbc = build_valid_inputs(gates)
        performance["summary"][0]["compressed_bytes"] = 119
        for row in performance["medians"]:
            if row["codec_id"] == candidate_id:
                row["compressed_bytes"] = 59
        failed = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertFalse(failed["category_gate_passed"])
        self.assertFalse(failed["gate_results"]["aggregate_ratio"])
        self.assertFalse(failed["gate_results"]["all_family_ratio"])

    def test_evaluator_fails_on_decode_memory_boundary(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        evaluator = load_module("evaluate_clue_v2_memory", EVALUATOR)
        limit = gates["requirements"]["maximum_cold_decompression_peak_rss_bytes"]
        receipt, performance, pbc = build_valid_inputs(gates)
        receipt["candidate_proof"]["standalone_decode_summary"]["peak_rss_bytes"] = (
            limit + 1
        )
        failed = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertFalse(failed["gate_results"]["decompression_memory"])
        self.assertFalse(failed["category_gate_passed"])
        # Exactly the limit stays eligible.
        receipt, performance, pbc = build_valid_inputs(gates)
        receipt["candidate_proof"]["standalone_decode_summary"]["peak_rss_bytes"] = (
            limit
        )
        boundary = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertTrue(boundary["gate_results"]["decompression_memory"])

    def test_evaluator_fails_on_shim_floor_ineligibility(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        evaluator = load_module("evaluate_clue_v2_shim", EVALUATOR)
        receipt, performance, pbc = build_valid_inputs(gates)
        receipt["candidate_proof"]["standalone_decode_summary"][
            "all_shim_floor_eligible"
        ] = False
        receipt["candidate_proof"]["standalone_decode_trials"][-1][
            "shim_floor_eligible"
        ] = False
        failed = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertFalse(failed["gate_results"]["clean_child_shim_floor_eligibility"])
        self.assertFalse(failed["category_gate_passed"])


if __name__ == "__main__":
    unittest.main()
