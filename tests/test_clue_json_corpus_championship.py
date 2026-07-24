"""Range-refusal and frozen-identity guards for the championship corpus config.

The championship fetcher must refuse any range overlapping any consumed v1 or v2
range AND must mutually refuse the two new championship ranges for any future
acquisition. These tests pin the two frozen ranges, their record counts, and the
disjointness against every declared range across all three corpus configs.
"""

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
SCRIPT = REPOSITORY / "scripts" / "fetch-clue-json-corpus-championship-v1.py"
CORPUS = REPOSITORY / "config" / "clue-json-log-corpus-championship-v1.json"
CORPUS_V1 = REPOSITORY / "config" / "clue-json-log-corpus-v1.json"
CORPUS_V2 = REPOSITORY / "config" / "clue-json-log-corpus-v2.json"

CONSUMED_RANGES = [
    (1, 250_000),
    (10_000_001, 10_250_000),
    (20_000_001, 20_250_000),
    (35_000_001, 35_250_000),
    (45_000_001, 45_250_000),
    (28_000_001, 28_250_000),
    (40_000_001, 40_250_000),
]


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_clue_championship", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load CLUE championship corpus fetcher")
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
        "name": "fixture-clue-championship",
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
                    "id": "fixture-championship",
                    "family": "fixture_championship",
                    "first_record_id": public_first,
                    "last_record_id": public_last,
                }
            ],
        },
    }


class ChampionshipCorpusTests(unittest.TestCase):
    def test_frozen_identity_ranges_and_seal(self):
        config = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(config["provider"]["doi"], "10.5281/zenodo.7119953")
        self.assertEqual(config["archive"]["size_bytes"], 635_105_552)
        sealed = config["selection"]["public_validation"]
        self.assertEqual(
            [row["id"] for row in sealed],
            ["clue-championship-e", "clue-championship-f"],
        )
        self.assertEqual(
            [(row["first_record_id"], row["last_record_id"]) for row in sealed],
            [(15_000_001, 15_250_000), (32_000_001, 32_250_000)],
        )
        self.assertEqual(
            [row["last_record_id"] - row["first_record_id"] + 1 for row in sealed],
            [250_000, 250_000],
        )
        self.assertTrue(all(row["size_bytes"] is None for row in sealed))
        self.assertTrue(all(row["sha256"] is None for row in sealed))

    def test_championship_ranges_are_disjoint_from_all_declared_ranges(self):
        module = load_module()
        declared = module.collect_declared_ranges([CORPUS_V1, CORPUS_V2, CORPUS])
        champ = json.loads(CORPUS.read_text(encoding="utf-8"))["selection"][
            "public_validation"
        ]
        # Must not raise: neither championship range overlaps any declared range,
        # and each is allowed to match only its own id in the championship config.
        module.assert_ranges_available(champ, declared)

    def test_new_ranges_are_disjoint_and_in_distinct_neighborhoods(self):
        # Both ranges must be fully non-overlapping with every consumed range and
        # sit in a distinct temporal neighborhood. championship-e clears 4.75M from
        # every boundary; championship-f clears 2.75M (nearest neighbor is the
        # consumed 35,000,001 range) - the dispatch's ">= 3.7M" prose is corrected
        # in the protocol doc; the ranges stay frozen as dispatched.
        min_gaps = {(15_000_001, 15_250_000): 4_750_001, (32_000_001, 32_250_000): 2_750_001}
        for (first, last), expected_min in min_gaps.items():
            observed_min = None
            for c_first, c_last in CONSUMED_RANGES:
                self.assertFalse(
                    not (last < c_first or c_last < first),
                    f"championship range overlaps consumed {c_first}-{c_last}",
                )
                gap = min(abs(first - c_last), abs(c_first - last))
                observed_min = gap if observed_min is None else min(observed_min, gap)
            self.assertEqual(observed_min, expected_min)
            self.assertGreaterEqual(observed_min, 2_000_000)

    def test_default_declared_configs_include_all_three(self):
        module = load_module()
        names = {path.name for path in module.DECLARED_RANGE_CONFIGS}
        self.assertEqual(
            names,
            {
                "clue-json-log-corpus-v1.json",
                "clue-json-log-corpus-v2.json",
                "clue-json-log-corpus-championship-v1.json",
            },
        )

    def test_overlap_with_a_consumed_v2_range_is_refused(self):
        module = load_module()
        declared = module.collect_declared_ranges([CORPUS_V1, CORPUS_V2, CORPUS])
        colliding = [
            {
                "id": "colliding",
                "family": "colliding",
                "first_record_id": 40_100_000,
                "last_record_id": 40_200_000,
            }
        ]
        with self.assertRaisesRegex(ValueError, "overlaps already-declared"):
            module.assert_ranges_available(colliding, declared)

    def test_championship_e_refuses_overlap_with_f(self):
        module = load_module()
        declared = module.collect_declared_ranges([CORPUS])
        colliding = [
            {
                "id": "would-collide-with-f",
                "family": "x",
                "first_record_id": 32_100_000,
                "last_record_id": 32_150_000,
            }
        ]
        with self.assertRaisesRegex(ValueError, "overlaps already-declared"):
            module.assert_ranges_available(colliding, declared)

    def test_public_validation_refuses_overlap_before_lock_or_io(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = write_fixture(root)
            config = root / "config.json"
            config.write_text(
                json.dumps(config_for(archive, 15_000_001, 15_000_002)),
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
                    declared_range_configs=(CORPUS,),
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
