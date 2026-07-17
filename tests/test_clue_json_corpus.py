import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "fetch-clue-json-corpus.py"
RECEIPT = REPOSITORY / "runs" / "clue-json-log-development-acquisition-v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_clue_json_corpus", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load CLUE corpus fetcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(root: Path, member: str = "clue.json"):
    data = b"".join(
        json.dumps({"id": identifier, "type": "fixture"}).encode() + b"\n"
        for identifier in range(1, 7)
    )
    archive = root / "clue.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(member, data)
    return archive


def config_for(archive: Path):
    return {
        "schema_version": 1,
        "name": "fixture-clue",
        "category": "structured_cloud_event_logs",
        "claim_ceiling": "fixture only",
        "provider": {
            "license_spdx": "CC-BY-4.0",
            "doi": "10.0000/fixture",
            "record_url": "https://example.test/fixture",
        },
        "archive": {
            "filename": "clue.zip",
            "url": archive.as_uri(),
            "size_bytes": archive.stat().st_size,
            "publisher_digest_algorithm": "md5",
            "publisher_digest": hashlib.md5(archive.read_bytes()).hexdigest(),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "member": "clue.json",
        },
        "selection": {
            "rule": "fixture rule",
            "expected_id_equals_line_number": True,
            "development": [
                {
                    "id": "early",
                    "family": "early",
                    "first_record_id": 1,
                    "last_record_id": 2,
                },
                {
                    "id": "late",
                    "family": "late",
                    "first_record_id": 5,
                    "last_record_id": 6,
                },
            ],
            "public_validation": [
                {
                    "id": "validation",
                    "family": "validation",
                    "first_record_id": 3,
                    "last_record_id": 4,
                }
            ],
        },
    }


def frozen_ranges(config: dict):
    selection = config["selection"]
    return selection["development"] + selection["public_validation"]


class ClueJsonCorpusTests(unittest.TestCase):
    def test_frozen_protocol_identity_ranges_and_seal(self):
        config = json.loads(
            (REPOSITORY / "config" / "clue-json-log-corpus-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["provider"]["license_spdx"], "CC-BY-4.0")
        self.assertEqual(config["provider"]["doi"], "10.5281/zenodo.7119953")
        self.assertEqual(config["archive"]["size_bytes"], 635_105_552)
        self.assertEqual(
            config["archive"]["publisher_digest"],
            "9e318370f96b68077667e9cdc05f26a5",
        )
        self.assertEqual(
            config["archive"]["sha256"],
            "0c9eadb104acf1da6de738ba9babe957c83cd8602a01fa6d846a6ea4a6611d96",
        )
        self.assertEqual(
            [
                row["last_record_id"] - row["first_record_id"] + 1
                for row in frozen_ranges(config)
            ],
            [250_000] * 5,
        )
        ordered = sorted(frozen_ranges(config), key=lambda row: row["first_record_id"])
        self.assertTrue(
            all(
                left["last_record_id"] < right["first_record_id"]
                for left, right in zip(ordered, ordered[1:])
            )
        )
        for row in config["selection"]["development"]:
            self.assertGreater(row["size_bytes"], 0)
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
        for row in config["selection"]["public_validation"]:
            self.assertIsNone(row["size_bytes"])
            self.assertIsNone(row["sha256"])

    def test_acquisition_receipt_matches_machine_enforced_pins(self):
        config = json.loads(
            (REPOSITORY / "config" / "clue-json-log-corpus-v1.json").read_text(
                encoding="utf-8"
            )
        )
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(receipt["archive"], config["archive"])
        self.assertEqual(receipt["items"], config["selection"]["development"])
        self.assertEqual(receipt["record_count"], 750_000)
        self.assertEqual(receipt["size_bytes"], 203_578_132)
        self.assertFalse(receipt["public_validation_parsed"])

    def test_development_ranges_are_exact_and_byte_preserving(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_fixture(root)
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive)), encoding="utf-8")
            manifest_path = module.build(
                config, "development", root / "output", root / "cache"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual([row["record_count"] for row in manifest["items"]], [2, 2])
            self.assertEqual(
                [row["path"] for row in manifest["items"]],
                ["early.jsonl", "late.jsonl"],
            )
            self.assertTrue(
                all(row["dataset"] == "fixture-clue" for row in manifest["items"])
            )
            self.assertTrue(
                all(
                    row["source_url"] == manifest["provider"]["record_url"]
                    for row in manifest["items"]
                )
            )
            self.assertEqual(
                [
                    json.loads(line)["id"]
                    for line in (root / "output" / "early.jsonl")
                    .read_bytes()
                    .splitlines()
                ],
                [1, 2],
            )
            self.assertEqual(
                [
                    json.loads(line)["id"]
                    for line in (root / "output" / "late.jsonl")
                    .read_bytes()
                    .splitlines()
                ],
                [5, 6],
            )

    def test_incomplete_range_removes_temporary_outputs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            source = b'{"id": 1}\n'
            selections = [
                {
                    "id": "incomplete",
                    "family": "incomplete",
                    "first_record_id": 1,
                    "last_record_id": 2,
                }
            ]
            with self.assertRaisesRegex(ValueError, "selected range is incomplete"):
                module.select_ranges(
                    source=io.BytesIO(source),
                    selections=selections,
                    output=output,
                )
            self.assertEqual(list(output.iterdir()), [])

    def test_pinned_range_mismatch_removes_temporary_outputs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            source = b'{"id": 1}\n'
            selections = [
                {
                    "id": "drifted",
                    "family": "drifted",
                    "first_record_id": 1,
                    "last_record_id": 1,
                    "size_bytes": len(source),
                    "sha256": "0" * 64,
                }
            ]
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                module.select_ranges(
                    source=io.BytesIO(source),
                    selections=selections,
                    output=output,
                )
            self.assertEqual(list(output.iterdir()), [])

    def test_validation_refuses_before_creating_cache_or_output(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_fixture(root)
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to acquire"):
                module.build(
                    config,
                    "public-validation",
                    root / "output",
                    root / "cache",
                )
            self.assertFalse((root / "output").exists())
            self.assertFalse((root / "cache").exists())

    def test_archive_roster_and_record_ids_are_validated(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_fixture(root, "../clue.json")
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "archive member roster"):
                module.build(config, "development", root / "output", root / "cache")


if __name__ == "__main__":
    unittest.main()
