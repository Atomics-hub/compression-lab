import importlib.util
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-jls2-decode-ab.py"


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_decode_ab", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load JLS2 decode A/B benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(mbps: float, family_mbps: float):
    return {
        "aggregate_mbps": mbps,
        "rows": [
            {
                "family": "example",
                "source_bytes": 100,
                "source_sha256": "a" * 64,
                "encoded_bytes": 10,
                "encoded_sha256": "b" * 64,
                "mbps": family_mbps,
            }
        ],
    }


class JLS2DecodeABTests(unittest.TestCase):
    def test_summary_uses_paired_improvements(self):
        module = load_module()
        summary = module.summarize(
            [result(100.0, 80.0), result(200.0, 160.0)],
            [result(120.0, 100.0), result(220.0, 200.0)],
        )
        aggregate = summary["aggregate"]
        self.assertEqual(aggregate["median_baseline_mbps"], 150.0)
        self.assertEqual(aggregate["median_candidate_mbps"], 170.0)
        self.assertAlmostEqual(
            aggregate["median_paired_improvement_percent"], 15.0
        )
        family = summary["families"][0]
        self.assertAlmostEqual(
            family["median_paired_improvement_percent"], 25.0
        )
        self.assertTrue(family["exact"])

    def test_summary_rejects_fixture_drift(self):
        module = load_module()
        candidate = result(120.0, 100.0)
        candidate["rows"][0]["encoded_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "fixture identity mismatch"):
            module.summarize([result(100.0, 80.0)], [candidate])


if __name__ == "__main__":
    unittest.main()
