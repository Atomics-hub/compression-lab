#!/usr/bin/env python3
"""Verify and atomically import the immutable CLUE-LDS JLS2 v2 first score.

The workflow-run provenance constants below are placeholders. They are set once,
at import time, after the single authorized scored dispatch produces its
retained artifact; the pre-acquisition readiness lock does not freeze this
importer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
EXPECTED_REPOSITORY = "Atomics-hub/compression-lab"
# Set at import time from the single scored dispatch (run 30055586630, the
# passing attempt 2 on the ruff-fixed main). The importer was byte-identical to
# the audited head 67f6709 before these two provenance constants were filled.
EXPECTED_RUN_ID = 30055586630
EXPECTED_HEAD_SHA = "b187308c86566e74a3243e9fe3664cd87fa3299f"
EXPECTED_ARTIFACT_NAME = f"clue-jls2-public-validation-v2-{EXPECTED_RUN_ID}"
DECISION_NAME = "clue-jls2-public-validation-v2-first-score"
BUNDLE_NAME = "clue-jls2-public-validation-v2-first-score-bundle"
SHA256_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")
MIB = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(MIB):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def safe_relative_path(raw: str) -> Path:
    if raw.startswith("./"):
        raw = raw[2:]
    pure = PurePosixPath(raw)
    if not raw or pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ValueError(f"unsafe checksum path: {raw!r}")
    return Path(*pure.parts)


def parse_checksums(path: Path) -> dict[Path, str]:
    checksums: dict[Path, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = SHA256_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"malformed SHA256SUMS line {line_number}")
        relative = safe_relative_path(match.group(2))
        if relative == Path("SHA256SUMS"):
            raise ValueError("SHA256SUMS must not list itself")
        if relative in checksums:
            raise ValueError(f"duplicate checksum path: {relative.as_posix()}")
        checksums[relative] = match.group(1)
    if not checksums:
        raise ValueError("SHA256SUMS is empty")
    return checksums


def verify_complete_checksum_manifest(root: Path) -> dict[Path, str]:
    checksum_path = root / "SHA256SUMS"
    if not checksum_path.is_file() or checksum_path.is_symlink():
        raise ValueError("missing regular SHA256SUMS file")
    symlinks = [path for path in root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise ValueError(
            f"evidence contains a symlink: {symlinks[0].relative_to(root)}"
        )
    checksums = parse_checksums(checksum_path)
    actual_files = {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    listed_files = set(checksums)
    missing = sorted(listed_files - actual_files)
    unlisted = sorted(actual_files - listed_files)
    if missing:
        raise ValueError(f"checksum-listed file is missing: {missing[0].as_posix()}")
    if unlisted:
        raise ValueError(
            f"evidence contains an unlisted file: {unlisted[0].as_posix()}"
        )
    for relative, expected in checksums.items():
        actual = sha256_file(root / relative)
        if actual != expected:
            raise ValueError(f"checksum mismatch: {relative.as_posix()}")
    return checksums


def require_identical(left: Path, right: Path, description: str) -> None:
    if sha256_file(left) != sha256_file(right):
        raise ValueError(f"publication {description} differs from retained evidence")


def verify_publication_bundle(publication: Path) -> dict[str, Any]:
    bundle_path = publication / "bundle.json"
    bundle = load_json(bundle_path)
    if bundle.get("name") != BUNDLE_NAME:
        raise ValueError("unexpected publication bundle identity")
    if bundle.get("public_brand") != "Atompress":
        raise ValueError("unexpected public brand")
    if bundle.get("technical_codec") != "JLS2":
        raise ValueError("unexpected technical codec identity")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("publication bundle has no artifact map")
    for raw_name, expected in artifacts.items():
        if not isinstance(raw_name, str) or not isinstance(expected, str):
            raise ValueError("publication artifact map must contain string pairs")
        relative = safe_relative_path(raw_name)
        artifact = publication / relative
        if not artifact.is_file() or artifact.is_symlink():
            raise ValueError(f"publication artifact is missing: {raw_name}")
        if sha256_file(artifact) != expected:
            raise ValueError(f"publication artifact digest mismatch: {raw_name}")
    return bundle


def validate_evidence(
    root: Path,
    *,
    expected_gates: Path,
    expected_result: str,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"evidence directory does not exist: {root}")
    required = [
        "decision.json",
        "jls2/receipt.json",
        "jls2/performance/results.json",
        "pbc-result.json",
        "validation-manifest.json",
        "readiness-lock-receipt.json",
        "publication/bundle.json",
        "publication/decision.json",
        "publication/receipt.json",
        "publication/performance.json",
        "publication/pbc-result.json",
        "publication/validation-manifest.json",
        "publication/gates.json",
        "publication/README.md",
        "publication/comparison.svg",
    ]
    for relative in required:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required evidence is missing: {relative}")

    checksums = verify_complete_checksum_manifest(root)
    decision = load_json(root / "decision.json")
    publication = root / "publication"
    bundle = verify_publication_bundle(publication)
    if decision.get("name") != DECISION_NAME:
        raise ValueError("unexpected decision identity")
    if decision.get("result") != expected_result:
        raise ValueError(
            f"expected a {expected_result!r} result, got {decision.get('result')!r}"
        )
    if bundle.get("status") != decision.get("result"):
        raise ValueError("publication status differs from decision")
    if bundle.get("category_gate_passed") != decision.get("category_gate_passed"):
        raise ValueError("publication category decision differs from decision")

    sources = decision.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("decision has no source bindings")
    source_paths = {
        "receipt_sha256": root / "jls2" / "receipt.json",
        "performance_sha256": root / "jls2" / "performance" / "results.json",
        "pbc_sha256": root / "pbc-result.json",
        "gates_sha256": publication / "gates.json",
    }
    for key, path in source_paths.items():
        if sources.get(key) != sha256_file(path):
            raise ValueError(f"decision source binding failed: {key}")

    require_identical(root / "decision.json", publication / "decision.json", "decision")
    require_identical(
        root / "jls2" / "receipt.json",
        publication / "receipt.json",
        "receipt",
    )
    require_identical(
        root / "jls2" / "performance" / "results.json",
        publication / "performance.json",
        "performance result",
    )
    require_identical(
        root / "pbc-result.json",
        publication / "pbc-result.json",
        "PBC result",
    )
    require_identical(
        root / "validation-manifest.json",
        publication / "validation-manifest.json",
        "validation manifest",
    )
    require_identical(expected_gates.resolve(), publication / "gates.json", "gates")
    return {
        "decision": decision,
        "bundle": bundle,
        "file_count": len(checksums),
        "sha256sums_sha256": sha256_file(root / "SHA256SUMS"),
    }


def import_evidence(
    *,
    evidence: Path,
    output: Path,
    import_receipt: Path,
    expected_gates: Path,
    expected_result: str,
    repository: str,
    workflow_run_id: int,
    head_sha: str,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
) -> Path:
    if repository != EXPECTED_REPOSITORY:
        raise ValueError(f"unexpected repository: {repository}")
    if workflow_run_id != EXPECTED_RUN_ID:
        raise ValueError(f"unexpected workflow run: {workflow_run_id}")
    if head_sha != EXPECTED_HEAD_SHA:
        raise ValueError(f"unexpected workflow head SHA: {head_sha}")
    if artifact_id <= 0:
        raise ValueError("artifact ID must be positive")
    if artifact_name != EXPECTED_ARTIFACT_NAME:
        raise ValueError(f"unexpected artifact name: {artifact_name}")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest) is None:
        raise ValueError("artifact digest must be a lowercase sha256: digest")
    if output.exists():
        raise ValueError("refusing to replace an existing first-score import")
    if import_receipt.exists():
        raise ValueError("refusing to replace an existing import receipt")

    verified = validate_evidence(
        evidence,
        expected_gates=expected_gates,
        expected_result=expected_result,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    import_receipt.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-importing-", dir=output.parent)
    )
    temporary_receipt = import_receipt.with_name(f".{import_receipt.name}.tmp")
    if temporary_receipt.exists():
        shutil.rmtree(staging)
        raise ValueError("refusing to replace a pending import receipt")
    try:
        shutil.rmtree(staging)
        shutil.copytree(evidence, staging)
        copied = validate_evidence(
            staging,
            expected_gates=expected_gates,
            expected_result=expected_result,
        )
        if copied["sha256sums_sha256"] != verified["sha256sums_sha256"]:
            raise ValueError("copied evidence manifest differs from source")
        receipt = {
            "schema_version": 1,
            "name": "clue-jls2-public-validation-v2-first-score-import",
            "repository": repository,
            "workflow_run_id": workflow_run_id,
            "workflow_head_sha": head_sha,
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "artifact_digest": artifact_digest,
            "result": verified["decision"]["result"],
            "category_gate_passed": verified["decision"]["category_gate_passed"],
            "file_count_excluding_sha256sums": verified["file_count"],
            "sha256sums_sha256": verified["sha256sums_sha256"],
            "decision_sha256": sha256_file(staging / "decision.json"),
            "publication_bundle_sha256": sha256_file(
                staging / "publication/bundle.json"
            ),
            "claim_ceiling": verified["decision"]["claim_ceiling"],
        }
        temporary_receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staging.rename(output)
        try:
            temporary_receipt.replace(import_receipt)
        except BaseException:
            output.rename(staging)
            raise
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        if temporary_receipt.exists():
            temporary_receipt.unlink()
        raise
    return import_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "runs" / "clue-jls2-public-validation-v2",
    )
    parser.add_argument(
        "--import-receipt",
        type=Path,
        default=REPOSITORY / "runs" / "clue-jls2-public-validation-v2-import.json",
    )
    parser.add_argument(
        "--expected-gates",
        type=Path,
        default=REPOSITORY / "config" / "clue-jls2-public-validation-v2-gates.json",
    )
    parser.add_argument(
        "--expected-result", choices=("passed", "not_passed"), default="not_passed"
    )
    parser.add_argument("--repository", default=EXPECTED_REPOSITORY)
    parser.add_argument("--workflow-run-id", type=int, default=EXPECTED_RUN_ID)
    parser.add_argument("--head-sha", default=EXPECTED_HEAD_SHA)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-name", default=EXPECTED_ARTIFACT_NAME)
    parser.add_argument("--artifact-digest", required=True)
    args = parser.parse_args()
    try:
        receipt = import_evidence(
            evidence=args.evidence,
            output=args.output,
            import_receipt=args.import_receipt,
            expected_gates=args.expected_gates,
            expected_result=args.expected_result,
            repository=args.repository,
            workflow_run_id=args.workflow_run_id,
            head_sha=args.head_sha,
            artifact_id=args.artifact_id,
            artifact_name=args.artifact_name,
            artifact_digest=args.artifact_digest,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise SystemExit(f"CLUE-LDS v2 first-score import refused: {error}") from error
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
