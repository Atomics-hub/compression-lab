"""Guards binding the championship roster config to its frozen doc.

The roster is a prospective, not-yet-executed protocol freeze. These tests make
config/doc drift fail CI: every roster identity token in the machine-readable
config must appear verbatim in the doc, the claim ceiling must match, and the
cross-references must resolve.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-log-championship-roster-v1.json"
DOC = ROOT / "docs" / "benchmarks" / "2026-07-24-json-log-championship-roster-v1.md"
LANES = ROOT / "docs" / "RESEARCH_LANES.md"

class ChampionshipRosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_bytes())
        cls.doc = DOC.read_text(encoding="utf-8")
        cls.lanes = LANES.read_text(encoding="utf-8")

    def test_config_shape(self) -> None:
        self.assertEqual(self.config["name"], "json-log-championship-roster-v1")
        self.assertEqual(self.config["status"], "frozen prospective roster; not yet executed")
        self.assertEqual(self.config["doc_path"], "docs/benchmarks/2026-07-24-json-log-championship-roster-v1.md")
        self.assertTrue(self.config["no_measurements_note"])

    def test_doc_references_config(self) -> None:
        self.assertIn("config/json-log-championship-roster-v1.json", self.doc)

    def test_lane_references_doc(self) -> None:
        self.assertIn(self.config["doc_path"], self.lanes)

    def test_claim_ceiling_matches_and_is_bounded(self) -> None:
        ceiling = self.config["claim_ceiling"]
        self.assertIn(
            "Category-scoped public-validation product pass on the two named previously unopened CLUE-LDS temporal ranges",
            ceiling,
        )
        # The banned superlatives may appear only inside an explicit prohibition.
        for banned in ("state-of-the-art", "market-leading", "world-best"):
            self.assertIn(banned, ceiling)
        self.assertIn("may not support", self.doc)
        self.assertIn("never beaten", self.doc)

    def test_every_roster_tool_and_identity_is_in_the_doc(self) -> None:
        tools = {entry["tool"] for entry in self.config["roster"]}
        self.assertEqual(
            tools,
            {
                "JLS2 / Axiom",
                "Brotli-11",
                "Zstandard (high-ratio)",
                "XZ / LZMA",
                "7-Zip",
                "Kanzi-max",
                "ZPAQ",
                "PBC",
            },
        )
        for entry in self.config["roster"]:
            self.assertIn(entry["tool"], self.doc)
            for key in ("commit", "asset_sha256", "binary_sha256", "source_zip_sha256"):
                value = entry.get(key)
                if value:
                    self.assertIn(value, self.doc, f"{entry['tool']} {key} missing from doc")

    def test_kanzi_and_zpaq_are_present_and_not_omittable(self) -> None:
        rostered = {entry["tool"] for entry in self.config["roster"]}
        self.assertIn("Kanzi-max", rostered)
        self.assertIn("ZPAQ", rostered)
        self.assertIn("quietly omitted", self.config["kanzi_zpaq_rule"])
        self.assertIn("quietly omitted", self.doc)

    def test_unavailable_specialists_stay_unavailable(self) -> None:
        by_tool = {entry["tool"]: entry for entry in self.config["unavailable_or_contextual"]}
        for name in ("LogFold", "LogPrism", "LogLite", "DeLog"):
            self.assertEqual(by_tool[name]["status"], "unavailable")
            self.assertIn(name, self.doc)

    def test_zpaq_method_notation_is_correct(self) -> None:
        zpaq = next(e for e in self.config["roster"] if e["tool"] == "ZPAQ")
        # Eligible ZPAQ is level 5 / 16 MiB block = -method 54 (343.3 MiB decode, in-gate).
        self.assertIn("-method 54 ", zpaq["settings"])
        self.assertNotIn("-method 510", zpaq["settings"])
        self.assertIn("-method 54", self.doc)
        self.assertIn("343.3 MiB", self.doc)
        # The 1 GiB block (-method 510, 1272.1 MiB decode) is the contextual ceiling only.
        ceiling = next(
            e for e in self.config["unavailable_or_contextual"] if e["tool"] == "ZPAQ (research ceiling)"
        )
        self.assertEqual(ceiling["status"], "contextual")
        self.assertIn("-method 510", ceiling["settings"])
        self.assertIn("1272.1 MiB", ceiling["reason"])
        self.assertIn("-method 510", self.doc)

    def test_memory_gate_matches_v2(self) -> None:
        self.assertEqual(self.config["memory_rules"]["eligible_decode_gate_bytes"], 536870912)
        self.assertEqual(
            self.config["memory_rules"]["instrument_sha256"],
            "805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306",
        )

    def test_sequencing_freezes_before_holdout(self) -> None:
        rule = self.config["sequencing"]["rule"]
        self.assertIn("frozen BEFORE any private-holdout", rule)
        self.assertIn("never enter", rule)


if __name__ == "__main__":
    unittest.main()
