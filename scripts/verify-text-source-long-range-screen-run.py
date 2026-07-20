#!/usr/bin/env python3
"""Verify every retained long-range screen receipt and recompute its decision."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-long-range-screen-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_PREDICTOR_RESULT = (
    REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-v1.json"
)
DEFAULT_KANZI = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-long-range-screen-v1"


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


RUNNER = load_script(
    "long_range_screen_runner_for_verifier",
    REPOSITORY / "scripts" / "benchmark-text-source-long-range-screen.py",
)


def validate_preflight(rows: object, config: dict[str, Any]) -> None:
    if (
        not isinstance(rows, list)
        or len(rows) != len(config["variants"])
        or [row.get("variant") for row in rows if isinstance(row, dict)]
        != [row["id"] for row in config["variants"]]
    ):
        raise ValueError("long-range preflight roster differs")
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "variant",
                "source_bytes",
                "artifact_bytes",
                "artifact_sha256",
                "exact_roundtrip",
            }
            or row.get("source_bytes") != 364_544
            or type(row.get("artifact_bytes")) is not int
            or row["artifact_bytes"] <= 0
            or not isinstance(row.get("artifact_sha256"), str)
            or len(row["artifact_sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in row["artifact_sha256"]
            )
            or row.get("exact_roundtrip") is not True
        ):
            raise ValueError("long-range preflight evidence differs")


def verify(
    *,
    config_path: Path,
    corpus: Path,
    baseline_path: Path,
    predictor_result_path: Path,
    kanzi: Path,
    output: Path,
) -> dict[str, Any]:
    config_raw, config = RUNNER.read_canonical(config_path)
    RUNNER.validate_config(config)
    items, baseline = RUNNER.verify_dependencies(
        config=config,
        corpus=corpus,
        baseline_path=baseline_path,
        predictor_result_path=predictor_result_path,
        kanzi=kanzi,
    )
    result_path = output / "results.json"
    result_raw, result = RUNNER.read_canonical(result_path)
    bindings = result.get("bindings", {})
    if (
        result.get("name")
        != "text-source-long-range-kanzi-decomposition-screen-result-v1"
        or result.get("completed") is not True
        or result.get("all_required_completed") is not True
        or result.get("trial_count") != 24
        or result.get("measurement") != config["measurement"]
        or result.get("variants") != config["variants"]
        or result.get("screen_boundary")
        != {track: config["splits"][track] for track in RUNNER.TRACKS}
        or result.get("claim_ceiling") != config["claim_ceiling"]
        or result.get("public_validation_status") != "sealed and unaccessed"
        or result.get("private_holdout_status") != "sealed and unaccessed"
        or bindings.get("config_sha256") != RUNNER.sha256_bytes(config_raw)
        or any(bindings.get(key) != value for key, value in config["bindings"].items())
        or not isinstance(bindings.get("repository_commit"), str)
        or len(bindings["repository_commit"]) != 40
        or any(
            character not in "0123456789abcdef"
            for character in bindings["repository_commit"]
        )
    ):
        raise ValueError("long-range result identity or binding differs")
    validate_preflight(result.get("preflight"), config)

    expected_paths = {
        RUNNER.trial_path(output, variant["id"], item["id"], repetition)
        for variant in config["variants"]
        for item in items
        for repetition in range(config["measurement"]["measured_repetitions"])
    }
    trial_root = output / "trials"
    observed_paths = set(trial_root.glob("*/*.json"))
    if observed_paths != expected_paths or any(path.is_symlink() for path in observed_paths):
        raise ValueError("long-range trial receipt roster differs")
    items_by_id = {item["id"]: item for item in items}
    variants = RUNNER.variant_map(config)
    trials = []
    for path in sorted(expected_paths):
        _raw, receipt = RUNNER.read_canonical(path)
        RUNNER.validate_existing_trial(
            receipt,
            destination=path,
            bindings=bindings,
            item=items_by_id[receipt["item_id"]],
            variant=variants[receipt["variant"]],
            repetition=receipt["repetition"],
            kanzi=kanzi,
        )
        trials.append(receipt)
    expected_summary = RUNNER.summarize(
        trials=trials,
        items=items,
        baseline=baseline,
        config=config,
    )
    if result.get("summary") != expected_summary:
        raise ValueError("long-range decision does not reconstruct from receipts")
    if result_raw != RUNNER.json_bytes(result):
        raise ValueError("long-range result is not canonical")
    return {
        "verified": True,
        "trial_count": len(trials),
        "exact_deterministic_item_variant_count": sum(
            row["passed"] for row in expected_summary["item_rows"]
        ),
        "axiom_prototype_admitted": expected_summary["axiom_prototype_admitted"],
        "axiom_wins": expected_summary["axiom_wins"],
        "decision": expected_summary["decision"],
        "result_sha256": RUNNER.sha256_bytes(result_raw),
        "claim_ceiling": result["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--predictor-result", type=Path, default=DEFAULT_PREDICTOR_RESULT
    )
    parser.add_argument("--kanzi", type=Path, default=DEFAULT_KANZI)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = verify(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            predictor_result_path=args.predictor_result,
            kanzi=args.kanzi,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"long-range run verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
