from __future__ import annotations

import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "config" / "incompressible-precompressed-gates-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-incompressible-precompressed-protocol.md"
)
PORTFOLIO = REPOSITORY / "config" / "compression-category-matrix.json"
ACQUISITION = REPOSITORY / "runs" / "text-source-development-acquisition-v1.json"


class IncompressiblePrecompressedProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = CONFIG.read_bytes()
        cls.config = json.loads(cls.raw)
        cls.text = PROTOCOL.read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.text.split())

    def test_machine_protocol_is_canonical_and_uses_the_full_baseline_roster(self) -> None:
        self.assertEqual(
            self.raw,
            (json.dumps(self.config, indent=2, sort_keys=True) + "\n").encode(),
        )
        self.assertEqual(self.config["schema_version"], 1)
        self.assertEqual(
            self.config["name"], "incompressible-precompressed-product-gates-v1"
        )
        self.assertEqual(len(self.config["baseline_roster"]), 13)
        self.assertEqual(self.config["baseline_roster"][0], "store")
        self.assertIn("zstd-9", self.config["baseline_roster"])
        self.assertIn("brotli-11", self.config["baseline_roster"])
        self.assertIn("7zip-lzma2-9", self.config["baseline_roster"])

    def test_information_boundary_never_turns_random_store_into_a_ratio_win(self) -> None:
        boundary = self.config["information_theoretic_boundary"]
        self.assertFalse(boundary["five_percent_ratio_target_feasible"])
        self.assertTrue(boundary["store_tie_is_success_not_a_ratio_win"])
        selector = self.config["selector_safety_gates"]
        self.assertEqual(
            selector["maximum_complete_artifact_bytes_above_equally_framed_store"],
            0,
        )
        self.assertTrue(
            selector["selector_evidence_must_be_bounded_independent_of_input_size"]
        )
        self.assertTrue(
            selector["final_output_comparison_must_override_a_wrong_sample_choice"]
        )
        for phrase in (
            "By pigeonhole counting",
            "A store tie is a safety success, never a compression-ratio win",
            "zero bytes more",
            "does not hide Axiom framing on one side",
        ):
            self.assertIn(phrase, self.normalized)

    def test_development_sources_and_unseen_policies_are_frozen_but_unopened(self) -> None:
        families = {row["family_id"]: row for row in self.config["development_families"]}
        self.assertEqual(
            set(families),
            {
                "shake256-uniform",
                "deceptive-region-order",
                "magic-spoofed-random",
                "licensed-precompressed-source",
                "licensed-precompressed-wikimedia",
            },
        )
        self.assertEqual(
            len(families["deceptive-region-order"]["layouts"]), 5
        )
        self.assertEqual(
            set(families["magic-spoofed-random"]["magic_prefixes_hex"]),
            {"gzip", "zip", "png", "jpeg", "pdf", "zstd", "xz", "7zip"},
        )
        self.assertIn(
            "Counter-mode 1 MiB blocks",
            families["shake256-uniform"]["generation"],
        )
        acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
        for family_id in (
            "licensed-precompressed-source",
            "licensed-precompressed-wikimedia",
        ):
            self.assertEqual(
                families[family_id]["source_aggregate_manifest_sha256"],
                acquisition["aggregate_manifest_sha256"],
            )
            self.assertEqual(len(families[family_id]["precompression_codecs"]), 6)
        self.assertEqual(
            families["licensed-precompressed-source"]["source_ids"],
            ["cpython-3.14.6-source", "rust-1.97.1-source"],
        )
        self.assertEqual(
            families["licensed-precompressed-wikimedia"]["source_ids"],
            ["enwikibooks-20260701"],
        )
        self.assertEqual(
            self.config["public_validation_policy"]["status"],
            "policy frozen; corpus unopened and unselected",
        )
        self.assertEqual(
            self.config["private_holdout_policy"]["status"],
            "policy frozen; corpus unselected and inaccessible",
        )
        self.assertIn("future lineage-disjoint", self.normalized)
        self.assertIn("unchanged candidate exactly once", self.normalized)

    def test_operational_streaming_integrity_and_public_chart_gates_are_complete(self) -> None:
        operational = self.config["operational_gates"]
        self.assertEqual(operational["maximum_selector_input_bytes"], 262_144)
        self.assertEqual(operational["minimum_native_compression_mbps"], 1_000.0)
        self.assertEqual(operational["minimum_native_decompression_mbps"], 1_500.0)
        self.assertEqual(operational["maximum_compression_peak_rss_bytes"], 128 * 1024**2)
        self.assertEqual(operational["maximum_decompression_peak_rss_bytes"], 128 * 1024**2)
        self.assertEqual(operational["required_native_streaming_window_bytes"], 64 * 1024**2)
        self.assertEqual(
            self.config["measurement_policy"]["large_file_sizes_bytes"],
            [1 * 1024**3, 4 * 1024**3],
        )
        integrity = self.config["format_and_integrity_gates"]
        self.assertTrue(all(integrity.values()))
        for phrase in (
            "ordinary generated files, never sparse-file logical sizes",
            "beyond 32-bit length boundaries",
            "every one-bit mutation of the fixed header",
            "second supported operating system and architecture",
            "immutable five-file bundle",
            "Store-size ties are labeled ties, not wins",
            "whether Axiom beat each row",
            "prepare-incompressible-precompressed-execution.py",
            "verify-incompressible-precompressed-plan.py",
            "immutable 49-task plan",
            "31 generated items and 18 licensed",
            "pre-execution lock, not a corpus or benchmark result",
            "build-incompressible-precompressed-development.py",
            "verify-incompressible-precompressed-development.py",
            "streamed in fixed 1 MiB blocks",
            "one `input.bin` member",
            "exactly 49 ordinary item files",
            "regenerates all 31 CC0 identities",
            "adaptive-v3 `.clab` fallback is safety evidence, not the candidate",
            "selector evidence grows with input length",
            "may attempt a whole-input Zstandard encoding",
            "No readiness credit is awarded by this static audit",
            "tracked licensed acquisition receipt",
            "does not depend on the ignored licensed source-corpus manifest",
            "independent reproducer must rebuild them",
        ):
            self.assertIn(phrase, self.normalized)

    def test_portfolio_does_not_credit_the_unbuilt_corpus_as_a_completed_gate(self) -> None:
        portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        category = next(
            row
            for row in portfolio["categories"]
            if row["id"] == "incompressible_precompressed"
        )
        self.assertEqual(category["readiness_percent"], 10)
        self.assertFalse(category["completion_gates"]["frozen_licensed_splits"])
        self.assertEqual(
            category["current_evidence"],
            "docs/benchmarks/2026-07-17-incompressible-precompressed-protocol.md",
        )
        self.assertIn("not yet constructed", category["current_result"])
        self.assertEqual(category["tested_standards"], [])


if __name__ == "__main__":
    unittest.main()
