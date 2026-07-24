"""Consistency guards binding the championship gates, doc, reducer, and #109 roster.

Config/doc/reducer drift fails CI: the frozen ranges, reducer constants, walls,
eligibility framing, tool-failure discipline, claim ceiling, and #109 roster
identities must agree across the gates config, the protocol doc, and the reducer.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "config" / "clue-jls2-championship-screen-v1-gates.json"
CORPUS = ROOT / "config" / "clue-json-log-corpus-championship-v1.json"
DOC = ROOT / "docs" / "benchmarks" / "2026-07-25-clue-jls2-championship-screen-protocol.md"
ROSTER = ROOT / "config" / "json-log-championship-roster-v1.json"
LANES = ROOT / "docs" / "RESEARCH_LANES.md"
REDUCER = ROOT / "scripts" / "reduce-clue-jls2-championship-screen-v1.py"


def load_reducer():
    spec = importlib.util.spec_from_file_location("championship_reducer_gates", REDUCER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChampionshipGatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gates = json.loads(GATES.read_bytes())
        cls.corpus = json.loads(CORPUS.read_bytes())
        cls.roster = json.loads(ROSTER.read_bytes())
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.lanes = LANES.read_text(encoding="utf-8")
        cls.reducer = load_reducer()

    def test_gates_identity(self):
        self.assertEqual(self.gates["name"], "clue-jls2-championship-screen-v1")
        self.assertEqual(self.gates["technical_codec"], "JLS2")
        self.assertEqual(self.gates["public_brand"], "Axiom")

    def test_frozen_ranges_match_corpus_and_doc(self):
        items = self.gates["validation"]["expected_items"]
        self.assertEqual(
            [(row["first_record_id"], row["last_record_id"]) for row in items],
            [(15_000_001, 15_250_000), (32_000_001, 32_250_000)],
        )
        sealed = self.corpus["selection"]["public_validation"]
        self.assertEqual(
            [(row["first_record_id"], row["last_record_id"]) for row in sealed],
            [(15_000_001, 15_250_000), (32_000_001, 32_250_000)],
        )
        self.assertEqual(self.gates["validation"]["expected_record_counts"],
                         {"clue-championship-e": 250000, "clue-championship-f": 250000})
        self.assertIn("15,000,001", self.doc)
        self.assertIn("15,250,000", self.doc)
        self.assertIn("32,000,001", self.doc)
        self.assertIn("32,250,000", self.doc)

    def test_reducer_constants_match_gates(self):
        reducer_block = self.gates["reducer"]
        self.assertEqual(reducer_block["contender_numerator"], 95)
        self.assertEqual(reducer_block["contender_denominator"], 100)
        self.assertEqual(self.reducer.CONTENDER_NUMERATOR, 95)
        self.assertEqual(self.reducer.CONTENDER_DENOMINATOR, 100)

    def test_eligible_roster_matches_reducer_and_doc(self):
        eligible = tuple(self.gates["roster"]["eligible_opponent_codec_ids"])
        self.assertEqual(set(eligible), set(self.reducer.ELIGIBLE_OPPONENT_CODEC_IDS))
        self.assertEqual(
            set(eligible),
            {
                "kanzi-max",
                "zpaq-5-m54",
                "brotli-11",
                "zstd-22",
                "xz-lzma2-9e",
                "7zip-9",
                "pbc-only",
            },
        )
        self.assertEqual(
            tuple(self.gates["roster"]["required_research_opponent_codec_ids"]),
            self.reducer.REQUIRED_RESEARCH_OPPONENT_CODEC_IDS,
        )

    def test_equality_semantics_are_documented(self):
        self.assertIn("PASSES", self.reducer.EQUALITY_SEMANTICS)
        self.assertIn("<=", self.reducer.EQUALITY_SEMANTICS)
        self.assertIn("<=", self.gates["reducer"]["equality_semantics"])
        self.assertIn("equality passes", self.gates["reducer"]["equality_semantics"].lower())
        self.assertIn("equality passes", self.doc.lower())

    def test_per_family_is_outright_win_not_five_percent_margin(self):
        rule = self.gates["reducer"]["per_family_and_per_item_rule"]
        self.assertIn("WIN OUTRIGHT", rule)
        self.assertIn("zero bytes", rule)
        self.assertIn("NO separate per-family 5% margin", rule)
        self.assertIn("WIN OUTRIGHT", self.reducer.EQUALITY_SEMANTICS)
        # The 5% margin applies to the aggregate only.
        self.assertIn("aggregate only", rule)
        self.assertEqual(self.gates["reducer"]["contender_numerator"], 95)
        self.assertIn("outright win", self.doc.lower())
        self.assertIn("allowed regression is zero", self.doc.lower())

    def test_supersession_of_109_is_documented(self):
        supersession = self.gates["supersession"]
        self.assertIn("2026-07-25", supersession["authority"])
        self.assertIn("json-log-championship-roster-v1", supersession["supersedes_for_this_screen_only"])
        self.assertIn("not edited", supersession["unchanged"].lower())
        self.assertIn("supersede", self.doc.lower())
        self.assertIn("championship candidate", self.doc)
        self.assertIn("public championship contender", self.doc)
        # #109 itself is not modified by this PR: its file must still say "not yet executed".
        self.assertEqual(self.roster["status"], "frozen prospective roster; not yet executed")

    def test_pbc_is_first_class_attempted_via_v2_machinery(self):
        eligible = {row["codec_id"]: row for row in self.gates["roster"]["eligible_opponents"]}
        pbc = eligible["pbc-only"]
        self.assertEqual(pbc["gates_path"], "config/clue-pbc-championship-screen-v1-gates.json")
        self.assertIn("benchmark-pbc-competitor.py", pbc["attempt_path"])
        self.assertIn("invalid-tool-failure", pbc["attempt_path"])
        self.assertIn("pbc-only", self.gates["roster"]["eligible_opponent_codec_ids"])
        self.assertIn("first-class attempted", self.doc.lower())
        pbc_gates = json.loads(
            (ROOT / "config" / "clue-pbc-championship-screen-v1-gates.json").read_bytes()
        )
        self.assertEqual(
            pbc_gates["requirements"]["expected_families"],
            ["clue_championship_e", "clue_championship_f"],
        )
        self.assertEqual(pbc_gates["source"]["commit"], "bac1f86d29624cb585bb4475235d22a28e60ffea")

    def test_lock_re_pin_procedure_documented(self):
        self.assertIn("re-pin", self.doc.lower())
        self.assertIn("squash-merge", self.doc.lower())
        self.assertIn("readiness_commit", self.doc)
        self.assertIn("workflow_dispatch", self.doc)

    def test_walls_are_frozen_and_justified(self):
        walls = self.gates["walls"]
        self.assertEqual(walls["per_item_wall_seconds_default"], 600.0)
        self.assertEqual(walls["per_codec_wall_overrides_seconds"]["zpaq-5-m54"], 1800.0)
        self.assertEqual(walls["per_codec_wall_overrides_seconds"]["jls2"], 1800.0)
        self.assertIn("113.8", walls["zpaq_wall_justification"])
        self.assertIn("600 s", self.doc)
        self.assertIn("1800 s", self.doc)
        self.assertIn("113.8", self.doc)

    def test_zpaq_method_notation_and_memory(self):
        eligible = {row["codec_id"]: row for row in self.gates["roster"]["eligible_opponents"]}
        self.assertIn("-method 54 ", eligible["zpaq-5-m54"]["settings"])
        self.assertNotIn("-method 510", eligible["zpaq-5-m54"]["settings"])
        self.assertIn("343.3 MiB", eligible["zpaq-5-m54"]["memory_context"])
        contextual = {row["codec_id"]: row for row in self.gates["roster"]["contextual_opponents"]}
        self.assertIn("-method 510", contextual["zpaq-5-m510"]["settings"])
        self.assertIn("1272.1 MiB", contextual["zpaq-5-m510"]["reason"])
        self.assertIn("343.3 MiB", self.doc)
        self.assertIn("1272.1 MiB", self.doc)

    def test_zpaq_jit_nojit_build_identity_recorded(self):
        eligible = {row["codec_id"]: row for row in self.gates["roster"]["eligible_opponents"]}
        self.assertEqual(
            eligible["zpaq-5-m54"]["source_zip_sha256"],
            "e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418",
        )
        self.assertIn("byte-identical", eligible["zpaq-5-m54"]["build"])
        self.assertIn("byte-identical", self.doc)
        self.assertIn("NOJIT", self.doc)

    def test_roster_identities_agree_with_109(self):
        roster_by_tool = {row["tool"]: row for row in self.roster["roster"]}
        eligible = {row["codec_id"]: row for row in self.gates["roster"]["eligible_opponents"]}
        self.assertEqual(
            eligible["kanzi-max"]["commit"], roster_by_tool["Kanzi-max"]["commit"]
        )
        self.assertEqual(
            eligible["brotli-11"]["commit"], roster_by_tool["Brotli-11"]["commit"]
        )
        self.assertEqual(
            eligible["7zip-9"]["asset_sha256"], roster_by_tool["7-Zip"]["asset_sha256"]
        )
        self.assertEqual(
            eligible["pbc-only"]["license_sha256"], roster_by_tool["PBC"]["license_sha256"]
        )

    def test_512_mib_product_cap_is_jls2_only(self):
        requirements = self.gates["requirements"]
        self.assertEqual(requirements["maximum_cold_decompression_peak_rss_bytes"], 536870912)
        self.assertEqual(requirements["product_decode_rss_cap_applies_to"], "jls2")
        self.assertIn("regardless of their own", self.gates["roster"]["eligibility_framing"])
        self.assertIn("512 MiB decoder-RSS product cap FOR JLS2", self.doc)

    def test_tool_failure_classification_present(self):
        self.assertTrue(self.gates["requirements"]["require_tool_failure_classification"])
        self.assertIn("invalid-tool-failure", self.doc)
        self.assertIn("never counted as a JLS2 win", self.doc)
        self.assertIn("quietly omitted", self.gates["roster"]["kanzi_zpaq_rule"])

    def test_claim_ceiling_is_bounded_and_documented(self):
        ceiling = self.gates["claim_ceiling"]
        self.assertIn("public championship contender", ceiling)
        for banned in ("world-best", "state-of-the-art", "market-leading"):
            self.assertIn(banned, ceiling)
        self.assertIn("public championship contender", self.doc)
        self.assertIn("never beaten", ceiling)

    def test_moon_ledger_not_charged(self):
        self.assertIn("NOT the Lane 2 moonshot".lower(), self.gates["moonshot_ledger_note"].lower())
        self.assertIn("not charged against the moon", self.doc.lower())

    def test_lane_references_this_doc(self):
        self.assertIn(
            "docs/benchmarks/2026-07-25-clue-jls2-championship-screen-protocol.md",
            self.lanes,
        )

    def test_does_not_change_v1_or_v2(self):
        self.assertEqual(self.gates["prior_scores"]["v1"]["result"], "not_passed")
        self.assertEqual(self.gates["prior_scores"]["v2"]["result"], "passed")
        self.assertTrue(self.gates["prior_scores"]["v1"]["immutable"])
        self.assertTrue(self.gates["prior_scores"]["v2"]["immutable"])


if __name__ == "__main__":
    unittest.main()
