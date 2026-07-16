import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
EVALUATOR = (
    REPOSITORY / "scripts" / "evaluate-jls2-public-validation.py"
)


class JLS2PublicValidationTests(unittest.TestCase):
    def test_evaluator_enforces_frozen_cross_codec_gates(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            families = ["one", "two", "three"]
            jls2 = {
                "first_score": True,
                "completed": True,
                "repetitions": 5,
                "frozen_base_commit": "frozen",
                "segment_target_bytes": 16,
                "manifest_sha256": "manifest",
                "git": {"commit": "benchmark"},
                "rows": [
                    {
                        "family": family,
                        "original_bytes": 1000,
                        "source_sha256": family,
                        "encoded_bytes": 70,
                        "zstd9_bytes": 100,
                        "brotli11_bytes": 80,
                        "roundtrip_verified": True,
                        "deterministic_frame": True,
                        "no_expansion_vs_direct_frame": True,
                    }
                    for family in families
                ],
                "aggregate": {
                    "compression_mbps": 150.0,
                    "decompression_mbps": 300.0,
                },
            }
            pbc = {
                "passed": True,
                "repetitions": 5,
                "training_repetitions": 2,
                "manifest_sha256": "manifest",
                "benchmark_source": {"commit": "benchmark"},
                "rows": [
                    {
                        "family": family,
                        "method": "pbc_only",
                        "original_bytes": 1000,
                        "source_sha256": family,
                        "jls2_bytes": 70,
                        "zstd9_bytes": 100,
                        "archive_bytes": 200,
                        "roundtrip_verified": True,
                    }
                    for family in families
                ],
                "decision": {"primary_method": "pbc_only"},
            }
            gates = {
                "claim_ceiling": "test",
                "decision_rule": "all",
                "private_holdout": "sealed",
                "candidate": {
                    "frozen_base_commit": "frozen",
                    "segment_target_bytes": 16,
                },
                "validation": {
                    "expected_families": families,
                    "minimum_repetitions": 5,
                },
                "baselines": {
                    "pbc_method": "pbc_only",
                    "pbc_training_repetitions": 2,
                },
                "requirements": {
                    "require_exact_roundtrip": True,
                    "require_deterministic_jls2": True,
                    "require_no_expansion_vs_equally_framed_direct": True,
                    "minimum_gain_vs_zstd9_percent_per_family": 5.0,
                    "minimum_aggregate_gain_vs_zstd9_percent": 10.0,
                    "minimum_families_smaller_than_brotli11": 2,
                    "require_aggregate_smaller_than_brotli11": True,
                    "minimum_aggregate_compression_mbps": 100.0,
                    "minimum_aggregate_decompression_mbps": 250.0,
                    "require_jls2_smaller_than_fixed_pbc_per_family": True,
                    "require_jls2_smaller_than_fixed_pbc_aggregate": True,
                },
            }
            jls2_path = root / "jls2.json"
            pbc_path = root / "pbc.json"
            gates_path = root / "gates.json"
            output = root / "decision.json"
            jls2_path.write_text(json.dumps(jls2), encoding="utf-8")
            pbc["accepted_sha256"] = hashlib.sha256(
                jls2_path.read_bytes()
            ).hexdigest()
            pbc_path.write_text(json.dumps(pbc), encoding="utf-8")
            gates_path.write_text(json.dumps(gates), encoding="utf-8")

            command = [
                sys.executable,
                str(EVALUATOR),
                "--jls2",
                str(jls2_path),
                "--pbc",
                str(pbc_path),
                "--gates",
                str(gates_path),
                "--output",
                str(output),
            ]
            passed = subprocess.run(
                command,
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertTrue(
                json.loads(output.read_text(encoding="utf-8"))["passed"]
            )

            jls2["rows"][0]["encoded_bytes"] = 99
            jls2_path.write_text(json.dumps(jls2), encoding="utf-8")
            pbc["rows"][0]["jls2_bytes"] = 99
            pbc["accepted_sha256"] = hashlib.sha256(
                jls2_path.read_bytes()
            ).hexdigest()
            pbc_path.write_text(json.dumps(pbc), encoding="utf-8")
            failed = subprocess.run(
                command,
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 2, failed.stderr)
            decision = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(decision["passed"])
            self.assertFalse(decision["gate_results"]["zstd9_per_family"])


if __name__ == "__main__":
    unittest.main()
