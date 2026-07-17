import json
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG = REPOSITORY / "config" / "tabular-successor-corpus-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-tabular-successor-corpus-protocol.md"
)
FETCHER = REPOSITORY / "scripts" / "fetch_tabular_successor_corpus.py"
SPECIFICATION = importlib.util.spec_from_file_location(
    "fetch_tabular_successor_corpus",
    FETCHER,
)
assert SPECIFICATION is not None and SPECIFICATION.loader is not None
FETCH_MODULE = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(FETCH_MODULE)


class TabularSuccessorCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_fresh_tracks_are_balanced_and_disjoint(self):
        development = self.config["development"]
        validation = self.config["public_validation"]
        self.assertEqual(len(development), 6)
        self.assertEqual(len(validation), 4)
        self.assertEqual(
            [item["track"] for item in development].count("record_table"), 3
        )
        self.assertEqual(
            [item["track"] for item in development].count("dense_feature_matrix"),
            3,
        )
        self.assertEqual(
            [item["track"] for item in validation].count("record_table"), 2
        )
        self.assertEqual(
            [item["track"] for item in validation].count("dense_feature_matrix"),
            2,
        )
        development_ids = {item["dataset_id"] for item in development}
        validation_ids = {item["dataset_id"] for item in validation}
        consumed_ids = {791, 321, 349, 417}
        self.assertTrue(development_ids.isdisjoint(validation_ids))
        self.assertTrue(development_ids.isdisjoint(consumed_ids))
        self.assertTrue(validation_ids.isdisjoint(consumed_ids))

    def test_validation_is_declared_but_unopened(self):
        for item in self.config["public_validation"]:
            self.assertIsNone(item["archive_sha256"])
            self.assertIsNone(item["selected_item_bytes"])
            self.assertIsNone(item["selected_item_sha256"])
            self.assertIsNone(item["source_complete"])
            self.assertEqual(item["page_url"].split("/")[4], str(item["dataset_id"]))
        policy = self.config["archive_integrity_policy"]["public_validation"]
        self.assertIn("Do not acquire", policy)
        self.assertIn("Retain the first", policy)

    def test_development_acquisition_is_fully_pinned(self):
        for item in self.config["development"]:
            self.assertRegex(item["archive_sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(item["selected_item_bytes"], 0)
            self.assertRegex(item["selected_item_sha256"], r"^[0-9a-f]{64}$")
            self.assertIs(item["source_complete"], True)

    def test_track_labels_are_evaluation_only(self):
        routing = self.config["contamination_policy"]["production_routing"]
        allowed = self.config["contamination_policy"]["allowed_use"]
        self.assertIn("evaluation-only", routing)
        self.assertIn("bounded bytes", routing)
        self.assertIn("No consumed bytes", allowed)
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("never production-selector inputs", protocol)
        self.assertIn("space-delimited matrices are not converted to CSV", protocol)

    def test_successor_manifest_preserves_track_and_syntax_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            archive = cache / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("matrix.data", b"1 0 1\n0 1 0\n")
            source = {
                "id": "fixture",
                "family": "fixture_matrix",
                "track": "dense_feature_matrix",
                "title": "Fixture",
                "doi": "10.1234/fixture",
                "page_url": "https://example.test/fixture",
                "archive_url": archive.as_uri(),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "member": "matrix.data",
                "member_compression": "none",
                "delimiter": "space",
                "structure": "fixed-width binary matrix",
            }
            config = {
                "schema_version": 1,
                "name": "fixture",
                "category": "fixture",
                "claim_ceiling": "test only",
                "provider": {
                    "name": "Fixture",
                    "license_spdx": "CC-BY-4.0",
                },
                "contamination_policy": {
                    "production_routing": "evaluation-only labels; bounded bytes"
                },
                "selection": {
                    "max_item_bytes": 1024,
                    "slice_rule": "exact fixture",
                },
                "development": [source],
                "public_validation": [source | {"id": "validation-fixture"}],
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            manifest_path = FETCH_MODULE.build(
                config_path,
                "development",
                root / "output",
                cache,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            item = manifest["items"][0]
            self.assertEqual(item["track"], "dense_feature_matrix")
            self.assertEqual(item["delimiter"], "space")
            self.assertEqual(item["structure"], "fixed-width binary matrix")
            self.assertEqual(manifest["evaluation_tracks"], ["dense_feature_matrix"])


if __name__ == "__main__":
    unittest.main()
