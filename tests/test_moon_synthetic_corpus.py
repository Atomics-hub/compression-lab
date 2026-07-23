#!/usr/bin/env python3
"""Tests for the moonshot cycle-1 synthetic NDJSON corpus generator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "moon-synthetic-corpus.py"
SPEC = importlib.util.spec_from_file_location("moon_synthetic_corpus", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load the moon synthetic corpus generator")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MoonSyntheticCorpusTests(unittest.TestCase):
    def generate(
        self, root: Path, name: str, **overrides: object
    ) -> tuple[bytes, dict]:
        args = {
            "seed": 7,
            "records": 200,
            "record_size": 24,
            "key_cardinality": 32,
            "value_cardinality": 64,
            "session_concurrency": 8,
            "duplication_factor": 1.0,
            "timestamp_monotonicity": 1.0,
            "template_count": len(MODULE.TEMPLATES),
        }
        args.update(overrides)
        output = root / f"{name}.ndjson"
        receipt = root / f"{name}.receipt.json"
        argv = [
            "--seed",
            str(args["seed"]),
            "--records",
            str(args["records"]),
            "--record-size",
            str(args["record_size"]),
            "--key-cardinality",
            str(args["key_cardinality"]),
            "--value-cardinality",
            str(args["value_cardinality"]),
            "--session-concurrency",
            str(args["session_concurrency"]),
            "--duplication-factor",
            str(args["duplication_factor"]),
            "--timestamp-monotonicity",
            str(args["timestamp_monotonicity"]),
            "--template-count",
            str(args["template_count"]),
            "--output",
            str(output),
            "--receipt-out",
            str(receipt),
            "--force",
        ]
        self.assertEqual(MODULE.main(argv), 0)
        data = output.read_bytes()
        parsed = json.loads(receipt.read_text())
        return data, parsed

    def test_output_is_deterministic_from_the_seed(self) -> None:
        with self.subTest("same seed"):
            root = Path(self.make_root())
            first, first_receipt = self.generate(root, "a", seed=42)
            second, second_receipt = self.generate(root, "b", seed=42)
            self.assertEqual(first, second)
            self.assertEqual(
                first_receipt["emitted_sha256"], second_receipt["emitted_sha256"]
            )
        with self.subTest("different seed"):
            root = Path(self.make_root())
            first, _ = self.generate(root, "a", seed=1)
            second, _ = self.generate(root, "b", seed=2)
            self.assertNotEqual(first, second)

    def test_receipt_pins_version_seed_params_and_digest(self) -> None:
        root = Path(self.make_root())
        data, receipt = self.generate(root, "c", seed=9, records=150)
        self.assertEqual(receipt["generator_version"], MODULE.GENERATOR_VERSION)
        self.assertEqual(receipt["evidence_stage"], "development_only_prescreen")
        self.assertEqual(receipt["seed"], 9)
        self.assertEqual(receipt["parameters"]["records"], 150)
        self.assertEqual(receipt["emitted_bytes"], len(data))
        self.assertEqual(receipt["emitted_sha256"], hashlib.sha256(data).hexdigest())

    def test_emits_the_requested_record_count_of_valid_ndjson(self) -> None:
        root = Path(self.make_root())
        data, _ = self.generate(root, "d", records=123)
        lines = data.decode("utf-8").splitlines()
        self.assertEqual(len(lines), 123)
        for line in lines:
            record = json.loads(line)
            self.assertIn("event", record)

    def test_duplication_factor_raises_record_repetition(self) -> None:
        root = Path(self.make_root())
        unique, _ = self.generate(root, "u", records=300, duplication_factor=1.0)
        repeated, _ = self.generate(root, "r", records=300, duplication_factor=5.0)
        unique_lines = unique.decode().splitlines()
        repeated_lines = repeated.decode().splitlines()
        self.assertGreater(len(set(unique_lines)), len(set(repeated_lines)))

    def test_template_count_bounds_distinct_shapes(self) -> None:
        root = Path(self.make_root())
        single, _ = self.generate(root, "one", records=200, template_count=1)
        events = {json.loads(line)["event"] for line in single.decode().splitlines()}
        self.assertEqual(len(events), 1)

    def test_full_monotonicity_never_steps_the_timestamp_backward(self) -> None:
        root = Path(self.make_root())
        data, _ = self.generate(root, "mono", records=400, timestamp_monotonicity=1.0)
        stamps = [json.loads(line)["ts"] for line in data.decode().splitlines()]
        self.assertEqual(stamps, sorted(stamps))

    def test_invalid_parameters_fail_closed(self) -> None:
        root = Path(self.make_root())
        with self.assertRaises(ValueError):
            self.generate(root, "bad", duplication_factor=0.5)
        with self.assertRaises(ValueError):
            self.generate(root, "bad2", template_count=999)
        with self.assertRaises(ValueError):
            self.generate(root, "bad3", timestamp_monotonicity=2.0)

    def make_root(self) -> str:
        root = tempfile.mkdtemp(prefix="moon-synthetic-corpus-test-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root


if __name__ == "__main__":
    unittest.main()
