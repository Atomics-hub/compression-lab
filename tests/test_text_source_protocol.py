from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "config" / "text-source-category-protocol-v1.json"
GATES = ROOT / "config" / "text-source-gates-v1.json"
PORTFOLIO = ROOT / "config" / "compression-category-matrix.json"
PATH_RULES = ROOT / "config" / "text-source-path-rules-v1.json"


class TextSourceProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        cls.gates = json.loads(GATES.read_text(encoding="utf-8"))

    def test_text_and_source_are_independent_tracks(self) -> None:
        self.assertEqual(self.protocol["schema_version"], 1)
        self.assertEqual(
            self.protocol["source_code"]["category_id"],
            "source_code_bundles",
        )
        self.assertEqual(
            self.protocol["natural_language"]["category_id"],
            "english_wikimedia_wikitext",
        )
        separation = self.protocol["category_separation"]["rule"].lower()
        self.assertIn("independent", separation)
        self.assertIn("says nothing about the other", separation)

    def test_source_projects_are_licensed_declared_and_lineage_disjoint(self) -> None:
        track = self.protocol["source_code"]
        development = track["development"]
        validation = track["public_validation"]
        self.assertEqual(len(development), 4)
        self.assertEqual(len(validation), 4)
        self.assertEqual(
            {item["language_stratum"] for item in development},
            {"python_and_c", "typescript", "rust", "c_and_cpp"},
        )
        self.assertEqual(
            {item["language_stratum"] for item in validation},
            {"python", "typescript", "rust", "c_and_cpp"},
        )
        development_families = {item["project_family"] for item in development}
        validation_families = {item["project_family"] for item in validation}
        self.assertTrue(development_families.isdisjoint(validation_families))
        self.assertIn("unmodified", track["bundle_rule"]["framing"])
        for item in development + validation:
            self.assertTrue(item["archive_url"].startswith("https://"))
            self.assertTrue(item["license_spdx"])
            self.assertTrue(item["license_url"].startswith("https://"))
        for item in validation:
            self.assertIsNone(item["archive_sha256"])
            self.assertIsNone(item["derived_item_sha256"])
        self.assertTrue(
            all(item["acquisition_status"] == "acquired_development" for item in development)
        )
        self.assertTrue(all(item["archive_sha256"] for item in development))
        self.assertTrue(all(item["derived_item_sha256"] for item in development))
        self.assertTrue(
            all(item["acquisition_status"] == "sealed_unacquired" for item in validation)
        )

    def test_source_path_rules_and_both_framings_are_exactly_bound(self) -> None:
        bundle = self.protocol["source_code"]["bundle_rule"]
        self.assertEqual(bundle["path_rules"], "config/text-source-path-rules-v1.json")
        self.assertEqual(
            bundle["path_rules_sha256"],
            hashlib.sha256(PATH_RULES.read_bytes()).hexdigest(),
        )
        rules = json.loads(PATH_RULES.read_text(encoding="utf-8"))
        self.assertEqual(
            rules["selected_extensions"], bundle["selected_extensions"]
        )
        self.assertIn("retained-file count", bundle["framing"])
        self.assertIn("Concatenate entries", bundle["manifest_hash"])
        extractor = self.protocol["natural_language"]["extractor_rule"]
        self.assertIn("retained-page count", extractor["framing"])
        self.assertIn("Concatenate entries", extractor["manifest_hash"])

    def test_wikimedia_projects_are_split_and_famous_benchmark_is_context_only(self) -> None:
        track = self.protocol["natural_language"]
        development = track["development"]
        validation = track["public_validation"]
        self.assertEqual(len(development), 3)
        self.assertEqual(len(validation), 3)
        development_families = {item["project_family"] for item in development}
        validation_families = {item["project_family"] for item in validation}
        self.assertTrue(development_families.isdisjoint(validation_families))
        for item in development + validation:
            self.assertEqual(item["dump_date"], "20260701")
            self.assertTrue(item["archive_url"].startswith("https://dumps.wikimedia.org/"))
            self.assertTrue(item["checksum_url"].startswith("https://dumps.wikimedia.org/"))
        for item in validation:
            self.assertIsNone(item["archive_sha256"])
            self.assertIsNone(item["derived_item_sha256"])
        self.assertTrue(all(item["publisher_digest"] for item in development))
        self.assertTrue(all(item["publisher_digest"] is None for item in validation))
        self.assertTrue(
            all(item["acquisition_status"] == "acquired_development" for item in development)
        )
        self.assertTrue(all(item["archive_sha256"] for item in development))
        self.assertTrue(all(item["derived_item_sha256"] for item in development))
        diagnostic = track["diagnostics_only"][0]
        self.assertEqual(diagnostic["id"], "enwik9")
        self.assertIn("never", diagnostic["reason"].lower())
        self.assertIn("validation", diagnostic["reason"].lower())

    def test_baseline_tiers_and_claim_boundary_are_explicit(self) -> None:
        practical = {
            row["codec_id"] for row in self.gates["baseline_tiers"]["practical_required"]
        }
        self.assertTrue(
            {
                "store",
                "lz4-1",
                "gzip-9",
                "bzip2-9",
                "bzip3-max",
                "zstd-9",
                "zstd-22-ultra",
                "brotli-11",
                "xz-lzma2-9e",
                "7zip-lzma2-9",
                "7zip-ppmd-9",
                "kanzi-max",
                "libbsc-max",
            }.issubset(practical)
        )
        research = {
            row["codec_id"] for row in self.gates["baseline_tiers"]["research_ceiling"]
        }
        self.assertEqual(
            research,
            {"zpaq-5", "paq8px-forcetext", "cmix", "nncp"},
        )
        policy = self.gates["comparability_policy"]
        self.assertIn("cannot be counted as wins", policy["practical_gate"])
        self.assertIn("never disappear", policy["research_context"])
        self.assertIn("world-best", self.gates["claim_rule"])
        self.assertIn("independent reproduction", self.gates["claim_rule"])

    def test_operational_gates_are_bounded_and_exact(self) -> None:
        ratio = self.gates["ratio_mode_requirements"]
        self.assertEqual(
            ratio["minimum_aggregate_gain_vs_strongest_practical_percent"],
            5.0,
        )
        self.assertGreater(ratio["minimum_compression_mbps"], 0)
        self.assertGreater(ratio["minimum_decompression_mbps"], 0)
        shared = self.gates["shared_requirements"]
        self.assertTrue(shared["require_exact_roundtrip"])
        self.assertTrue(shared["require_deterministic_output"])
        self.assertTrue(shared["require_complete_frame_accounting"])
        self.assertTrue(shared["require_bounded_input_derived_selection"])
        streaming = self.gates["streaming_requirements"]
        self.assertEqual(streaming["target_segment_bytes"], 16 * 1024 * 1024)
        self.assertEqual(streaming["maximum_concurrent_segments"], 2)
        self.assertGreaterEqual(streaming["minimum_large_file_bytes"], 1024**3)

    def test_portfolio_exposes_both_tracks_without_a_combined_claim(self) -> None:
        portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        categories = {row["id"]: row for row in portfolio["categories"]}
        self.assertNotIn("plain_text_source", categories)
        self.assertIn("source_code_bundles", categories)
        self.assertIn("english_wikimedia_wikitext", categories)
        practical_codecs = [
            row["codec_id"]
            for row in self.gates["baseline_tiers"]["practical_required"]
        ]
        for category_id in ("source_code_bundles", "english_wikimedia_wikitext"):
            self.assertEqual(categories[category_id]["status"], "untested")
            self.assertEqual(
                categories[category_id]["tested_standards"], practical_codecs
            )
            result = categories[category_id]["current_result"].lower()
            self.assertIn("census completed", result)
            self.assertIn("no axiom candidate", result)


if __name__ == "__main__":
    unittest.main()
