from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify-clue-jls2-public-validation-v2-lock.py"
LOCK_NAME = "clue-jls2-public-validation-v2-readiness-lock"
EXPECTED_ITEM_IDS = ["clue-validation-v2-c", "clue-validation-v2-d"]


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_verifier(repository: Path):
    spec = importlib.util.spec_from_file_location(
        f"verify_v2_lock_{repository.name}", VERIFIER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPOSITORY = repository
    return module


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def write_lf(path: Path, text: str) -> None:
    # Write exact bytes with LF newlines so the working tree matches the git
    # blob regardless of the host's core.autocrlf/eol defaults (Windows CI).
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    # Hermetic newline handling: never translate checked-out text to CRLF, so
    # working-tree byte hashes equal the committed blob hashes on every host.
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "core.eol", "lf")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")


def make_repo(root: Path) -> tuple[Path, dict[str, str]]:
    repo = root / "repo"
    init_repo(repo)
    tracked = {
        "config/clue-jls2-public-validation-v2-gates.json": '{"name": "gates"}\n',
        "config/clue-json-log-corpus-v2.json": '{"name": "corpus"}\n',
        "scripts/benchmark.py": "print('benchmark')\n",
    }
    for relative, content in tracked.items():
        write_lf(repo / relative, content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    locked = {
        relative: digest_bytes((repo / relative).read_bytes()) for relative in tracked
    }
    lock = {
        "schema_version": 1,
        "name": LOCK_NAME,
        "readiness_commit": head,
        "claim_ceiling": "category-scoped public validation only",
        "authorization": {
            "maximum_acquisitions": 1,
            "maximum_scored_attempts": 1,
            "split": "public_validation",
            "expected_item_ids": EXPECTED_ITEM_IDS,
            "retain_failed_or_interrupted_attempt": True,
            "prohibit_post_score_tuning": True,
        },
        "locked_paths": locked,
    }
    lock_path = repo / "config" / "clue-jls2-public-validation-v2-lock.json"
    write_lf(lock_path, json.dumps(lock, indent=2) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "lock")
    return repo, locked


class ClueJLS2V2ValidationLockTests(unittest.TestCase):
    def test_clean_tree_satisfies_the_readiness_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo, locked = make_repo(Path(raw))
            module = load_verifier(repo)
            lock_path = repo / "config" / "clue-jls2-public-validation-v2-lock.json"
            receipt = module.verify_lock(lock_path)
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["verified_paths"], locked)
            self.assertEqual(receipt["tracked_status"], "")

    def test_lock_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo, _ = make_repo(Path(raw))
            module = load_verifier(repo)
            lock_path = repo / "config" / "clue-jls2-public-validation-v2-lock.json"
            drifted = repo / "config" / "clue-json-log-corpus-v2.json"
            write_lf(drifted, '{"name": "tampered"}\n')
            with self.assertRaisesRegex(ValueError, "drifted"):
                module.verify_lock(lock_path, require_clean=False)

    def test_dirty_tree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo, _ = make_repo(Path(raw))
            module = load_verifier(repo)
            lock_path = repo / "config" / "clue-jls2-public-validation-v2-lock.json"
            write_lf(repo / "scripts" / "benchmark.py", "print('x')\n")
            with self.assertRaisesRegex(ValueError, "clean tracked tree"):
                module.verify_lock(lock_path, require_clean=True)

    def test_missing_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo, _ = make_repo(Path(raw))
            module = load_verifier(repo)
            with self.assertRaisesRegex(ValueError, "readiness lock is missing"):
                module.verify_lock(repo / "config" / "absent.json")

    def test_wrong_item_roster_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo, _ = make_repo(Path(raw))
            module = load_verifier(repo)
            lock_path = repo / "config" / "clue-jls2-public-validation-v2-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["authorization"]["expected_item_ids"] = ["clue-validation-a"]
            write_lf(lock_path, json.dumps(lock, indent=2) + "\n")
            git(repo, "commit", "-q", "-am", "tamper roster")
            with self.assertRaisesRegex(ValueError, "item roster"):
                module.verify_lock(lock_path, require_clean=False)

    def test_one_attempt_authorization_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo, _ = make_repo(Path(raw))
            module = load_verifier(repo)
            lock_path = repo / "config" / "clue-jls2-public-validation-v2-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["authorization"]["maximum_scored_attempts"] = 2
            write_lf(lock_path, json.dumps(lock, indent=2) + "\n")
            git(repo, "commit", "-q", "-am", "tamper attempts")
            with self.assertRaisesRegex(ValueError, "one scored attempt"):
                module.verify_lock(lock_path, require_clean=False)


if __name__ == "__main__":
    unittest.main()
