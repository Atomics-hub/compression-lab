#!/usr/bin/env python3
"""Tests for the moonshot cycle-1 prescreen sweep runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest

REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "moon-prescreen-runner.py"
SPEC = importlib.util.spec_from_file_location("moon_prescreen_runner", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load the moon prescreen runner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

STUB_KERNEL = textwrap.dedent(
    """
    import json
    import sys

    args = sys.argv[1:]

    def value(flag):
        return args[args.index(flag) + 1]

    with open(value("--tape-out"), "wb") as handle:
        handle.write(b"stub-tape-bytes")
    receipt = {
        "schema": "clab-moon-kernel-encode-receipt-v1",
        "evidence_stage": "development_only_prescreen",
        "arm": value("--arm"),
        "item_projection": {"complete_bytes": 1234},
        "declared_model_state_bytes": 119947264,
        "decode_matches_source": True,
        "predicted_kill_criterion": "stub",
    }
    with open(value("--receipt-out"), "w") as handle:
        json.dump(receipt, handle)
    """
)


class Fixture:
    """A complete, internally consistent runner fixture on disk."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.corpus = root / "synthetic-highdup.ndjson"
        corpus_bytes = b'{"a":1}\n{"a":1}\n{"a":2}\n'
        self.corpus.write_bytes(corpus_bytes)
        self.corpus_sha = hashlib.sha256(corpus_bytes).hexdigest()
        self.corpus_len = len(corpus_bytes)

        self.stub = root / "stub_kernel.py"
        self.stub.write_text(STUB_KERNEL, encoding="utf-8")

        self.references_path = root / "local-references.json"
        self.references_path.write_text(json.dumps(self.references()), encoding="utf-8")
        self.output_dir = root / "out"
        self.budget_state = root / "budget.json"

    def references(self) -> dict:
        return {
            "schema": "moon-local-references-v1",
            "kanzi": {
                "path": "/opt/kanzi",
                "sha256": "k" * 64,
                "version": "kanzi 2.3",
                "args": ["-c", "-l", "5"],
            },
            "zpaq": {
                "path": "/opt/zpaq",
                "sha256": "z" * 64,
                "version": "zpaq 7.15",
                "args": ["-m5", "-B16"],
            },
            "snapshots": {
                "synthetic-highdup": {
                    "source_bytes": self.corpus_len,
                    "source_sha256": self.corpus_sha,
                    "kanzi_max_bytes": 2000,
                    "kanzi_seconds": 0.1,
                    "zpaq_m54_bytes": 1500,
                    "zpaq_seconds": 0.2,
                }
            },
        }

    def config(self, **overrides: object) -> dict:
        base = {
            "schema": "moon-prescreen-runner-config-v1",
            "kernel_command": [sys.executable, str(self.stub)],
            "references": str(self.references_path),
            "budget_state": str(self.budget_state),
            "output_dir": str(self.output_dir),
            "arms": ["h1-floor"],
            "snapshots": [
                {
                    "name": "synthetic-highdup",
                    "path": str(self.corpus),
                    "sha256": self.corpus_sha,
                    "item_index": 0,
                }
            ],
        }
        base.update(overrides)
        return base

    def write_config(self, **overrides: object) -> Path:
        path = self.root / "config.json"
        path.write_text(json.dumps(self.config(**overrides)), encoding="utf-8")
        return path

    def loaded(self, **overrides: object):
        config = MODULE.Config(self.write_config(**overrides))
        references = MODULE.References(config.references_path)
        verified = MODULE.verify_snapshots(config, references)
        return config, references, verified


