from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "config" / "clue-jls2-public-validation-gates.json"
CORPUS = ROOT / "config" / "clue-json-log-corpus-v1.json"
FETCHER = ROOT / "scripts" / "fetch-clue-json-corpus.py"
VERIFIER = ROOT / "scripts" / "verify-clue-jls2-public-validation-lock.py"
BENCHMARK = ROOT / "scripts" / "benchmark-clue-jls2-public-validation.py"
EVALUATOR = ROOT / "scripts" / "evaluate-clue-jls2-public-validation.py"
PBC_GATES = ROOT / "config" / "clue-pbc-public-validation-gates.json"
READINESS = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-17-clue-jls2-public-validation-readiness.md"
)


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


class ClueJLS2ValidationReadinessTests(unittest.TestCase):
    def test_candidate_and_development_evidence_are_frozen(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        candidate = gates["candidate"]
        self.assertEqual(gates["public_brand"], "Atompress")
        self.assertEqual(gates["technical_codec"], "JLS2")
        for relative, expected in candidate["frozen_paths"].items():
            self.assertEqual(
                digest_at_commit(candidate["frozen_implementation_commit"], relative),
                expected,
            )
        evidence = gates["development_evidence"]
        for prefix in ("ratio_census", "standalone_local", "standalone_hosted"):
            self.assertEqual(
                digest(ROOT / evidence[f"{prefix}_path"]),
                evidence[f"{prefix}_sha256"],
            )

    def test_validation_ranges_are_sealed_and_gate_is_decisive(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(gates["validation"]["corpus_config_sha256"], digest(CORPUS))
        expected = gates["validation"]["expected_items"]
        sealed = corpus["selection"]["public_validation"]
        self.assertEqual([row["id"] for row in expected], [row["id"] for row in sealed])
        self.assertTrue(all(row["size_bytes"] is None for row in sealed))
        self.assertTrue(all(row["sha256"] is None for row in sealed))
        requirements = gates["requirements"]
        self.assertEqual(
            requirements[
                "minimum_aggregate_gain_vs_strongest_complete_exact_byte_baseline_percent"
            ],
            5.0,
        )
        self.assertEqual(
            requirements[
                "minimum_family_gain_vs_strongest_complete_exact_byte_baseline_percent"
            ],
            5.0,
        )
        self.assertEqual(requirements["minimum_families_passing_ratio_gate"], 2)
        self.assertEqual(requirements["minimum_aggregate_compression_mbps"], 100.0)
        self.assertEqual(
            requirements["minimum_aggregate_standalone_decompression_mbps"],
            250.0,
        )
        self.assertFalse(gates["authorization"]["validation_currently_authorized"])
        self.assertEqual(gates["authorization"]["maximum_acquisitions"], 1)
        self.assertEqual(gates["authorization"]["maximum_scored_attempts"], 1)
        self.assertEqual(gates["private_holdout"]["status"], "sealed")

    def test_complete_roster_and_unavailable_markers_are_required(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        self.assertEqual(len(gates["baselines"]["standard_codec_ids"]), 10)
        self.assertEqual(gates["baselines"]["specialist"]["name"], "PBC-only")
        self.assertEqual(
            gates["baselines"]["specialist"]["gates_sha256"], digest(PBC_GATES)
        )
        sources = gates["baselines"]["required_external_sources"]
        self.assertEqual(
            sources["zstd"]["commit"],
            "f8745da6ff1ad1e7bab384bd1f9d742439278e99",
        )
        self.assertEqual(
            sources["7zip"]["asset_sha256"],
            "41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e",
        )
        self.assertEqual(
            set(gates["baselines"]["unavailable_context"]),
            {"LogFold", "LogPrism", "LogLite", "DeLog"},
        )
        self.assertTrue(gates["baselines"]["unavailable_is_not_a_win"])
        self.assertEqual(
            gates["baselines"]["eligibility_audit_sha256"],
            digest(ROOT / gates["baselines"]["eligibility_audit_path"]),
        )
        text = READINESS.read_text(encoding="utf-8")
        self.assertIn("validation remains unopened and unauthorized", text.lower())
        self.assertIn("absence is not a JLS2 win", text)
        self.assertIn("each of the two families", text)

    def test_explicit_validation_still_refuses_without_final_lock(self) -> None:
        fetcher = load_module("fetch_clue_without_final_lock", FETCHER)
        verifier = load_module("verify_clue_missing_lock", VERIFIER)
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

    def test_pbc_contract_and_projection_use_the_identical_bytes(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        pbc_gates = json.loads(PBC_GATES.read_text(encoding="utf-8"))
        self.assertEqual(pbc_gates["settings"]["methods"], ["pbc_only"])
        self.assertEqual(
            pbc_gates["requirements"]["expected_families"],
            ["clue_validation_a", "clue_validation_b"],
        )
        benchmark = load_module("benchmark_clue_projection", BENCHMARK)
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
            ["clue_validation_a", "clue_validation_b"],
        )
        self.assertEqual([row["encoded_bytes"] for row in accepted["rows"]], [100, 101])

    def test_evaluator_enforces_ratio_speed_memory_integrity_and_roster(self) -> None:
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        evaluator = load_module("evaluate_clue_first_score", EVALUATOR)
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
                    "compression_peak_rss_bytes": 128 * 1024 * 1024,
                    "decompression_peak_rss_bytes": 96 * 1024 * 1024,
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
        decode_trials = [
            {
                "family": item["family"],
                "round": repetition + 1,
                "warmup": False,
                "mbps": 300.0,
                "exact": True,
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
                "standalone_decode_trials": decode_trials,
                "standalone_decode_summary": {
                    "median_aggregate_mbps": 300.0,
                    "minimum_aggregate_mbps": 300.0,
                    "peak_rss_bytes": 96 * 1024 * 1024,
                    "all_exact": True,
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
        pbc_rows = []
        for item in expected:
            pbc_rows.append(
                {
                    "family": item["family"],
                    "method": "pbc_only",
                    "original_bytes": 1000,
                    "source_sha256": hashlib.sha256(item["id"].encode()).hexdigest(),
                    "archive_bytes": 75,
                }
            )
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
        result = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertTrue(result["category_gate_passed"])
        self.assertTrue(all(result["gate_results"].values()))
        self.assertEqual(len(result["comparison_rows"]), 16)
        self.assertEqual(
            sum(row["compressed_bytes"] is None for row in result["comparison_rows"]),
            4,
        )
        self.assertTrue(result["unavailable_is_not_a_win"])

        performance["summary"][0]["compressed_bytes"] = 119
        for row in performance["medians"]:
            if row["codec_id"] == candidate_id:
                row["compressed_bytes"] = 59
        failed = evaluator.evaluate(receipt, performance, pbc, gates)
        self.assertFalse(failed["category_gate_passed"])
        self.assertFalse(failed["gate_results"]["aggregate_ratio"])
        self.assertFalse(failed["gate_results"]["all_family_ratio"])


if __name__ == "__main__":
    unittest.main()
