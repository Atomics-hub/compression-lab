from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseRecordTests(unittest.TestCase):
    def test_changelog_records_the_published_release(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.1.0] - 2026-07-16", changelog)
        self.assertNotIn("## [0.1.0] - Unreleased", changelog)
        self.assertIn("five platform wheels", changelog)
        self.assertIn("controlling benchmark-evidence bundle", changelog)

    def test_release_record_does_not_revert_to_prelaunch_state(self) -> None:
        readiness = (ROOT / "docs" / "release-readiness.md").read_text(
            encoding="utf-8"
        )
        for fact in (
            "Version 0.1.0 was released on **2026-07-16**",
            "3b17b7b7978aa392dfaee2d053925c3565ebb58e",
            "29509611019",
            "private vulnerability reporting enabled",
            "requires owner review",
        ):
            self.assertIn(fact, readiness)
        for stale in (
            "repository is still private",
            "make the repository public",
            "The project name was absent from PyPI",
        ):
            self.assertNotIn(stale, readiness)

    def test_completed_checklist_has_no_unresolved_v010_launch_action(self) -> None:
        checklist = (ROOT / "docs" / "release-checklist.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("# Public release checklist — v0.1.0 (completed)", checklist)
        self.assertNotIn("- [ ]", checklist)
        self.assertIn("not a standing authorization", " ".join(checklist.split()))
        self.assertIn("https://pypi.org/project/compression-lab/0.1.0/", checklist)


if __name__ == "__main__":
    unittest.main()
