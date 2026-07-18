import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py"
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
SPEC = importlib.util.spec_from_file_location("research_ceiling_execution_plan", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load research-ceiling execution planner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourceResearchCeilingExecutionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.plan = MODULE.build_plan(
            self.config,
            baseline_fixture(),
            config_sha256="a" * 64,
            baseline_sha256="b" * 64,
            repository_commit="c" * 40,
        )

    def test_plan_keeps_every_formal_and_resource_screen_task_visible(self) -> None:
        self.assertEqual(self.plan["formal_candidate_roster"], MODULE.FORMAL_CANDIDATES)
        self.assertEqual(
            self.plan["execution_profile_roster"], MODULE.EXECUTION_PROFILES
        )
        self.assertEqual(len(self.plan["tasks"]), 35)
        self.assertEqual(len({row["task_id"] for row in self.plan["tasks"]}), 35)
        self.assertEqual(
            self.plan["measurement_policy"][
                "maximum_wall_hours_per_family_per_codec"
            ],
            12.0,
        )
        self.assertTrue(
            all(row["execution_status"].startswith("pending") for row in self.plan["tasks"])
        )
        self.assertEqual({row["axiom_outcome"] for row in self.plan["tasks"]}, {"untested"})

    def test_local_paq_screen_never_substitutes_for_absolute_ceiling(self) -> None:
        local = [
            row
            for row in self.plan["tasks"]
            if row["profile_id"] == "paq8px-11L-local-screen"
        ]
        absolute = [
            row
            for row in self.plan["tasks"]
            if row["profile_id"] == "paq8px-12L-absolute"
        ]
        self.assertEqual(len(local), 7)
        self.assertEqual(len(absolute), 7)
        self.assertFalse(any(row["formal_ceiling_eligible"] for row in local))
        self.assertTrue(all(row["formal_ceiling_eligible"] for row in absolute))
        self.assertTrue(all("-11L" in row["compression_command"] for row in local))
        self.assertTrue(all("-12L" in row["compression_command"] for row in absolute))
        self.assertIn("never substitute", self.plan["formal_completion_rule"])

    def test_track_specific_nncp_and_complete_cmix_accounting_are_frozen(self) -> None:
        nncp = [
            row
            for row in self.plan["tasks"]
            if row["profile_id"] == "nncp-3.3-transformer"
        ]
        for row in nncp:
            self.assertTrue(row["second_host_decode_required"])
            if row["track"] == "english_wikimedia_wikitext":
                self.assertIn("--preprocess", row["compression_command"])
                self.assertIn("16384,512", row["compression_command"])
            else:
                self.assertNotIn("--preprocess", row["compression_command"])
        cmix = [
            row
            for row in self.plan["tasks"]
            if row["profile_id"] == "cmix-v21-strong-text"
        ]
        self.assertTrue(all(row["counted_side_asset_bytes"] == 411_996 for row in cmix))
        self.assertFalse(any(row["second_host_decode_required"] for row in cmix))
        self.assertTrue(
            all("$TOOLCHAIN/dictionary/english.dic" in row["compression_command"] for row in cmix)
        )

    def test_zpaq_staging_and_plan_immutability_are_explicit(self) -> None:
        zpaq = [
            row for row in self.plan["tasks"] if row["profile_id"] == "zpaq-5-m510"
        ]
        self.assertEqual(len(zpaq), 7)
        self.assertTrue(all("510" in row["compression_command"] for row in zpaq))
        self.assertTrue(all("-noattributes" in row["compression_command"] for row in zpaq))
        self.assertTrue(all(row["staged_input_name"] == "input.bin" for row in zpaq))
        self.assertTrue(
            all(row["staged_input_mtime_utc"] == "2000-01-01T00:00:00Z" for row in zpaq)
        )
        with tempfile.TemporaryDirectory() as raw:
            destination = Path(raw) / "plan.json"
            MODULE.write_immutable(destination, self.plan)
            MODULE.write_immutable(destination, self.plan)
            changed = dict(self.plan)
            changed["claim_ceiling"] = "changed"
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                MODULE.write_immutable(destination, changed)


if __name__ == "__main__":
    unittest.main()
