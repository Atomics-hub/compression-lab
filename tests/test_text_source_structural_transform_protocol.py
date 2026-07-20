from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-text-source-structural-transform-protocol.md"
)


class TextSourceStructuralTransformProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PROTOCOL.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_hypotheses_are_predeclared_and_attributable(self) -> None:
        self.assertIn("TS-H1: framing demultiplex", self.text)
        self.assertIn("TS-H2: deterministic source extension lanes", self.text)
        self.assertIn("Explicitly deferred", self.text)
        self.assertIn("before running any transformed item", self.text)

    def test_complete_candidate_bytes_and_exactness_are_required(self) -> None:
        normalized = " ".join(self.lower.split())
        for phrase in (
            "count every envelope and backend byte",
            "payload sha-256",
            "fails closed on any payload mutation",
            "deletes the extracted payload",
            "no rejected bytes reach the backend",
            "one-bit backend-payload mutation",
            "every possible one-bit mutation of the fixed axtp2 header",
            "no extracted payload retained",
            "never allocates from declared header sizes",
            "all 87 truncated header lengths",
            "truncated/appended payloads",
            "stale/partial output",
            "nonnegative integer output limit",
            "exact source-size boundary",
            "forged uint64 maximum declaration",
            "caps record count",
            "same record and path/title limits",
            "more than 4,096 extension lanes",
            "cannot emit a structurally valid artifact",
            "independently derives the sorted extension roster",
            "unused zero-length lanes",
            "noncanonical and rejected",
            "maximal common prefix",
            "shorter prefix plus a longer suffix",
            "alternate encoding",
            "exact original size and",
            "two measured candidate artifacts",
            "no external dictionary",
            "one backend thread",
            "all 33 structural receipts",
            "all 630 practical-baseline",
            "all 15 practical standards",
            "explicit yes/no",
            "candidate beat each standard",
            "portability status",
            "runner comparability",
            "same-host context, not a paired timing claim",
            "remain publishable as negative evidence",
            "publication fail closed",
        ):
            self.assertIn(phrase, normalized)
        self.assertIn("publish-text-source-structural-transform.py", self.text)

    def test_numeric_gates_do_not_promote_a_weak_probe_to_a_win(self) -> None:
        for threshold in (
            "0.50% smaller",
            "0.25% larger",
            "2.00% smaller",
            "3.00% smaller",
        ):
            self.assertIn(threshold, self.text)
        self.assertIn("does not establish the requested 5% category win", self.text)
        self.assertIn("rejected and retained as negative evidence", self.text)

    def test_baseline_validation_and_ceiling_boundaries_remain_intact(self) -> None:
        normalized = " ".join(self.text.split())
        self.assertIn("complete 630-trial practical census", self.text)
        self.assertIn("fully clean commit", self.text)
        self.assertIn("complete identity, outcome, phase count", normalized)
        self.assertIn("wall-time sum", self.text)
        self.assertIn("peak-RSS maximum", self.text)
        self.assertIn("public validation: sealed and unaccessed", self.lower)
        self.assertIn("private holdout: sealed and unaccessed", self.lower)
        self.assertIn("research-ceiling codecs: separately audited", self.lower)

    def test_successor_route_is_frozen_before_results_and_keeps_the_full_gate(self) -> None:
        normalized = " ".join(self.text.split())
        for phrase in (
            "config/text-source-successor-routing-v1.json",
            "scripts/route-text-source-structural-successor.py",
            "scripts/verify-text-source-structural-successor-decision.py",
            "frozen before TS-H1/H2",
            "bounded reversible lexical-role channels",
            "bounded mixed byte/token predictor",
            "completely counted development-trained static dictionary",
            "at least 5.00% smaller",
            "regress no item by more than 0.50%",
            "starts with zero Axiom wins",
            "cannot be converted into wins",
        ):
            self.assertIn(phrase, normalized)


if __name__ == "__main__":
    unittest.main()
