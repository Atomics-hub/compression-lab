import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "render-category-scorecard.py"
SPEC = importlib.util.spec_from_file_location("category_scorecard", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load category scorecard renderer")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CategoryScorecardTests(unittest.TestCase):
    def test_committed_validation_scorecard_renders_all_evidence_sections(self):
        scorecard = json.loads(
            (
                REPOSITORY
                / "runs"
                / "jls2-public-validation-summary.json"
            ).read_text(encoding="utf-8")
        )
        rendered = MODULE.render(scorecard)
        committed = (
            REPOSITORY
            / "docs"
            / "benchmarks"
            / "2026-07-16-jls2-public-validation-decision.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(rendered, committed)
        self.assertIn("Overall frozen gate: ❌ FAIL", rendered)
        self.assertIn("| zstd level 9", rendered)
        self.assertIn("✅ win: 28.77% smaller", rendered)
        self.assertIn("⚠️ mixed: 4.58% smaller", rendered)
        self.assertIn("decompression at least 250 mbps | ❌ fail", rendered)
        self.assertIn("Private holdout: sealed", rendered)

    def test_renderer_rejects_duplicate_codec_rows(self):
        scorecard = json.loads(
            (
                REPOSITORY
                / "runs"
                / "jls2-public-validation-summary.json"
            ).read_text(encoding="utf-8")
        )
        scorecard["standards"].append(scorecard["standards"][0])
        with self.assertRaisesRegex(ValueError, "unique"):
            MODULE.render(scorecard)

    def test_output_can_be_written_as_a_complete_markdown_artifact(self):
        scorecard_path = (
            REPOSITORY / "runs" / "jls2-public-validation-summary.json"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "scorecard.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(scorecard_path),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("# JLS2", output.read_text(encoding="utf-8"))
            self.assertTrue(output.read_text(encoding="utf-8").endswith("\n"))


if __name__ == "__main__":
    unittest.main()
