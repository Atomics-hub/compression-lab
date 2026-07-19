#!/usr/bin/env python3
"""Verify the BWT screen publication entirely offline."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any
from xml.etree import ElementTree


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PUBLICATION = REPOSITORY / "runs" / "text-source-bwt-screen-v1" / "publication"
EXPECTED_FILES = {
    "README.md",
    "comparison.json",
    "comparison.svg",
    "evidence.json",
    "receipt.json",
}


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


PUBLICATION = load_script(
    "bwt_publication_for_offline_verifier",
    REPOSITORY / "scripts" / "publish-text-source-bwt-screen.py",
)


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"publication artifact is not an ordinary file: {path.name}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PUBLICATION.json_bytes(value):
        raise ValueError(f"publication artifact is not canonical JSON: {path.name}")
    return value


def verify(publication: Path) -> dict[str, Any]:
    if publication.is_symlink() or not publication.is_dir():
        raise ValueError("publication must be an ordinary directory")
    if {path.name for path in publication.iterdir()} != EXPECTED_FILES:
        raise ValueError("publication file roster is invalid")
    if any(path.is_symlink() or not path.is_file() for path in publication.iterdir()):
        raise ValueError("publication contains a non-ordinary artifact")

    receipt = read_canonical_json(publication / "receipt.json")
    comparison = read_canonical_json(publication / "comparison.json")
    evidence = read_canonical_json(publication / "evidence.json")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("name")
        != "text-source-bwt-kanzi-decomposition-publication-receipt-v1"
        or set(receipt.get("artifacts", {})) != EXPECTED_FILES - {"receipt.json"}
        or receipt.get("axiom_wins") != 0
    ):
        raise ValueError("BWT publication receipt identity is invalid")
    for name, digest in receipt["artifacts"].items():
        if PUBLICATION.sha256_file(publication / name) != digest:
            raise ValueError(f"BWT publication artifact digest differs: {name}")

    PUBLICATION.validate_public_evidence(evidence)
    if (
        PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(evidence["results"]))
        != evidence["result_sha256"]
        or PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(evidence["config"]))
        != evidence["config_sha256"]
        or PUBLICATION.sha256_file(publication / "evidence.json")
        != comparison.get("public_evidence_sha256")
    ):
        raise ValueError("BWT publication evidence binding is inconsistent")
    expected_run_verification = PUBLICATION.reconstruct_run_verification(evidence)
    if evidence.get("run_verification") != expected_run_verification:
        raise ValueError("BWT publication run verification does not reconstruct")

    expected_comparison = PUBLICATION.derive(
        evidence["results"],
        result_sha256=evidence["result_sha256"],
        receipts_sha256=evidence["raw_trial_receipts_manifest_sha256"],
        public_evidence_sha256=PUBLICATION.sha256_file(publication / "evidence.json"),
    )
    if comparison != expected_comparison:
        raise ValueError("BWT publication comparison does not reconstruct from evidence")
    expected_presentation = {
        "README.md": PUBLICATION.render_markdown(expected_comparison).encode("utf-8"),
        "comparison.svg": PUBLICATION.render_svg(expected_comparison).encode("utf-8"),
    }
    for name, expected in expected_presentation.items():
        if (publication / name).read_bytes() != expected:
            raise ValueError(f"BWT publication presentation does not reconstruct: {name}")

    expected_receipt = {
        "schema_version": 1,
        "name": "text-source-bwt-kanzi-decomposition-publication-receipt-v1",
        "result_sha256": expected_comparison["result_sha256"],
        "trial_receipts_manifest_sha256": expected_comparison[
            "trial_receipts_manifest_sha256"
        ],
        "public_evidence_sha256": expected_comparison["public_evidence_sha256"],
        "bindings": expected_comparison["bindings"],
        "artifacts": {
            name: PUBLICATION.sha256_file(publication / name)
            for name in EXPECTED_FILES - {"receipt.json"}
        },
        "axiom_wins": 0,
        "claim_ceiling": expected_comparison["claim_ceiling"],
    }
    if receipt != expected_receipt:
        raise ValueError("BWT publication receipt does not reconstruct")
    ElementTree.fromstring((publication / "comparison.svg").read_bytes())
    return {
        "verified": True,
        "offline": True,
        "trial_count": expected_run_verification["trial_count"],
        "track_count": len(expected_comparison["tracks"]),
        "comparison_rows_per_track": 5,
        "diagnostics_per_track": 4,
        "all_diagnostic_gains_negative": True,
        "track_decisions": expected_comparison["track_decisions"],
        "axiom_wins": 0,
        "decision": expected_comparison["decision"],
        "result_sha256": expected_comparison["result_sha256"],
        "public_evidence_sha256": expected_comparison["public_evidence_sha256"],
        "claim_ceiling": expected_comparison["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", nargs="?", type=Path, default=DEFAULT_PUBLICATION)
    args = parser.parse_args()
    try:
        result = verify(args.publication)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"BWT publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
