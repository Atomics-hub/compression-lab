#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.native import structured_text_encode  # noqa: E402
from compresslab.structured_text import (  # noqa: E402
    DICTIONARY_SAMPLE_BYTES,
    _dictionary_limit,
)


SAMPLED_TRAINER_PATH = REPOSITORY / "scripts" / "train-sampled-channel-probe.py"
SAMPLED_SPEC = importlib.util.spec_from_file_location(
    "sampled_channel_probe", SAMPLED_TRAINER_PATH
)
if SAMPLED_SPEC is None or SAMPLED_SPEC.loader is None:
    raise RuntimeError("could not load sampled-channel probe helpers")
SAMPLED = importlib.util.module_from_spec(SAMPLED_SPEC)
SAMPLED_SPEC.loader.exec_module(SAMPLED)
TRAINER = SAMPLED.TRAINER


def repository_path(value: str) -> Path:
    path = (REPOSITORY / value).resolve()
    path.relative_to(REPOSITORY.resolve())
    return path


def verify_artifact(path: Path, expected_sha256: str, label: str) -> None:
    actual = TRAINER.sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(
            f"{label} digest mismatch: expected {expected_sha256}, got {actual}"
        )


def validate_frozen_inputs(model_config: dict[str, Any], model_path: Path) -> None:
    if model_config.get("status") != "frozen_before_blind_validation":
        raise ValueError("model was not frozen before blind validation")
    verify_artifact(
        repository_path(model_config["protocol"]["path"]),
        model_config["protocol"]["sha256"],
        "protocol",
    )
    verify_artifact(
        repository_path(model_config["sampling_implementation"]["path"]),
        model_config["sampling_implementation"]["sha256"],
        "sampling implementation",
    )
    training = model_config["training"]
    for prefix in ("first_run", "repeat_run"):
        verify_artifact(
            repository_path(training[f"{prefix}_path"]),
            training[f"{prefix}_sha256"],
            prefix.replace("_", " "),
        )
    verify_artifact(
        repository_path(training["config_path"]),
        training["config_sha256"],
        "training config",
    )
    verify_artifact(
        model_path,
        TRAINER.sha256_file(model_path),
        "model config",
    )


def fixed_decision(sample: dict[str, Any], model: dict[str, Any]) -> bool:
    if model["score"] != (
        "complete_sampled_channel_bytes_minus_complete_sampled_interleaved_bytes"
    ):
        raise ValueError("unsupported fixed score")
    if model["operator"] != "lt" or model["threshold_bytes"] != 0:
        raise ValueError("unsupported fixed predicate")
    return sample["raw"] < 0


def evaluate(
    rows: list[dict[str, Any]], decisions: list[bool], body_budget: int
) -> tuple[dict[str, Any], dict[str, bool]]:
    metrics = TRAINER.metrics(rows, decisions)
    winners = [index for index, row in enumerate(rows) if row["channel_wins"]]
    attempted_winners = sum(decisions[index] for index in winners)
    winner_capture = (
        100.0 * attempted_winners / len(winners) if winners else 100.0
    )
    probe_seconds = sum(row["sample"]["probe_seconds"] for row in rows)
    routed_seconds = probe_seconds + sum(
        row["channel_attempt_seconds"]
        for row, decision in zip(rows, decisions)
        if decision
    )
    generic_seconds = sum(row["channel_attempt_seconds"] for row in rows)
    improvement = 100.0 * (generic_seconds - routed_seconds) / generic_seconds
    selected_bytes = sum(
        min(row["interleaved_bytes"], row["channel_bytes"])
        if decision
        else row["interleaved_bytes"]
        for row, decision in zip(rows, decisions)
    )
    interleaved_bytes = sum(row["interleaved_bytes"] for row in rows)
    bounds_pass = all(
        row["sample"]["sample_body_bytes"] <= body_budget for row in rows
    )
    fallback_pass = selected_bytes <= interleaved_bytes
    metrics.update(
        {
            "attempted_winner_families": attempted_winners,
            "winner_family_capture_percent": winner_capture,
            "probe_seconds": probe_seconds,
            "generic_channel_attempt_seconds": generic_seconds,
            "probe_routed_seconds": routed_seconds,
            "route_time_improvement_percent": improvement,
            "selected_payload_bytes": selected_bytes,
            "interleaved_payload_bytes": interleaved_bytes,
        }
    )
    gates_config = MODEL_CONFIG["blind_gates"]
    winner_gate = len(winners) < 3 or winner_capture >= gates_config[
        "minimum_winner_family_capture_percent_when_at_least_three_winners"
    ]
    gates = {
        "savings_capture": metrics["savings_capture_percent"]
        >= gates_config["minimum_savings_capture_percent"],
        "winner_family_capture": winner_gate,
        "avoided_losing_attempts": metrics["avoided_losing_attempts_percent"]
        >= gates_config["minimum_avoided_losing_attempts_percent"],
        "payload_regret": metrics["payload_regret_percent_of_stx1"]
        <= gates_config["maximum_payload_regret_percent_of_stx1"],
        "route_time": improvement
        >= gates_config["minimum_route_time_improvement_percent"],
        "exact_interleaved_fallback": fallback_pass,
        "sample_bound": bounds_pass,
        "within_run_repeatability": True,
    }
    return metrics, gates


