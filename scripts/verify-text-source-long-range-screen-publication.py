#!/usr/bin/env python3
"""Verify the long-range screen publication without corpus or private run files."""

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
    REPOSITORY / "runs" / "text-source-long-range-screen-v1" / "publication"
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
    "long_range_publication_verifier_dependency",
    REPOSITORY / "scripts" / "publish-text-source-long-range-screen.py",
)
BASELINE_VERIFY = load_script(
    "baseline_verifier_for_long_range_publication",
    REPOSITORY / "scripts" / "verify-text-source-baseline-publication.py",
)
RUN_VERIFY = load_script(
    "run_verifier_for_long_range_publication",
    REPOSITORY / "scripts" / "verify-text-source-long-range-screen-run.py",
)


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"publication artifact is not an ordinary file: {path.name}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PUBLICATION.json_bytes(value):
        raise ValueError(f"publication artifact is not canonical JSON: {path.name}")
    return value


def reconstruct_run_verification(evidence: dict[str, Any]) -> dict[str, Any]:
    result = evidence["results"]
    summary = result["summary"]
    config = evidence["config"]
    RUN_VERIFY.validate_preflight(result.get("preflight"), config)
    if (
        result.get("name")
        != "text-source-long-range-kanzi-decomposition-screen-result-v1"
        or result.get("completed") is not True
        or result.get("all_required_completed") is not True
        or result.get("trial_count") != len(evidence["trials"])
        or result.get("measurement") != config["measurement"]
        or result.get("variants") != config["variants"]
        or result.get("screen_boundary")
        != {track: config["splits"][track] for track in PUBLICATION.RUNNER.TRACKS}
        or result.get("claim_ceiling") != config["claim_ceiling"]
        or result.get("public_validation_status") != "sealed and unaccessed"
        or result.get("private_holdout_status") != "sealed and unaccessed"
        or result["bindings"].get("config_sha256") != evidence["config_sha256"]
        or summary.get("decision")
        != "reject_shared_implicit_long_range_factorization_direction"
        or summary.get("axiom_prototype_admitted") is not False
        or summary.get("axiom_wins") != 0
    ):
        raise ValueError("public long-range result identity or decision differs")
    receipts = [row["receipt"] for row in evidence["trials"]]
    expected_pairs = {
        (variant["id"], item_id, repetition)
        for variant in config["variants"]
        for track in PUBLICATION.RUNNER.TRACKS
        for item_id in config["splits"][track]["screen_items"]
        for repetition in range(config["measurement"]["measured_repetitions"])
    }
    observed_pairs = {
        (row.get("variant"), row.get("item_id"), row.get("repetition"))
        for row in receipts
    }
    if observed_pairs != expected_pairs or len(receipts) != len(expected_pairs):
        raise ValueError("public long-range trial roster differs")
    for row in receipts:
        if (
            row.get("bindings") != result["bindings"]
            or row.get("passed") is not True
            or row.get("exact_roundtrip") is not True
            or row.get("error") is not None
            or row.get("compression", {}).get("returncode") != 0
            or row.get("decompression", {}).get("returncode") != 0
            or row.get("compression", {}).get("timed_out") is not False
            or row.get("decompression", {}).get("timed_out") is not False
        ):
            raise ValueError("public long-range successful trial differs")
    # Recompute every result summary field from the public receipts and the
    # already-published item rows; no corpus paths or executable are needed.
    item_metadata = {}
    for row in summary["item_rows"]:
        item_metadata[row["item_id"]] = {
            "id": row["item_id"],
            "track": row["track"],
            "source_bytes": row["source_bytes"],
        }
    baseline_map = {
        row["item_id"]: row["baseline_bytes"] for row in summary["item_rows"]
    }
    pseudo_baseline = {
        "summary": {
            "item_codec_rows": [
                {
                    "codec_id": "kanzi-max",
                    "item_id": item_id,
                    "artifact_bytes": baseline_map[item_id],
                }
                for item_id in sorted(item_metadata)
            ]
        }
    }
    ordered_item_ids = [
        item_id
        for track in PUBLICATION.RUNNER.TRACKS
        for item_id in config["splits"][track]["screen_items"]
    ]
    expected_summary = PUBLICATION.RUNNER.summarize(
        trials=receipts,
        items=[item_metadata[item_id] for item_id in ordered_item_ids],
        baseline=pseudo_baseline,
        config=config,
    )
    if summary != expected_summary:
        raise ValueError("public long-range decision does not reconstruct")
    return {
        "verified": True,
        "trial_count": len(receipts),
        "exact_deterministic_item_variant_count": sum(
            row["passed"] for row in expected_summary["item_rows"]
        ),
        "axiom_prototype_admitted": False,
        "axiom_wins": 0,
        "decision": expected_summary["decision"],
        "result_sha256": evidence["result_sha256"],
        "claim_ceiling": result["claim_ceiling"],
    }


