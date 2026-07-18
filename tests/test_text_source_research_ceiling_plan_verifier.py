import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_baseline_publication import (
    MODULE as BASELINE_PUBLICATION,
    fixture as baseline_fixture,
    write_trial_receipts,
)


REPOSITORY = Path(__file__).resolve().parents[1]
PLANNER_PATH = (
    REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py"
)
VERIFIER_PATH = REPOSITORY / "scripts" / "verify-text-source-research-ceiling-plan.py"
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load("research_ceiling_planner_test_dependency", PLANNER_PATH)
VERIFIER = load("research_ceiling_plan_verifier", VERIFIER_PATH)


class TextSourceResearchCeilingPlanVerifierTests(unittest.TestCase):
    def test_checked_in_plan_recomputes_and_rejects_post_result_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            baseline = baseline_fixture()
            baseline_path = root / "private-baseline" / "results.json"
            baseline_path.parent.mkdir()
            baseline_path.write_bytes(BASELINE_PUBLICATION.json_bytes(baseline))
            write_trial_receipts(baseline_path.parent, baseline)
            publication = root / "baseline-publication"
            BASELINE_PUBLICATION.publish(baseline_path, publication)

            config_raw = CONFIG.read_bytes()
            plan = PLANNER.build_plan(
                json.loads(config_raw),
                baseline,
                config_sha256=PLANNER.sha256_bytes(config_raw),
                baseline_sha256=PLANNER.sha256_file(baseline_path),
                repository_commit="c" * 40,
            )
            plan_path = root / "plan.json"
            PLANNER.write_immutable(plan_path, plan)
            result = VERIFIER.verify(plan_path, CONFIG, publication)
            self.assertTrue(result["verified"])
            self.assertEqual(result["formal_task_count"], 28)
            self.assertEqual(result["context_task_count"], 7)

            plan["tasks"][0]["execution_status"] = "completed_after_peeking"
            plan_path.write_bytes(PLANNER.json_bytes(plan))
            with self.assertRaisesRegex(ValueError, "differs from recomputed protocol"):
                VERIFIER.verify(plan_path, CONFIG, publication)


if __name__ == "__main__":
    unittest.main()
