import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-20-source-python-grammar-binding-gdb1-protocol.md"
)
SCRIPT = REPOSITORY / "scripts" / "verify-source-python-grammar-binding-gdb1-result.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load_module("source_python_gdb1_verifier", SCRIPT)


class SourcePythonGrammarBindingGdb1ProtocolTests(unittest.TestCase):
    def config(self) -> dict:
        return json.loads(CONFIG.read_bytes())

    def system(
        self, system_id: str, complete_bytes: int, per_file_bytes: int = 100
    ) -> dict:
        empty_sha = hashlib.sha256(b"").hexdigest()
        components = [
            {
                "bytes": complete_bytes if name == "solid_payload" else 0,
                "name": name,
                "sha256": empty_sha,
            }
            for name in MODULE.COMPONENTS
        ]
        artifact_sha = hashlib.sha256(system_id.encode()).hexdigest()
        restored_sha = hashlib.sha256(b"restored manifest").hexdigest()
        return {
            "complete_bundle_bytes": complete_bytes,
            "components": components,
            "corruption_preflight_passed": True,
            "id": system_id,
            "per_file_diagnostics": [
                {
                    "exact_roundtrip": True,
                    "fallback": False,
                    "file_id": hashlib.sha256(name.encode()).hexdigest(),
                    "frame_bytes": per_file_bytes,
                }
                for name in ("a.py", "b.py")
            ],
            "repetitions": [
                {
                    "artifact_sha256": artifact_sha,
                    "compression_seconds": 1.0,
                    "decompression_seconds": 0.5,
                    "exact_roundtrip": True,
                    "peak_rss_bytes": 1024,
                    "repetition": repetition,
                    "restored_manifest_sha256": restored_sha,
                }
                for repetition in range(2)
            ],
        }

    def result(self, stage: str, config_sha256: str) -> dict:
        sizes = {
            "kanzi-max": 1000,
            "xz-lzma2-9e": 1100,
            "zstd-22-trained-dictionary": 1050,
            "cmix-v21-text": 900,
            "a0-token-trivia-range": 940,
            "a1-flat-identifiers": 850 if stage == "training_screen" else 820,
            "a2-scope-bindings": 840 if stage == "training_screen" else 800,
        }
        return {
            "access": {
                "development_holdout": (
                    "sealed and unaccessed"
                    if stage == "training_screen"
                    else "accessed exactly once"
                ),
                "private_holdout": "sealed and unaccessed",
                "public_validation": "sealed and unaccessed",
                "rust_llvm_typescript": "sealed and unaccessed",
            },
            "bindings": {
                "config_sha256": config_sha256,
                "dependency_lock_sha256": "a" * 64,
                "derived_corpus_manifest_sha256": "b" * 64,
                "repository_commit": "c" * 40,
            },
            "claim_ceiling": self.config()["claim_ceiling"],
            "decision": (
                "admit_one_shot_development_holdout"
                if stage == "training_screen"
                else "admit_separately_frozen_validation"
            ),
            "name": "source-python-grammar-binding-gdb1-result-v1",
            "stage": stage,
            "systems": [
                self.system(system_id, size) for system_id, size in sizes.items()
            ],
        }

    def test_config_is_canonical_and_freezes_attributable_python_only_design(
        self,
    ) -> None:
        raw = CONFIG.read_bytes()
        config = json.loads(raw)
        self.assertEqual(raw, MODULE.json_bytes(config))
        MODULE.validate_config(config)
        self.assertEqual(config["dependencies"]["cst"]["package"], "LibCST")
        self.assertEqual(config["dependencies"]["cst"]["version"], "1.8.6")
        self.assertEqual(config["corpus"]["allowed_project"], "cpython-3.14.6-source")
        self.assertIn("rust-1.97.1-source", config["corpus"]["reserved_not_accessed"])
        self.assertIn("llvm-22.1.8-source", config["corpus"]["reserved_not_accessed"])
        self.assertEqual(
            config["accounting"]["gate_denominator"], "complete_bundle_bytes"
        )
        self.assertIn(
            "only its occurrence stream replaced", config["arms"][2]["occurrence_model"]
        )

    def test_protocol_freezes_strong_baselines_gates_and_claim_ceiling(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        for phrase in (
            "A2 minus A1 isolates scope/binding identity",
            "at least 8.00% smaller",
            "one-shot development holdout",
            "complete_bundle_bytes",
            "cmix v21",
            "TypeScript, Rust, LLVM",
            "cannot establish an Axiom win",
        ):
            self.assertIn(phrase, protocol)

    def test_training_result_reconstructs_integer_gates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            path = root / "g0.json"
            path.write_bytes(MODULE.json_bytes(result))
            verified = MODULE.verify(path)
            self.assertTrue(verified["passed"])
            self.assertEqual(verified["strongest_complete_baseline"], "cmix-v21-text")
            self.assertTrue(verified["gate_checks"]["a0_competent"])
            self.assertTrue(verified["gate_checks"]["scope_attribution"])

    def test_holdout_requires_bound_passing_g0_and_reconstructs_g1(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config_sha = MODULE.sha256_bytes(CONFIG.read_bytes())
            g0 = self.result("training_screen", config_sha)
            g0_path = root / "g0.json"
            g0_path.write_bytes(MODULE.json_bytes(g0))
            g1 = self.result("development_holdout", config_sha)
            g1["bindings"]["g0_result_sha256"] = MODULE.sha256_bytes(
                g0_path.read_bytes()
            )
            g1_path = root / "g1.json"
            g1_path.write_bytes(MODULE.json_bytes(g1))
            with self.assertRaisesRegex(ValueError, "requires the immutable G0"):
                MODULE.verify(g1_path)
            verified = MODULE.verify(g1_path, g0_result_path=g0_path)
            self.assertTrue(verified["passed"])
            self.assertTrue(verified["gate_checks"]["strong_headroom"])
            self.assertTrue(verified["gate_checks"]["per_file_guard"])

    def test_component_tamper_and_false_decision_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            result["systems"][0]["components"][1]["bytes"] += 1
            path = root / "tampered.json"
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "declared decision differs"):
                MODULE.verify(path)

            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            a2 = next(
                row for row in result["systems"] if row["id"] == "a2-scope-bindings"
            )
            a2["complete_bundle_bytes"] = 849
            a2["components"][1]["bytes"] = 849
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "declared decision differs"):
                MODULE.verify(path)


if __name__ == "__main__":
    unittest.main()