class PrescreenRunnerTests(unittest.TestCase):
    def make_root(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="moon-prescreen-runner-test-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    @unittest.skipUnless(
        hasattr(os, "wait4"),
        "the clean-RSS instrument requires POSIX os.wait4",
    )
    def test_end_to_end_run_records_the_full_metric_tuple(self) -> None:
        fixture = Fixture(self.make_root())
        summary = MODULE.run(fixture.write_config())
        self.assertEqual(summary["schema"], "moon-prescreen-sweep-v1")
        self.assertEqual(summary["budget"]["consumed_after"], 1)
        self.assertEqual(len(summary["runs"]), 1)
        self.assertEqual(summary["runs"][0]["status"], "measured")

        receipt = json.loads(Path(summary["runs"][0]["receipt_path"]).read_text())
        for key in (
            "schema",
            "evidence_stage",
            "snapshot",
            "arm",
            "run_index",
            "status",
            "kill_reason",
            "projected_complete_bytes",
            "ratio_vs_local_kanzi",
            "ratio_vs_local_zpaq16",
            "peak_rss_bytes",
            "rss_shim_floor_bytes",
            "wall_seconds",
            "decode_matches",
            "declared_model_state_bytes",
            "predicted_kill_criterion",
            "references",
        ):
            self.assertIn(key, receipt, f"missing receipt key {key}")
        self.assertEqual(receipt["evidence_stage"], "development_only_prescreen")
        self.assertEqual(receipt["projected_complete_bytes"], 1234)
        self.assertAlmostEqual(receipt["ratio_vs_local_kanzi"], 1234 / 2000)
        self.assertAlmostEqual(receipt["ratio_vs_local_zpaq16"], 1234 / 1500)
        self.assertTrue(receipt["decode_matches"])
        self.assertEqual(receipt["declared_model_state_bytes"], 119947264)
        self.assertEqual(
            receipt["predicted_kill_criterion"], MODULE.KILL_LINES["h1-floor"]
        )
        # Reference-binary pins copied into the receipt (helm tightening #1).
        self.assertEqual(receipt["references"]["zpaq"]["args"], ["-m5", "-B16"])
        self.assertEqual(receipt["references"]["zpaq"]["m54_bytes"], 1500)
        # Budget persisted.
        self.assertEqual(
            json.loads(fixture.budget_state.read_text())["runs_consumed"], 1
        )

    def test_snapshot_sha_mismatch_is_refused(self) -> None:
        fixture = Fixture(self.make_root())
        config_path = fixture.write_config(
            snapshots=[
                {
                    "name": "synthetic-highdup",
                    "path": str(fixture.corpus),
                    "sha256": "0" * 64,
                    "item_index": 0,
                }
            ]
        )
        with self.assertRaises(SystemExit) as caught:
            MODULE.run(config_path)
        self.assertIn("mismatch", str(caught.exception))

    def test_unknown_arm_is_refused(self) -> None:
        fixture = Fixture(self.make_root())
        with self.assertRaises(SystemExit) as caught:
            MODULE.Config(fixture.write_config(arms=["not-an-arm"]))
        self.assertIn("unknown arm", str(caught.exception))

    def test_budget_cap_refuses_when_exhausted(self) -> None:
        fixture = Fixture(self.make_root())
        MODULE.write_budget(fixture.budget_state, MODULE.RUN_BUDGET_CAP)
        config, references, verified = fixture.loaded()
        with self.assertRaises(SystemExit) as caught:
            MODULE.sweep(config, references, verified)
        self.assertIn("budget exhausted", str(caught.exception))

    def test_over_budget_rss_is_recorded_and_the_sweep_continues(self) -> None:
        fixture = Fixture(self.make_root())
        config, references, verified = fixture.loaded()

        def fake_execute(_config, _snapshot, _arm, _tape, _receipt, _rss):
            report = {
                "maxrss_bytes": 600 * 1024 * 1024,
                "shim_maxrss_bytes": 5 * 1024 * 1024,
                "wall_ns": 1_000_000,
                "exit_code": 0,
                "timed_out": False,
            }
            kernel_receipt = {
                "item_projection": {"complete_bytes": 1234},
                "declared_model_state_bytes": 119947264,
                "decode_matches_source": True,
            }
            return report, kernel_receipt

        summary = MODULE.sweep(config, references, verified, execute=fake_execute)
        self.assertEqual(summary["runs"][0]["status"], "killed_by_budget")
        receipt = json.loads(Path(summary["runs"][0]["receipt_path"]).read_text())
        self.assertEqual(receipt["kill_reason"], "peak_rss_over_512_mib")
        # Partial data is still present (record-and-kill, not crash).
        self.assertEqual(receipt["projected_complete_bytes"], 1234)
        self.assertEqual(receipt["peak_rss_bytes"], 600 * 1024 * 1024)
        # The budget still counted the run.
        self.assertEqual(summary["budget"]["consumed_after"], 1)

    def test_encode_failure_is_recorded_without_crashing(self) -> None:
        fixture = Fixture(self.make_root())
        config, references, verified = fixture.loaded()

        def fake_execute(_config, _snapshot, _arm, _tape, _receipt, _rss):
            report = {
                "maxrss_bytes": None,
                "shim_maxrss_bytes": None,
                "wall_ns": 5_000,
                "exit_code": 1,
                "timed_out": False,
            }
            return report, None

        summary = MODULE.sweep(config, references, verified, execute=fake_execute)
        receipt = json.loads(Path(summary["runs"][0]["receipt_path"]).read_text())
        self.assertEqual(receipt["status"], "encode_failed")
        self.assertIsNone(receipt["projected_complete_bytes"])
        self.assertIsNone(receipt["ratio_vs_local_zpaq16"])
        # The kill line is still echoed even when the encode failed.
        self.assertEqual(
            receipt["predicted_kill_criterion"], MODULE.KILL_LINES["h1-floor"]
        )

    def test_classify_run_covers_the_budget_triggers(self) -> None:
        ok = MODULE.classify_run(
            {"exit_code": 0, "wall_ns": 1_000, "maxrss_bytes": 1_000}, {"x": 1}
        )
        self.assertEqual(ok, ("measured", None))
        timeout = MODULE.classify_run({"timed_out": True}, None)
        self.assertEqual(timeout, ("killed_by_budget", "wall_timeout"))
        slow = MODULE.classify_run(
            {"exit_code": 0, "wall_ns": 700 * 1_000_000_000, "maxrss_bytes": 1},
            {"x": 1},
        )
        self.assertEqual(slow, ("killed_by_budget", "wall_over_600_s"))
        failed = MODULE.classify_run({"exit_code": 2}, None)
        self.assertEqual(failed, ("encode_failed", "encode_nonzero_exit"))


if __name__ == "__main__":
    unittest.main()
