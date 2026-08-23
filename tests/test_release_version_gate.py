from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-release-version.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def load_verifier():
    specification = importlib.util.spec_from_file_location(
        "release_version_verifier", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_fixture(root: Path, versions: dict[str, str]) -> None:
    (root / "src/compresslab").mkdir(parents=True)
    (root / "native").mkdir()
    (root / "native-dense").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nversion = "{versions["pyproject"]}"\n',
        encoding="utf-8",
    )
    (root / "src/compresslab/__init__.py").write_text(
        f'__version__ = "{versions["python"]}"\n', encoding="utf-8"
    )
    for directory, key in (("native", "native"), ("native-dense", "native_dense")):
        (root / directory / "Cargo.toml").write_text(
            f'[package]\nname = "fixture"\nversion = "{versions[key]}"\n',
            encoding="utf-8",
        )
    (root / "CHANGELOG.md").write_text(
        f'## [{versions["pyproject"]}] - 2026-01-01\n', encoding="utf-8"
    )


class ReleaseVersionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def test_current_repository_and_matching_tag_pass(self) -> None:
        result = self.verifier.verify_release_version(ROOT)
        version = result["version"]
        tagged = self.verifier.verify_release_version(ROOT, f"v{version}")
        self.assertEqual(tagged["tag"], f"v{version}")

    def test_mismatched_tag_is_refused(self) -> None:
        version = self.verifier.verify_release_version(ROOT)["version"]
        with self.assertRaisesRegex(ValueError, "tag does not match"):
            self.verifier.verify_release_version(ROOT, f"v{version}.mismatch")

    def test_disagreeing_metadata_is_refused(self) -> None:
        versions = {
            "pyproject": "1.2.3",
            "python": "1.2.3",
            "native": "1.2.4",
            "native_dense": "1.2.3",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fixture(root, versions)
            with self.assertRaisesRegex(ValueError, "versions disagree"):
                self.verifier.verify_release_version(root, "v1.2.3")

    def test_missing_changelog_release_is_refused(self) -> None:
        versions = {key: "1.2.3" for key in (
            "pyproject", "python", "native", "native_dense"
        )}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fixture(root, versions)
            (root / "CHANGELOG.md").write_text("## [Unreleased]\n", encoding="utf-8")
            untagged = self.verifier.verify_release_version(root)
            self.assertEqual(untagged["version"], "1.2.3")
            with self.assertRaisesRegex(ValueError, "no release section"):
                self.verifier.verify_release_version(root, "v1.2.3")

    def test_workflow_gates_all_artifact_builders_before_publication(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("verify-release-version.py", workflow)
        for job, name in (
            ("sdist", "Source distribution"),
            ("wheels", "Wheel / ${{ matrix.os }}"),
            ("standalone", "Standalone JLS2 decoder / ${{ matrix.os }}"),
        ):
            self.assertIn(
                f"  {job}:\n    name: {name}\n    needs: version",
                workflow,
            )
        self.assertIn('if [[ "$GITHUB_REF_TYPE" == "tag" ]]', workflow)
        self.assertIn('--tag "$GITHUB_REF_NAME"', workflow)


if __name__ == "__main__":
    unittest.main()
