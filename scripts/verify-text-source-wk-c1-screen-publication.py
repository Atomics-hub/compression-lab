#!/usr/bin/env python3
"""Verify a WK-C1 publication entirely offline."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLICATION = ROOT / "runs" / "text-source-wk-c1-screen-v1" / "publication"


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


PUBLICATION = load_script(
    "wk_c1_publication_for_offline_verifier",
    ROOT / "scripts" / "publish-text-source-wk-c1-screen.py",
)


def read_canonical(path: Path) -> dict[str, Any]:
    _raw, value = PUBLICATION.read_canonical(path)
    return value


def verify(publication: Path) -> dict[str, Any]:
    PUBLICATION.validate_dependencies()
    if publication.is_symlink() or not publication.is_dir():
        raise ValueError("WK-C1 publication must be an ordinary directory")
    entries = list(publication.iterdir())
    if {path.name for path in entries} != PUBLICATION.EXPECTED_FILES:
        raise ValueError("WK-C1 publication file roster differs")
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("WK-C1 publication contains a non-ordinary artifact")

    receipt = read_canonical(publication / "receipt.json")
    PUBLICATION.require_keys(
        receipt,
        {
            "schema_version",
            "name",
            "result_sha256",
            "public_evidence_sha256",
            "trial_receipts_manifest_sha256",
            "frozen_dependencies",
            "decision",
            "axiom_wins",
            "claim_ceiling",
            "artifacts",
        },
        "WK-C1 publication receipt",
    )
    if (
        receipt["schema_version"] != 1
        or receipt["name"] != "text-source-wk-c1-publication-receipt-v1"
        or receipt["frozen_dependencies"] != PUBLICATION.FROZEN_DEPENDENCIES
        or receipt["axiom_wins"] != 0
        or not isinstance(receipt["artifacts"], dict)
        or set(receipt["artifacts"])
        != PUBLICATION.EXPECTED_FILES - {"receipt.json"}
    ):
        raise ValueError("WK-C1 publication receipt identity differs")
    for name, digest in receipt["artifacts"].items():
        PUBLICATION.require_sha256(digest, f"artifact digest {name}")
        if PUBLICATION.sha256_file(publication / name) != digest:
            raise ValueError(f"WK-C1 publication artifact digest differs: {name}")

    evidence = read_canonical(publication / "evidence.json")
    PUBLICATION.validate_evidence(evidence)
    results_raw, results = PUBLICATION.read_canonical(publication / "results.json")
    if results != evidence["results"] or PUBLICATION.sha256_bytes(results_raw) != evidence["result_sha256"]:
        raise ValueError("WK-C1 copied result differs from public evidence")
    evidence_sha256 = PUBLICATION.sha256_file(publication / "evidence.json")
    comparison = read_canonical(publication / "comparison.json")
    expected_comparison = PUBLICATION.derive(
        evidence["config"],
        evidence["results"],
        [row["receipt"] for row in evidence["trials"]],
        result_sha256=evidence["result_sha256"],
        evidence_sha256=evidence_sha256,
    )
    if comparison != expected_comparison:
        raise ValueError("WK-C1 comparison does not reconstruct from evidence")
    if (publication / "README.md").read_text(encoding="utf-8") != PUBLICATION.render_markdown(comparison):
        raise ValueError("WK-C1 README does not reconstruct")
    expected_svg = PUBLICATION.render_svg(comparison)
    if (publication / "comparison.svg").read_text(encoding="utf-8") != expected_svg:
        raise ValueError("WK-C1 chart does not reconstruct")
    ElementTree.fromstring(expected_svg.encode("utf-8"))

    expected_receipt = {
        "schema_version": 1,
        "name": "text-source-wk-c1-publication-receipt-v1",
        "result_sha256": comparison["result_sha256"],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "trial_receipts_manifest_sha256": evidence["trial_receipts_manifest_sha256"],
        "frozen_dependencies": PUBLICATION.FROZEN_DEPENDENCIES,
        "decision": comparison["decision"],
        "axiom_wins": 0,
        "claim_ceiling": comparison["claim_ceiling"],
        "artifacts": {
            name: PUBLICATION.sha256_file(publication / name)
            for name in PUBLICATION.EXPECTED_FILES - {"receipt.json"}
        },
    }
    if receipt != expected_receipt:
        raise ValueError("WK-C1 publication receipt does not reconstruct")
    return {
        "verified": True,
        "offline": True,
        "trial_count": 8,
        "comparison_rows": 4,
        "decision": comparison["decision"],
        "rejected": comparison["rejected"],
        "full_signal": comparison["gates"]["full_signal"],
        "full_strong_signal": comparison["gates"]["full_strong_signal"],
        "axiom_wins": 0,
        "result_sha256": comparison["result_sha256"],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "claim_ceiling": comparison["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", nargs="?", type=Path, default=DEFAULT_PUBLICATION)
    args = parser.parse_args()
    try:
        result = verify(args.publication)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"WK-C1 publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
