#!/usr/bin/env python3
"""Audit the public-checkout verification gate and write a compact receipt."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional, Sequence, Tuple
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
GUARD_NAME = "commit_object_present"

GUARDED_SITES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    (
        "tests/test_clue_jls2_validation_lock.py",
        "ClueJLS2ValidationLockTests",
        (
            "test_committed_receipt_binds_the_clean_lock_commit",
            "test_current_tree_still_satisfies_the_readiness_lock",
        ),
    ),
    (
        "tests/test_dms2_public_validation.py",
        "DMS2PublicValidationTests",
        (
            "test_final_lock_pins_the_merged_readiness_surface",
            "test_explicit_acquisition_still_refuses_a_drifted_lock",
            "test_candidate_and_development_evidence_are_frozen",
        ),
    ),
    (
        "tests/test_tbl1_public_validation.py",
        "TBL1PublicValidationTests",
        (
            "test_final_lock_pins_merged_readiness_controls",
            "test_declared_candidate_hashes_match_frozen_base_commit",
        ),
    ),
    (
        "tests/test_text_source_development_evidence.py",
        "TextSourceDevelopmentEvidenceTests",
        ("test_receipt_is_bound_to_the_historical_pre_acquisition_surface",),
    ),
    (
        "tests/test_jls2_native_decoder_evidence.py",
        "JLS2NativeDecoderEvidenceTests",
        ("test_receipt_binds_artifacts_sources_and_external_runs",),
    ),
)

NUMERIC_TEST = "tests/test_numeric_ar5_numr_prototype.py"
NUMERIC_PROBE_METHOD = "test_frozen_frame_hash_is_stable"
DMS2_PRECEDENT = "tests/test_dms2_operational_evidence.py"
FROZEN_BOUNDARY: Tuple[Tuple[str, str], ...] = (
    (
        "config/clue-jls2-public-validation-lock.json",
        "tests/test_clue_jls2_validation_readiness.py",
    ),
    (
        "config/clue-jls2-public-validation-v2-lock.json",
        "tests/test_clue_jls2_v2_validation_readiness.py",
    ),
)
README_REQUIRED = (
    "full-history clone",
    "runs/public-checkout-verification-v1/README.md",
)
CHANGELOG_REQUIRED = "degrade to explanatory skips"

CLAIM_CEILING = (
    "Proves that the advertised verification suite's git-history-bound "
    "checks degrade to explicit skips instead of errors on shallow checkouts "
    "or source archives that do not retain the referenced commit objects; "
    "missing or malformed pins fail on full-history checkouts. The guard is "
    "exercised on this repository and a synthetic git fixture only. It does "
    "not prove test-suite completeness, benchmark representativeness, "
    "compression speed, compression ratio, packaging correctness, or release "
    "readiness, and it does not verify the historical bindings themselves on "
    "checkouts lacking those objects; the two lock-frozen readiness modules "
    "intentionally retain their full-history requirement."
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def check(name: str, passed: bool, evidence: str) -> Dict[str, Any]:
    return {
        "check": name,
        "evidence": evidence,
        "status": "pass" if passed else "fail",
    }


def object_present(commit: str, cwd: Path) -> bool:
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise AssertionError(f"invalid pinned commit: {commit!r}")
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=cwd,
        capture_output=True,
    )
    if present.returncode == 0:
        return True
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if shallow.returncode != 0 or shallow.stdout.strip() == "true":
        return False
    raise AssertionError(f"pinned commit is absent from a full-history checkout: {commit}")


def guard_is_wired(
    relative: str, class_name: str, methods: Tuple[str, ...]
) -> Tuple[bool, str]:
    source = (REPOSITORY / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    guard_defined = any(
        isinstance(node, ast.FunctionDef) and node.name == GUARD_NAME
        for node in tree.body
    )
    wired = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in methods:
                    segment = ast.get_source_segment(source, item) or ""
                    wired[item.name] = f"{GUARD_NAME}(" in segment
    fail_closed = (
        "--is-shallow-repository" in source
        and "pinned commit is absent from a full-history checkout" in source
        and "invalid pinned commit" in source
    )
    passed = guard_defined and fail_closed and set(methods) == set(wired) and all(
        wired.values()
    )
    evidence = (
        f"guard_defined={guard_defined}; fail_closed={fail_closed}; "
        f"methods_wired={sum(wired.values())}/{len(methods)}"
    )
    return passed, evidence


def load_test_module(relative: str) -> Any:
    path = REPOSITORY / relative
    name = "audit_pcv_" + path.stem
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def run_single(module: Any, class_name: str, method: str) -> str:
    suite = unittest.TestSuite([getattr(module, class_name)(method)])
    result = unittest.TestResult()
    suite.run(result)
    if result.errors:
        return "error"
    if result.failures:
        return "failure"
    if result.skipped:
        return "skipped"
    return "success"


def hermetic_guard_probe() -> Tuple[bool, str]:
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary) / "repo"
        repo.mkdir()

        def git(*arguments: str) -> None:
            subprocess.run(
                ["git", *arguments], cwd=repo, check=True, capture_output=True
            )

        git("init", "-q")
        git("config", "core.autocrlf", "false")
        git("config", "core.eol", "lf")
        git("config", "user.email", "audit@example.invalid")
        git("config", "user.name", "Audit")
        (repo / "fixture.txt").write_bytes(b"public-checkout fixture\n")
        git("add", "fixture.txt")
        git("commit", "-q", "-m", "fixture")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        present = object_present(head, repo)
        try:
            object_present("0" * 40, repo)
        except AssertionError:
            full_history_absent_refused = True
        else:
            full_history_absent_refused = False
        try:
            object_present("not-a-commit", repo)
        except AssertionError:
            malformed_refused = True
        else:
            malformed_refused = False
        archive = Path(temporary) / "archive"
        archive.mkdir()
        archive_absent = object_present("0" * 40, archive)
    passed = (
        present
        and full_history_absent_refused
        and malformed_refused
        and not archive_absent
    )
    evidence = (
        f"present={present}; full_history_absent_refused="
        f"{full_history_absent_refused}; malformed_refused={malformed_refused}; "
        f"archive_absent={archive_absent}"
    )
    return passed, evidence


def numeric_degrades() -> Tuple[bool, str]:
    numeric_path = str(REPOSITORY / NUMERIC_TEST)
    probe = (
        "import importlib.util, sys, unittest\n"
        "class Blocker:\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'zstandard' or "
        "fullname.startswith('zstandard.'):\n"
        "            raise ModuleNotFoundError("
        "'zstandard blocked by audit', name='zstandard')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Blocker())\n"
        f"spec = importlib.util.spec_from_file_location("
        f"'audit_numeric_probe', {numeric_path!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert module.numeric is None, 'expected numeric to degrade'\n"
        f"suite = unittest.TestSuite("
        f"[module.NumericPrototypeTests({NUMERIC_PROBE_METHOD!r})])\n"
        "result = unittest.TestResult()\n"
        "suite.run(result)\n"
        "assert result.testsRun == 1, result.testsRun\n"
        "assert not result.errors and not result.failures, "
        "(result.errors, result.failures)\n"
        "assert len(result.skipped) == 1, 'expected the prototype to skip'\n"
        "print('numeric-degrades=ok')\n"
    )
    environment = dict(os.environ)
    source_root = str(REPOSITORY / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root if not existing else source_root + os.pathsep + existing
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPOSITORY,
    )
    passed = (
        completed.returncode == 0
        and "numeric-degrades=ok" in completed.stdout
    )
    tail = completed.stdout.strip() or completed.stderr.strip()
    detail = tail.splitlines()[-1] if tail else "no output"
    return passed, f"returncode={completed.returncode}; {detail}"


def audit(output: Path) -> Dict[str, Any]:
    checks = []
    for relative, class_name, methods in GUARDED_SITES:
        passed, evidence = guard_is_wired(relative, class_name, methods)
        checks.append(check(f"guard wired: {relative}", passed, evidence))

    passed, evidence = hermetic_guard_probe()
    checks.append(
        check("guard separates present and absent objects", passed, evidence)
    )

    for relative, class_name, methods in GUARDED_SITES:
        module = load_test_module(relative)
        outcomes = {
            method: run_single(module, class_name, method)
            for method in methods
        }
        degraded = all(
            outcome in ("success", "skipped")
            for outcome in outcomes.values()
        )
        evidence = "; ".join(
            f"{method}={outcome}" for method, outcome in outcomes.items()
        )
        checks.append(
            check(f"degrades without error: {relative}", degraded, evidence)
        )

    passed, evidence = numeric_degrades()
    checks.append(
        check(
            "numeric prototype skips when zstandard is unavailable",
            passed,
            evidence,
        )
    )

    readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
    readme_present = all(required in readme for required in README_REQUIRED)
    checks.append(
        check(
            "README documents the full-history precondition and the record",
            readme_present,
            f"required_strings_present={readme_present}",
        )
    )

    changelog = (REPOSITORY / "CHANGELOG.md").read_text(encoding="utf-8")
    checks.append(
        check(
            "CHANGELOG records the public-checkout hardening",
            CHANGELOG_REQUIRED in changelog,
            f"required_string_present={CHANGELOG_REQUIRED in changelog}",
        )
    )

    boundary = []
    for lock_relative, frozen_relative in FROZEN_BOUNDARY:
        lock = json.loads(
            (REPOSITORY / lock_relative).read_text(encoding="utf-8")
        )
        expected = lock["locked_paths"][frozen_relative]
        live = sha256_path(REPOSITORY / frozen_relative)
        boundary.append((frozen_relative, live == expected))
    checks.append(
        check(
            "lock-frozen readiness modules remain byte-identical",
            all(match for _, match in boundary),
            "; ".join(
                f"{relative}={'match' if match else 'drift'}"
                for relative, match in boundary
            ),
        )
    )

    precedent = (REPOSITORY / DMS2_PRECEDENT).read_text(encoding="utf-8")
    checks.append(
        check(
            "dms2 guard precedent unchanged",
            f"def {GUARD_NAME}(" in precedent,
            f"guard_defined={f'def {GUARD_NAME}(' in precedent}",
        )
    )

    failed = [row for row in checks if row["status"] != "pass"]
    if failed:
        for row in failed:
            print(
                f"failed: {row['check']}: {row['evidence']}",
                file=sys.stderr,
            )
        raise SystemExit(
            f"public-checkout verification failed "
            f"{len(failed)}/{len(checks)} checks; no receipt written"
        )

    receipt = {
        "schema_version": 1,
        "gate": "public-checkout-verification-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "checks": checks,
        "summary": {"passed": len(checks), "failed": 0, "total": len(checks)},
        "runner_identity": {
            "audit_script_sha256": sha256_path(Path(__file__).resolve()),
            "guarded_test_sha256": {
                relative: sha256_path(REPOSITORY / relative)
                for relative, _, _ in GUARDED_SITES
            },
            "numeric_test_sha256": sha256_path(REPOSITORY / NUMERIC_TEST),
        },
        "claim_ceiling": CLAIM_CEILING,
    }
    write_json(output, receipt)
    return receipt


def build_audit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "runs/public-checkout-verification-v1/receipt.json",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_audit_parser().parse_args(argv)
    receipt = audit(args.output)
    print(
        f"{receipt['status']}: {receipt['summary']['passed']}/"
        f"{receipt['summary']['total']} checks; {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
