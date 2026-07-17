from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-jls2-native-decoder.py"


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_native_gate", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load JLS2 native benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial(variant: str, family: str, round_number: int, rate: float):
    source_bytes = 1_000_000
    return {
        "variant": variant,
        "family": family,
        "round": round_number,
        "warmup": False,
        "source_bytes": source_bytes,
        "parent_wall_ns": int(source_bytes / rate * 1_000),
        "parent_mbps": rate,
        "peak_rss_bytes": 100 * 1024 * 1024,
        "exact": True,
    }


class JLS2NativeDecoderBenchmarkTests(unittest.TestCase):
    def test_protocol_is_pinned_to_lazy_product_commit(self) -> None:
        module = load_module()
        self.assertEqual(
            module.BASELINE_COMMIT,
            "604271cbc89a11c739848f68a7739ed523fb9a1b",
        )
        self.assertEqual(module.ROUNDS, 7)
        self.assertEqual(module.TARGET_MBPS, 250.0)

    def test_schedule_covers_every_pair_once_per_round(self) -> None:
        module = load_module()
        families = ["early", "middle", "late"]
        schedule = module.measurement_schedule(families)
        expected = {
            (family, variant) for family in families for variant in module.VARIANTS
        }
        self.assertEqual(len(schedule), 7)
        self.assertTrue(all(set(rows) == expected for rows in schedule))
        self.assertTrue(all(len(rows) == len(expected) for rows in schedule))

    def test_summary_accepts_only_reliable_candidate(self) -> None:
        module = load_module()
        trials = []
        for round_number in range(1, 8):
            for family in ("early", "middle", "late"):
                trials.append(trial("python", family, round_number, 260.0))
                trials.append(trial("native", family, round_number, 310.0))
        summary = module.summarize(trials)
        self.assertTrue(summary["candidate_qualifies_performance"])
        self.assertTrue(all(summary["gates"].values()))

    def test_summary_rejects_one_slow_round(self) -> None:
        module = load_module()
        trials = []
        for round_number in range(1, 8):
            for family in ("early", "middle", "late"):
                trials.append(trial("python", family, round_number, 260.0))
                rate = 200.0 if round_number == 4 else 310.0
                trials.append(trial("native", family, round_number, rate))
        summary = module.summarize(trials)
        self.assertFalse(summary["candidate_qualifies_performance"])
        self.assertFalse(summary["gates"]["all_rounds_at_or_above_250_mbps"])


if __name__ == "__main__":
    unittest.main()
