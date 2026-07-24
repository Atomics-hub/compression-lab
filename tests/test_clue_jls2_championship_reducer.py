"""Frozen contender-reducer semantics for the CLUE-LDS JLS2 championship screen.

The reducer is the crux of the screen. These tests pin the aggregate integer
boundary (equality passes the <=), the per-family/per-item OUTRIGHT-WIN rule (no
per-family 5% margin; equality is not a win), the per-item tool-failure
classification (a fail on item A leaves item B standing), the required-research
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


def opponent(codec_id, eligibility_class, per_family, invalid_families=()):
    items = {}
    for family in FAMILIES:
        bytes_ = per_family.get(family)
        if family in invalid_families:
            execution = valid_execution()
            execution["exact_roundtrip"] = False
        else:
            execution = valid_execution()
        items[family] = {"complete_bytes": bytes_, "execution": execution}
    return {
        "codec_id": codec_id,
        "eligibility_class": eligibility_class,
        "items": items,
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


ELIGIBLE = ["kanzi-max", "zpaq-5-m54", "brotli-11", "zstd-22", "xz-lzma2-9e", "7zip-9", "pbc-only"]


def uniform_roster(family_bytes):
    return [opponent(c, "eligible", dict(family_bytes)) for c in ELIGIBLE]


def cross_win_roster(e_min, f_min, big):
    # kanzi wins family e (e_min); zpaq wins family f (f_min); the rest sit at big.
    # strongest_e = e_min, strongest_f = f_min, strongest aggregate = min(e_min+big, big+f_min).
    rows = [
        opponent("kanzi-max", "eligible", {FAMILIES[0]: e_min, FAMILIES[1]: big}),
        opponent("zpaq-5-m54", "eligible", {FAMILIES[0]: big, FAMILIES[1]: f_min}),
    ]
    for c in ["brotli-11", "zstd-22", "xz-lzma2-9e", "7zip-9", "pbc-only"]:
        rows.append(opponent(c, "eligible", {FAMILIES[0]: big, FAMILIES[1]: big}))
    return rows


class ContenderMarginTests(unittest.TestCase):
    def test_exact_five_percent_equality_passes(self):
        self.assertTrue(R.meets_contender_margin(1_900_000, 2_000_000))
        self.assertEqual(1_900_000 * 100, 95 * 2_000_000)

    def test_one_byte_above_the_line_is_not_a_contender(self):
        self.assertFalse(R.meets_contender_margin(1_900_001, 2_000_000))

    def test_one_byte_below_the_line_is_a_contender(self):
        self.assertTrue(R.meets_contender_margin(1_899_999, 2_000_000))

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
            self.assertEqual(R.classify_execution(execution), "invalid-tool-failure", flag)

    def test_missing_execution_is_tool_failure(self):
        self.assertEqual(R.classify_execution(None), "invalid-tool-failure")
        self.assertEqual(R.classify_execution({}), "invalid-tool-failure")


class ReduceChampionshipTests(unittest.TestCase):
    def test_aggregate_at_equality_boundary_with_family_wins_is_contender(self):
        # Uniform opponents at (1000,1000): strongest aggregate 2000. JLS2 wins
        # family e big and clears aggregate at the exact 5% equality boundary.
        candidate = {FAMILIES[0]: 900, FAMILIES[1]: 1000}
        # 1900*100 == 95*2000 -> aggregate equality passes; but family f ties -> not.
        decision = R.reduce_championship(bundle(candidate, uniform_roster({FAMILIES[0]: 1000, FAMILIES[1]: 1000})))
        self.assertTrue(decision["aggregate_margin_ok"])
        self.assertFalse(decision["contender"])  # family f tie is not a win

    def test_aggregate_six_percent_plus_family_win_by_three_percent_is_contender(self):
        # Cross-win roster: strongest_e=strongest_f=1000, strongest aggregate=2064.
        # JLS2 (970,970): aggregate 1940 -> 6.0% smaller (>=5%); each family win 3%.
        candidate = {FAMILIES[0]: 970, FAMILIES[1]: 970}
        decision = R.reduce_championship(bundle(candidate, cross_win_roster(1000, 1000, 1064)))
        self.assertEqual(decision["strongest_eligible_aggregate_bytes"], 2064)
        self.assertTrue(decision["aggregate_margin_ok"])
        self.assertTrue(decision["all_families_won"])
        self.assertTrue(decision["contender"])
        self.assertEqual(decision["result"], "contender")

    def test_aggregate_passes_but_one_family_equality_is_not_a_contender(self):
        # JLS2 (940,1000): aggregate 1940 clears 5% vs 2064, but family f ties.
        candidate = {FAMILIES[0]: 940, FAMILIES[1]: 1000}
        decision = R.reduce_championship(bundle(candidate, cross_win_roster(1000, 1000, 1064)))
        self.assertTrue(decision["aggregate_margin_ok"])
        self.assertFalse(decision["all_families_won"])
        self.assertFalse(decision["contender"])
        loser = next(r for r in decision["family_decisions"] if r["family"] == FAMILIES[1])
        self.assertFalse(loser["candidate_won"])

    def test_aggregate_passes_but_one_family_loss_by_one_byte_is_not_a_contender(self):
        # JLS2 (940,1001): family f loses by 1 byte; aggregate still clears 5%.
        candidate = {FAMILIES[0]: 940, FAMILIES[1]: 1001}
        decision = R.reduce_championship(bundle(candidate, cross_win_roster(1000, 1000, 1064)))
        self.assertTrue(decision["aggregate_margin_ok"])
        self.assertFalse(decision["contender"])

    def test_zpaq_crash_is_not_a_contender(self):
        candidate = {FAMILIES[0]: 500, FAMILIES[1]: 500}
        opponents = cross_win_roster(1000, 1000, 1064)
        for row in opponents:
            if row["codec_id"] == "zpaq-5-m54":
                row["items"][FAMILIES[0]]["execution"]["exact_roundtrip"] = False
        decision = R.reduce_championship(bundle(candidate, opponents))
        self.assertFalse(decision["contender"])
        self.assertFalse(decision["required_research_opponents_valid"])
        self.assertFalse(decision["required_research_opponent_status"]["zpaq-5-m54"])

    def test_per_item_failure_leaves_the_other_item_standing(self):
        # brotli fails family e but is smallest on family f; its family-f result must
        # still define the family-f minimum that JLS2 has to beat.
        candidate = {FAMILIES[0]: 400, FAMILIES[1]: 490}
        opponents = uniform_roster({FAMILIES[0]: 1000, FAMILIES[1]: 1000})
        for row in opponents:
            if row["codec_id"] == "brotli-11":
                row["items"][FAMILIES[0]]["execution"]["finished_within_wall"] = False
                row["items"][FAMILIES[1]]["complete_bytes"] = 500
        decision = R.reduce_championship(bundle(candidate, opponents))
        family_f = next(r for r in decision["family_decisions"] if r["family"] == FAMILIES[1])
        self.assertEqual(family_f["strongest_eligible_codec"], "brotli-11")
        self.assertEqual(family_f["strongest_eligible_bytes"], 500)
        self.assertTrue(family_f["candidate_won"])  # 490 < 500
        brotli = next(r for r in decision["opponent_classifications"] if r["codec_id"] == "brotli-11")
        self.assertEqual(brotli["per_family_classification"][FAMILIES[0]], "invalid-tool-failure")
        self.assertEqual(brotli["per_family_classification"][FAMILIES[1]], "valid")
        self.assertFalse(brotli["aggregate_valid"])

    def test_contextual_tool_never_beats_or_is_beaten(self):
        candidate = {FAMILIES[0]: 500, FAMILIES[1]: 500}
        opponents = cross_win_roster(1000, 1000, 1064)
        opponents.append(opponent("zpaq-5-m510", "contextual", {FAMILIES[0]: 100, FAMILIES[1]: 100}))
        decision = R.reduce_championship(bundle(candidate, opponents))
        self.assertTrue(decision["contender"])
        self.assertIn("zpaq-5-m510", decision["contextual_codecs"])
        self.assertNotEqual(decision["strongest_eligible_aggregate_codec"], "zpaq-5-m510")

    def test_failed_jls2_gate_blocks_a_contender(self):
        candidate = {FAMILIES[0]: 500, FAMILIES[1]: 500}
        gates = full_gates()
        gates["decompression_memory"] = False
        decision = R.reduce_championship(bundle(candidate, cross_win_roster(1000, 1000, 1064), gates=gates))
        self.assertFalse(decision["contender"])
        self.assertFalse(decision["candidate_gates_all_pass"])

    def test_invalid_eligible_tool_is_excluded_from_aggregate(self):
        # xz fails both items -> aggregate-invalid, excluded; contender still possible.
        candidate = {FAMILIES[0]: 970, FAMILIES[1]: 970}
        opponents = cross_win_roster(1000, 1000, 1064)
        for row in opponents:
            if row["codec_id"] == "xz-lzma2-9e":
                for family in FAMILIES:
                    row["items"][family]["execution"]["finished_within_wall"] = False
        decision = R.reduce_championship(bundle(candidate, opponents))
        self.assertTrue(decision["contender"])
        xz = next(r for r in decision["opponent_classifications"] if r["codec_id"] == "xz-lzma2-9e")
        self.assertFalse(xz["aggregate_valid"])


if __name__ == "__main__":
    unittest.main()
