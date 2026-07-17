from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT / "runs" / "jls2-native-decoder-v1" / "hosted-arm64-reproduction.json"
)


class JLS2HostedReproductionTests(unittest.TestCase):
    def test_hosted_arm64_reproduction_is_explicit_and_bounded(self) -> None:
        hosted = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(hosted["workflow_run"]["run_id"], 29598982414)
        self.assertEqual(hosted["workflow_run"]["attempt"], 2)
        self.assertEqual(hosted["workflow_run"]["conclusion"], "success")
        self.assertTrue(hosted["passed"])
        self.assertTrue(all(hosted["gates"].values()))
        self.assertEqual(hosted["native"]["rounds_at_or_above_250_mbps"], 7)
        self.assertGreater(hosted["native"]["minimum_aggregate_mbps"], 250)
        self.assertLess(hosted["native"]["peak_rss_bytes"], 512 * 1024 * 1024)
        self.assertIn("development-only", hosted["claim_scope"])
        self.assertIn("not fresh public validation", hosted["claim_ceiling"].lower())
        self.assertRegex(hosted["source"]["results_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
