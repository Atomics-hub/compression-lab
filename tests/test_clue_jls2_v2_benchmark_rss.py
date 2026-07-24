from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "scripts" / "benchmark-clue-jls2-public-validation-v2.py"

spec = importlib.util.spec_from_file_location("benchmark_clue_v2_rss", BENCHMARK)
assert spec is not None and spec.loader is not None
BENCH = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BENCH)

REQUIREMENTS = {
    "maximum_shim_floor_bytes": 64 * 1024 * 1024,
    "maximum_shim_fraction_of_maxrss": 0.25,
}

HUNGRY_CHILD = (
    "data = bytearray(200 * 1024 * 1024)\n"
    "data[::4096] = b'x' * len(data[::4096])\n"
    "print(len(data))\n"
)


class ShimFloorEligibilityTests(unittest.TestCase):
    def test_eligible_when_floor_small_and_fraction_low(self) -> None:
        report = {
            "maxrss_bytes": 200 * 1024 * 1024,
            "shim_maxrss_bytes": 8 * 1024 * 1024,
        }
        self.assertTrue(BENCH.shim_floor_eligible(report, REQUIREMENTS))

    def test_ineligible_when_floor_exceeds_64_mib(self) -> None:
        report = {
            "maxrss_bytes": 4096 * 1024 * 1024,
            "shim_maxrss_bytes": 65 * 1024 * 1024,
        }
        self.assertFalse(BENCH.shim_floor_eligible(report, REQUIREMENTS))

    def test_ineligible_when_floor_exceeds_quarter_of_reading(self) -> None:
        # 40 MiB floor is under 64 MiB but is 40% of a 100 MiB reading.
        report = {
            "maxrss_bytes": 100 * 1024 * 1024,
            "shim_maxrss_bytes": 40 * 1024 * 1024,
        }
        self.assertFalse(BENCH.shim_floor_eligible(report, REQUIREMENTS))

    def test_boundary_at_exactly_a_quarter_is_eligible(self) -> None:
        report = {
            "maxrss_bytes": 100 * 1024 * 1024,
            "shim_maxrss_bytes": 25 * 1024 * 1024,
        }
        self.assertTrue(BENCH.shim_floor_eligible(report, REQUIREMENTS))

    def test_boundary_at_exactly_64_mib_floor_is_eligible(self) -> None:
        report = {
            "maxrss_bytes": 4096 * 1024 * 1024,
            "shim_maxrss_bytes": 64 * 1024 * 1024,
        }
        self.assertTrue(BENCH.shim_floor_eligible(report, REQUIREMENTS))

    def test_zero_reading_is_ineligible(self) -> None:
        report = {"maxrss_bytes": 0, "shim_maxrss_bytes": 0}
        self.assertFalse(BENCH.shim_floor_eligible(report, REQUIREMENTS))


class RequireEligibleTests(unittest.TestCase):
    def test_require_eligible_voids_ineligible_reading(self) -> None:
        report = {
            "maxrss_bytes": 100 * 1024 * 1024,
            "shim_maxrss_bytes": 90 * 1024 * 1024,
        }
        with self.assertRaisesRegex(ValueError, "voids the attempt"):
            BENCH.require_eligible(report, REQUIREMENTS, "decode:test")

    def test_require_eligible_accepts_eligible_reading(self) -> None:
        report = {
            "maxrss_bytes": 200 * 1024 * 1024,
            "shim_maxrss_bytes": 8 * 1024 * 1024,
        }
        BENCH.require_eligible(report, REQUIREMENTS, "decode:test")


@unittest.skipUnless(hasattr(os, "wait4"), "requires os.wait4")
class CleanChildWiringTests(unittest.TestCase):
    def test_clean_child_measure_reads_a_hungry_child(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report_path = Path(raw) / "clean-rss.json"
            report, returncode, _stdout, _stderr = BENCH.clean_child_measure(
                [sys.executable, "-S", "-E", "-c", HUNGRY_CHILD], report_path
            )
            self.assertEqual(returncode, 0)
            self.assertEqual(int(report["exit_code"]), 0)
            self.assertGreater(int(report["maxrss_bytes"]), 150 * 1024 * 1024)
            self.assertIn("shim_maxrss_bytes", report)
            self.assertGreater(int(report["wall_ns"]), 0)

    def test_clean_child_measure_refuses_to_overwrite_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report_path = Path(raw) / "clean-rss.json"
            report_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                BENCH.clean_child_measure([sys.executable, "-c", "pass"], report_path)

    def test_measure_clean_rss_is_the_pinned_instrument(self) -> None:
        # The benchmark wires candidate resource rows through the frozen instrument.
        self.assertEqual(BENCH.MEASURE_CLEAN_RSS.name, "measure-clean-rss.py")
        self.assertTrue(BENCH.MEASURE_CLEAN_RSS.is_file())


if __name__ == "__main__":
    unittest.main()
