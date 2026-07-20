from __future__ import annotations

import json
from pathlib import Path
import random
import runpy
import unittest


ROOT = Path(__file__).resolve().parents[1]
CODEC = runpy.run_path(str(ROOT / "scripts/source-python-gdb1-synthetic-codec.py"))
VERIFY = runpy.run_path(str(ROOT / "scripts/verify-source-python-gdb1-checkpoint.py"))


class SourcePythonGdb1CheckpointTests(unittest.TestCase):
    def test_checkpoint_is_frozen_incomplete_and_measurement_locked(self) -> None:
        result = VERIFY["verify"]()
        self.assertTrue(result["verified"])
        self.assertFalse(result["measurement_authorized"])
        self.assertEqual(len(result["pending_linux_baselines"]), 3)
        self.assertEqual(result["cmix_complete_decoder_distribution_bytes"], 10_338_103)

    def test_range_coder_deterministic_roundtrip_and_corruption(self) -> None:
        rng = random.Random(20260720)
        for size in list(range(64)) + [255, 4096, 20_000]:
            raw = bytes(rng.randrange(256) for _ in range(size))
            coded = CODEC["range_encode"](raw)
            self.assertEqual(coded, CODEC["range_encode"](raw))
            self.assertEqual(CODEC["range_decode"](coded, size), raw)
        with self.assertRaises(ValueError):
            CODEC["range_decode"](b"bad", 4)

    def test_all_arms_roundtrip_and_a2_uses_scope_events(self) -> None:
        data = b"x=1\ndef f(y):\n    return x+y\nprint(f(x))\n"
        files = [("scope.py", 0o644, data)]
        for arm in ("a0-token-trivia-range", "a1-flat-identifiers"):
            first = CODEC["encode"](files, arm)
            self.assertEqual(first, CODEC["encode"](files, arm))
            self.assertEqual(CODEC["decode"](first), files)
        scope = CODEC["ScopeUse"]
        plan = [
            scope(1, 0, True),
            scope(1, 0, True),
            scope(2, 1, True),
            scope(2, 1, False),
            scope(2, 1, False),
            scope(1, 0, False, True),
            scope(1, 0, False),
            scope(1, 0, False),
        ]
        archive = CODEC["encode"](files, "a2-scope-bindings", {"scope.py": plan})
        header_size = int.from_bytes(archive[7:11], "big")
        header = json.loads(archive[11 : 11 + header_size])
        self.assertEqual(header["files"][0]["mode"], "tokenized")
        self.assertGreater(header["files"][0]["identifier_count"], 0)
        self.assertEqual(CODEC["decode"](archive), files)

    def test_fallback_and_archive_tampering_fail_closed(self) -> None:
        files = [("broken.py", 0o600, b"'''unterminated\n")]
        archive = CODEC["encode"](files, "a2-scope-bindings")
        self.assertEqual(CODEC["decode"](archive), files)
        mutated = bytearray(archive)
        mutated[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "hash differs"):
            CODEC["decode"](bytes(mutated))
        with self.assertRaises(ValueError):
            CODEC["encode"]([(b"../escape".decode(), 0o644, b"x\n")], "a0-token-trivia-range")

    def test_derived_slots_and_unfinished_baselines_cannot_authorize_g0(self) -> None:
        corpus = json.loads(
            (ROOT / "config/source-python-gdb1-derived-corpus-contract-v1.json").read_bytes()
        )
        baselines = json.loads(
            (ROOT / "config/source-python-gdb1-baseline-distributions-v1.json").read_bytes()
        )
        self.assertTrue(all(value is None for value in corpus["sealed_outputs"].values()))
        self.assertFalse(corpus["measurement_authorized"])
        self.assertFalse(baselines["measurement_authorized"])
        self.assertIn("incomplete", baselines["accounting"]["status"])


if __name__ == "__main__":
    unittest.main()
