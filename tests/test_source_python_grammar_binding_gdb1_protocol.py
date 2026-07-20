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
            "implementation_identity_sha256": (
                self.config()["bindings"]["kanzi_binary_sha256"]
                if system_id == "kanzi-max"
                else hashlib.sha256(
                    ("implementation/" + system_id).encode()
                ).hexdigest()
            ),
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
                "prior_baseline_public_evidence_sha256": self.config()["bindings"][
                    "existing_baseline_public_evidence_sha256"
                ],
                "repository_commit": "c" * 40,
                "source_corpus_manifest_sha256": self.config()["bindings"][
                    "existing_corpus_manifest_sha256"
                ],
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
        changed = json.loads(MODULE.json_bytes(config))
        changed["arms"][0]["occurrence_model"] = "flat"
        with self.assertRaisesRegex(ValueError, "A2-minus-A1 attribution differs"):
            MODULE.validate_config(changed)

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

    def test_required_baseline_cannot_disappear_or_become_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            cmix = next(
                row for row in result["systems"] if row["id"] == "cmix-v21-text"
            )
            cmix["repetitions"][0]["compression_seconds"] = 21_601
            result["decision"] = "reject_gdb1_without_opening_development_holdout"
            path = root / "ineligible.json"
            path.write_bytes(MODULE.json_bytes(result))
            verified = MODULE.verify(path)
            self.assertFalse(verified["passed"])
            self.assertFalse(verified["gate_checks"]["common"])
            self.assertIsNone(verified["strongest_complete_baseline"])

            result["systems"] = [
                row for row in result["systems"] if row["id"] != "cmix-v21-text"
            ]
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "system roster differs"):
                MODULE.verify(path)

    def test_determinism_memory_and_time_fail_closed_as_honest_negative(self) -> None:
        mutations = {
            "nondeterministic": lambda row: row["repetitions"][1].__setitem__(
                "artifact_sha256", "d" * 64
            ),
            "over_memory": lambda row: row["repetitions"][0].__setitem__(
                "peak_rss_bytes", 8 * 1024**3 + 1
            ),
            "over_time": lambda row: row["repetitions"][0].__setitem__(
                "decompression_seconds", 21_601
            ),
        }
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "negative.json"
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    result = self.result(
                        "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
                    )
                    mutate(result["systems"][0])
                    result["decision"] = (
                        "reject_gdb1_without_opening_development_holdout"
                    )
                    path.write_bytes(MODULE.json_bytes(result))
                    verified = MODULE.verify(path)
                    self.assertFalse(verified["passed"])
                    self.assertFalse(verified["gate_checks"]["common"])

    def test_holdout_rejects_per_file_regression(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config_sha = MODULE.sha256_bytes(CONFIG.read_bytes())
            g0_path = root / "g0.json"
            g0_path.write_bytes(
                MODULE.json_bytes(self.result("training_screen", config_sha))
            )
            g1 = self.result("development_holdout", config_sha)
            g1["bindings"]["g0_result_sha256"] = MODULE.sha256_bytes(
                g0_path.read_bytes()
            )
            a2 = next(row for row in g1["systems"] if row["id"] == "a2-scope-bindings")
            a2["per_file_diagnostics"][0]["frame_bytes"] = 101
            g1["decision"] = "reject_gdb1_and_do_not_tune_on_consumed_holdout"
            g1_path = root / "g1.json"
            g1_path.write_bytes(MODULE.json_bytes(g1))
            verified = MODULE.verify(g1_path, g0_result_path=g0_path)
            self.assertFalse(verified["passed"])
            self.assertFalse(verified["gate_checks"]["per_file_guard"])

    def test_holdout_rejects_failed_g0_and_stage_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config_sha = MODULE.sha256_bytes(CONFIG.read_bytes())
            failed_g0 = self.result("training_screen", config_sha)
            a2 = next(
                row for row in failed_g0["systems"] if row["id"] == "a2-scope-bindings"
            )
            a2["complete_bundle_bytes"] = 849
            a2["components"][1]["bytes"] = 849
            failed_g0["decision"] = "reject_gdb1_without_opening_development_holdout"
            g0_path = root / "failed-g0.json"
            g0_path.write_bytes(MODULE.json_bytes(failed_g0))
            g1 = self.result("development_holdout", config_sha)
            g1["bindings"]["g0_result_sha256"] = MODULE.sha256_bytes(
                g0_path.read_bytes()
            )
            g1_path = root / "g1.json"
            g1_path.write_bytes(MODULE.json_bytes(g1))
            with self.assertRaisesRegex(ValueError, "opened without a G0 pass"):
                MODULE.verify(g1_path, g0_result_path=g0_path)

            passing_g0 = self.result("training_screen", config_sha)
            g0_path.write_bytes(MODULE.json_bytes(passing_g0))
            g1["bindings"]["g0_result_sha256"] = MODULE.sha256_bytes(
                g0_path.read_bytes()
            )
            for field in (
                "dependency_lock_sha256",
                "derived_corpus_manifest_sha256",
            ):
                with self.subTest(field=field):
                    changed = json.loads(MODULE.json_bytes(g1))
                    changed["bindings"][field] = "e" * 64
                    g1_path.write_bytes(MODULE.json_bytes(changed))
                    with self.assertRaisesRegex(
                        ValueError, "dependency lock or derived corpus changed"
                    ):
                        MODULE.verify(g1_path, g0_result_path=g0_path)

    def test_pinned_source_baseline_and_kanzi_identities_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "identity.json"
            config_sha = MODULE.sha256_bytes(CONFIG.read_bytes())
            result = self.result("training_screen", config_sha)
            result["bindings"]["source_corpus_manifest_sha256"] = "e" * 64
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "evidence binding differs"):
                MODULE.verify(path)

            result = self.result("training_screen", config_sha)
            result["bindings"]["prior_baseline_public_evidence_sha256"] = "e" * 64
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "evidence binding differs"):
                MODULE.verify(path)

            result = self.result("training_screen", config_sha)
            kanzi = next(row for row in result["systems"] if row["id"] == "kanzi-max")
            kanzi["implementation_identity_sha256"] = "e" * 64
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "Kanzi binary identity differs"):
                MODULE.verify(path)

    def test_noncanonical_symlink_access_and_roster_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "result.json"
            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            path.write_bytes(MODULE.json_bytes(result) + b"\n")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(path)
            canonical = root / "canonical.json"
            canonical.write_bytes(MODULE.json_bytes(result))
            symlink = root / "symlink.json"
            symlink.symlink_to(canonical)
            with self.assertRaisesRegex(ValueError, "ordinary file"):
                MODULE.verify(symlink)

            result["access"]["development_holdout"] = "accessed exactly once"
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "sealed-data declaration differs"):
                MODULE.verify(path)
            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            result["stage"] = "validation"
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "stage differs"):
                MODULE.verify(path)
            result = self.result(
                "training_screen", MODULE.sha256_bytes(CONFIG.read_bytes())
            )
            result["systems"].append(result["systems"][0])
            path.write_bytes(MODULE.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "system roster differs"):
                MODULE.verify(path)


if __name__ == "__main__":
    unittest.main()
