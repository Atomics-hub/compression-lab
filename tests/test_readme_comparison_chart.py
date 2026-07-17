from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReadmeComparisonChartTests(unittest.TestCase):
    def test_checked_in_chart_and_scorecard_match_frozen_evidence(self) -> None:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "render-readme-comparison-chart.py"),
                "--check",
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
