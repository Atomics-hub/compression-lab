#!/usr/bin/env python3
"""Verify the record-neighborhood publication without the private run tree."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PUBLICATION = (
    REPOSITORY
    / "runs"
    / "text-source-record-neighborhood-screen-v1"
    / "publication"
)
DEFAULT_BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


PUBLICATION = load_script(
    "record_neighborhood_publication_for_verification",
    REPOSITORY / "scripts" / "publish-text-source-record-neighborhood-screen.py",
)


def verify(publication: Path, baseline_publication: Path) -> dict[str, Any]:
    if (
        publication.is_symlink()
        or not publication.is_dir()
        or {path.name for path in publication.iterdir()} != PUBLICATION.EXPECTED_FILES
        or any(path.is_symlink() for path in publication.iterdir())
    ):
        raise ValueError("record-neighborhood publication file roster differs")
    _evidence_raw, evidence = PUBLICATION.read_canonical(
        publication / "evidence.json"
    )
    _comparison_raw, comparison = PUBLICATION.read_canonical(
        publication / "comparison.json"
    )
    _receipt_raw, receipt = PUBLICATION.read_canonical(publication / "receipt.json")
    _baseline_raw, baseline_evidence = PUBLICATION.read_canonical(
        baseline_publication / "evidence.json"
    )
    PUBLICATION.validate_public_evidence(evidence)
    if (
        evidence.get("baseline_public_evidence_sha256")
        != PUBLICATION.sha256_file(baseline_publication / "evidence.json")
        or evidence.get("baseline_results_sha256")
        != baseline_evidence.get("raw_results_sha256")
        or not isinstance(baseline_evidence.get("results"), dict)
    ):
        raise ValueError("record-neighborhood baseline publication binding differs")
    expected_comparison = PUBLICATION.derive(
        evidence["results"],
        baseline_evidence["results"],
        evidence["structural_control_rows"],
        result_sha256=evidence["result_sha256"],
        receipts_sha256=evidence["raw_trial_receipts_manifest_sha256"],
        baseline_results_sha256=evidence["baseline_results_sha256"],
        baseline_public_evidence_sha256=evidence[
            "baseline_public_evidence_sha256"
        ],
        public_evidence_sha256=PUBLICATION.sha256_file(
            publication / "evidence.json"
        ),
    )
    if comparison != expected_comparison:
        raise ValueError("record-neighborhood comparison does not reconstruct")
    if (publication / "README.md").read_text(encoding="utf-8") != PUBLICATION.render_markdown(
        comparison
    ) or (publication / "comparison.svg").read_text(
        encoding="utf-8"
    ) != PUBLICATION.render_svg(comparison):
        raise ValueError("record-neighborhood rendered publication differs")
    expected_artifacts = {
        name: PUBLICATION.sha256_file(publication / name)
        for name in PUBLICATION.EXPECTED_FILES
        if name != "receipt.json"
    }
    if (
        receipt.get("name")
        != "text-source-record-neighborhood-publication-receipt-v1"
        or receipt.get("schema_version") != 1
        or receipt.get("artifacts") != expected_artifacts
        or receipt.get("result_sha256") != comparison["result_sha256"]
        or receipt.get("public_evidence_sha256")
        != comparison["public_evidence_sha256"]
        or receipt.get("trial_receipts_manifest_sha256")
        != comparison["trial_receipts_manifest_sha256"]
        or receipt.get("bindings") != comparison["bindings"]
        or receipt.get("claim_ceiling") != comparison["claim_ceiling"]
    ):
        raise ValueError("record-neighborhood publication receipt differs")
    standards = [
        sum(row["kind"] == "practical_baseline" for row in track["rows"])
        for track in comparison["tracks"]
    ]
    candidates = [
        sum(row["kind"] == "axiom_experimental_candidate" for row in track["rows"])
        for track in comparison["tracks"]
    ]
    if standards != [15, 15] or candidates != [1, 1]:
        raise ValueError("record-neighborhood comparison roster differs")
    return {
        "axiom_prototype_admitted": comparison["integrity"][
            "axiom_prototype_admitted"
        ],
        "axiom_wins": comparison["integrity"]["axiom_wins"],
        "candidates_per_track": 1,
        "claim_ceiling": comparison["claim_ceiling"],
        "decision": comparison["decision"],
        "standards_per_track": 15,
        "trial_count": comparison["integrity"]["trial_count"],
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, default=DEFAULT_PUBLICATION)
    parser.add_argument(
        "--baseline-publication", type=Path, default=DEFAULT_BASELINE_PUBLICATION
    )
    args = parser.parse_args()
    try:
        result = verify(args.publication, args.baseline_publication)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"record-neighborhood publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
