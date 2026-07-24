"""Frozen contender-reducer semantics for the CLUE-LDS JLS2 championship screen.

The reducer is the crux of the screen. These tests pin the integer boundary
(equality passes the <=), the tool-failure classification, the required-research
opponent rule, and the contextual/unavailable non-counting rule.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REDUCER = ROOT / "scripts" / "reduce-clue-jls2-championship-screen-v1.py"


def load_reducer():
    spec = importlib.util.spec_from_file_location("championship_reducer", REDUCER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load_reducer()

FAMILIES = ["clue_championship_e", "clue_championship_f"]


def valid_execution() -> dict[str, bool]:
    return {
        "finished_within_wall": True,
        "exact_roundtrip": True,
        "order_preserved": True,
        "timezone_preserved": True,
        "deterministic_output": True,
    }


def full_gates() -> dict[str, bool]:
    return {
        "deterministic_output": True,
        "complete_frame_accounting": True,
        "bounded_direct_fallback": True,
        "corruption_rejection": True,
        "exact_standalone_decode": True,
        "clean_child_shim_floor_eligibility": True,
        "compression_memory": True,
        "decompression_memory": True,
        "aggregate_compression_speed": True,
        "aggregate_standalone_decompression_speed": True,
        "minimum_compression_repetition_speed": True,
        "minimum_standalone_decompression_repetition_speed": True,
    }


def opponent(codec_id, eligibility_class, per_family, execution=None):
    return {
        "codec_id": codec_id,
        "eligibility_class": eligibility_class,
        "aggregate_complete_bytes": sum(per_family.values()) if per_family else None,
        "family_complete_bytes": per_family,
        "execution": valid_execution() if execution is None else execution,
    }


def bundle(candidate_family, opponents, gates=None):
    return {
        "families": FAMILIES,
        "candidate": {
            "codec_id": "jls2",
            "aggregate_complete_bytes": sum(candidate_family.values()),
            "family_complete_bytes": candidate_family,
            "gates": full_gates() if gates is None else gates,
        },
        "opponents": opponents,
    }


class ContenderMarginTests(unittest.TestCase):
    def test_exact_five_percent_equality_passes(self):
        # candidate * 100 == 95 * strongest -> equality satisfies the <-, contender.
        self.assertTrue(R.meets_contender_margin(1_900_000, 2_000_000))
        self.assertEqual(1_900_000 * 100, 95 * 2_000_000)

    def test_one_byte_above_the_line_is_not_a_contender(self):
        self.assertFalse(R.meets_contender_margin(1_900_001, 2_000_000))

    def test_one_byte_below_the_line_is_a_contender(self):
        self.assertTrue(R.meets_contender_margin(1_899_999, 2_000_000))

    def test_much_smaller_is_a_contender(self):
        self.assertTrue(R.meets_contender_margin(1_000_000, 2_000_000))

    def test_equal_bytes_is_not_a_contender(self):
        self.assertFalse(R.meets_contender_margin(2_000_000, 2_000_000))

    def test_non_positive_reference_raises(self):
        with self.assertRaises(ValueError):
            R.meets_contender_margin(100, 0)


class ClassificationTests(unittest.TestCase):
    def test_all_flags_true_is_valid(self):
        self.assertEqual(R.classify_execution(valid_execution()), "valid")

    def test_missing_flag_is_tool_failure(self):
        for flag in R.EXECUTION_VALIDITY_FLAGS:
            execution = valid_execution()
            execution[flag] = False
            self.assertEqual(
                R.classify_execution(execution), "invalid-tool-failure", flag
            )

    def test_missing_execution_is_tool_failure(self):
        self.assertEqual(R.classify_execution(None), "invalid-tool-failure")
        self.assertEqual(R.classify_execution({}), "invalid-tool-failure")


class ReduceChampionshipTests(unittest.TestCase):
    def _standard_opponents(self, per_family_bytes):
        # A full eligible roster all at the same (larger) size.
        rows = []
        for codec_id in R.ELIGIBLE_OPPONENT_CODEC_IDS:
            rows.append(opponent(codec_id, "eligible", dict(per_family_bytes)))
        return rows

    def test_clean_contender_at_the_equality_boundary(self):
        strongest = {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        candidate = {"clue_championship_e": 950_000, "clue_championship_f": 950_000}
        decision = R.reduce_championship(bundle(candidate, self._standard_opponents(strongest)))
        self.assertTrue(decision["contender"])
        self.assertEqual(decision["result"], "contender")
        self.assertTrue(decision["aggregate_margin_ok"])
        self.assertTrue(all(row["margin_ok"] for row in decision["family_decisions"]))
        self.assertTrue(decision["required_research_opponents_valid"])

    def test_one_byte_over_the_line_is_not_a_contender(self):
        strongest = {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        candidate = {"clue_championship_e": 950_001, "clue_championship_f": 950_000}
        decision = R.reduce_championship(bundle(candidate, self._standard_opponents(strongest)))
        self.assertFalse(decision["contender"])

    def test_kanzi_tool_failure_blocks_a_contender_and_is_recorded(self):
        strongest = {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        candidate = {"clue_championship_e": 500_000, "clue_championship_f": 500_000}
        opponents = self._standard_opponents(strongest)
        # Break Kanzi: crash flag off. It must not be a win or loss.
        for row in opponents:
            if row["codec_id"] == "kanzi-max":
                row["execution"]["exact_roundtrip"] = False
                row["aggregate_complete_bytes"] = None
                row["family_complete_bytes"] = {}
        decision = R.reduce_championship(bundle(candidate, opponents))
        self.assertFalse(decision["contender"])
        self.assertFalse(decision["required_research_opponents_valid"])
        self.assertFalse(decision["required_research_opponent_status"]["kanzi-max"])
        by_codec = {
            row["codec_id"]: row["classification"]
            for row in decision["opponent_classifications"]
        }
        self.assertEqual(by_codec["kanzi-max"], "invalid-tool-failure")

    def test_contextual_tool_never_beats_or_is_beaten(self):
        # A contextual tool smaller than JLS2 must not flip the decision.
        strongest = {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        candidate = {"clue_championship_e": 500_000, "clue_championship_f": 500_000}
        opponents = self._standard_opponents(strongest)
        opponents.append(
            opponent(
                "zpaq-5-m510",
                "contextual",
                {"clue_championship_e": 100_000, "clue_championship_f": 100_000},
            )
        )
        decision = R.reduce_championship(bundle(candidate, opponents))
        self.assertTrue(decision["contender"])
        self.assertIn("zpaq-5-m510", decision["contextual_codecs"])
        self.assertNotEqual(decision["strongest_eligible_aggregate_codec"], "zpaq-5-m510")

    def test_failed_jls2_gate_blocks_a_contender(self):
        strongest = {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        candidate = {"clue_championship_e": 500_000, "clue_championship_f": 500_000}
        gates = full_gates()
        gates["decompression_memory"] = False
        decision = R.reduce_championship(
            bundle(candidate, self._standard_opponents(strongest), gates=gates)
        )
        self.assertFalse(decision["contender"])
        self.assertFalse(decision["candidate_gates_all_pass"])

    def test_family_regression_blocks_a_contender(self):
        # JLS2 clears aggregate but loses one family outright.
        opponents = self._standard_opponents(
            {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        )
        candidate = {"clue_championship_e": 400_000, "clue_championship_f": 1_050_000}
        decision = R.reduce_championship(bundle(candidate, opponents))
        self.assertFalse(decision["contender"])
        loser = next(
            row for row in decision["family_decisions"]
            if row["family"] == "clue_championship_f"
        )
        self.assertFalse(loser["candidate_smaller"])

    def test_invalid_eligible_tool_is_excluded_from_strongest(self):
        # xz tool-fails: strongest is the min of the remaining valid eligible.
        opponents = self._standard_opponents(
            {"clue_championship_e": 1_000_000, "clue_championship_f": 1_000_000}
        )
        for row in opponents:
            if row["codec_id"] == "xz-lzma2-9e":
                row["execution"]["finished_within_wall"] = False
                row["aggregate_complete_bytes"] = None
                row["family_complete_bytes"] = {}
        candidate = {"clue_championship_e": 500_000, "clue_championship_f": 500_000}
        decision = R.reduce_championship(bundle(candidate, opponents))
        # kanzi and zpaq still valid, so a contender is still possible.
        self.assertTrue(decision["contender"])
        by_codec = {
            row["codec_id"]: row["classification"]
            for row in decision["opponent_classifications"]
        }
        self.assertEqual(by_codec["xz-lzma2-9e"], "invalid-tool-failure")


if __name__ == "__main__":
    unittest.main()
