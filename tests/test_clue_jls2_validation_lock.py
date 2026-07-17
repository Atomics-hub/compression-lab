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


class ClueJLS2ValidationLockTests(unittest.TestCase):
    def test_committed_receipt_binds_the_clean_lock_commit(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["readiness_commit"], lock["readiness_commit"])
        self.assertEqual(receipt["authorization"], lock["authorization"])
        self.assertEqual(receipt["verified_paths"], lock["locked_paths"])
        self.assertEqual(receipt["lock_sha256"], digest_bytes(LOCK.read_bytes()))
        committed_lock = subprocess.run(
            ["git", "show", f"{receipt['head_commit']}:config/{LOCK.name}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(receipt["lock_sha256"], digest_bytes(committed_lock))
        self.assertEqual(receipt["tracked_status"], "")

    def test_current_tree_still_satisfies_the_readiness_lock(self) -> None:
        specification = importlib.util.spec_from_file_location(
            "clue_jls2_lock_verifier", VERIFIER
        )
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        verified = module.verify_lock(LOCK, require_clean=False)
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertTrue(verified["passed"])
        self.assertEqual(verified["verified_paths"], lock["locked_paths"])


if __name__ == "__main__":
    unittest.main()
