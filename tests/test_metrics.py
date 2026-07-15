import unittest

from compresslab.metrics import median_trials, summarize


def row(codec, repetition, size, compression_ns, decompression_ns):
    return {
        "run_id": "r",
        "item_id": "item",
        "item_category": "text",
        "item_split": "validation",
        "codec_id": codec,
        "codec_family": codec,
        "repetition": repetition,
        "original_bytes": 1000,
        "compressed_bytes": size,
        "compression_ns": compression_ns,
        "decompression_ns": decompression_ns,
        "compression_cpu_ns": compression_ns,
        "decompression_cpu_ns": decompression_ns,
        "compression_peak_rss_bytes": 100,
        "decompression_peak_rss_bytes": 100,
        "roundtrip_ok": True,
        "source_sha256": "a",
        "restored_sha256": "a",
        "error": "",
    }


class MetricsTests(unittest.TestCase):
    def test_median_and_summary(self):
        trials = [
            row("fast", 1, 800, 100, 100),
            row("fast", 2, 800, 300, 300),
            row("fast", 3, 800, 200, 200),
            row("small", 1, 400, 500, 500),
            row("small", 2, 400, 700, 700),
            row("small", 3, 400, 600, 600),
        ]
        medians = median_trials(trials)
        self.assertEqual(len(medians), 2)
        fast = next(value for value in medians if value["codec_id"] == "fast")
        self.assertEqual(fast["compression_ns"], 200)
        summary = summarize(medians, [100.0])
        self.assertEqual(len(summary), 2)
        self.assertTrue(all(value["pareto"] for value in summary))
        self.assertIn("total_ms_at_100mbps", summary[0])


if __name__ == "__main__":
    unittest.main()
