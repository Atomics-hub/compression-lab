from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "jls2-native-decoder-v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class JLS2NativeDecoderEvidenceTests(unittest.TestCase):
    def test_passed_gate_is_complete_exact_and_machine_readable(self) -> None:
        result = json.loads((RUN / "results.json").read_text(encoding="utf-8"))
        summary = result["summary"]
        candidate = next(
            row for row in summary["variants"] if row["variant"] == "native"
        )
        self.assertEqual(result["protocol"], "jls2-standalone-native-decoder-v1")
        self.assertEqual(len(result["trials"]), 48)
        self.assertEqual(sum(not row["warmup"] for row in result["trials"]), 42)
        self.assertTrue(result["all_scheduled_exact"])
        self.assertTrue(summary["candidate_qualifies_performance"])
        self.assertTrue(all(summary["gates"].values()))
        self.assertEqual(candidate["rounds_at_or_above_250_mbps"], 7)
        self.assertGreaterEqual(candidate["minimum_aggregate_parent_mbps"], 250)
        self.assertTrue(
            all(row["median_parent_mbps"] >= 250 for row in candidate["family_rows"])
        )

    def test_chart_keeps_delivery_and_standards_runners_separate(self) -> None:
        report = (RUN / "README.md").read_text(encoding="utf-8")
        chart = (RUN / "native-decoder-scorecard.svg").read_text(encoding="utf-8")
        root = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (
            "585.43 mb/s",
            "398.40 mb/s",
            "+69.98%",
            "48/48",
            "18.08% smaller",
            "immutable same-run standards speed table",
            "unmaterialized and unopened",
        ):
            self.assertIn(text, report.lower())
        for codec in (
            "jls2",
            "brotli-11",
            "zstd-19",
            "bz2-9",
            "lzma-9",
            "7zip-9",
            "zstd-9",
            "zstd-3",
            "gzip-9",
            "lz4-1",
            "store",
        ):
            self.assertIn(f">{codec}<", chart)
        for heading in (
            "JLS2 SIZE",
            "C MB/S",
            "JLS2 C",
            "D MB/S",
            "JLS2 D",
            "PEAK C/D MIB",
            "EXACT",
            "RUNNER",
        ):
            self.assertIn(f">{heading}<", chart)
        self.assertEqual(chart.count(">same run<"), 11)
        self.assertIn("native delivery speed above is a separate A/B", chart)
        self.assertIn("jls2-native-decoder-v1/README.md", root)

    def test_receipt_binds_artifacts_sources_and_external_runs(self) -> None:
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["decision"],
            "standalone-native-decode-development-gate-passed",
        )
        self.assertEqual(
            receipt["candidate_implementation_commit"],
            "86d86f80dad86735e53829c6009eb29cee0ea324",
        )
        self.assertGreater(receipt["ci"]["cross_platform_run_id"], 0)
        self.assertGreater(receipt["ci"]["release_artifact_run_id"], 0)
        self.assertEqual(receipt["ci"]["cross_platform_conclusion"], "success")
        self.assertEqual(receipt["ci"]["release_artifact_conclusion"], "success")
        checksum_lines = (
            (RUN / "release-SHA256SUMS")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(len(checksum_lines), 9)
        self.assertEqual(sum("dist/" in line for line in checksum_lines), 6)
        self.assertEqual(sum("standalone/" in line for line in checksum_lines), 3)
        for relative, expected in receipt["artifacts"].items():
            self.assertEqual(sha256_file(ROOT / relative), expected)
        for relative, expected in receipt["publication_sources"].items():
            self.assertEqual(sha256_file(ROOT / relative), expected)


if __name__ == "__main__":
    unittest.main()
