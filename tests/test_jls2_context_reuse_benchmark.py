from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark-jls2-context-reuse.py"


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_context_reuse", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load context-reuse benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial(variant: str, item_id: str, round_number: int, rate: float, rss: int):
    size = 1_000_000
    return {
        "variant": variant,
        "item_id": item_id,
        "source_bytes": size,
        "wall_ns": int(size / rate * 1000),
        "mbps": rate,
        "peak_rss_bytes": rss,
        "round": round_number,
        "warmup": False,
        "exact": True,
    }


class JLS2ContextReuseBenchmarkTests(unittest.TestCase):
    def test_frozen_constants(self) -> None:
        module = load_module()
        self.assertEqual(module.ROUNDS, 7)
        self.assertEqual(module.STRESS_RECORDS, 21_800)
        self.assertEqual(
            module.BASELINE_COMMIT,
            "7b081f6f11c2561c36289cfc57f7d3715ab8c594",
        )

    def test_stress_generator_is_exact_and_stable(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "stress.jsonl"
            original_records = module.STRESS_RECORDS
            module.STRESS_RECORDS = 2
            try:
                module.build_stress_source(path)
            finally:
                module.STRESS_RECORDS = original_records
            lines = path.read_bytes().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith(b'{"k000":0,"k001":1'))
        self.assertTrue(lines[1].startswith(b'{"k000":1,"k001":2'))
        self.assertTrue(lines[0].endswith(b'"k255":5}'))

    def test_summary_accepts_memory_win_without_speed_regression(self) -> None:
        module = load_module()
        items = ("clue-a", "clue-b", "clue-c", module.STRESS_ID)
        rows = []
        for round_number in range(1, 8):
            for item_id in items:
                rows.append(trial("baseline", item_id, round_number, 300.0, 200))
                candidate_rss = 150 if item_id == module.STRESS_ID else 200
                rows.append(
                    trial("candidate", item_id, round_number, 295.0, candidate_rss)
                )
        summary = module.summarize(rows, 7)
        self.assertTrue(summary["passed"])

    def test_summary_rejects_unproven_memory_hypothesis(self) -> None:
        module = load_module()
        items = ("clue-a", "clue-b", "clue-c", module.STRESS_ID)
        rows = []
        for round_number in range(1, 8):
            for item_id in items:
                rows.append(trial("baseline", item_id, round_number, 300.0, 200))
                rows.append(trial("candidate", item_id, round_number, 300.0, 190))
        summary = module.summarize(rows, 7)
        self.assertFalse(summary["passed"])
        self.assertFalse(
            summary["gates"]["stress_peak_rss_reduction_at_least_20_percent"]
        )


if __name__ == "__main__":
    unittest.main()
