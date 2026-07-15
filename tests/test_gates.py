import unittest

from compresslab.gates import evaluate_candidate


class GateTests(unittest.TestCase):
    def test_frontier_failure_is_visible(self):
        base = {
            "run_id": "run",
            "trials": [
                {"codec_id": "candidate", "roundtrip_ok": True},
            ],
            "summary": [
                {"codec_id": "candidate", "selector_time_percent": 1.0},
                {"codec_id": "baseline", "selector_time_percent": 0.0},
            ],
            "medians": [
                {
                    "item_id": "item",
                    "codec_id": "candidate",
                    "original_bytes": 1000,
                    "compressed_bytes": 900,
                    "total_ms_at_100mbps": 20.0,
                },
                {
                    "item_id": "item",
                    "codec_id": "baseline",
                    "original_bytes": 1000,
                    "compressed_bytes": 500,
                    "total_ms_at_100mbps": 10.0,
                },
            ],
        }
        gates = {
            "requirements": {
                "roundtrip_failures": 0,
                "max_frame_overhead_bytes": 64,
                "max_expansion_percent_plus_frame": 0.5,
                "max_selector_time_percent": 5.0,
                "frontier_tolerance_size_percent": 5.0,
                "frontier_tolerance_total_time_percent": 10.0,
                "target_frontier_coverage_percent": 80.0,
            }
        }
        report = evaluate_candidate(base, gates, "candidate", 100.0)
        self.assertFalse(report["passed"])
        coverage = next(
            check for check in report["checks"] if check["name"] == "frontier_coverage"
        )
        self.assertEqual(coverage["actual"], 0.0)


if __name__ == "__main__":
    unittest.main()
