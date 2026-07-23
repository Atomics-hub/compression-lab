from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "fetch-clue-json-corpus-v2.py"
CORPUS = REPOSITORY / "config" / "clue-json-log-corpus-v2.json"
CORPUS_V1 = REPOSITORY / "config" / "clue-json-log-corpus-v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_clue_json_corpus_v2", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load CLUE v2 corpus fetcher")
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


def config_for(archive: Path, public_first: int = 3, public_last: int = 4):
    return {
        "schema_version": 1,
        "name": "fixture-clue-v2",
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
            "development": [],
            "public_validation": [
                {
                    "id": "fixture-validation-v2",
                    "family": "fixture_validation_v2",
                    "first_record_id": public_first,
                    "last_record_id": public_last,
                }
            ],
        },
    }


class ClueJsonCorpusV2Tests(unittest.TestCase):
    def test_frozen_protocol_identity_ranges_and_seal(self):
        config = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(config["provider"]["license_spdx"], "CC-BY-4.0")
        self.assertEqual(config["provider"]["doi"], "10.5281/zenodo.7119953")
        self.assertEqual(config["archive"]["size_bytes"], 635_105_552)
        sealed = config["selection"]["public_validation"]
        self.assertEqual(
            [row["id"] for row in sealed],
            ["clue-validation-v2-c", "clue-validation-v2-d"],
        )
        self.assertEqual(
            [row["last_record_id"] - row["first_record_id"] + 1 for row in sealed],
            [250_000, 250_000],
        )
        self.assertTrue(all(row["size_bytes"] is None for row in sealed))
        self.assertTrue(all(row["sha256"] is None for row in sealed))

    def test_v2_ranges_are_disjoint_from_all_declared_ranges(self):
        module = load_module()
        declared = module.collect_declared_ranges([CORPUS_V1, CORPUS])
        v2 = json.loads(CORPUS.read_text(encoding="utf-8"))["selection"][
            "public_validation"
        ]
        # Must not raise: the two v2 ranges do not overlap any declared range.
        module.assert_ranges_available(v2, declared)

    def test_overlap_with_a_declared_range_is_refused(self):
        module = load_module()
        declared = module.collect_declared_ranges([CORPUS_V1, CORPUS])
        # A range that collides with the consumed v1 clue-validation-a window.
        colliding = [
            {
                "id": "colliding",
                "family": "colliding",
                "first_record_id": 35_100_000,
                "last_record_id": 35_200_000,
            }
        ]
        with self.assertRaisesRegex(ValueError, "overlaps already-declared"):
            module.assert_ranges_available(colliding, declared)

    def test_public_validation_refuses_overlap_before_lock_or_io(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_fixture(root)
            # A fixture whose declared v2 window collides with v1's 45,000,001 range.
            config = root / "config.json"
            config.write_text(
                json.dumps(config_for(archive, 45_000_001, 45_000_002)),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "overlaps already-declared"):
                module.build(
                    config,
                    "public-validation",
                    root / "output",
                    root / "cache",
                    allow_public_validation=True,
                    validation_lock=root / "missing-lock.json",
                    declared_range_configs=(CORPUS_V1,),
                )
            self.assertFalse((root / "output").exists())
            self.assertFalse((root / "cache").exists())

    def test_public_validation_refuses_without_final_lock(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_fixture(root)
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "valid final readiness lock"):
                module.build(
                    config,
                    "public-validation",
                    root / "output",
                    root / "cache",
                    allow_public_validation=True,
                    validation_lock=root / "missing-lock.json",
                    declared_range_configs=(),
                )
            self.assertFalse((root / "output").exists())
            self.assertFalse((root / "cache").exists())

    def test_public_validation_requires_allow_flag(self):
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
                    declared_range_configs=(),
                )
            self.assertFalse((root / "output").exists())

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


if __name__ == "__main__":
    unittest.main()
