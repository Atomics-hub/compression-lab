import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
GATES = REPOSITORY / "config" / "dense-matrix-development-gates-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-dense-matrix-representation-protocol.md"
)


class DenseMatrixProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gates = json.loads(GATES.read_text(encoding="utf-8"))

    def test_ratio_targets_match_frozen_census(self):
        baseline = self.gates["frozen_baseline"]
        ratio = self.gates["ratio_gates"]
        self.assertEqual(baseline["aggregate_bytes"], 200_311)
        self.assertEqual(baseline["unchanged_tbs1_aggregate_bytes"], 320_264)
        self.assertEqual(
            ratio["maximum_aggregate_bytes_for_five_percent_gain_vs_bz2_9"],
            190_295,
        )
        self.assertEqual(
            ratio[
                "minimum_families_with_five_percent_gain_vs_strongest_standard"
            ],
            2,
        )

    def test_selector_cannot_use_evaluation_metadata(self):
        boundary = self.gates["contamination_boundary"]
        selector = self.gates["selector_gates"]
        self.assertIn("filenames", boundary["evaluation_only"])
        self.assertIn("bounded bytes", boundary["production_inputs"])
        self.assertEqual(selector["maximum_sample_bytes"], 1_048_576)
        self.assertIn("no row may use", selector["training"])

    def test_hypotheses_and_public_validation_boundary_are_visible(self):
        self.assertEqual(
            [row["id"] for row in self.gates["hypotheses"]],
            ["DMT1", "DMI1", "DMB1"],
        )
        self.assertEqual(
            self.gates["corpus"]["public_validation"],
            "unopened",
        )
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("Gisette and Madelon, remain unopened", protocol)
        self.assertIn("No hypothesis may special-case", protocol)
        self.assertIn("publish the next full comparison chart", protocol)


if __name__ == "__main__":
    unittest.main()
