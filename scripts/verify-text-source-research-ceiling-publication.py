#!/usr/bin/env python3
"""Verify the public text/source research-frontier bundle without private files."""

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
    REPOSITORY / "runs" / "text-source-research-ceiling-publication-v1"
)


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLICATION = load_script(
    "research_frontier_publication_for_verifier",
    REPOSITORY / "scripts" / "publish-text-source-research-ceiling.py",
)


def canonical_embedded(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"embedded {name} is not an object")
    if json.loads(PUBLICATION.json_bytes(value)) != value:
        raise ValueError(f"embedded {name} is not JSON-safe")
    return value


def verify(publication: Path, baseline_publication: Path) -> dict[str, Any]:
    if publication.is_symlink() or not publication.is_dir():
        raise ValueError("publication must be an ordinary directory")
    if {path.name for path in publication.iterdir()} != PUBLICATION.EXPECTED_FILES:
        raise ValueError("publication file roster is invalid")
    if any(path.is_symlink() or not path.is_file() for path in publication.iterdir()):
        raise ValueError("publication contains a non-ordinary artifact")
    receipt = PUBLICATION.read_canonical_json(publication / "receipt.json")
    comparison = PUBLICATION.read_canonical_json(publication / "comparison.json")
    evidence = PUBLICATION.read_canonical_json(publication / "evidence.json")
    if (
        receipt.get("name")
        != "text-source-development-research-frontier-publication-receipt-v1"
        or type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or set(receipt.get("artifacts", {}))
        != PUBLICATION.EXPECTED_FILES - {"receipt.json"}
        or comparison.get("name")
        != "text-source-development-research-frontier-publication-v1"
        or evidence.get("name")
        != "text-source-development-research-frontier-public-evidence-v1"
    ):
        raise ValueError("publication identity is invalid")
    for name, digest in receipt["artifacts"].items():
        if PUBLICATION.sha256_file(publication / name) != digest:
            raise ValueError(f"publication artifact digest differs: {name}")
    plan = canonical_embedded(evidence.get("plan"), "plan")
    aggregate = canonical_embedded(evidence.get("aggregate"), "aggregate")
    baseline = canonical_embedded(
        evidence.get("baseline_comparison"), "baseline comparison"
    )
    baseline_receipt = canonical_embedded(
        evidence.get("baseline_receipt"), "baseline receipt"
    )
    PUBLICATION.BASELINE_VERIFY.verify(baseline_publication)
    checked_baseline = PUBLICATION.read_canonical_json(
        baseline_publication / "comparison.json"
    )
    checked_baseline_receipt = PUBLICATION.read_canonical_json(
        baseline_publication / "receipt.json"
    )
    if baseline != checked_baseline or baseline_receipt != checked_baseline_receipt:
        raise ValueError("embedded practical evidence differs from checked publication")
    expected_evidence_keys = {
        "schema_version",
        "name",
        "plan_sha256",
        "aggregate_sha256",
        "baseline_comparison_sha256",
        "baseline_receipt_sha256",
        "plan",
        "aggregate",
        "baseline_comparison",
        "baseline_receipt",
        "evidence_boundary",
    }
    if (
        set(evidence) != expected_evidence_keys
        or type(evidence.get("schema_version")) is not int
        or evidence["schema_version"] != 1
        or PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(plan))
        != evidence["plan_sha256"]
        or PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(aggregate))
        != evidence["aggregate_sha256"]
        or PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(baseline))
        != evidence["baseline_comparison_sha256"]
        or PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(baseline_receipt))
        != evidence["baseline_receipt_sha256"]
    ):
        raise ValueError("embedded evidence digest or field roster differs")
    for key in (
        "plan_sha256",
        "aggregate_sha256",
        "baseline_comparison_sha256",
        "baseline_receipt_sha256",
    ):
        if receipt.get(key) != evidence[key] or comparison.get(key) != evidence[key]:
            raise ValueError(f"publication binding differs: {key}")
    evidence_sha256 = PUBLICATION.sha256_file(publication / "evidence.json")
    if (
        receipt.get("evidence_sha256") != evidence_sha256
        or comparison.get("evidence_sha256") != evidence_sha256
        or receipt.get("claim_ceiling") != comparison.get("claim_ceiling")
    ):
        raise ValueError("publication evidence or claim binding differs")
    if (
        baseline_receipt.get("results_sha256") != baseline.get("results_sha256")
        or baseline_receipt.get("claim_ceiling") != baseline.get("claim_ceiling")
    ):
        raise ValueError("embedded practical publication binding differs")
    expected_comparison = PUBLICATION.derive(
        plan=plan,
        aggregate=aggregate,
        baseline=baseline,
        plan_sha256=evidence["plan_sha256"],
        aggregate_sha256=evidence["aggregate_sha256"],
        baseline_comparison_sha256=evidence["baseline_comparison_sha256"],
        baseline_receipt_sha256=evidence["baseline_receipt_sha256"],
        evidence_sha256=evidence_sha256,
    )
    if comparison != expected_comparison:
        raise ValueError("comparison does not reconstruct from public evidence")
    if (publication / "README.md").read_bytes() != PUBLICATION.render_markdown(
        comparison
    ).encode("utf-8"):
        raise ValueError("publication README does not reconstruct")
    if (publication / "comparison.svg").read_bytes() != PUBLICATION.render_svg(
        comparison
    ).encode("utf-8"):
        raise ValueError("publication SVG does not reconstruct")
    expected_receipt = {
        "schema_version": 1,
        "name": "text-source-development-research-frontier-publication-receipt-v1",
        "plan_sha256": evidence["plan_sha256"],
        "aggregate_sha256": evidence["aggregate_sha256"],
        "baseline_comparison_sha256": evidence[
            "baseline_comparison_sha256"
        ],
        "baseline_receipt_sha256": evidence["baseline_receipt_sha256"],
        "evidence_sha256": evidence_sha256,
        "artifacts": {
            name: PUBLICATION.sha256_file(publication / name)
            for name in PUBLICATION.EXPECTED_FILES - {"receipt.json"}
        },
        "claim_ceiling": expected_comparison["claim_ceiling"],
    }
    if receipt != expected_receipt:
        raise ValueError("publication receipt does not reconstruct")
    ElementTree.fromstring((publication / "comparison.svg").read_bytes())
    return {
        "verified": True,
        "track_count": len(comparison["tracks"]),
        "trial_count": comparison["trial_count"],
        "research_ceiling_complete": comparison["research_ceiling_complete"],
        "axiom_wins": comparison["integrity"]["axiom_wins"],
        "publication_receipt_sha256": PUBLICATION.sha256_file(
            publication / "receipt.json"
        ),
        "claim_ceiling": comparison["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", nargs="?", type=Path, default=DEFAULT_PUBLICATION)
    parser.add_argument(
        "--baseline-publication",
        type=Path,
        default=PUBLICATION.DEFAULT_BASELINE_PUBLICATION,
    )
    args = parser.parse_args()
    try:
        result = verify(args.publication, args.baseline_publication)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        ElementTree.ParseError,
    ) as error:
        raise SystemExit(f"research-frontier publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
