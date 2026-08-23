from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config" / "clue-jls2-public-validation-lock.json"
RECEIPT = ROOT / "runs" / "clue-jls2-public-validation-lock-v1.json"
VERIFIER = ROOT / "scripts" / "verify-clue-jls2-public-validation-lock.py"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def commit_object_present(commit: str) -> bool:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise AssertionError(f"invalid pinned commit: {commit!r}")
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
    )
    if present.returncode == 0:
        return True
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if shallow.returncode != 0 or shallow.stdout.strip() == "true":
        return False
    raise AssertionError(f"pinned commit is absent from a full-history checkout: {commit}")


class ClueJLS2ValidationLockTests(unittest.TestCase):
    def test_committed_receipt_binds_the_clean_lock_commit(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["readiness_commit"], lock["readiness_commit"])
        self.assertEqual(receipt["authorization"], lock["authorization"])
        self.assertEqual(receipt["verified_paths"], lock["locked_paths"])
        self.assertEqual(receipt["lock_sha256"], digest_bytes(LOCK.read_bytes()))
        self.assertEqual(receipt["tracked_status"], "")
        head = receipt["head_commit"]
        if not commit_object_present(head):
            self.skipTest(
                f"lock receipt head commit {head[:7]}... is not reachable "
                "from this checkout (shallow clone or source archive); the "
                "historical lock binding is verifiable only in "
                "clones retaining the object"
            )
        committed_lock = subprocess.run(
            ["git", "show", f"{receipt['head_commit']}:config/{LOCK.name}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(receipt["lock_sha256"], digest_bytes(committed_lock))

    def test_current_tree_still_satisfies_the_readiness_lock(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        readiness = lock["readiness_commit"]
        if not commit_object_present(readiness):
            self.skipTest(
                f"readiness commit {readiness[:7]}... is not reachable from "
                "this checkout (shallow clone or source archive); "
                "the live readiness-lock verification is possible only in "
                "clones retaining the object"
            )
        specification = importlib.util.spec_from_file_location(
            "clue_jls2_lock_verifier", VERIFIER
        )
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        verified = module.verify_lock(LOCK, require_clean=False)
        self.assertTrue(verified["passed"])
        self.assertEqual(verified["verified_paths"], lock["locked_paths"])


if __name__ == "__main__":
    unittest.main()
