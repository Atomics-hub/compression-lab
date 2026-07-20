#!/usr/bin/env python3
"""Strictly verify the immutable offline JLS2 A3 rejection publication."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = (
    ROOT / "scripts" / "publish-jls2-declared-size-lifetime-a3-attribution.py"
)
EXPECTED_PUBLISHER_SHA256 = (
    "e3f9c29e230c3d8cbe12a782205e68ca4ab00b78e9e10c25d4823fc807abf334"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_publisher() -> Any:
    if sha256_file(PUBLISHER) != EXPECTED_PUBLISHER_SHA256:
        raise RuntimeError("frozen JLS2 A3 publisher drifted")
    spec = importlib.util.spec_from_file_location("jls2_a3_publisher", PUBLISHER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen JLS2 A3 publisher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value


def verify(publication: Path) -> None:
    publisher = load_publisher()
    if publication.is_symlink() or not publication.is_dir():
        raise ValueError("publication must be a regular non-symlink directory")
    observed = {entry.name for entry in publication.iterdir()}
    if observed != publisher.PUBLICATION_ROSTER:
        raise ValueError(
            "publication roster mismatch; "
            f"missing={sorted(publisher.PUBLICATION_ROSTER - observed)}, "
            f"extra={sorted(observed - publisher.PUBLICATION_ROSTER)}"
        )
    for name in publisher.PUBLICATION_ROSTER:
        path = publication / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"publication member is not a regular file: {name}")
    for name, expected in publisher.EXPECTED_INPUT_SHA256.items():
        observed_digest = publisher.sha256_file(publication / name)
        if observed_digest != expected:
            raise ValueError(f"raw publication member digest mismatch: {name}")
    result = load_json(publication / "results.json")
    publisher.RAW.validate_result(result)
    summary = publisher.recompute(result)
    expected_comparison = publisher.build_comparison(result, summary)
    comparison = load_json(publication / "comparison.json")
    publisher.require_exact_keys(
        comparison,
        {
            "schema_version",
            "name",
            "decision",
            "product_ab_authorized",
            "claim_scope",
            "claim_ceiling",
            "threshold_bytes",
            "metric_rows",
            "fixture_rows",
            "integrity",
            "evidence_level",
            "runner_comparability",
        },
        "comparison",
    )
    publisher.require_exact_keys(
        comparison["integrity"],
        {
            "all_decodes_exact",
            "two_generation_topology_identical",
            "encoded_lifetime_credit_bytes",
            "format_encoder_selector_changed",
        },
        "comparison integrity",
    )
    for index, row in enumerate(comparison["metric_rows"]):
        publisher.require_exact_keys(
            row,
            {
                "metric",
                "observed_bytes",
                "threshold_bytes",
                "shortfall_bytes",
                "percent_of_threshold",
                "gate_passed",
            },
            f"comparison metric row {index}",
        )
    for index, row in enumerate(comparison["fixture_rows"]):
        publisher.require_exact_keys(
            row,
            {
                "fixture_id",
                "minimum_potential_bytes",
                "minimum_rss_reduction_bytes",
                "minimum_credited_bytes",
            },
            f"comparison fixture row {index}",
        )
    if comparison != expected_comparison:
        raise ValueError("comparison does not recompute exactly from raw evidence")
    if (publication / "comparison.svg").read_text(
        encoding="utf-8"
    ) != publisher.render_svg(expected_comparison):
        raise ValueError("comparison SVG is not the deterministic rendering")
    if (publication / "README.md").read_text(
        encoding="utf-8"
    ) != publisher.render_readme(expected_comparison):
        raise ValueError("README is not the deterministic rendering")
    receipt = load_json(publication / "receipt.json")
    publisher.require_exact_keys(
        receipt,
        {
            "schema_version",
            "name",
            "decision",
            "product_ab_authorized",
            "claim_ceiling",
            "source_artifact",
            "a2_identity",
            "summary",
            "publication_dependencies_sha256",
            "publication_files_sha256",
            "validation_accessed",
            "holdout_accessed",
        },
        "receipt",
    )
    publisher.require_exact_keys(
        receipt["source_artifact"],
        {
            "run_id",
            "job_id",
            "run_attempt",
            "run_conclusion",
            "artifact_id",
            "artifact_name",
            "artifact_digest",
            "workflow_head",
            "embedded_workflow_commit",
            "input_roster_sha256",
        },
        "receipt source artifact",
    )
    expected_source = {
        "run_id": publisher.EXPECTED_RUN_ID,
        "job_id": publisher.EXPECTED_JOB_ID,
        "run_attempt": publisher.EXPECTED_RUN_ATTEMPT,
        "run_conclusion": publisher.EXPECTED_RUN_CONCLUSION,
        "artifact_id": publisher.EXPECTED_ARTIFACT_ID,
        "artifact_name": publisher.EXPECTED_ARTIFACT_NAME,
        "artifact_digest": publisher.EXPECTED_ARTIFACT_DIGEST,
        "workflow_head": publisher.EXPECTED_WORKFLOW_HEAD,
        "embedded_workflow_commit": publisher.EXPECTED_EMBEDDED_WORKFLOW_COMMIT,
        "input_roster_sha256": publisher.EXPECTED_INPUT_SHA256,
    }
    if receipt["source_artifact"] != expected_source:
        raise ValueError("receipt source-artifact identity mismatch")
    if receipt["schema_version"] != 1:
        raise ValueError("receipt schema version mismatch")
    if receipt["name"] != f"{publisher.PUBLISHER_NAME}-receipt":
        raise ValueError("receipt name mismatch")
    if receipt["decision"] != "rejected" or receipt["product_ab_authorized"]:
        raise ValueError("receipt decision or product authorization mismatch")
    if receipt["claim_ceiling"] != result["claim_ceiling"]:
        raise ValueError("receipt claim ceiling mismatch")
    if receipt["a2_identity"] != result["a2_identity"]:
        raise ValueError("receipt A2 identity mismatch")
    if receipt["summary"] != summary:
        raise ValueError("receipt summary mismatch")
    expected_dependencies = {
        "publisher": publisher.sha256_file(PUBLISHER),
        "raw_verifier": publisher.RAW_VERIFIER_SHA256,
        "raw_contract": publisher.RAW_CONTRACT_SHA256,
        "protocol": publisher.PROTOCOL_SHA256,
    }
    if receipt["publication_dependencies_sha256"] != expected_dependencies:
        raise ValueError("receipt publication dependency identity mismatch")
    if receipt["validation_accessed"] or receipt["holdout_accessed"]:
        raise ValueError("receipt reports forbidden evaluation access")
    expected_file_keys = publisher.PUBLICATION_ROSTER - {"receipt.json"}
    if set(receipt["publication_files_sha256"]) != expected_file_keys:
        raise ValueError("receipt publication-file roster mismatch")
    for name, expected in receipt["publication_files_sha256"].items():
        if not isinstance(expected, str) or publisher.SHA256_PATTERN.fullmatch(
            expected
        ) is None:
            raise ValueError(f"receipt file digest is invalid: {name}")
        if publisher.sha256_file(publication / name) != expected:
            raise ValueError(f"receipt file digest mismatch: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", type=Path)
    args = parser.parse_args()
    verify(args.publication)
    print(f"verified {args.publication}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
