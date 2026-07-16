#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Iterable


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.native import structured_text_encode, zstd_compress  # noqa: E402
from compresslab.structured_text import (  # noqa: E402
    DICTIONARY_SAMPLE_BYTES,
    HEADER,
    MAGIC,
    MARKER,
    TRANSFORMED_SIZE,
    _dictionary_limit,
    encode_channelized,
)


TRAINER_PATH = REPOSITORY / "scripts" / "train-token-channel-estimator.py"
TRAINER_SPEC = importlib.util.spec_from_file_location("token_channel_estimator", TRAINER_PATH)
if TRAINER_SPEC is None or TRAINER_SPEC.loader is None:
    raise RuntimeError("could not load token-channel training helpers")
TRAINER = importlib.util.module_from_spec(TRAINER_SPEC)
TRAINER_SPEC.loader.exec_module(TRAINER)


BUDGETS = (24 * 1024, 48 * 1024, 96 * 1024, 192 * 1024)
SCORES = ("raw", "normalized")
LINK_BYTES_PER_SECOND = 12_500_000.0
COMPLEXITY_PENALTY_RATE = 0.0005


def dictionary_end(transformed: bytes) -> int:
    if len(transformed) < HEADER.size:
        raise ValueError("STX1 header is truncated")
    magic, count = HEADER.unpack(transformed[: HEADER.size])
    if magic != MAGIC or count > 254:
        raise ValueError("STX1 header is invalid")
    offset = HEADER.size
    for _ in range(count):
        if offset >= len(transformed):
            raise ValueError("STX1 dictionary is truncated")
        size = transformed[offset]
        offset += 1
        if size < 3 or size > 64 or size > len(transformed) - offset:
            raise ValueError("STX1 dictionary token is invalid")
        offset += size
    return offset


def align_range(transformed: bytes, start: int, end: int, body_start: int) -> tuple[int, int]:
    if start > body_start and transformed[start - 1] == MARKER:
        start += 1
    if end > start and transformed[end - 1] == MARKER:
        end -= 1
    return start, end


def representative_ranges(transformed: bytes, budget: int) -> list[tuple[int, int]]:
    body_start = dictionary_end(transformed)
    body_size = len(transformed) - body_start
    if body_size <= budget:
        return [(body_start, len(transformed))]

    first_size = budget // 3
    middle_size = budget // 3
    last_size = budget - first_size - middle_size
    proposed = [
        (body_start, body_start + first_size),
        (
            body_start + (body_size - middle_size) // 2,
            body_start + (body_size - middle_size) // 2 + middle_size,
        ),
        (len(transformed) - last_size, len(transformed)),
    ]
    aligned = [align_range(transformed, start, end, body_start) for start, end in proposed]
    merged: list[list[int]] = []
    for start, end in aligned:
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def sampled_transform(transformed: bytes, budget: int) -> bytes:
    body_start = dictionary_end(transformed)
    ranges = representative_ranges(transformed, budget)
    body = b"".join(transformed[start:end] for start, end in ranges)
    if len(body) > budget:
        raise AssertionError("sample exceeded its body budget")
    return transformed[:body_start] + body


def measure_sample(transformed: bytes, budget: int) -> dict[str, Any]:
    def run_once() -> tuple[bytes, int, int]:
        sample = sampled_transform(transformed, budget)
        interleaved_size = TRANSFORMED_SIZE.size + len(zstd_compress(sample, level=3))
        channel_size = len(
            encode_channelized(sample, lambda data: zstd_compress(data, level=3))
        )
        return sample, interleaved_size, channel_size

    run_once()
    durations = []
    sample = b""
    interleaved_size = 0
    channel_size = 0
    for _ in range(5):
        started = time.perf_counter()
        current_sample, current_interleaved, current_channel = run_once()
        durations.append(time.perf_counter() - started)
        if sample and (
            current_sample != sample
            or current_interleaved != interleaved_size
            or current_channel != channel_size
        ):
            raise AssertionError("sample probe is not deterministic")
        sample = current_sample
        interleaved_size = current_interleaved
        channel_size = current_channel
    delta = channel_size - interleaved_size
    return {
        "budget_bytes": budget,
        "sample_bytes": len(sample),
        "sample_sha256": hashlib.sha256(sample).hexdigest(),
        "interleaved_bytes": interleaved_size,
        "channel_bytes": channel_size,
        "raw": float(delta),
        "normalized": delta / len(sample) * 1_000_000.0,
        "probe_seconds": statistics.median(durations),
    }


def label_item(path: Path, family: str, dataset: str) -> dict[str, Any]:
    row = TRAINER.label_item(path, family, dataset)
    source = path.read_bytes()
    transformed = structured_text_encode(
        source,
        _dictionary_limit(source),
        DICTIONARY_SAMPLE_BYTES,
    )
    row["samples"] = {
        str(budget): measure_sample(transformed, budget) for budget in BUDGETS
    }
    return row


def model_key(model: dict[str, Any]) -> tuple[Any, ...]:
    mode_rank = {"never": 0, "always": 1, "sample": 2}[model["mode"]]
    return (
        mode_rank,
        model.get("budget_bytes", 0),
        SCORES.index(model.get("score", SCORES[0])),
        model.get("threshold", 0.0),
    )


