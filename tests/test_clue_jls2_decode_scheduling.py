from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-clue-jls2-decode-scheduling.py"


def load_module():
    spec = importlib.util.spec_from_file_location("clue_jls2_scheduling", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load CLUE JLS2 scheduling benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial(variant: str, family: str, round_number: int, mbps: float) -> dict:
    source_bytes = 1_000_000
    return {
        "variant": variant,
        "family": family,
        "round": round_number,
        "warmup": False,
        "source_bytes": source_bytes,
        "parent_wall_ns": int(source_bytes / mbps * 1_000),
        "parent_mbps": mbps,
        "encoded_bytes": 10,
        "encoded_sha256": "a" * 64,
        "peak_rss_bytes": 100 * 1024 * 1024,
        "exact": True,
    }


class ClueJls2DecodeSchedulingTests(unittest.TestCase):
    def test_schedule_covers_every_pair_once_per_round(self) -> None:
        module = load_module()
        variants = list(module.VARIANTS)
        families = ["early", "middle", "late"]
        schedule = module.measurement_schedule(variants, families, 7)
        expected = {(family, variant) for family in families for variant in variants}
        self.assertEqual(len(schedule), 7)
        self.assertTrue(all(set(round_pairs) == expected for round_pairs in schedule))
        self.assertTrue(
            all(len(round_pairs) == len(expected) for round_pairs in schedule)
        )

    def test_summary_selects_reliable_improved_variant(self) -> None:
        module = load_module()
        variants = list(module.VARIANTS)
        trials = []
        rates = {
            module.BASELINE: 260.0,
            "outer1-innerauto": 240.0,
            "outer2-inner1": 330.0,
            "outer2-inner2": 310.0,
        }
        for round_number in range(1, 8):
            for family in ("early", "middle", "late"):
                for variant in variants:
                    trials.append(trial(variant, family, round_number, rates[variant]))
        summary = module.summarize(trials, variants, 7)
        self.assertEqual(summary["selected_variant"], "outer2-inner1")
        selected = next(
            row for row in summary["variants"] if row["variant"] == "outer2-inner1"
        )
        self.assertTrue(selected["qualifies"])
        self.assertTrue(all(selected["selection_gates"].values()))


if __name__ == "__main__":
    unittest.main()
