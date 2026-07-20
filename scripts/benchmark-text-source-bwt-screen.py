#!/usr/bin/env python3
"""Run the frozen training-split Kanzi BWT decomposition screen."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import random
import statistics
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-bwt-screen-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_STRUCTURAL_RESULT = (
    REPOSITORY / "runs" / "text-source-structural-transform-development-v1" / "results.json"
)
DEFAULT_PREDICTOR_RESULT = REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-v1.json"
DEFAULT_LONG_RANGE_RESULT = REPOSITORY / "runs" / "text-source-long-range-screen-v1" / "results.json"
DEFAULT_RECORD_RESULT = (
    REPOSITORY / "runs" / "text-source-record-neighborhood-screen-v1" / "results.json"
)
DEFAULT_KANZI = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-bwt-screen-v1"
TRACKS = ("source_code_bundles", "english_wikimedia_wikitext")
VARIANTS = (
    "tb1-text-bwt-tpaqx-direct",
    "tb2-text-bwt-srt-zrlt-tpaqx",
    "tb3-text-bwt-srt-zrlt-fpaq-control",
    "tb4-raw-bwt-srt-zrlt-tpaqx",
)


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


LONG_RANGE = load_script(
    "long_range_runner_for_bwt_screen",
    REPOSITORY / "scripts" / "benchmark-text-source-long-range-screen.py",
)
json_bytes = LONG_RANGE.json_bytes
sha256_bytes = LONG_RANGE.sha256_bytes
sha256_file = LONG_RANGE.sha256_file
read_canonical = LONG_RANGE.read_canonical
repository_commit = LONG_RANGE.repository_commit
verify_screen_items = LONG_RANGE.verify_screen_items
variant_map = LONG_RANGE.variant_map
commands = LONG_RANGE.commands
trial_path = LONG_RANGE.trial_path
validate_existing_trial = LONG_RANGE.validate_existing_trial
run_trial = LONG_RANGE.run_trial
preflight = LONG_RANGE.preflight
BASELINE_RUNNER = LONG_RANGE.BASELINE_RUNNER
BASELINE_PUBLICATION = LONG_RANGE.BASELINE_PUBLICATION


def validate_config(config: dict[str, Any]) -> None:
    expected_bindings = {
        "baseline_results_sha256": "08b66858cc5b7438c3aa134545642a54c8ea434b9c16d86db3ce8cc46122a5bc",
        "corpus_manifest_sha256": "745ade4b15b1c78439d8f9cc89d8a55065f538f5aac2fc01a9c7fe698487a409",
        "kanzi_binary_sha256": "3c93e96fb108ebf8152e187ef0f830b03952200dc94b449fcec8d158e7474618",
        "long_range_result_sha256": "faad7b7736685a30e451cd7fc94f4fde9898b16afa102a0291e418f86a544d12",
        "predictor_result_sha256": "300a9cd657b0949b9b4af165d6e080ff3962afb1281a764bb5c894b508d2fa68",
        "record_neighborhood_result_sha256": "724594043816e47fe3f0eabfe7870ee8f54a3fb75f1cdbd3a4b5696df297882a",
        "structural_results_sha256": "92a29a1e184a04293ce04bfdd05f5e7ba7dd0d7f12873edce3d2926c1628db93",
    }
    expected_splits = {
        "source_code_bundles": {
            "screen_items": ["cpython-3.14.6-source", "typescript-6.0.3-source"],
            "reserved_evaluation_not_accessed_by_screen": [
                "rust-1.97.1-source",
                "llvm-22.1.8-source",
            ],
        },
        "english_wikimedia_wikitext": {
            "screen_items": ["enwikibooks-20260701", "enwikinews-20260701"],
            "reserved_evaluation_not_accessed_by_screen": ["enwikiversity-20260701"],
        },
    }
    expected_variants = [
        ("tb1-text-bwt-tpaqx-direct", "TEXT+UTF+BWT", "TPAQX"),
        ("tb2-text-bwt-srt-zrlt-tpaqx", "TEXT+UTF+BWT+SRT+ZRLT", "TPAQX"),
        ("tb3-text-bwt-srt-zrlt-fpaq-control", "TEXT+UTF+BWT+SRT+ZRLT", "FPAQ"),
        ("tb4-raw-bwt-srt-zrlt-tpaqx", "BWT+SRT+ZRLT", "TPAQX"),
    ]
    observed_variants = [
        (row.get("id"), row.get("transform"), row.get("entropy"))
        for row in config.get("variants", [])
    ]
    measurement = config.get("measurement", {})
    decision = config.get("decision", {})
    gate = decision.get("track_gate", {})
    selection = decision.get("selection", {})
    tracks = decision.get("tracks", {})
    final_gate = decision.get("final_axiom_codec_gate_reminder", {})
    expected_track_bytes = {
        "source_code_bundles": {
            "aggregate_baseline_complete_bytes": 6221486,
            "signal_maximum_complete_bytes": 6159271,
            "strong_maximum_complete_bytes": 6097056,
            "item_maximum_complete_bytes": {
                "cpython-3.14.6-source": 4534272,
                "typescript-6.0.3-source": 1718320,
            },
        },
        "english_wikimedia_wikitext": {
            "aggregate_baseline_complete_bytes": 24156788,
            "signal_maximum_complete_bytes": 23915220,
            "strong_maximum_complete_bytes": 23673652,
            "item_maximum_complete_bytes": {
                "enwikibooks-20260701": 12685899,
                "enwikinews-20260701": 11591672,
            },
        },
    }
    if (
        config.get("schema_version") != 1
        or config.get("name") != "text-source-bwt-kanzi-decomposition-screen-v1"
        or config.get("bindings") != expected_bindings
        or config.get("frozen_before_screen_results") is not True
        or config.get("splits") != expected_splits
        or observed_variants != expected_variants
        or measurement.get("measured_repetitions") != 2
        or measurement.get("warmups") != 0
        or measurement.get("jobs") != 1
        or measurement.get("block_bytes") != 1024**3
        or measurement.get("order_seed") != 20260718
        or measurement.get("timeout_seconds_per_process") != 7200
        or gate.get("integer_complete_byte_comparisons_only") is not True
        or gate.get("signal_gain_percent") != 1.0
        or gate.get("strong_gain_percent") != 2.0
        or gate.get("maximum_item_regression_percent") != 0.5
        or gate.get("maximum_peak_rss_bytes") != 4 * 1024**3
        or gate.get("required_identical_artifacts") != 2
        or gate.get("required_exact_roundtrip") is not True
        or selection.get("evaluate_tracks_independently") is not True
        or selection.get("fixed_variant_tie_order") != list(VARIANTS)
        or tracks != expected_track_bytes
        or final_gate
        != {
            "complete_artifact_accounting_required": True,
            "exact_roundtrip_required": True,
            "maximum_item_regression_percent": 0.5,
            "minimum_aggregate_gain_vs_strongest_complete_baseline_percent": 5.0,
            "two_byte_identical_measured_artifacts_required": True,
        }
        or "not Axiom artifacts" not in config.get("claim_ceiling", "")
    ):
        raise ValueError("BWT screen config differs from the frozen contract")
    for split in expected_splits.values():
        if set(split["screen_items"]) & set(
            split["reserved_evaluation_not_accessed_by_screen"]
        ):
            raise ValueError("BWT screen split overlaps reserved evaluation")


def verify_dependencies(
    *,
    config: dict[str, Any],
    corpus: Path,
    baseline_path: Path,
    structural_result_path: Path,
    predictor_result_path: Path,
    long_range_result_path: Path,
    record_result_path: Path,
    kanzi: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_raw, items = verify_screen_items(corpus, config)
    _baseline_raw, baseline = read_canonical(baseline_path)
    dependency_paths = {
        "structural_results_sha256": structural_result_path,
        "predictor_result_sha256": predictor_result_path,
        "long_range_result_sha256": long_range_result_path,
        "record_neighborhood_result_sha256": record_result_path,
    }
    for path in dependency_paths.values():
        read_canonical(path)
    bindings = config["bindings"]
    if (
        sha256_bytes(manifest_raw) != bindings["corpus_manifest_sha256"]
        or sha256_file(baseline_path) != bindings["baseline_results_sha256"]
        or sha256_file(kanzi) != bindings["kanzi_binary_sha256"]
        or any(sha256_file(path) != bindings[key] for key, path in dependency_paths.items())
        or baseline.get("completed") is not True
        or baseline.get("all_required_completed") is not True
        or baseline.get("tools", {}).get("kanzi", {}).get("binary_sha256")
        != bindings["kanzi_binary_sha256"]
    ):
        raise ValueError("BWT screen dependency binding differs")
    BASELINE_PUBLICATION.validate_trial_receipts(baseline_path, baseline)
    baseline_rows = {
        (row["item_id"], row["codec_id"]): row
        for row in baseline["summary"]["item_codec_rows"]
    }
    expected_baseline_bytes = {
        "cpython-3.14.6-source": 4511714,
        "typescript-6.0.3-source": 1709772,
        "enwikibooks-20260701": 12622786,
        "enwikinews-20260701": 11534002,
    }
    for item in items:
        row = baseline_rows.get((item["id"], "kanzi-max"))
        if (
            row is None
            or row.get("artifact_bytes") != expected_baseline_bytes[item["id"]]
            or row.get("passed") is not True
            or row.get("exact_roundtrip") is not True
            or row.get("deterministic_artifact") is not True
            or row.get("source_bytes") != item["source_bytes"]
        ):
            raise ValueError(f"BWT screen baseline row differs: {item['id']}")
    for track in TRACKS:
        aggregate = sum(
            expected_baseline_bytes[item["id"]]
            for item in items
            if item["track"] == track
        )
        if aggregate != config["decision"]["tracks"][track][
            "aggregate_baseline_complete_bytes"
        ]:
            raise ValueError(f"BWT screen aggregate baseline differs: {track}")
    return items, baseline


def summarize(
    *,
    trials: list[dict[str, Any]],
    items: list[dict[str, Any]],
    baseline: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    baseline_map = {
        row["item_id"]: row
        for row in baseline["summary"]["item_codec_rows"]
        if row["codec_id"] == "kanzi-max"
    }
    repetitions = config["measurement"]["measured_repetitions"]
    gate = config["decision"]["track_gate"]
    track_limits = config["decision"]["tracks"]
    item_rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        for item in items:
            group = [
                row
                for row in trials
                if row["variant"] == variant and row["item_id"] == item["id"]
            ]
            successful = [row for row in group if row.get("passed") is True]
            sizes = {row["artifact_bytes"] for row in successful}
            digests = {row["artifact_sha256"] for row in successful}
            passed = (
                len(group) == repetitions
                and len(successful) == repetitions
                and all(row.get("exact_roundtrip") is True for row in group)
                and len(sizes) == 1
                and len(digests) == 1
            )
            baseline_bytes = baseline_map[item["id"]]["artifact_bytes"]
            artifact_bytes = next(iter(sizes)) if passed else None
            maximum_item_bytes = track_limits[item["track"]][
                "item_maximum_complete_bytes"
            ][item["id"]]
            encode_peak = max(
                (row["compression"]["peak_rss_bytes"] for row in group), default=0
            )
            decode_peak = max(
                (
                    row["decompression"]["peak_rss_bytes"]
                    for row in group
                    if row.get("decompression") is not None
                ),
                default=0,
            )
            item_rows.append(
                {
                    "variant": variant,
                    "item_id": item["id"],
                    "track": item["track"],
                    "source_bytes": item["source_bytes"],
                    "baseline_bytes": baseline_bytes,
                    "artifact_bytes": artifact_bytes,
                    "artifact_sha256": next(iter(digests)) if passed else None,
                    "gain_vs_kanzi_percent": (
                        (baseline_bytes - artifact_bytes) / baseline_bytes * 100.0
                        if passed
                        else None
                    ),
                    "maximum_item_bytes": maximum_item_bytes,
                    "item_guard_passed": bool(passed and artifact_bytes <= maximum_item_bytes),
                    "median_compression_ns": (
                        int(statistics.median(row["compression"]["wall_ns"] for row in group))
                        if passed
                        else None
                    ),
                    "median_decompression_ns": (
                        int(statistics.median(row["decompression"]["wall_ns"] for row in group))
                        if passed
                        else None
                    ),
                    "compression_peak_rss_bytes": encode_peak,
                    "decompression_peak_rss_bytes": decode_peak,
                    "resource_limit_passed": bool(
                        passed
                        and encode_peak <= gate["maximum_peak_rss_bytes"]
                        and decode_peak <= gate["maximum_peak_rss_bytes"]
                    ),
                    "exact_roundtrip": passed,
                    "deterministic_artifact": passed,
                    "passed": passed,
                }
            )

    track_rows: list[dict[str, Any]] = []
    signal_by_track: dict[str, set[str]] = {}
    tie_order = {variant: index for index, variant in enumerate(VARIANTS)}
    for track in TRACKS:
        limits = track_limits[track]
        variants = []
        for variant in VARIANTS:
            selected_items = [
                row
                for row in item_rows
                if row["track"] == track and row["variant"] == variant
            ]
            complete = len(selected_items) == 2 and all(row["passed"] for row in selected_items)
            artifact_bytes = (
                sum(row["artifact_bytes"] for row in selected_items) if complete else None
            )
            item_guard_passed = complete and all(
                row["item_guard_passed"] for row in selected_items
            )
            resource_limit_passed = complete and all(
                row["resource_limit_passed"] for row in selected_items
            )
            ratio_signal = bool(
                complete
                and item_guard_passed
                and artifact_bytes <= limits["signal_maximum_complete_bytes"]
            )
            ratio_strong = bool(
                complete
                and item_guard_passed
                and artifact_bytes <= limits["strong_maximum_complete_bytes"]
            )
            variants.append(
                {
                    "variant": variant,
                    "baseline_bytes": limits["aggregate_baseline_complete_bytes"],
                    "artifact_bytes": artifact_bytes,
                    "gain_vs_kanzi_percent": (
                        (
                            limits["aggregate_baseline_complete_bytes"] - artifact_bytes
                        )
                        / limits["aggregate_baseline_complete_bytes"]
                        * 100.0
                        if complete
                        else None
                    ),
                    "complete": complete,
                    "item_guard_passed": item_guard_passed,
                    "resource_limit_passed": resource_limit_passed,
                    "ratio_signal": ratio_signal,
                    "ratio_strong_signal": ratio_strong,
                    "resource_rejected_ratio_signal": bool(
                        ratio_signal and not resource_limit_passed
                    ),
                    "track_signal": bool(ratio_signal and resource_limit_passed),
                    "track_strong_signal": bool(ratio_strong and resource_limit_passed),
                }
            )
        signal_by_track[track] = {
            row["variant"] for row in variants if row["track_signal"]
        }
        eligible = [row for row in variants if row["track_signal"]]
        selected = (
            min(eligible, key=lambda row: (row["artifact_bytes"], tie_order[row["variant"]]))
            if eligible
            else None
        )
        if selected is None:
            decision = "reject_raw_bwt_direction_for_track"
        elif selected["track_strong_signal"]:
            decision = "admit_token_bwt_representation_prototype_for_track"
        else:
            decision = "retain_diagnostic_bwt_signal_only_for_track"
        track_rows.append(
            {
                "track": track,
                "baseline": "kanzi-max",
                "screen_items": config["splits"][track]["screen_items"],
                "variants": variants,
                "selected_variant": selected["variant"] if selected else None,
                "selected_artifact_bytes": selected["artifact_bytes"] if selected else None,
                "selected_strong_signal": (
                    selected["track_strong_signal"] if selected else False
                ),
                "decision": decision,
            }
        )
    shared = set.intersection(*(signal_by_track[track] for track in TRACKS))
    return {
        "item_rows": item_rows,
        "tracks": track_rows,
        "shared_signal_variants": [variant for variant in VARIANTS if variant in shared],
        "axiom_wins": 0,
        "decision": "track_specific_bwt_screen_complete",
    }


def benchmark(
    *,
    config_path: Path,
    corpus: Path,
    baseline_path: Path,
    structural_result_path: Path,
    predictor_result_path: Path,
    long_range_result_path: Path,
    record_result_path: Path,
    kanzi: Path,
    output: Path,
) -> Path:
    config_raw, config = read_canonical(config_path)
    validate_config(config)
    commit = repository_commit()
    items, baseline = verify_dependencies(
        config=config,
        corpus=corpus,
        baseline_path=baseline_path,
        structural_result_path=structural_result_path,
        predictor_result_path=predictor_result_path,
        long_range_result_path=long_range_result_path,
        record_result_path=record_result_path,
        kanzi=kanzi,
    )
    preflight_rows = preflight(config, kanzi)
    bindings = {
        "repository_commit": commit,
        "config_sha256": sha256_bytes(config_raw),
        **config["bindings"],
    }
    repetitions = config["measurement"]["measured_repetitions"]
    schedule = [
        (variant["id"], item["id"], repetition)
        for variant in config["variants"]
        for item in items
        for repetition in range(repetitions)
    ]
    if len(schedule) != 32:
        raise ValueError("BWT screen schedule must contain exactly 32 trials")
    random.Random(config["measurement"]["order_seed"]).shuffle(schedule)
    items_by_id = {item["id"]: item for item in items}
    variants_by_id = variant_map(config)
    trials = []
    for index, (variant_id, item_id, repetition) in enumerate(schedule, start=1):
        print(f"[{index}/32] r{repetition} {item_id} x {variant_id}", flush=True)
        trials.append(
            run_trial(
                output=output,
                bindings=bindings,
                item=items_by_id[item_id],
                variant=variants_by_id[variant_id],
                repetition=repetition,
                kanzi=kanzi,
                timeout_seconds=config["measurement"]["timeout_seconds_per_process"],
            )
        )
    summary = summarize(trials=trials, items=items, baseline=baseline, config=config)
    result = {
        "schema_version": 1,
        "name": "text-source-bwt-kanzi-decomposition-screen-result-v1",
        "completed": True,
        "all_required_completed": all(row["passed"] for row in summary["item_rows"]),
        "trial_count": len(trials),
        "bindings": bindings,
        "screen_boundary": {track: config["splits"][track] for track in TRACKS},
        "measurement": config["measurement"],
        "preflight": preflight_rows,
        "variants": config["variants"],
        "summary": summary,
        "claim_ceiling": config["claim_ceiling"],
        "public_validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
    }
    destination = output / "results.json"
    if destination.exists():
        _raw, existing = read_canonical(destination)
        if existing != result:
            raise ValueError("BWT screen result differs from retained result")
    else:
        BASELINE_RUNNER.write_json_atomic(destination, result)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--structural-result", type=Path, default=DEFAULT_STRUCTURAL_RESULT)
    parser.add_argument("--predictor-result", type=Path, default=DEFAULT_PREDICTOR_RESULT)
    parser.add_argument("--long-range-result", type=Path, default=DEFAULT_LONG_RANGE_RESULT)
    parser.add_argument("--record-result", type=Path, default=DEFAULT_RECORD_RESULT)
    parser.add_argument("--kanzi", type=Path, default=DEFAULT_KANZI)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = benchmark(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            structural_result_path=args.structural_result,
            predictor_result_path=args.predictor_result,
            long_range_result_path=args.long_range_result,
            record_result_path=args.record_result,
            kanzi=args.kanzi,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"BWT screen failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
