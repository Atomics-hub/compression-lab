"""Integrity + reproduction guards for the published championship screen result.

Locks the checked-in `runs/clue-jls2-championship-screen-v1/` evidence: every
SHA256SUMS entry must verify, the frozen reducer re-run on the checked-in bundle
must reproduce `not_contender`, and the published docs must reference the run.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "clue-jls2-championship-screen-v1"
REDUCER = ROOT / "scripts" / "reduce-clue-jls2-championship-screen-v1.py"
RESULTS = ROOT / "docs" / "benchmarks" / "2026-07-25-clue-jls2-championship-screen-results.md"
LANES = ROOT / "docs" / "RESEARCH_LANES.md"
README = ROOT / "README.md"


def load_reducer():
    spec = importlib.util.spec_from_file_location("championship_reducer_evidence", REDUCER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ChampionshipEvidenceTests(unittest.TestCase):
    def test_all_sha256sums_entries_verify(self) -> None:
        sums = (RUN / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        checked = 0
        for line in sums:
            line = line.strip()
            if not line:
                continue
            digest, _, relative = line.partition("  ")
            target = (RUN / relative).resolve()
            self.assertTrue(target.is_file(), f"missing evidence file: {relative}")
            self.assertEqual(sha256_file(target), digest, relative)
            checked += 1
        self.assertEqual(checked, 14)

    def test_published_decision_is_not_contender(self) -> None:
        decision = json.loads((RUN / "decision.json").read_bytes())
        self.assertEqual(decision["result"], "not_contender")
        self.assertFalse(decision["contender"])
        self.assertEqual(decision["candidate_aggregate_complete_bytes"], 4_323_039)
        self.assertEqual(decision["strongest_eligible_aggregate_codec"], "zpaq-5-m54")
        self.assertEqual(decision["strongest_eligible_aggregate_bytes"], 1_540_588)
        self.assertFalse(decision["candidate_gates_all_pass"])
        self.assertFalse(decision["all_families_won"])
        self.assertFalse(decision["required_research_opponents_valid"])

    def test_frozen_reducer_reproduces_the_decision_from_the_bundle(self) -> None:
        reducer = load_reducer()
        bundle = json.loads((RUN / "score" / "bundle.json").read_bytes())
        redo = reducer.reduce_championship(bundle)
        self.assertEqual(redo["result"], "not_contender")
        self.assertFalse(redo["contender"])
        self.assertEqual(redo["candidate_aggregate_complete_bytes"], 4_323_039)
        self.assertEqual(redo["strongest_eligible_aggregate_codec"], "zpaq-5-m54")
        self.assertEqual(redo["strongest_eligible_aggregate_bytes"], 1_540_588)
        # kanzi and xz are invalid-tool-failures; never counted, and kanzi (a
        # required research opponent) keeps this from ever being a clean contender.
        by_codec = {r["codec_id"]: r for r in redo["opponent_classifications"]}
        self.assertEqual(by_codec["kanzi-max"]["per_family_classification"],
                         {"clue_championship_e": "invalid-tool-failure",
                          "clue_championship_f": "invalid-tool-failure"})
        self.assertEqual(by_codec["xz-lzma2-9e"]["per_family_classification"],
                         {"clue_championship_e": "invalid-tool-failure",
                          "clue_championship_f": "invalid-tool-failure"})

    def test_recomputed_receipt_matches_the_decision(self) -> None:
        decision = json.loads((RUN / "decision.json").read_bytes())
        recomputed = json.loads((RUN / "decision-recomputed.json").read_bytes())
        for key in ("result", "contender", "candidate_aggregate_complete_bytes",
                    "strongest_eligible_aggregate_codec",
                    "strongest_eligible_aggregate_bytes", "all_families_won",
                    "candidate_gates_all_pass", "required_research_opponents_valid"):
            self.assertEqual(decision[key], recomputed[key], key)

    def test_jls2_compression_memory_gate_failed_on_family_e(self) -> None:
        bundle = json.loads((RUN / "score" / "bundle.json").read_bytes())
        gates = bundle["candidate"]["gates"]
        self.assertFalse(gates["compression_memory"])
        self.assertTrue(gates["decompression_memory"])
        self.assertEqual(bundle["candidate"]["compression_peak_rss_bytes"], 645_296_128)
        self.assertGreater(bundle["candidate"]["compression_peak_rss_bytes"], 536_870_912)

    def test_docs_publish_the_result(self) -> None:
        results = RESULTS.read_text(encoding="utf-8")
        self.assertIn("not_contender", results)
        self.assertIn("2.81", results)
        self.assertIn("runs/clue-jls2-championship-screen-v1/", results)
        self.assertIn("2026-07-25-clue-jls2-championship-screen-results.md",
                      LANES.read_text(encoding="utf-8"))
        self.assertIn("championship-screen-results", README.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
