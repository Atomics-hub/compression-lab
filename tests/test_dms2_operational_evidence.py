import hashlib
import json
from pathlib import Path
import subprocess
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SPEED = REPOSITORY / "runs" / "dms2-safe-selector-development-gate-v2.json"
OPERATIONAL = REPOSITORY / "runs" / "dms2-operational-development-gate-v1.json"
CROSS_PLATFORM = REPOSITORY / "runs" / "dms2-cross-platform-ci-receipt-v1.json"
DECISION = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-dms2-native-development-gate.md"
)


EXPECTED_SOURCE_PATHS = {
    "src/compresslab/dense_matrix_transform.py",
    "src/compresslab/dense_native.py",
    "native-dense/src/lib.rs",
    "native-dense/Cargo.toml",
    "native-dense/Cargo.lock",
    ".github/workflows/ci.yml",
}


def sha256_git_blob(commit: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def commit_object_present(commit: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPOSITORY,
            capture_output=True,
        ).returncode
        == 0
    )


class DMS2OperationalEvidenceTests(unittest.TestCase):
    def test_all_local_gates_pass_without_opening_validation(self):
        speed = json.loads(SPEED.read_text(encoding="utf-8"))
        operational = json.loads(OPERATIONAL.read_text(encoding="utf-8"))
        self.assertTrue(operational["gate_results"]["all_passed"])
        self.assertTrue(speed["aggregate"]["ratio_gate_passed"])
        self.assertTrue(speed["aggregate"]["compression_gate_passed"])
        self.assertTrue(speed["aggregate"]["decompression_gate_passed"])
        self.assertEqual(
            speed["remaining_gates"],
            ["portable wheel verification on Linux and Windows"],
        )
        self.assertEqual(speed["public_validation"], "unopened")
        self.assertEqual(speed["private_holdout"], "sealed")

    def test_operational_receipt_is_bound_and_complete(self):
        speed = json.loads(SPEED.read_text(encoding="utf-8"))
        digest = hashlib.sha256(OPERATIONAL.read_bytes()).hexdigest()
        self.assertEqual(speed["operational_evidence_sha256"], digest)
        operational = json.loads(OPERATIONAL.read_text(encoding="utf-8"))
        self.assertEqual(
            operational["record_table_regression"]["regression_percent"], 0.0
        )
        self.assertTrue(
            all(
                row["oracle_selected"] and row["no_expansion_vs_direct"]
                for row in operational["selector"]["rows"]
            )
        )
        self.assertLess(
            max(
                row[operation]["maximum_resident_set_bytes"]
                for row in operational["frame_memory"]
                for operation in ("compression", "decompression")
            ),
            operational["memory_ceiling_bytes"],
        )

    def test_public_chart_matches_machine_readable_evidence(self):
        speed = json.loads(SPEED.read_text(encoding="utf-8"))
        decision = DECISION.read_text(encoding="utf-8")
        readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        self.assertEqual(speed["aggregate"]["complete_bytes"], 189_738)
        for text in (decision,):
            self.assertIn("54.85", text)
            self.assertIn("268.18", text)
            self.assertIn("5.28% smaller", text)
            self.assertIn("not a world-best claim", text)
        self.assertIn("33.45", readme)
        self.assertIn("313.99", readme)
        self.assertIn("43.55%", readme)
        self.assertIn("frozen gate failed", readme.lower())

    def test_cross_platform_receipt_binds_green_jobs_and_source(self):
        receipt = json.loads(CROSS_PLATFORM.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["tested_commit"],
            "4e816ca37b7e9d7b639b474d7dedc4ac077df8b4",
        )
        self.assertEqual(
            {run["event"] for run in receipt["successful_runs"]},
            {"push", "pull_request"},
        )
        self.assertEqual(
            set(receipt["platform_jobs"]), {"linux", "macos", "windows"}
        )
        self.assertTrue(
            all(
                jobs["full_suite"]["conclusion"] == "success"
                and jobs["native_wheel"]["conclusion"] == "success"
                for jobs in receipt["platform_jobs"].values()
            )
        )
        # Structural binding that holds in every checkout, mainline or not:
        # the receipt pins exactly these six sources, each a 64-hex digest.
        source = receipt["source_sha256"]
        self.assertEqual(set(source), EXPECTED_SOURCE_PATHS)
        for value in source.values():
            self.assertRegex(value, r"^[0-9a-f]{64}$")

        # The receipt records the sources AS TESTED at tested_commit. Verify
        # each pinned hash against that commit's git blob rather than the live
        # working-tree bytes: files like .github/workflows/ci.yml may evolve
        # (e.g. the Windows CI enforcement repair) without rewriting this frozen
        # evidence. Mirrors test_jls2_native_decoder_evidence's historical bind.
        #
        # Unlike that precedent's mainline publication commit, tested_commit
        # 4e816ca... was squash-merged; the squash orphaned the branch commit,
        # so it is NOT an ancestor of main and mainline-only checkouts (CI) do
        # not carry the object. Where the object is present (full clones that
        # retain the old branch ref) the git blobs are verified; otherwise the
        # historical check is skipped -- the pinned hashes remain the record and
        # cannot be re-derived without the object. commit_object_present() is
        # the authoritative missing-object signal, so a git-show failure while
        # the commit IS present surfaces as a real binding mismatch, not a skip.
        commit = receipt["tested_commit"]
        if not commit_object_present(commit):
            self.skipTest(
                f"tested_commit {commit[:7]}... is a squash-merged branch "
                "commit not reachable from mainline checkouts; source binding "
                "verifiable only in clones retaining the object"
            )
        for path, expected in source.items():
            self.assertEqual(sha256_git_blob(commit, path), expected)


if __name__ == "__main__":
    unittest.main()
