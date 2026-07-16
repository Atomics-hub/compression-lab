#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Iterable


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.native import (  # noqa: E402
    structured_text_encode,
    structured_text_split_channels,
    zstd_compress,
)
from compresslab.structured_text import (  # noqa: E402
    DICTIONARY_SAMPLE_BYTES,
    ESCAPED_MARKER,
    HEADER,
    TRANSFORMED_SIZE,
    _dictionary_limit,
    encode_channelized,
)


FEATURES = (
    "side_density",
    "dictionary_utilization",
    "mean_code",
    "entropy",
    "top1_share",
    "top4_share",
    "repeat_rate",
)
LINK_BYTES_PER_SECOND = 12_500_000.0
COMPLEXITY_PENALTY_RATE = 0.0005


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def channel_features(transformed: bytes) -> dict[str, float]:
    _, dictionary_size = HEADER.unpack(transformed[: HEADER.size])
    _, side = structured_text_split_channels(transformed)
    codes = [value for value in side if value != ESCAPED_MARKER]
    counts = Counter(codes)
    total = len(codes)
    if not total:
        return {feature: 0.0 for feature in FEATURES}

    probabilities = [count / total for count in counts.values()]
    entropy_bits = -sum(p * math.log2(p) for p in probabilities)
    entropy_scale = math.log2(max(2, dictionary_size))
    ordered_counts = sorted(counts.values(), reverse=True)
    denominator = max(1, dictionary_size - 1)
    repeats = sum(left == right for left, right in zip(codes, codes[1:]))
    return {
        "side_density": len(side) / len(transformed),
        "dictionary_utilization": len(counts) / max(1, dictionary_size),
        "mean_code": statistics.fmean(codes) / denominator,
        "entropy": entropy_bits / entropy_scale,
        "top1_share": ordered_counts[0] / total,
        "top4_share": sum(ordered_counts[:4]) / total,
        "repeat_rate": repeats / max(1, total - 1),
    }


def label_item(path: Path, family: str, dataset: str) -> dict[str, Any]:
    source = path.read_bytes()
    transformed = structured_text_encode(
        source,
        _dictionary_limit(source),
        DICTIONARY_SAMPLE_BYTES,
    )
    features = channel_features(transformed)
    interleaved_size = TRANSFORMED_SIZE.size + len(zstd_compress(transformed, level=3))

    encode_channelized(transformed, lambda data: zstd_compress(data, level=3))
    durations = []
    channel_payload = b""
    for _ in range(5):
        started = time.perf_counter()
        channel_payload = encode_channelized(
            transformed,
            lambda data: zstd_compress(data, level=3),
        )
        durations.append(time.perf_counter() - started)

    channel_size = len(channel_payload)
    savings = max(0, interleaved_size - channel_size)
    return {
        "family": family,
        "dataset": dataset,
        "path": path.name,
        "input_bytes": len(source),
        "sha256": hashlib.sha256(source).hexdigest(),
        "transformed_bytes": len(transformed),
        "interleaved_bytes": interleaved_size,
        "channel_bytes": channel_size,
        "channel_delta_bytes": channel_size - interleaved_size,
        "channel_wins": channel_size < interleaved_size,
        "available_savings_bytes": savings,
        "channel_attempt_seconds": statistics.median(durations),
        "false_positive_cost_bytes": statistics.median(durations)
        * LINK_BYTES_PER_SECOND,
        "features": features,
    }


def predicate_key(predicate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        FEATURES.index(predicate["feature"]),
        0 if predicate["op"] == "lt" else 1,
        predicate["threshold"],
    )


def model_key(model: dict[str, Any]) -> tuple[Any, ...]:
    predicates = model.get("predicates", [])
    mode_rank = {"never": 0, "always": 1, "and": 2}[model["mode"]]
    return (
        len(predicates),
        mode_rank,
        tuple(predicate_key(predicate) for predicate in predicates),
    )


def predicts(model: dict[str, Any], row: dict[str, Any]) -> bool:
    if model["mode"] == "never":
        return False
    if model["mode"] == "always":
        return True
    for predicate in model["predicates"]:
        value = row["features"][predicate["feature"]]
        if predicate["op"] == "lt":
            accepted = value < predicate["threshold"]
        else:
            accepted = value > predicate["threshold"]
        if not accepted:
            return False
    return True


