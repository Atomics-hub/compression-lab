#!/usr/bin/env python3
"""Verify the checked-in predictor ceiling publication without its corpus."""

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
    REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-publication-v1"
)
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
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
    "predictor_ceiling_publication_verifier_dependency",
    REPOSITORY / "scripts" / "publish-text-source-predictor-ceiling.py",
)


def read_canonical_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PUBLICATION.json_bytes(value):
        raise ValueError(f"publication artifact is not canonical JSON: {path.name}")
    return raw, value


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def verify(
    publication: Path,
    baseline_path: Path = DEFAULT_BASELINE,
) -> dict[str, Any]:
    if publication.is_symlink() or not publication.is_dir():
        raise ValueError("publication must be an ordinary directory")
    observed = {path.name for path in publication.iterdir()}
    if observed != EXPECTED_FILES:
        raise ValueError("publication file roster is invalid")
    if any(path.is_symlink() or not path.is_file() for path in publication.iterdir()):
        raise ValueError("publication contains a non-ordinary artifact")

    _receipt_raw, receipt = read_canonical_json(publication / "receipt.json")
    comparison_raw, comparison = read_canonical_json(publication / "comparison.json")
    evidence_raw, evidence = read_canonical_json(publication / "evidence.json")
    baseline_raw, baseline = read_canonical_json(baseline_path)
    if (
        type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or receipt.get("name")
        != "text-source-predictor-entropy-ceiling-publication-receipt-v1"
        or set(receipt.get("artifacts", {})) != EXPECTED_FILES - {"receipt.json"}
    ):
        raise ValueError("publication receipt identity is invalid")
    for name, digest in receipt["artifacts"].items():
        if (
            not is_sha256(digest)
            or PUBLICATION.sha256_bytes((publication / name).read_bytes()) != digest
        ):
            raise ValueError(f"publication artifact digest differs: {name}")
    if (
        evidence.get("name")
        != "text-source-predictor-entropy-ceiling-public-evidence-v1"
        or evidence.get("result_sha256")
        != PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(evidence.get("result")))
        or evidence.get("config_sha256")
        != PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(evidence.get("config")))
        or evidence.get("baseline_results_sha256")
        != PUBLICATION.sha256_bytes(baseline_raw)
        or evidence.get("result_verification", {}).get("verified") is not True
        or evidence.get("result_verification", {}).get("axiom_wins") != 0
        or evidence.get("result_verification", {}).get("full_codec_build_admissions")
        != 0
    ):
        raise ValueError("publication evidence binding is inconsistent")
    PUBLICATION.BASELINE_PUBLICATION.validate_trial_receipts(baseline_path, baseline)

    expected_comparison = PUBLICATION.derive(evidence["result"], baseline)
    expected_comparison["result_sha256"] = evidence["result_sha256"]
    expected_comparison["public_evidence_sha256"] = PUBLICATION.sha256_bytes(
        evidence_raw
    )
    if comparison_raw != PUBLICATION.json_bytes(expected_comparison):
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
        "name": "text-source-predictor-entropy-ceiling-publication-receipt-v1",
        "result_sha256": expected_comparison["result_sha256"],
        "public_evidence_sha256": expected_comparison["public_evidence_sha256"],
        "artifacts": {
            name: PUBLICATION.sha256_bytes((publication / name).read_bytes())
            for name in EXPECTED_FILES - {"receipt.json"}
        },
        "claim_ceiling": expected_comparison["claim_ceiling"],
    }
    if receipt != expected_receipt:
        raise ValueError("publication receipt does not reconstruct")
    ElementTree.fromstring((publication / "comparison.svg").read_bytes())
    return {
        "verified": True,
        "track_count": len(comparison["tracks"]),
        "practical_codec_count_per_track": 15,
        "axiom_estimate_count_per_track": 3,
        "result_sha256": comparison["result_sha256"],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "axiom_wins": comparison["integrity"]["axiom_wins"],
        "claim_ceiling": comparison["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", nargs="?", type=Path, default=DEFAULT_PUBLICATION)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    try:
        result = verify(args.publication, args.baseline)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"predictor publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
