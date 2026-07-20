#!/usr/bin/env python3
"""Apply the frozen text/source successor routing rules to verified probe evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-successor-routing-v1.json"
DEFAULT_PUBLICATION = (
    REPOSITORY
    / "runs"
    / "text-source-structural-transform-development-v1"
    / "publication"
)
DEFAULT_OUTPUT = (
    REPOSITORY / "runs" / "text-source-structural-successor-decision-v1.json"
)
TRACK_ORDER = ["source_code_bundles", "english_wikimedia_wikitext"]
EXPECTED_VARIANTS = {
    "source_code_bundles": ["ts-h1-demux", "ts-h2-extension-lanes"],
    "english_wikimedia_wikitext": ["ts-h1-demux"],
}
OBSERVED_FIELDS = [
    "complete_bytes",
    "gain_vs_kanzi_percent",
    "minimum_item_gain_percent",
    "hypothesis_gate_passed",
    "final_specialist_admission_passed",
    "exact_roundtrip",
    "deterministic_artifact",
    "decision",
]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLICATION_VERIFY = load_script(
    "structural_publication_for_successor_routing",
    REPOSITORY / "scripts" / "verify-text-source-structural-publication.py",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def validate_config(config: dict[str, Any]) -> None:
    if (
        set(config)
        != {
            "schema_version",
            "name",
            "frozen_before_structural_results",
            "structural_publication_name",
            "global_successor_gate",
            "tracks",
            "claim_ceiling",
        }
        or type(config.get("schema_version")) is not int
        or config["schema_version"] != 1
        or config.get("name") != "text-source-structural-successor-routing-v1"
        or config.get("frozen_before_structural_results") is not True
        or config.get("structural_publication_name")
        != "text-source-structural-transform-development-publication-v1"
        or list(config.get("tracks", {}))
        != ["english_wikimedia_wikitext", "source_code_bundles"]
        or not isinstance(config.get("claim_ceiling"), str)
        or not config["claim_ceiling"]
    ):
        raise ValueError("successor routing config identity is invalid")
    gate = config.get("global_successor_gate")
    if (
        not isinstance(gate, dict)
        or gate.get("minimum_gain_vs_strongest_eligible_complete_baseline_percent")
        != 5.0
        or gate.get("maximum_item_regression_percent") != 0.5
        or gate.get("exact_roundtrip_required") is not True
        or gate.get("two_byte_identical_measured_artifacts_required") is not True
        or gate.get("complete_artifact_accounting") is not True
        or gate.get("unavailable_or_incomplete_baseline_is_not_an_axiom_win")
        is not True
        or gate.get("public_validation_status") != "sealed and unaccessed"
        or gate.get("private_holdout_status") != "sealed and unaccessed"
    ):
        raise ValueError("global successor gate is invalid")
    allowed_fields = {
        "hypothesis_gate_passed",
        "final_specialist_admission_passed",
    }
    for track_id in TRACK_ORDER:
        track = config["tracks"].get(track_id)
        rules = track.get("ordered_rules") if isinstance(track, dict) else None
        if not isinstance(rules, list) or len(rules) < 2:
            raise ValueError(f"successor rule roster is invalid: {track_id}")
        ids = []
        hypotheses = []
        for index, rule in enumerate(rules):
            if (
                not isinstance(rule, dict)
                or set(rule)
                != {"rule_id", "hypothesis_id", "condition", "action"}
                or not all(
                    isinstance(rule.get(key), str) and rule[key]
                    for key in ("rule_id", "hypothesis_id", "action")
                )
            ):
                raise ValueError(f"successor rule is invalid: {track_id}")
            ids.append(rule["rule_id"])
            hypotheses.append(rule["hypothesis_id"])
            condition = rule["condition"]
            if index == len(rules) - 1:
                if condition != {"otherwise": True}:
                    raise ValueError("last successor rule must be the only fallback")
            elif (
                not isinstance(condition, dict)
                or set(condition) != {"variant", "field", "equals"}
                or condition["variant"] not in EXPECTED_VARIANTS[track_id]
                or condition["field"] not in allowed_fields
                or type(condition["equals"]) is not bool
            ):
                raise ValueError(f"conditional successor rule is invalid: {track_id}")
        if len(ids) != len(set(ids)):
            raise ValueError(f"successor rule identities repeat: {track_id}")
        if not all(hypotheses):
            raise ValueError(f"successor hypothesis identity is empty: {track_id}")


def candidate_rows(comparison: dict[str, Any], track_id: str) -> dict[str, dict[str, Any]]:
    tracks = [row for row in comparison.get("tracks", []) if row.get("track_id") == track_id]
    if len(tracks) != 1:
        raise ValueError(f"structural comparison track roster differs: {track_id}")
    candidates = [
        row for row in tracks[0].get("rows", []) if row.get("kind") == "axiom_candidate"
    ]
    result = {row.get("id"): row for row in candidates}
    if list(result) != EXPECTED_VARIANTS[track_id] or len(result) != len(candidates):
        raise ValueError(f"structural candidate roster differs: {track_id}")
    for variant, row in result.items():
        if (
            any(field not in row for field in OBSERVED_FIELDS)
            or type(row["hypothesis_gate_passed"]) is not bool
            or type(row["final_specialist_admission_passed"]) is not bool
            or type(row["exact_roundtrip"]) is not bool
            or type(row["deterministic_artifact"]) is not bool
            or row["final_specialist_admission_passed"]
            and not row["hypothesis_gate_passed"]
            or (
                row["hypothesis_gate_passed"]
                and (
                    not row["exact_roundtrip"]
                    or not row["deterministic_artifact"]
                    or type(row["complete_bytes"]) is not int
                    or row["complete_bytes"] <= 0
                    or type(row["gain_vs_kanzi_percent"]) not in {int, float}
                    or type(row["minimum_item_gain_percent"]) not in {int, float}
                )
            )
        ):
            raise ValueError(f"structural candidate outcome is invalid: {variant}")
    return result


def route_track(
    track_id: str,
    track_config: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    selected = None
    for rule in track_config["ordered_rules"]:
        condition = rule["condition"]
        if condition == {"otherwise": True}:
            selected = rule
            break
        observed = candidates[condition["variant"]][condition["field"]]
        if observed == condition["equals"]:
            selected = rule
            break
    if selected is None:
        raise ValueError(f"no successor rule matched: {track_id}")
    observations = []
    for variant in EXPECTED_VARIANTS[track_id]:
        row = candidates[variant]
        observations.append(
            {"variant": variant} | {field: row[field] for field in OBSERVED_FIELDS}
        )
    return {
        "track_id": track_id,
        "selected_rule_id": selected["rule_id"],
        "selected_hypothesis_id": selected["hypothesis_id"],
        "action": selected["action"],
        "observations": observations,
        "axiom_win": False,
    }


def build_decision(
    *,
    config: dict[str, Any],
    comparison: dict[str, Any],
    config_sha256: str,
    comparison_sha256: str,
    publication_receipt_sha256: str,
) -> dict[str, Any]:
    validate_config(config)
    if (
        comparison.get("name") != config["structural_publication_name"]
        or comparison.get("stage") != "development structural representation probe"
        or comparison.get("validation_status") != "sealed and unaccessed"
        or comparison.get("private_holdout_status") != "sealed and unaccessed"
    ):
        raise ValueError("structural comparison evidence boundary is invalid")
    decisions = [
        route_track(
            track_id,
            config["tracks"][track_id],
            candidate_rows(comparison, track_id),
        )
        for track_id in TRACK_ORDER
    ]
    return {
        "schema_version": 1,
        "name": "text-source-structural-successor-decision-v1",
        "completed": True,
        "bindings": {
            "routing_config_sha256": config_sha256,
            "structural_comparison_sha256": comparison_sha256,
            "structural_publication_receipt_sha256": publication_receipt_sha256,
            "structural_results_sha256": comparison["structural_results_sha256"],
            "baseline_results_sha256": comparison["baseline_results_sha256"],
        },
        "decisions": decisions,
        "successor_gate": config["global_successor_gate"],
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "axiom_wins": 0,
        "claim_ceiling": config["claim_ceiling"],
    }


def write_immutable(path: Path, payload: dict[str, Any]) -> Path:
    encoded = json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError("refusing to replace a differing successor decision")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return path


def decide(config_path: Path, publication: Path, output: Path) -> Path:
    PUBLICATION_VERIFY.verify(publication)
    config = read_canonical_json(config_path)
    comparison_path = publication / "comparison.json"
    receipt_path = publication / "receipt.json"
    comparison = read_canonical_json(comparison_path)
    decision = build_decision(
        config=config,
        comparison=comparison,
        config_sha256=sha256_file(config_path),
        comparison_sha256=sha256_file(comparison_path),
        publication_receipt_sha256=sha256_file(receipt_path),
    )
    result = write_immutable(output, decision)
    validate_decision(config_path, publication, result)
    return result


def validate_decision(
    config_path: Path, publication: Path, decision_path: Path
) -> dict[str, Any]:
    verification = PUBLICATION_VERIFY.verify(publication)
    config = read_canonical_json(config_path)
    comparison_path = publication / "comparison.json"
    receipt_path = publication / "receipt.json"
    comparison = read_canonical_json(comparison_path)
    expected = build_decision(
        config=config,
        comparison=comparison,
        config_sha256=sha256_file(config_path),
        comparison_sha256=sha256_file(comparison_path),
        publication_receipt_sha256=sha256_file(receipt_path),
    )
    observed = read_canonical_json(decision_path)
    if observed != expected:
        raise ValueError("successor decision does not reconstruct from public evidence")
    return {
        "verified": True,
        "decision_count": len(observed["decisions"]),
        "routing_config_sha256": observed["bindings"]["routing_config_sha256"],
        "structural_comparison_sha256": observed["bindings"][
            "structural_comparison_sha256"
        ],
        "structural_public_evidence_sha256": verification[
            "public_evidence_sha256"
        ],
        "axiom_wins": 0,
        "decision_sha256": sha256_file(decision_path),
        "claim_ceiling": observed["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--publication", type=Path, default=DEFAULT_PUBLICATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = decide(args.config, args.publication, args.output)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"text/source successor routing failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