def predicates_for(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predicates = []
    for feature in FEATURES:
        values = sorted({row["features"][feature] for row in rows})
        thresholds = [(left + right) / 2 for left, right in zip(values, values[1:])]
        for threshold in thresholds:
            for operation in ("lt", "gt"):
                predicates.append(
                    {
                        "feature": feature,
                        "op": operation,
                        "threshold": threshold,
                    }
                )
    return predicates


def candidate_models(rows: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    yield {"mode": "never", "predicates": []}
    yield {"mode": "always", "predicates": []}
    predicates = predicates_for(rows)
    for predicate in predicates:
        yield {"mode": "and", "predicates": [predicate]}
    for left_index, left in enumerate(predicates):
        for right in predicates[left_index + 1 :]:
            if left["feature"] == right["feature"]:
                continue
            ordered = sorted((left, right), key=predicate_key)
            yield {"mode": "and", "predicates": ordered}


def objective(model: dict[str, Any], rows: list[dict[str, Any]]) -> float:
    cost = 0.0
    for row in rows:
        attempt = predicts(model, row)
        if row["channel_wins"] and not attempt:
            cost += row["available_savings_bytes"]
        elif not row["channel_wins"] and attempt:
            cost += row["false_positive_cost_bytes"]
    predicate_count = len(model.get("predicates", []))
    cost += (
        COMPLEXITY_PENALTY_RATE
        * sum(row["interleaved_bytes"] for row in rows)
        * predicate_count
    )
    return cost


def fit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(candidate_models(rows), key=lambda model: (objective(model, rows), model_key(model)))


def metrics(rows: list[dict[str, Any]], decisions: list[bool]) -> dict[str, Any]:
    winners = [index for index, row in enumerate(rows) if row["channel_wins"]]
    losers = [index for index, row in enumerate(rows) if not row["channel_wins"]]
    available = sum(rows[index]["available_savings_bytes"] for index in winners)
    captured = sum(
        rows[index]["available_savings_bytes"]
        for index in winners
        if decisions[index]
    )
    regret = available - captured
    stx1_bytes = sum(row["interleaved_bytes"] for row in rows)
    return {
        "families": len(rows),
        "winner_families": len(winners),
        "loser_families": len(losers),
        "predicted_attempts": sum(decisions),
        "available_savings_bytes": available,
        "captured_savings_bytes": captured,
        "savings_capture_percent": 100.0 * captured / available if available else 100.0,
        "avoided_losing_attempts": sum(not decisions[index] for index in losers),
        "avoided_losing_attempts_percent": (
            100.0 * sum(not decisions[index] for index in losers) / len(losers)
            if losers
            else 100.0
        ),
        "payload_regret_bytes": regret,
        "payload_regret_percent_of_stx1": 100.0 * regret / stx1_bytes,
    }


def leave_one_out(rows: list[dict[str, Any]]) -> tuple[list[bool], list[dict[str, Any]]]:
    decisions = []
    folds = []
    for index, holdout in enumerate(rows):
        training = rows[:index] + rows[index + 1 :]
        model = fit(training)
        decision = predicts(model, holdout)
        decisions.append(decision)
        folds.append(
            {
                "holdout_family": holdout["family"],
                "decision": decision,
                "channel_wins": holdout["channel_wins"],
                "model": model,
            }
        )
    return decisions, folds


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
        default=REPOSITORY / "runs" / "token-channel-estimator-training.json",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    sources = {source["dataset"]: source for source in config["sources"]}
    rows = []
    for item in manifest["items"]:
        source = sources[item["dataset"]]
        path = args.corpus / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {path}")
        print(f"label {source['family']} {path.name}", flush=True)
        rows.append(label_item(path, source["family"], item["dataset"]))
    rows.sort(key=lambda row: row["family"])

    decisions, folds = leave_one_out(rows)
    final_model = fit(rows)
    final_decisions = [predicts(final_model, row) for row in rows]
    result = {
        "schema_version": 1,
        "protocol": "json-token-channel-estimator-v1",
        "training_config": str(args.config.relative_to(REPOSITORY)),
        "training_config_sha256": sha256_file(args.config),
        "feature_order": list(FEATURES),
        "link_bytes_per_second": LINK_BYTES_PER_SECOND,
        "complexity_penalty_rate": COMPLEXITY_PENALTY_RATE,
        "rows": rows,
        "leave_one_family_out": {
            "metrics": metrics(rows, decisions),
            "folds": folds,
        },
        "final_model": final_model,
        "final_training_metrics": metrics(rows, final_decisions),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["leave_one_family_out"]["metrics"], indent=2, sort_keys=True))
    print(json.dumps({"final_model": final_model}, indent=2, sort_keys=True))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