MODEL_CONFIG: dict[str, Any] = {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=Path,
        default=REPOSITORY / "config" / "fixed-sign-sampled-channel-probe-v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "runs" / "fixed-sign-sampled-probe-validation.json",
    )
    args = parser.parse_args()

    global MODEL_CONFIG
    MODEL_CONFIG = json.loads(args.model.read_text(encoding="utf-8"))
    validate_frozen_inputs(MODEL_CONFIG, args.model)
    validation = MODEL_CONFIG["validation"]
    validation_config_path = repository_path(validation["config_path"])
    verify_artifact(
        validation_config_path,
        validation["config_sha256"],
        "validation config",
    )
    validation_config = json.loads(validation_config_path.read_text(encoding="utf-8"))
    corpus = repository_path(validation["corpus_path"])
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    sources = {source["dataset"]: source for source in validation_config["sources"]}
    body_budget = MODEL_CONFIG["model"]["body_budget_bytes"]
    if body_budget != 24 * 1024:
        raise ValueError("the blind evaluator permits only the frozen 24 KiB budget")

    rows = []
    for item in manifest["items"]:
        source_config = sources[item["dataset"]]
        path = corpus / item["path"]
        if TRAINER.sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        print(f"blind-score {source_config['family']} {path.name}", flush=True)
        row = TRAINER.label_item(path, source_config["family"], item["dataset"])
        source = path.read_bytes()
        transformed = structured_text_encode(
            source,
            _dictionary_limit(source),
            DICTIONARY_SAMPLE_BYTES,
        )
        sample = SAMPLED.measure_sample(transformed, body_budget)
        sample["sample_body_bytes"] = (
            sample["sample_bytes"] - SAMPLED.dictionary_end(transformed)
        )
        row["sample"] = sample
        row["decision"] = fixed_decision(sample, MODEL_CONFIG["model"])
        row["selected_bytes"] = (
            min(row["interleaved_bytes"], row["channel_bytes"])
            if row["decision"]
            else row["interleaved_bytes"]
        )
        rows.append(row)
    rows.sort(key=lambda row: row["family"])
    decisions = [row["decision"] for row in rows]
    metrics, gates = evaluate(rows, decisions, body_budget)
    result = {
        "schema_version": 1,
        "protocol": "fixed-sign-sampled-channel-probe-v1",
        "model_config": str(args.model.relative_to(REPOSITORY)),
        "model_config_sha256": TRAINER.sha256_file(args.model),
        "validation_config": str(validation_config_path.relative_to(REPOSITORY)),
        "validation_config_sha256": TRAINER.sha256_file(validation_config_path),
        "model": MODEL_CONFIG["model"],
        "rows": rows,
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"metrics": metrics, "gates": gates, "passed": result["passed"]}, indent=2, sort_keys=True))
    print(args.output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
