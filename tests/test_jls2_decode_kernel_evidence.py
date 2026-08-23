from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
RUN = REPOSITORY / "runs" / "jls2-decode-kernel-development-v1"
PUBLICATION_COMMIT = "43a7165f4f62b1fe0e86f37bba90f0b74cc0c224"
BASE_COMMIT = "493f6ac5a2ea32c1d870698e38cb1732b6423c20"
CANDIDATE_COMMIT = "ae28430b55fa27755e9cce3fcb7cc5abb30c593c"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_digest(commit: str, relative: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def commit_reachable(commit: str) -> bool:
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise AssertionError(f"invalid pinned commit: {commit!r}")
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=REPOSITORY,
        capture_output=True,
    )
    if present.returncode == 0:
        reachable = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=REPOSITORY,
            capture_output=True,
        )
        if reachable.returncode == 0:
            return True
        if reachable.returncode == 1:
            raise AssertionError(
                f"pinned commit is present but not reachable from HEAD: {commit}"
            )
        raise AssertionError(f"could not verify pinned commit reachability: {commit}")
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if shallow.returncode != 0:
        raise AssertionError("could not determine whether checkout is shallow")
    if shallow.stdout.strip() == "true":
        return False
    raise AssertionError(
        f"pinned commit is absent from a full-history checkout: {commit}"
    )


class JLS2DecodeKernelEvidenceTests(unittest.TestCase):
    def test_receipt_binds_artifacts_and_historical_sources(self):
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        ab = json.loads((RUN / "ab-result.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["gate"], "jls2-decode-kernel-development-v1")
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(ab["passed"])
        self.assertEqual(receipt["base_commit"], ab["base"]["commit"])
        self.assertEqual(receipt["candidate_commit"], ab["candidate"]["commit"])
        self.assertEqual(receipt["base_commit"], BASE_COMMIT)
        self.assertEqual(receipt["candidate_commit"], CANDIDATE_COMMIT)
        for name, expected in receipt["artifact_sha256"].items():
            self.assertEqual(digest(RUN / name), expected)
        missing_commits = [
            commit
            for commit in (PUBLICATION_COMMIT, BASE_COMMIT, CANDIDATE_COMMIT)
            if not commit_reachable(commit)
        ]
        if missing_commits:
            self.skipTest(
                "historical commits are not reachable from this shallow "
                "checkout: "
                + ", ".join(commit[:7] + "..." for commit in missing_commits)
            )
        self.assertEqual(
            receipt["publisher_sha256"],
            git_blob_digest(
                PUBLICATION_COMMIT, "scripts/publish-jls2-decode-kernel.py"
            ),
        )
        for label, commit in (
            ("base", BASE_COMMIT),
            ("candidate", CANDIDATE_COMMIT),
        ):
            for relative, expected in ab[label]["source_sha256"].items():
                self.assertEqual(git_blob_digest(commit, relative), expected)

    def test_exact_bytes_speed_gate_and_public_chart(self):
        receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
        aggregate = receipt["aggregate_byte_api"]
        self.assertEqual(aggregate["candidate_rounds_at_or_above_250_mbps"], 7)
        self.assertGreater(aggregate["median_paired_improvement_percent"], 20)
        self.assertEqual(
            receipt["aggregate_product"]["encoded_bytes_unchanged"], 2_693_313
        )
        self.assertTrue(all(receipt["candidate_product_gates"].values()))

        report = (RUN / "README.md").read_text(encoding="utf-8")
        root = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        self.assertIn("21.66%", report)
        self.assertIn("7/7", report)
        self.assertIn("does not change the retained JLS2 public-validation failure", report)
        self.assertIn("jls2-decode-kernel-development-v1/README.md", root)
        self.assertIn("## Measured standings", root)
        self.assertNotIn("## Current limitations", root)


if __name__ == "__main__":
    unittest.main()
