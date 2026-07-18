from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
PLANNER_SCRIPT = (
    REPOSITORY / "scripts" / "prepare-incompressible-precompressed-execution.py"
)
VERIFIER_SCRIPT = (
    REPOSITORY / "scripts" / "verify-incompressible-precompressed-plan.py"
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load("incompressible_precompressed_planner", PLANNER_SCRIPT)
VERIFIER = load("incompressible_precompressed_plan_verifier", VERIFIER_SCRIPT)


class IncompressiblePrecompressedExecutionPlanTests(unittest.TestCase):
    @classmethod
    def build(cls) -> dict:
        config = PLANNER.read_canonical_json(PLANNER.DEFAULT_CONFIG)
        acquisition = PLANNER.read_canonical_json(PLANNER.DEFAULT_ACQUISITION)
        return PLANNER.build_plan(
            config,
            acquisition,
            config_sha256=PLANNER.sha256_file(PLANNER.DEFAULT_CONFIG),
            acquisition_sha256=PLANNER.sha256_file(PLANNER.DEFAULT_ACQUISITION),
            repository_commit="a" * 40,
        )

    def test_plan_contains_all_31_generated_and_18_licensed_tasks(self) -> None:
        plan = self.build()
        self.assertEqual(plan["task_count"], 49)
        self.assertEqual(len({row["task_id"] for row in plan["tasks"]}), 49)
        generated = [row for row in plan["tasks"] if row["kind"] == "generated"]
        precompressed = [
            row for row in plan["tasks"] if row["kind"] == "precompressed"
        ]
        self.assertEqual(len(generated), 31)
        self.assertEqual(len(precompressed), 18)
        self.assertEqual(plan["axiom_wins"], 0)
        self.assertEqual(plan["development_corpus_status"], "planned_not_constructed")
        self.assertEqual(plan["public_validation_status"], "unopened and unselected")
        self.assertEqual(plan["private_holdout_status"], "inaccessible and unselected")
        self.assertNotIn("licensed_source_manifest_sha256", plan["bindings"])
        self.assertEqual(
            plan["bindings"]["licensed_acquisition_sha256"],
            PLANNER.sha256_file(PLANNER.DEFAULT_ACQUISITION),
        )

    def test_every_generated_recipe_and_precompression_identity_is_explicit(self) -> None:
        plan = self.build()
        shake = [
            row for row in plan["tasks"] if row["family_id"] == "shake256-uniform"
        ]
        self.assertEqual(len(shake), 10)
        self.assertEqual(shake[0]["planned_bytes"], 0)
        self.assertEqual(shake[-1]["planned_bytes"], 64 * 1024**2)
        self.assertTrue(
            all(
                row["generation"]["algorithm"] == "counter-mode-shake256-v1"
                and row["generation"]["block_bytes"] == 1024**2
                for row in shake
            )
        )
        magic = [
            row
            for row in plan["tasks"]
            if row["family_id"] == "magic-spoofed-random"
        ]
        self.assertEqual(len(magic), 16)
        self.assertEqual(len({row["generation"]["magic_id"] for row in magic}), 8)
        profiles = {row["precompression_profile_id"] for row in plan["tasks"] if row["kind"] == "precompressed"}
        self.assertEqual(profiles, set(PLANNER.EXPECTED_PRECOMPRESSION))
        source_ids = {
            row["source"]["source_id"]
            for row in plan["tasks"]
            if row["kind"] == "precompressed"
        }
        self.assertEqual(
            source_ids,
            {
                "cpython-3.14.6-source",
                "rust-1.97.1-source",
                "enwikibooks-20260701",
            },
        )

    def test_immutable_plan_verifies_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "plan.json"
            plan = self.build()
            PLANNER.write_immutable(path, plan)
            PLANNER.write_immutable(path, plan)
            result = VERIFIER.verify(
                config_path=PLANNER.DEFAULT_CONFIG,
                acquisition_path=PLANNER.DEFAULT_ACQUISITION,
                plan_path=path,
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["generated_task_count"], 31)
            self.assertEqual(result["precompressed_task_count"], 18)
            plan["axiom_wins"] = 1
            path.write_bytes(PLANNER.json_bytes(plan))
            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                VERIFIER.verify(
                    config_path=PLANNER.DEFAULT_CONFIG,
                    acquisition_path=PLANNER.DEFAULT_ACQUISITION,
                    plan_path=path,
                )

    def test_tracked_acquisition_is_the_complete_source_identity_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan_path = root / "plan.json"
            plan = self.build()
            plan_path.write_bytes(PLANNER.json_bytes(plan))
            acquisition = PLANNER.read_canonical_json(PLANNER.DEFAULT_ACQUISITION)
            acquisition["items"][0]["bundle_sha256"] = "f" * 64
            acquisition_path = root / "acquisition.json"
            acquisition_path.write_bytes(PLANNER.json_bytes(acquisition))
            with self.assertRaisesRegex(ValueError, "binding is invalid"):
                VERIFIER.verify(
                    config_path=PLANNER.DEFAULT_CONFIG,
                    acquisition_path=acquisition_path,
                    plan_path=plan_path,
                )

            original_acquisition = json.loads(
                PLANNER.DEFAULT_ACQUISITION.read_bytes()
            )
            original_acquisition_path = root / "original-acquisition.json"
            original_acquisition_path.write_bytes(
                PLANNER.json_bytes(original_acquisition)
            )
            plan["bindings"]["licensed_acquisition_sha256"] = (
                PLANNER.sha256_file(original_acquisition_path)
            )
            derivative = next(
                row for row in plan["tasks"] if row["kind"] == "precompressed"
            )
            derivative["source"]["bundle_sha256"] = "e" * 64
            plan_path.write_bytes(PLANNER.json_bytes(plan))
            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                VERIFIER.verify(
                    config_path=PLANNER.DEFAULT_CONFIG,
                    acquisition_path=original_acquisition_path,
                    plan_path=plan_path,
                )

    def test_plan_reconstructs_from_tracked_inputs_without_a_corpus_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config_path = root / "gates.json"
            acquisition_path = root / "acquisition.json"
            config_path.write_bytes(PLANNER.DEFAULT_CONFIG.read_bytes())
            acquisition_path.write_bytes(PLANNER.DEFAULT_ACQUISITION.read_bytes())
            config = PLANNER.read_canonical_json(config_path)
            acquisition = PLANNER.read_canonical_json(acquisition_path)
            plan = PLANNER.build_plan(
                config,
                acquisition,
                config_sha256=PLANNER.sha256_file(config_path),
                acquisition_sha256=PLANNER.sha256_file(acquisition_path),
                repository_commit="b" * 40,
            )
            plan_path = root / "plan.json"
            plan_path.write_bytes(PLANNER.json_bytes(plan))
            self.assertFalse((root / "corpora").exists())
            verified = VERIFIER.verify(
                config_path=config_path,
                acquisition_path=acquisition_path,
                plan_path=plan_path,
            )
            self.assertTrue(verified["verified"])
            self.assertEqual(verified["task_count"], 49)


if __name__ == "__main__":
    unittest.main()
