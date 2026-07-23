"""Tests for the clean child peak-RSS instrument.

The load-bearing regression: a trivial child measured from a deliberately
large parent must read small. The old instrument (wait4 directly from the
large parent) reads the parent's footprint instead - the artifact proven in
docs/benchmarks/2026-07-23-jls2-rss-instrument-diagnostic.md.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure-clean-rss.py"

specification = importlib.util.spec_from_file_location("measure_clean_rss", SCRIPT)
assert specification is not None and specification.loader is not None
measure_clean_rss = importlib.util.module_from_spec(specification)
specification.loader.exec_module(measure_clean_rss)

HUNGRY_CHILD = (
    "data = bytearray(200 * 1024 * 1024)\n"
    "data[::4096] = b'x' * len(data[::4096])\n"
    "print(len(data))\n"
)


@unittest.skipUnless(hasattr(os, "wait4"), "requires os.wait4")
class CleanRssMeasurementTest(unittest.TestCase):
    def measure(self, command: list[str]) -> dict:
        with tempfile.TemporaryDirectory() as work:
            report_path = Path(work) / "report.json"
            exit_code = measure_clean_rss.measure(command, report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        report["measured_exit_code"] = exit_code
        return report

    def test_reads_a_memory_hungry_child_accurately(self) -> None:
        report = self.measure([sys.executable, "-S", "-E", "-c", HUNGRY_CHILD])
        self.assertEqual(report["exit_code"], 0)
        self.assertGreater(report["maxrss_bytes"], 180 * 1024 * 1024)
        self.assertLess(report["maxrss_bytes"], 500 * 1024 * 1024)

    def test_trivial_child_from_large_parent_reads_small(self) -> None:
        ballast = bytearray(300 * 1024 * 1024)
        ballast[::4096] = b"x" * len(ballast[::4096])
        try:
            report = self.measure([sys.executable, "-S", "-E", "-c", "print('ok')"])
        finally:
            del ballast
        self.assertEqual(report["exit_code"], 0)
        self.assertLess(report["maxrss_bytes"], 100 * 1024 * 1024)
        self.assertLess(report["shim_maxrss_bytes"], 100 * 1024 * 1024)

    @unittest.skipUnless(sys.platform == "linux", "fork-inheritance is Linux-specific")
    def test_old_instrument_reads_the_parent_footprint(self) -> None:
        ballast = bytearray(300 * 1024 * 1024)
        ballast[::4096] = b"x" * len(ballast[::4096])
        try:
            process = subprocess.Popen(
                [sys.executable, "-S", "-E", "-c", "print('ok')"],
                stdout=subprocess.DEVNULL,
            )
            _, _, usage = os.wait4(process.pid, 0)
        finally:
            del ballast
        self.assertGreater(usage.ru_maxrss * 1024, 200 * 1024 * 1024)

    def test_exit_code_and_report_fields_pass_through(self) -> None:
        report = self.measure([sys.executable, "-S", "-E", "-c", "raise SystemExit(7)"])
        self.assertEqual(report["exit_code"], 7)
        self.assertEqual(report["measured_exit_code"], 7)
        self.assertEqual(report["schema"], "clean-rss-measurement-v1")
        self.assertEqual(report["platform"], sys.platform)
        for field in ("maxrss_raw", "maxrss_bytes", "shim_maxrss_bytes", "wall_ns"):
            self.assertIn(field, report)


if __name__ == "__main__":
    unittest.main()
