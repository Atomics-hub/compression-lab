from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish-dms2-public-validation.py"
SPEC = importlib.util.spec_from_file_location("dms2_publication", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def trial(item: str, codec: str, compressed: int, elapsed: int = 100) -> dict:
    return {
        "item_id": item,
        "codec_id": codec,
        "original_bytes": 1000,
        "compressed_bytes": compressed,
        "compression_ns": elapsed,
        "decompression_ns": elapsed,
        "compression_peak_rss_bytes": 1024 * 1024,
        "decompression_peak_rss_bytes": 1024 * 1024,
        "roundtrip_ok": True,
    }


class DMS2PublicationTests(unittest.TestCase):
    def test_retained_public_bundle_is_bound_and_leads_with_failure(self) -> None:
        root = ROOT / "runs" / "dms2-public-validation-v1"
        bundle = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
        comparison = json.loads(
            (root / "comparison.json").read_text(encoding="utf-8")
        )
        report = (root / "README.md").read_text(encoding="utf-8")
        self.assertEqual(bundle["status"], "not_passed")
        self.assertEqual(comparison["candidate_bytes"], 11_937_137)
        self.assertEqual(comparison["strongest_baseline"], "brotli-11")
        self.assertAlmostEqual(
            comparison["candidate_vs_strongest_percent"], 43.553382, places=5
        )
        self.assertEqual(len(comparison["comparison_chart"]), 11)
        self.assertFalse(comparison["frozen_decision_passed"])
        self.assertIn("Status: **not passed**", report)
        for name, expected in bundle["artifacts"].items():
            self.assertEqual(
                hashlib.sha256((root / name).read_bytes()).hexdigest(), expected
            )

    def test_comparison_excludes_extra_baseline_items(self) -> None:
        gates = {
            "validation": {"expected_items": [{"id": "a"}, {"id": "b"}]},
            "baselines": {"codec_ids": ["base"]},
        }
        expected = [trial("a", "base", 40), trial("b", "base", 50)]
        extra = trial("extra", "base", 1)
        baseline = {
            "corpus": [{"id": "extra"}, {"id": "a"}, {"id": "b"}],
            "medians": [extra, *expected],
            "trials": [extra, *expected],
        }
        baseline_memory = {"medians": [extra, *expected]}
        candidate_rows = [trial("a", "dms2-stream", 50), trial("b", "dms2-stream", 50)]
        candidate = {
            "corpus": [{"id": "a"}, {"id": "b"}],
            "medians": candidate_rows,
            "trials": candidate_rows,
            "summary": {
                "original_bytes": 2000,
                "compressed_bytes": 100,
                "compression_mbps": 10.0,
                "decompression_mbps": 20.0,
            },
        }
        candidate_memory = {
            "summary": {
                "compression_peak_rss_bytes": 2 * 1024 * 1024,
                "decompression_peak_rss_bytes": 3 * 1024 * 1024,
            }
        }
        decision = {"passed": False, "families": [], "gate_results": {"ratio": False}}
        comparison = MODULE.build_comparison(
            gates=gates,
            decision=decision,
            baseline=baseline,
            baseline_memory=baseline_memory,
            candidate=candidate,
            candidate_memory=candidate_memory,
        )
        base = comparison["comparison_chart"][1]
        self.assertEqual(base["complete_bytes"], 90)
        self.assertAlmostEqual(base["dms2_size_delta_percent"], 100 / 9)
        self.assertEqual(comparison["baseline_corpus_ids"], ["extra", "a", "b"])
        self.assertFalse(comparison["validity"]["frozen_aggregate_gate_valid"])

    def test_report_leads_with_not_passed(self) -> None:
        comparison = {
            "original_bytes": 10,
            "candidate_bytes": 8,
            "strongest_baseline": "base",
            "strongest_baseline_bytes": 7,
            "candidate_vs_strongest_percent": 100 / 7,
            "families": [],
            "comparison_chart": [],
            "gate_results": {"ratio": False},
            "validity": {
                "reason": "mismatch",
                "speed_comparability": "contextual",
                "cold_memory_comparability": "same host",
            },
            "claim_ceiling": "no win claim",
        }
        report = MODULE.render_report(comparison)
        self.assertIn("Status: **not passed**", report)
        self.assertIn("Failed frozen gates: `ratio`", report)
        self.assertIn("no win claim", report)


if __name__ == "__main__":
    unittest.main()
