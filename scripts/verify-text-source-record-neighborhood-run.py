#!/usr/bin/env python3
"""Verify every receipt and recompute the record-neighborhood decision."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


RUNNER = load_script(
    "record_neighborhood_runner_for_verification",
    REPOSITORY / "scripts" / "benchmark-text-source-record-neighborhood-screen.py",
)


def validate_processes(
    receipt: dict[str, Any], item: dict[str, Any], kanzi: Path, transform: Path
) -> None:
    processes = receipt.get("processes")
    expected = RUNNER.expected_process_commands(item, kanzi, transform)
    if not isinstance(processes, dict) or set(processes) != {
        "compression",
        "decompression",
    }:
        raise ValueError("record-neighborhood process phases differ")
    for phase in ("compression", "decompression"):
        rows = processes[phase]
        if not isinstance(rows, list) or len(rows) != 3:
            raise ValueError("record-neighborhood process count differs")
        for index, row in enumerate(rows):
            if (
                not isinstance(row, dict)
                or set(row)
                != {
                    "command",
                    "cpu_ns",
                    "peak_rss_bytes",
                    "returncode",
                    "stderr",
                    "stdout",
                    "timed_out",
                    "wall_ns",
                }
                or row.get("command") != expected[phase][index]
                or row.get("returncode") != 0
                or row.get("timed_out") is not False
                or type(row.get("wall_ns")) is not int
                or row["wall_ns"] <= 0
                or type(row.get("cpu_ns")) is not int
                or row["cpu_ns"] < 0
                or type(row.get("peak_rss_bytes")) is not int
                or row["peak_rss_bytes"] < 0
                or not isinstance(row.get("stdout"), str)
                or not isinstance(row.get("stderr"), str)
            ):
                raise ValueError("record-neighborhood process receipt differs")


def validate_receipt(
    receipt: dict[str, Any],
    *,
    bindings: dict[str, str],
    item: dict[str, Any],
    repetition: int,
    kanzi: Path,
    transform: Path,
) -> None:
    expected = {
        "baseline_bytes": item["baseline_bytes"],
        "bindings": bindings,
        "item_id": item["id"],
        "repetition": repetition,
        "schema_version": 1,
        "source_bytes": item["source_bytes"],
        "source_sha256": item["source_sha256"],
        "structural_control_bytes": item["structural_control_bytes"],
        "track": item["track"],
        "variant": RUNNER.VARIANT,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("record-neighborhood trial identity differs")
    if (
        receipt.get("passed") is not True
        or receipt.get("exact_roundtrip") is not True
        or receipt.get("error") is not None
        or type(receipt.get("candidate_bytes")) is not int
        or receipt["candidate_bytes"] <= RUNNER.FRAME_HEADER.size
        or type(receipt.get("backend_payload_bytes")) is not int
        or receipt["candidate_bytes"]
        != RUNNER.FRAME_HEADER.size + receipt["backend_payload_bytes"]
        or type(receipt.get("transformed_bytes")) is not int
        or receipt["transformed_bytes"] <= 0
        or not isinstance(receipt.get("candidate_sha256"), str)
        or len(receipt["candidate_sha256"]) != 64
        or type(receipt.get("compression_wall_ns")) is not int
        or receipt["compression_wall_ns"] <= 0
        or type(receipt.get("decompression_wall_ns")) is not int
        or receipt["decompression_wall_ns"] <= 0
    ):
        raise ValueError("record-neighborhood successful trial differs")
    validate_processes(receipt, item, kanzi, transform)
    if receipt["compression_wall_ns"] != sum(
        row["wall_ns"] for row in receipt["processes"]["compression"]
    ) or receipt["decompression_wall_ns"] != sum(
        row["wall_ns"] for row in receipt["processes"]["decompression"]
    ):
        raise ValueError("record-neighborhood process totals differ")


def verify(
    *,
    config_path: Path,
    corpus: Path,
    baseline_path: Path,
    structural_result_path: Path,
    structural_evidence_path: Path,
    long_range_result_path: Path,
    transform: Path,
    kanzi: Path,
    output: Path,
) -> dict[str, Any]:
    config_raw, config = RUNNER.read_canonical(config_path)
    RUNNER.validate_config(config)
    items, _baseline = RUNNER.verify_dependencies(
        config=config,
        corpus=corpus,
        baseline_path=baseline_path,
        structural_result_path=structural_result_path,
        structural_evidence_path=structural_evidence_path,
        long_range_result_path=long_range_result_path,
        transform=transform,
        kanzi=kanzi,
    )
    result_raw, result = RUNNER.read_canonical(output / "results.json")
    bindings = result.get("bindings", {})
    if (
        result.get("name") != "text-source-record-neighborhood-screen-result-v1"
        or result.get("completed") is not True
        or result.get("all_required_completed") is not True
        or result.get("trial_count") != 8
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
    ):
        raise ValueError("record-neighborhood result identity or binding differs")
    expected_paths = {
        RUNNER.trial_path(output, item["id"], repetition)
        for item in items
        for repetition in range(config["measurement"]["measured_repetitions"])
    }
    observed_paths = set((output / "trials").glob("*/*.json"))
    if observed_paths != expected_paths or any(path.is_symlink() for path in observed_paths):
        raise ValueError("record-neighborhood trial receipt roster differs")
    by_id = {item["id"]: item for item in items}
    trials = []
    for path in sorted(expected_paths):
        _raw, receipt = RUNNER.read_canonical(path)
        validate_receipt(
            receipt,
            bindings=bindings,
            item=by_id[receipt["item_id"]],
            repetition=receipt["repetition"],
            kanzi=kanzi,
            transform=transform,
        )
        trials.append(receipt)
    expected_summary = RUNNER.summarize(trials=trials, items=items, config=config)
    if result.get("summary") != expected_summary:
        raise ValueError("record-neighborhood decision does not reconstruct")
    return {
        "axiom_prototype_admitted": expected_summary["axiom_prototype_admitted"],
        "axiom_wins": expected_summary["axiom_wins"],
        "claim_ceiling": result["claim_ceiling"],
        "decision": expected_summary["decision"],
        "exact_deterministic_item_count": sum(
            row["passed"] for row in expected_summary["item_rows"]
        ),
        "result_sha256": RUNNER.sha256_bytes(result_raw),
        "trial_count": len(trials),
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=RUNNER.DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=RUNNER.DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=RUNNER.DEFAULT_BASELINE)
    parser.add_argument(
        "--structural-result", type=Path, default=RUNNER.DEFAULT_STRUCTURAL_RESULT
    )
    parser.add_argument(
        "--structural-evidence", type=Path, default=RUNNER.DEFAULT_STRUCTURAL_EVIDENCE
    )
    parser.add_argument(
        "--long-range-result", type=Path, default=RUNNER.DEFAULT_LONG_RANGE_RESULT
    )
    parser.add_argument("--transform", type=Path, default=RUNNER.DEFAULT_TRANSFORM)
    parser.add_argument("--kanzi", type=Path, default=RUNNER.DEFAULT_KANZI)
    parser.add_argument("--output", type=Path, default=RUNNER.DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = verify(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            structural_result_path=args.structural_result,
            structural_evidence_path=args.structural_evidence,
            long_range_result_path=args.long_range_result,
            transform=args.transform,
            kanzi=args.kanzi,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"record-neighborhood run verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