def predicts(model: dict[str, Any], row: dict[str, Any]) -> bool:
    if model["mode"] == "never":
        return False
    if model["mode"] == "always":
        return True
    sample = row["samples"][str(model["budget_bytes"])]
    return sample[model["score"]] < model["threshold"]


def candidate_models(rows: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    yield {"mode": "never"}
    yield {"mode": "always"}
    for budget in BUDGETS:
        for score in SCORES:
            values = sorted({row["samples"][str(budget)][score] for row in rows})
            for left, right in zip(values, values[1:]):
                yield {
                    "mode": "sample",
                    "budget_bytes": budget,
                    "score": score,
                    "threshold": (left + right) / 2,
                }


def objective(model: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    cost = 0.0
    if model["mode"] == "sample":
        budget = str(model["budget_bytes"])
        cost += sum(
            row["samples"][budget]["probe_seconds"] * LINK_BYTES_PER_SECOND
            for row in rows
        )
        cost += COMPLEXITY_PENALTY_RATE * sum(
            row["interleaved_bytes"] for row in rows
        )
    for row in rows:
        attempt = predicts(model, row)
        if row["channel_wins"] and not attempt:
            cost += row["available_savings_bytes"]
        elif not row["channel_wins"] and attempt:
            cost += row["false_positive_cost_bytes"]
    return cost


def fit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(candidate_models(rows), key=lambda model: (objective(model, rows), model_key(model)))


def route_seconds(
    rows: list[dict[str, Any]], decisions: list[bool], models: list[dict[str, Any]]
) -> float:
    total = 0.0
    for row, decision, model in zip(rows, decisions, models):
        if model["mode"] == "sample":
            total += row["samples"][str(model["budget_bytes"])]["probe_seconds"]
        if decision:
            total += row["channel_attempt_seconds"]
    return total


def evaluation(
    rows: list[dict[str, Any]], decisions: list[bool], models: list[dict[str, Any]]
) -> dict[str, Any]:
    measured = TRAINER.metrics(rows, decisions)
    routed_seconds = route_seconds(rows, decisions, models)
    generic_seconds = sum(row["channel_attempt_seconds"] for row in rows)
    measured.update(
        {
            "generic_channel_attempt_seconds": generic_seconds,
            "probe_routed_seconds": routed_seconds,
            "route_time_improvement_percent": 100.0
            * (generic_seconds - routed_seconds)
            / generic_seconds,
        }
    )
    return measured


def leave_one_out(
    rows: list[dict[str, Any]],
) -> tuple[list[bool], list[dict[str, Any]], list[dict[str, Any]]]:
    decisions = []
    models = []
    folds = []
    for index, holdout in enumerate(rows):
        training = rows[:index] + rows[index + 1 :]
        model = fit(training)
        decision = predicts(model, holdout)
        decisions.append(decision)
        models.append(model)
        folds.append(
            {
                "holdout_family": holdout["family"],
                "decision": decision,
                "channel_wins": holdout["channel_wins"],
                "model": model,
            }
        )
    return decisions, models, folds


def gates(metrics: dict[str, Any]) -> dict[str, bool]:
    return {
        "savings_capture": metrics["savings_capture_percent"] >= 75.0,
        "avoided_losing_attempts": metrics["avoided_losing_attempts_percent"] >= 50.0,
        "payload_regret": metrics["payload_regret_percent_of_stx1"] <= 0.50,
        "route_time": metrics["route_time_improvement_percent"] >= 10.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPOSITORY / "corpora" / "public-json-estimator-train-v1",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "config" / "public-json-estimator-train-v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "runs" / "sampled-channel-probe-training.json",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    sources = {source["dataset"]: source for source in config["sources"]}
    rows = []
    for item in manifest["items"]:
        source = sources[item["dataset"]]
        path = args.corpus / item["path"]
        if TRAINER.sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        print(f"probe {source['family']} {path.name}", flush=True)
        rows.append(label_item(path, source["family"], item["dataset"]))
    rows.sort(key=lambda row: row["family"])

    decisions, fold_models, folds = leave_one_out(rows)
    cross_validation = evaluation(rows, decisions, fold_models)
    cross_validation_gates = gates(cross_validation)
    final_model = fit(rows)
    final_decisions = [predicts(final_model, row) for row in rows]
    final_models = [final_model] * len(rows)
    result = {
        "schema_version": 1,
        "protocol": "sampled-token-channel-probe-v1",
        "training_config": str(args.config.relative_to(REPOSITORY)),
        "training_config_sha256": TRAINER.sha256_file(args.config),
        "budgets": list(BUDGETS),
        "scores": list(SCORES),
        "rows": rows,
        "leave_one_family_out": {
            "metrics": cross_validation,
            "gates": cross_validation_gates,
            "passed": all(cross_validation_gates.values()),
            "folds": folds,
        },
        "final_model": final_model,
        "final_training_metrics": evaluation(rows, final_decisions, final_models),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["leave_one_family_out"], indent=2, sort_keys=True))
    print(json.dumps({"final_model": final_model}, indent=2, sort_keys=True))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
