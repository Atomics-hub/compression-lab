#!/usr/bin/env python3
"""Unit tests for the off-ledger moonshot synthetic precheck."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "moon-synthetic-precheck.py"
SPEC = importlib.util.spec_from_file_location("moon_synthetic_precheck", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load synthetic precheck")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SyntheticPrecheckTests(unittest.TestCase):
    def test_generator_is_exact_deterministic_and_regime_varying(self) -> None:
        first = MODULE.generate(8192, MODULE.DEFAULT_SEED)
        second = MODULE.generate(8192, MODULE.DEFAULT_SEED)
        self.assertEqual(len(first), 8192)
        self.assertEqual(first, second)
        self.assertNotEqual(first[:2048], first[-2048:])
        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            "ffd0804f1f8c32cb626c68c107f6b4e1201213f4e588bbe631748d9c418da623",
        )

    def test_default_item_is_exactly_four_mib_and_digest_is_pinned(self) -> None:
        source = MODULE.generate()
        self.assertEqual(len(source), 4 * 1024 * 1024)
        self.assertEqual(
            hashlib.sha256(source).hexdigest(),
            "842e4e8759cc0f453f03e8a3f640c1053c0cafe92e4b45491c6d3768f68275ed",
        )

    def test_archived_precheck_binds_the_kernel_receipt(self) -> None:
        evidence = REPOSITORY / "runs" / "moon-cycle2-c3-synthetic-precheck-v1"
        precheck = json.loads((evidence / "precheck-receipt.json").read_text())
        kernel_bytes = (evidence / "kernel-receipt.json").read_bytes()
        clean_bytes = (evidence / "clean-rss.json").read_bytes()
        clean = json.loads(clean_bytes)
        self.assertEqual(
            hashlib.sha256(kernel_bytes).hexdigest(),
            precheck["kernel_receipt_sha256"],
        )
        self.assertTrue(precheck["throughput_gate_passed"])
        self.assertTrue(precheck["decode_matches_source"])
        self.assertEqual(
            hashlib.sha256(clean_bytes).hexdigest(),
            precheck["clean_rss_receipt_sha256"],
        )
        self.assertEqual(precheck["wall_ns"], clean["wall_ns"])
        self.assertEqual(precheck["peak_rss_bytes"], clean["maxrss_bytes"])
        self.assertEqual(
            precheck["rss_shim_floor_bytes"], clean["shim_maxrss_bytes"]
        )
        self.assertEqual(len(precheck["kernel_binary_sha256"]), 64)
        self.assertLessEqual(
            precheck["projected_public_wall_ns"], precheck["margin_ceiling_ns"]
        )


if __name__ == "__main__":
    unittest.main()
