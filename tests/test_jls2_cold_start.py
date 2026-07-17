from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-jls2-cold-start.py"


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_cold_start", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load JLS2 cold-start benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial(variant: str, mode: str, family: str, round_number: int, rate: float):
    source_bytes = 1_000_000
    return {
        "variant": variant,
        "mode": mode,
        "family": family,
        "round": round_number,
        "warmup": False,
        "source_bytes": source_bytes,
        "parent_wall_ns": int(source_bytes / rate * 1_000),
        "parent_mbps": rate,
        "encoded_bytes": 10,
        "encoded_sha256": "a" * 64,
        "exact": True,
        "worker": {"peak_rss_bytes": 100 * 1024 * 1024},
    }


class JLS2ColdStartTests(unittest.TestCase):
    def test_schedule_covers_every_pair_once_per_round(self) -> None:
        module = load_module()
        families = ["early", "middle", "late"]
        schedule = module.measurement_schedule(families, 7)
        expected = {
            (family, mode, variant)
            for family in families
            for mode in module.MODES
            for variant in module.VARIANTS
        }
        self.assertEqual(len(schedule), 7)
        self.assertTrue(all(set(rows) == expected for rows in schedule))
        self.assertTrue(all(len(rows) == len(expected) for rows in schedule))

    def test_summary_accepts_reliable_candidate(self) -> None:
        module = load_module()
        trials = []
        for round_number in range(1, 8):
            for family in ("early", "middle", "late"):
                for mode in module.MODES:
                    trials.append(
                        trial("baseline", mode, family, round_number, 260.0)
                    )
                    trials.append(
                        trial("candidate", mode, family, round_number, 310.0)
                    )
        result = module.summarize(trials, 7)
        self.assertTrue(result["candidate_qualifies"])
        self.assertTrue(result["gates"]["encoded_identity"])
        self.assertTrue(all(result["gates"]["cli"].values()))
        self.assertTrue(all(result["gates"]["worker"].values()))


if __name__ == "__main__":
    unittest.main()
