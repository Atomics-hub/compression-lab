#!/usr/bin/env python3
"""Fail-closed verifier scaffold for frozen Python grammar/binding GDB1 results."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
COMPONENTS = (
    "format_header_and_flags",
    "solid_payload",
    "file_manifest_paths_modes_and_sizes",
    "fallback_map_and_raw_escape_bytes",
    "all_tables_permutations_and_stream_directory_bytes",
    "trained_dictionary_if_any",
    "decoder_source_or_binary",
    "parser_and_runtime_distribution",
    "license_and_version_manifest",
)
HEX = frozenset("0123456789abcdef")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path.name} must be an ordinary file")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"{path.name} is not canonical JSON")
    return raw, value


def validate_config(config: dict[str, Any]) -> None:
    if (
        config.get("schema_version") != 1
        or config.get("name") != "source-python-grammar-binding-gdb1-v1"
        or config.get("frozen_before_dependency_acquisition_and_measurement")
        is not True
        or config.get("accounting", {}).get("gate_denominator")
        != "complete_bundle_bytes"
        or tuple(config.get("accounting", {}).get("complete_bundle_components", []))
        != COMPONENTS
    ):
        raise ValueError("GDB1 identity or complete accounting differs")
    arms = config.get("arms")
    if not isinstance(arms, list) or [row.get("id") for row in arms] != [
        "a0-token-trivia-range",
        "a1-flat-identifiers",
        "a2-scope-bindings",
    ]:
        raise ValueError("GDB1 attributable arm roster differs")
    if (
        [row.get("occurrence_model") for row in arms]
        != [
            "none",
            "One first-occurrence spelling lexicon plus a single global identifier MTF list; no scope information.",
            "The A1 spelling lexicon with only its occurrence stream replaced by deterministic lexical-scope NEW, FREE, and current-scope MTF-rank events.",
        ]
        or config.get("coder", {}).get("version") != "axiom-int-range-v1"
        or "identical coder" not in config.get("coder", {}).get("rule", "")
    ):
        raise ValueError("GDB1 A2-minus-A1 attribution differs")
    baselines = config.get("baselines")
    if (
        not isinstance(baselines, list)
        or [row.get("id") for row in baselines]
        != [
            "kanzi-max",
            "xz-lzma2-9e",
            "zstd-22-trained-dictionary",
            "cmix-v21-text",
        ]
        or any(row.get("required") is not True for row in baselines)
    ):
        raise ValueError("GDB1 required baseline roster differs")
    bindings = config.get("bindings", {})
    if (
        not is_sha256(bindings.get("existing_baseline_public_evidence_sha256"))
        or not is_sha256(bindings.get("existing_corpus_manifest_sha256"))
        or not is_sha256(bindings.get("kanzi_binary_sha256"))
        or "G1 must match both G0 identities exactly"
        not in bindings.get("result_binding_policy", "")
    ):
        raise ValueError("GDB1 pinned evidence identities differ")
    corpus = config.get("corpus", {})
    partitions = corpus.get("partitions", {})
    buckets = {
        name: set(partitions.get(name, []))
        for name in ("dictionary_fit", "training_screen", "development_holdout")
    }
    if (
        corpus.get("allowed_project") != "cpython-3.14.6-source"
        or set.union(*buckets.values()) != set(range(10))
        or any(
            left & right
            for left in buckets.values()
            for right in buckets.values()
            if left is not right
        )
        or buckets["development_holdout"] != {8, 9}
        or set(corpus.get("reserved_not_accessed", []))
        != {
            "rust-1.97.1-source",
            "llvm-22.1.8-source",
            "typescript-6.0.3-source",
            "all public-validation inputs",
            "all private-holdout inputs",
        }
    ):
        raise ValueError("GDB1 Python-only split or sealed roster differs")
    dependency = config.get("dependencies", {}).get("cst", {})
    if dependency != {
        "package": "LibCST",
        "strategy": "Lossless Module.bytes/code identity plus MetadataWrapper ScopeProvider; traversal is lexical source order with explicit conservative raw fallback for any unresolved or unsupported binding case.",
        "version": "1.8.6",
    }:
        raise ValueError("GDB1 pinned lossless CST strategy differs")
    common = config.get("gates", {}).get("common", {})
    g0 = config.get("gates", {}).get("g0_training_signal", {})
    g1 = config.get("gates", {}).get("g1_development_strong", {})
    product = config.get("gates", {}).get("product_reminder", {})
    if (
        common.get("deterministic_repetitions") != 2
        or common.get("maximum_peak_rss_bytes") != 8 * 1024**3
        or common.get("maximum_seconds_per_operation") != 21_600
        or g0.get("a0_maximum_regression_vs_strongest_baseline_basis_points") != 500
        or g0.get("a2_minimum_gain_vs_a1_basis_points") != 100
        or g1.get("a2_minimum_gain_vs_strongest_baseline_basis_points") != 800
        or g1.get("a2_minimum_gain_vs_a1_basis_points") != 100
        or g1.get("maximum_independent_file_regression_basis_points") != 50
        or product.get("minimum_gain_vs_strongest_unseen_baseline_basis_points") != 500
    ):
        raise ValueError("GDB1 integer gates differ")


def validate_components(system: dict[str, Any]) -> bool:
    components = system.get("components")
    if not isinstance(components, list) or [
        row.get("name") for row in components
    ] != list(COMPONENTS):
        return False
    total = 0
    for component in components:
        if (
            not isinstance(component, dict)
            or set(component) != {"bytes", "name", "sha256"}
            or type(component.get("bytes")) is not int
            or component["bytes"] < 0
            or not is_sha256(component.get("sha256"))
        ):
            return False
        total += component["bytes"]
    return (
        type(system.get("complete_bundle_bytes")) is int
        and system["complete_bundle_bytes"] == total
    )


def common_eligible(system: dict[str, Any], config: dict[str, Any]) -> bool:
    if (
        not validate_components(system)
        or not is_sha256(system.get("implementation_identity_sha256"))
        or system.get("corruption_preflight_passed") is not True
    ):
        return False
    repetitions = system.get("repetitions")
    expected = config["gates"]["common"]["deterministic_repetitions"]
    if not isinstance(repetitions, list) or len(repetitions) != expected:
        return False
    digests: set[str] = set()
    manifest_digests: set[str] = set()
    for repetition, row in enumerate(repetitions):
        if (
            not isinstance(row, dict)
            or row.get("repetition") != repetition
            or row.get("exact_roundtrip") is not True
            or not is_sha256(row.get("artifact_sha256"))
            or not is_sha256(row.get("restored_manifest_sha256"))
            or type(row.get("compression_seconds")) not in (int, float)
            or type(row.get("decompression_seconds")) not in (int, float)
            or row["compression_seconds"] < 0
            or row["decompression_seconds"] < 0
            or row["compression_seconds"]
            > config["gates"]["common"]["maximum_seconds_per_operation"]
            or row["decompression_seconds"]
            > config["gates"]["common"]["maximum_seconds_per_operation"]
            or type(row.get("peak_rss_bytes")) is not int
            or row["peak_rss_bytes"] < 0
            or row["peak_rss_bytes"]
            > config["gates"]["common"]["maximum_peak_rss_bytes"]
        ):
            return False
        digests.add(row["artifact_sha256"])
        manifest_digests.add(row["restored_manifest_sha256"])
    return len(digests) == len(manifest_digests) == 1


def per_file_map(system: dict[str, Any]) -> dict[str, int] | None:
    rows = system.get("per_file_diagnostics")
    if not isinstance(rows, list):
        return None
    result: dict[str, int] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"exact_roundtrip", "fallback", "file_id", "frame_bytes"}
            or not is_sha256(row.get("file_id"))
            or row.get("exact_roundtrip") is not True
            or type(row.get("fallback")) is not bool
            or type(row.get("frame_bytes")) is not int
            or row["frame_bytes"] < 0
            or row["file_id"] in result
        ):
            return None
        result[row["file_id"]] = row["frame_bytes"]
    return result if result else None


def verify(
    result_path: Path,
    config_path: Path = DEFAULT_CONFIG,
    g0_result_path: Path | None = None,
) -> dict[str, Any]:
    config_raw, config = read_canonical(config_path)
    validate_config(config)
    result_raw, result = read_canonical(result_path)
    bindings = result.get("bindings", {})
    if (
        result.get("name") != "source-python-grammar-binding-gdb1-result-v1"
        or result.get("claim_ceiling") != config["claim_ceiling"]
        or bindings.get("config_sha256") != sha256_bytes(config_raw)
        or bindings.get("source_corpus_manifest_sha256")
        != config["bindings"]["existing_corpus_manifest_sha256"]
        or bindings.get("prior_baseline_public_evidence_sha256")
        != config["bindings"]["existing_baseline_public_evidence_sha256"]
        or not is_sha256(bindings.get("dependency_lock_sha256"))
        or not is_sha256(bindings.get("derived_corpus_manifest_sha256"))
        or not isinstance(bindings.get("repository_commit"), str)
        or len(bindings["repository_commit"]) != 40
        or not set(bindings["repository_commit"]) <= HEX
    ):
        raise ValueError("GDB1 result identity or evidence binding differs")
    stage = result.get("stage")
    if stage not in {"training_screen", "development_holdout"}:
        raise ValueError("GDB1 stage differs")
    access = result.get("access")
    expected_access = {
        "training_screen": {
            "development_holdout": "sealed and unaccessed",
            "public_validation": "sealed and unaccessed",
            "private_holdout": "sealed and unaccessed",
            "rust_llvm_typescript": "sealed and unaccessed",
        },
        "development_holdout": {
            "development_holdout": "accessed exactly once",
            "public_validation": "sealed and unaccessed",
            "private_holdout": "sealed and unaccessed",
            "rust_llvm_typescript": "sealed and unaccessed",
        },
    }[stage]
    if access != expected_access:
        raise ValueError("GDB1 sealed-data declaration differs")
    systems = result.get("systems")
    if not isinstance(systems, list):
        raise ValueError("GDB1 system roster is absent")
    by_id = {row.get("id"): row for row in systems if isinstance(row, dict)}
    required_ids = [row["id"] for row in config["baselines"]] + [
        row["id"] for row in config["arms"]
    ]
    if len(by_id) != len(systems) or set(by_id) != set(required_ids):
        raise ValueError("GDB1 system roster differs")
    if (
        by_id["kanzi-max"].get("implementation_identity_sha256")
        != config["bindings"]["kanzi_binary_sha256"]
    ):
        raise ValueError("GDB1 Kanzi binary identity differs")
    eligibility = {
        system_id: common_eligible(by_id[system_id], config)
        for system_id in required_ids
    }
    baseline_ids = [row["id"] for row in config["baselines"]]
    arm_ids = [row["id"] for row in config["arms"]]
    complete = all(eligibility.values())
    strongest_id = None
    strongest_bytes = None
    if all(eligibility[system_id] for system_id in baseline_ids):
        strongest_id = min(
            baseline_ids,
            key=lambda system_id: (
                by_id[system_id]["complete_bundle_bytes"],
                system_id,
            ),
        )
        strongest_bytes = by_id[strongest_id]["complete_bundle_bytes"]
    a0 = by_id[arm_ids[0]]["complete_bundle_bytes"] if eligibility[arm_ids[0]] else None
    a1 = by_id[arm_ids[1]]["complete_bundle_bytes"] if eligibility[arm_ids[1]] else None
    a2 = by_id[arm_ids[2]]["complete_bundle_bytes"] if eligibility[arm_ids[2]] else None
    gate_checks: dict[str, bool] = {"common": complete}
    if stage == "training_screen":
        gate_checks["a0_competent"] = (
            a0 is not None
            and strongest_bytes is not None
            and a0 * 10_000 <= strongest_bytes * 10_500
        )
        gate_checks["scope_attribution"] = (
            a1 is not None and a2 is not None and a2 * 10_000 <= a1 * 9_900
        )
    else:
        if g0_result_path is None:
            raise ValueError(
                "GDB1 development holdout requires the immutable G0 result"
            )
        g0_raw, g0 = read_canonical(g0_result_path)
        if bindings.get("g0_result_sha256") != sha256_bytes(g0_raw):
            raise ValueError("GDB1 G0 binding differs")
        g0_bindings = g0.get("bindings", {})
        if bindings.get("dependency_lock_sha256") != g0_bindings.get(
            "dependency_lock_sha256"
        ) or bindings.get("derived_corpus_manifest_sha256") != g0_bindings.get(
            "derived_corpus_manifest_sha256"
        ):
            raise ValueError("GDB1 dependency lock or derived corpus changed after G0")
        g0_verification = verify(g0_result_path, config_path)
        if not g0_verification["passed"]:
            raise ValueError("GDB1 development holdout was opened without a G0 pass")
        gate_checks["strong_headroom"] = (
            a2 is not None
            and strongest_bytes is not None
            and a2 * 10_000 <= strongest_bytes * 9_200
        )
        gate_checks["scope_attribution"] = (
            a1 is not None and a2 is not None and a2 * 10_000 <= a1 * 9_900
        )
        diagnostics = {
            system_id: per_file_map(by_id[system_id]) for system_id in required_ids
        }
        file_rosters = [set(rows) for rows in diagnostics.values() if rows is not None]
        guard = (
            len(file_rosters) == len(required_ids)
            and len({frozenset(rows) for rows in file_rosters}) == 1
        )
        if guard:
            candidate_diagnostics = diagnostics[arm_ids[2]]
            baseline_diagnostics = [
                diagnostics[baseline_id] for baseline_id in baseline_ids
            ]
            assert candidate_diagnostics is not None
            assert all(rows is not None for rows in baseline_diagnostics)
            complete_baseline_diagnostics = [
                rows for rows in baseline_diagnostics if rows is not None
            ]
            for file_id, candidate_bytes in candidate_diagnostics.items():
                best = min(rows[file_id] for rows in complete_baseline_diagnostics)
                if candidate_bytes * 10_000 > best * 10_050:
                    guard = False
                    break
        gate_checks["per_file_guard"] = guard
    passed = all(gate_checks.values())
    declared = result.get("decision")
    expected_decision = (
        "admit_one_shot_development_holdout"
        if stage == "training_screen" and passed
        else "admit_separately_frozen_validation"
        if stage == "development_holdout" and passed
        else "reject_gdb1_without_opening_development_holdout"
        if stage == "training_screen"
        else "reject_gdb1_and_do_not_tune_on_consumed_holdout"
    )
    if declared != expected_decision:
        raise ValueError("GDB1 declared decision differs from reconstructed gates")
    return {
        "verified": True,
        "stage": stage,
        "passed": passed,
        "decision": expected_decision,
        "gate_checks": gate_checks,
        "strongest_complete_baseline": strongest_id,
        "strongest_complete_baseline_bytes": strongest_bytes,
        "result_sha256": sha256_bytes(result_raw),
        "claim_ceiling": result["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--g0-result", type=Path)
    args = parser.parse_args()
    try:
        summary = verify(args.result, args.config, args.g0_result)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"GDB1 result verification failed: {error}") from error
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
