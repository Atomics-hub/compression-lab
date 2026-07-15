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

    def test_stability_gates_are_enforced(self):
        results = {
            "run_id": "stable-run",
            "config": {"minimum_trial_time_ms": 5.0},
            "system": {
                "cpu_count": 8,
                "state_samples": [
                    {
                        "label": "run-start",
                        "load_average_1m_5m_15m": [4.0, 3.0, 2.0],
                    },
                    {
                        "label": "run-end",
                        "load_average_1m_5m_15m": [80.0, 20.0, 10.0],
                    },
                ],
            },
            "trials": [
                {
                    "codec_id": "candidate",
                    "roundtrip_ok": True,
                    "compression_batch_target_met": True,
                    "decompression_batch_target_met": True,
                },
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
                    "compressed_bytes": 500,
                    "total_ms_at_100mbps": 10.0,
                },
                {
                    "item_id": "item",
                    "codec_id": "baseline",
                    "original_bytes": 1000,
                    "compressed_bytes": 600,
                    "total_ms_at_100mbps": 12.0,
                },
            ],
            "stability": {
                "per_codec": [
                    {
                        "codec_id": "candidate",
                        "repetitions": 7,
                        "metrics": {
                            "compression_mbps": {"cv_percent": 4.0},
                            "decompression_mbps": {"cv_percent": 6.0},
                        },
                        "frontier_coverage": {
                            "100mbps": {"range_percentage_points": 0.0}
                        },
                    }
                ]
            },
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
                "minimum_repetitions": 7,
                "max_unmet_batch_targets": 0,
                "max_compression_throughput_cv_percent": 5.0,
                "max_decompression_throughput_cv_percent": 5.0,
                "max_frontier_coverage_range_percentage_points": 5.0,
                "max_normalized_preflight_load_1m": 1.5,
            }
        }
        report = evaluate_candidate(results, gates, "candidate", 100.0)
        self.assertFalse(report["passed"])
        failed = {check["name"] for check in report["checks"] if not check["passed"]}
        self.assertEqual(failed, {"decompression_throughput_repeatability"})


if __name__ == "__main__":
    unittest.main()