def verify(
    publication: Path,
    baseline_publication: Path = DEFAULT_BASELINE_PUBLICATION,
) -> dict[str, Any]:
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
        != "text-source-long-range-kanzi-decomposition-publication-receipt-v1"
        or set(receipt.get("artifacts", {})) != EXPECTED_FILES - {"receipt.json"}
    ):
        raise ValueError("publication receipt identity is invalid")
    for name, digest in receipt["artifacts"].items():
        if PUBLICATION.sha256_file(publication / name) != digest:
            raise ValueError(f"publication artifact digest differs: {name}")
    PUBLICATION.validate_public_evidence(evidence)
    if (
        PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(evidence["results"]))
        != evidence["result_sha256"]
        or PUBLICATION.sha256_bytes(PUBLICATION.json_bytes(evidence["config"]))
        != evidence["config_sha256"]
        or PUBLICATION.sha256_file(publication / "evidence.json")
        != comparison.get("public_evidence_sha256")
    ):
        raise ValueError("publication evidence binding is inconsistent")
    expected_run_verification = reconstruct_run_verification(evidence)
    if evidence.get("run_verification") != expected_run_verification:
        raise ValueError("publication run verification does not reconstruct")
    BASELINE_VERIFY.verify(baseline_publication)
    baseline_evidence = read_canonical_json(baseline_publication / "evidence.json")
    baseline_evidence_sha256 = PUBLICATION.sha256_file(
        baseline_publication / "evidence.json"
    )
    if (
        baseline_evidence.get("raw_results_sha256")
        != evidence["baseline_results_sha256"]
        or baseline_evidence_sha256
        != evidence["baseline_public_evidence_sha256"]
    ):
        raise ValueError("long-range baseline publication binding differs")
    expected_comparison = PUBLICATION.derive(
        evidence["results"],
        baseline_evidence["results"],
        result_sha256=evidence["result_sha256"],
        receipts_sha256=evidence["raw_trial_receipts_manifest_sha256"],
        baseline_results_sha256=evidence["baseline_results_sha256"],
        baseline_public_evidence_sha256=baseline_evidence_sha256,
        public_evidence_sha256=PUBLICATION.sha256_file(
            publication / "evidence.json"
        ),
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
        "name": "text-source-long-range-kanzi-decomposition-publication-receipt-v1",
        "result_sha256": expected_comparison["result_sha256"],
        "trial_receipts_manifest_sha256": expected_comparison[
            "trial_receipts_manifest_sha256"
        ],
        "baseline_results_sha256": expected_comparison["baseline_results_sha256"],
        "baseline_public_evidence_sha256": expected_comparison[
            "baseline_public_evidence_sha256"
        ],
        "public_evidence_sha256": expected_comparison["public_evidence_sha256"],
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
        "trial_count": expected_run_verification["trial_count"],
        "track_count": len(expected_comparison["tracks"]),
        "standards_per_track": 15,
        "diagnostics_per_track": 3,
        "axiom_prototype_admitted": False,
        "axiom_wins": 0,
        "decision": expected_comparison["decision"],
        "result_sha256": expected_comparison["result_sha256"],
        "public_evidence_sha256": expected_comparison["public_evidence_sha256"],
        "claim_ceiling": expected_comparison["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", nargs="?", type=Path, default=DEFAULT_PUBLICATION)
    parser.add_argument(
        "--baseline-publication", type=Path, default=DEFAULT_BASELINE_PUBLICATION
    )
    args = parser.parse_args()
    try:
        result = verify(args.publication, args.baseline_publication)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"long-range publication verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
