import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]


class TabularProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(
            (REPOSITORY / "config" / "tabular-corpus-v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.gates = json.loads(
            (REPOSITORY / "config" / "tabular-gates-v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_split_is_disjoint_and_large_enough(self):
        development = self.corpus["development"]
        validation = self.corpus["public_validation"]
        self.assertEqual(len(development), 4)
        self.assertEqual(len(validation), 4)
        development_ids = {item["dataset_id"] for item in development}
        validation_ids = {item["dataset_id"] for item in validation}
        self.assertTrue(development_ids.isdisjoint(validation_ids))
        self.assertEqual(
            self.gates["shared_requirements"][
                "required_public_validation_families"
            ],
            len(validation),
        )

    def test_sources_are_licensed_and_frozen_before_acquisition(self):
        self.assertEqual(self.corpus["provider"]["license_spdx"], "CC-BY-4.0")
        items = self.corpus["development"] + self.corpus["public_validation"]
        self.assertEqual(len({item["id"] for item in items}), len(items))
        self.assertEqual(len({item["family"] for item in items}), len(items))
        for item in items:
            self.assertTrue(item["page_url"].startswith("https://"))
            self.assertTrue(item["archive_url"].startswith("https://"))
            self.assertRegex(item["doi"], r"^10\.")
            if item in self.corpus["development"]:
                self.assertRegex(item["archive_sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(item["selected_item_bytes"], 0)
                self.assertRegex(
                    item["selected_item_sha256"], r"^[0-9a-f]{64}$"
                )
                self.assertIsInstance(item["source_complete"], bool)
            else:
                self.assertIsNone(item["archive_sha256"])
                self.assertIsNone(item["selected_item_bytes"])
                self.assertIsNone(item["selected_item_sha256"])
                self.assertIsNone(item["source_complete"])
            self.assertNotIn("..", Path(item["member"]).parts)
        self.assertEqual(self.corpus["private_holdout"]["status"], "sealed")

    def test_gate_roster_and_claim_boundary_are_explicit(self):
        baselines = set(self.gates["exact_byte_baselines"])
        self.assertTrue(
            {
                "gzip-9",
                "zstd-3",
                "zstd-9",
                "zstd-19",
                "brotli-11",
                "xz-lzma2-9",
                "7zip-lzma2-9",
            }.issubset(baselines)
        )
        shared = self.gates["shared_requirements"]
        self.assertTrue(shared["require_exact_roundtrip"])
        self.assertTrue(shared["require_deterministic_output"])
        self.assertTrue(shared["require_complete_frame_accounting"])
        self.assertIn("independent reproduction", self.gates["claim_rule"])

        streaming = self.gates["streaming_requirements"]
        self.assertEqual(streaming["target_segment_bytes"], 16 * 1024 * 1024)
        self.assertEqual(
            streaming["maximum_record_alignment_slack_bytes"],
            1024 * 1024,
        )
        self.assertGreaterEqual(
            streaming["minimum_large_file_bytes"],
            1024 * 1024 * 1024,
        )
        self.assertTrue(streaming["require_inner_and_outer_integrity_checks"])
        self.assertEqual(streaming["maximum_concurrent_segments"], 2)
        self.assertTrue(
            streaming["require_atomic_failure_without_output_clobber"]
        )


if __name__ == "__main__":
    unittest.main()
