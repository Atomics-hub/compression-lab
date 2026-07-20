#!/usr/bin/env python3
"""Verify a checked-in text/source structural publication without private run files."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any
from xml.etree import ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PUBLICATION = (
    REPOSITORY
    / "runs"
    / "text-source-structural-transform-development-v1"
    / "publication"
)
DEFAULT_BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)
EXPECTED_FILES = {
    "README.md",
    "comparison.json",
    "comparison.svg",
    "evidence.json",
    "receipt.json",
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLICATION = load_script(
    "text_source_structural_publication_verifier_dependency",
    REPOSITORY / "scripts" / "publish-text-source-structural-transform.py",
)
BASELINE_VERIFY = load_script(
    "text_source_baseline_verifier_for_structural_verifier",
    REPOSITORY / "scripts" / "verify-text-source-baseline-publication.py",
)


def read_canonical_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PUBLICATION.json_bytes(value):
        raise ValueError(f"publication artifact is not canonical JSON: {path.name}")
    return value


def verify(
    publication: Path,
    baseline_publication: Path = DEFAULT_BASELINE_PUBLICATION,
) -> dict[str, Any]:
    if publication.is_symlink() or not publication.is_dir():
        raise ValueError("publication must be an ordinary directory")
    observed = {path.name for path in publication.iterdir()}
    if observed != EXPECTED_FILES:
        raise ValueError("publication file roster is invalid")
    if any(path.is_symlink() or not path.is_file() for path in publication.iterdir()):
        raise ValueError("publication contains a non-ordinary artifact")

    receipt = read_canonical_json(publication / "receipt.json")
    comparison = read_canonical_json(publication / "comparison.json")
    evidence = read_canonical_json(publication / "evidence.json")
    if (
        type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or receipt.get("name")
        != "text-source-structural-transform-development-publication-receipt-v1"
        or set(receipt.get("artifacts", {})) != EXPECTED_FILES - {"receipt.json"}
    ):
        raise ValueError("publication receipt identity is invalid")
    for name, digest in receipt["artifacts"].items():
        if (
            not PUBLICATION.STRUCTURAL.is_sha256(digest)
            or PUBLICATION.sha256_file(publication / name) != digest
        ):
            raise ValueError(f"publication artifact digest differs: {name}")
    direct_fields = (
        "structural_results_sha256",
        "structural_trial_receipts_manifest_sha256",
        "baseline_results_sha256",
        "baseline_trial_receipts_manifest_sha256",
        "public_evidence_sha256",
        "baseline_public_evidence_sha256",
        "public_structural_trial_receipts_manifest_sha256",
        "bindings",
        "claim_ceiling",
    )
    if (
        comparison.get("name")
        != "text-source-structural-transform-development-publication-v1"
        or any(receipt.get(key) != comparison.get(key) for key in direct_fields)
        or evidence.get("structural_results_sha256")
        != comparison.get("structural_results_sha256")
        or evidence.get("raw_structural_trial_receipts_manifest_sha256")
        != comparison.get("structural_trial_receipts_manifest_sha256")
        or evidence.get("baseline_results_sha256")
        != comparison.get("baseline_results_sha256")
        or evidence.get("baseline_public_evidence_sha256")
        != comparison.get("baseline_public_evidence_sha256")
        or evidence.get("public_structural_trial_receipts_manifest_sha256")
        != comparison.get("public_structural_trial_receipts_manifest_sha256")
        or evidence.get("results", {}).get("bindings") != comparison.get("bindings")
        or PUBLICATION.sha256_file(publication / "evidence.json")
        != comparison.get("public_evidence_sha256")
    ):
        raise ValueError("publication cross-artifact binding is inconsistent")
    PUBLICATION.validate_public_evidence(evidence)
    BASELINE_VERIFY.verify(baseline_publication)
    baseline_evidence = read_canonical_json(baseline_publication / "evidence.json")
    baseline_public_evidence_sha256 = PUBLICATION.sha256_file(
        baseline_publication / "evidence.json"
    )
    if (
        baseline_evidence.get("raw_results_sha256")
        != evidence["baseline_results_sha256"]
        or baseline_public_evidence_sha256
        != evidence["baseline_public_evidence_sha256"]
    ):
        raise ValueError("structural baseline publication binding is inconsistent")
    failed_trial_count = sum(
        row["receipt"].get("passed") is not True for row in evidence["trials"]
    )
    expected_comparison = PUBLICATION.derive(
        evidence["results"],
        baseline_evidence["results"],
        structural_sha256=evidence["structural_results_sha256"],
        structural_receipts_sha256=evidence[
            "raw_structural_trial_receipts_manifest_sha256"
        ],
        baseline_sha256=evidence["baseline_results_sha256"],
        baseline_receipts_sha256=baseline_evidence[
            "raw_trial_receipts_manifest_sha256"
        ],
        public_evidence_sha256=PUBLICATION.sha256_file(
            publication / "evidence.json"
        ),
        baseline_public_evidence_sha256=baseline_public_evidence_sha256,
        public_receipts_sha256=evidence[
            "public_structural_trial_receipts_manifest_sha256"
        ],
        failed_trial_count=failed_trial_count,
    )
    if comparison != expected_comparison:
        raise ValueError("publication comparison does not reconstruct from evidence")
    expected_presentation = {
        "README.md": PUBLICATION.render_markdown(expected_comparison).encode("utf-8"),
        "comparison.svg": PUBLICATION.render_svg(expected_comparison).encode("utf-8"),
    }
    for name, expected in expected_presentation.items():
        if (publication / name).read_bytes() != expected:
            raise ValueError(f"publication presentation does not reconstruct: {name}")
    expected_receipt = {
        "schema_version": 1,
        "name": "text-source-structural-transform-development-publication-receipt-v1",
        "structural_results_sha256": expected_comparison[
            "structural_results_sha256"
        ],
        "structural_trial_receipts_manifest_sha256": expected_comparison[
            "structural_trial_receipts_manifest_sha256"
        ],
        "baseline_results_sha256": expected_comparison["baseline_results_sha256"],
        "baseline_trial_receipts_manifest_sha256": expected_comparison[
            "baseline_trial_receipts_manifest_sha256"
        ],
        "public_evidence_sha256": expected_comparison["public_evidence_sha256"],
        "baseline_public_evidence_sha256": expected_comparison[
            "baseline_public_evidence_sha256"
        ],
        "public_structural_trial_receipts_manifest_sha256": expected_comparison[
            "public_structural_trial_receipts_manifest_sha256"
        ],
        "bindings": expected_comparison["bindings"],
        "artifacts": {
            name: PUBLICATION.sha256_file(publication / name)
            for name in EXPECTED_FILES - {"receipt.json"}
        },
        "claim_ceiling": expected_comparison["claim_ceiling"],
    }
    if receipt != expected_receipt:
        raise ValueError("publication receipt does not reconstruct")
    ElementTree.fromstring((publication / "comparison.svg").read_bytes())
    return {
        "verified": True,
        "trial_count": comparison["trial_count"],
        "structural_results_sha256": comparison["structural_results_sha256"],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "claim_ceiling": comparison["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", nargs="?", type=Path, default=DEFAULT_PUBLICATION)
    parser.add_argument(
        "--baseline-publication",
        type=Path,
        default=DEFAULT_BASELINE_PUBLICATION,
    )
    args = parser.parse_args()
    try:
        result = verify(args.publication, args.baseline_publication)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"structural publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
