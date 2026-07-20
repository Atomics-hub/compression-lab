from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_PATH = (
    ROOT / "scripts" / "publish-jls2-declared-size-lifetime-a3-attribution.py"
)
VERIFIER_PATH = (
    ROOT / "scripts" / "verify-jls2-declared-size-lifetime-a3-publication.py"
)
PUBLICATION = (
    ROOT
    / "runs"
    / "jls2-declared-size-lifetime-a3-attribution-v1"
    / "publication"
)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLISHER = load(PUBLISHER_PATH, "jls2_a3_publication")
VERIFIER = load(VERIFIER_PATH, "jls2_a3_publication_verifier")


class JLS2DeclaredSizeLifetimeA3PublicationTests(unittest.TestCase):
    def copy_raw_artifact(self, parent: Path) -> Path:
        artifact = parent / "artifact"
        artifact.mkdir()
        for name in PUBLISHER.EXPECTED_INPUT_SHA256:
            shutil.copyfile(PUBLICATION / name, artifact / name)
        return artifact

    def test_committed_publication_verifies(self) -> None:
        VERIFIER.verify(PUBLICATION)

    def test_offline_republication_is_deterministic_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            artifact = self.copy_raw_artifact(root)
            output = root / "publication"
            receipt = PUBLISHER.publish(artifact, output)
            VERIFIER.verify(output)
            self.assertEqual(receipt["decision"], "rejected")
            self.assertFalse(receipt["product_ab_authorized"])
            self.assertEqual(
                receipt["summary"]["minimum_credited_bytes"], 83_722_100
            )
            self.assertEqual(
                receipt["summary"][
                    "minimum_phase_correlated_rss_reduction_bytes"
                ],
                99_414_016,
            )
            self.assertEqual(
                (output / "README.md").read_text(encoding="utf-8"),
                (PUBLICATION / "README.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (output / "comparison.svg").read_text(encoding="utf-8"),
                (PUBLICATION / "comparison.svg").read_text(encoding="utf-8"),
            )

    def test_publisher_rejects_overwrite_without_touching_output(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            artifact = self.copy_raw_artifact(root)
            output = root / "publication"
            output.mkdir()
            marker = output / "sentinel"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                PUBLISHER.publish(artifact, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_publisher_rejects_extra_or_tampered_artifact_members(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            artifact = self.copy_raw_artifact(root)
            (artifact / "extra.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact roster mismatch"):
                PUBLISHER.publish(artifact, root / "out-extra")
            (artifact / "extra.txt").unlink()
            with (artifact / "results.json").open("a", encoding="utf-8") as output:
                output.write(" ")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                PUBLISHER.publish(artifact, root / "out-tampered")

    def test_publisher_rejects_symlinked_input_member_and_directory(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            artifact = self.copy_raw_artifact(root)
            target = artifact / "results.json"
            real = root / "real-results.json"
            target.replace(real)
            target.symlink_to(real)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                PUBLISHER.publish(artifact, root / "out-member")
            directory_link = root / "artifact-link"
            directory_link.symlink_to(artifact, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "cannot be a symlink"):
                PUBLISHER.publish(directory_link, root / "out-directory")

    def test_verifier_rejects_extra_json_key_and_symlink_member(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            publication = root / "publication"
            shutil.copytree(PUBLICATION, publication)
            comparison_path = publication / "comparison.json"
            comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
            comparison["unexpected"] = True
            comparison_path.write_text(
                json.dumps(comparison, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "keys mismatch"):
                VERIFIER.verify(publication)

            shutil.rmtree(publication)
            shutil.copytree(PUBLICATION, publication)
            readme = publication / "README.md"
            real = root / "README.md"
            readme.replace(real)
            readme.symlink_to(real)
            with self.assertRaisesRegex(ValueError, "regular file"):
                VERIFIER.verify(publication)

    def test_receipt_binds_hosted_and_artifact_identity(self) -> None:
        receipt = json.loads((PUBLICATION / "receipt.json").read_text(encoding="utf-8"))
        source = receipt["source_artifact"]
        self.assertEqual(source["run_id"], 29_765_080_842)
        self.assertEqual(source["job_id"], 88_429_200_694)
        self.assertEqual(source["artifact_id"], 8_470_661_511)
        self.assertEqual(source["workflow_head"], "41d2aaea12e5126bb83106792bfd575dc12e7440")
        self.assertEqual(
            source["embedded_workflow_commit"],
            "3cfd54e798056bd419dbbd3daec4359be873a87b",
        )
        self.assertEqual(
            source["artifact_digest"],
            "sha256:42ae14e5a0cdd63f8673fe5f4256e0f1dda16f4cc86e80acb3570e66407d3a05",
        )


if __name__ == "__main__":
    unittest.main()
