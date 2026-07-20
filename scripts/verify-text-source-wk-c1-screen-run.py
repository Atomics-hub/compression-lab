#!/usr/bin/env python3
"""Verify a retained WK-C1 screen run from canonical receipts."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-wk-c1-screen-v1.json"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-wk-c1-screen-v1"


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


RUNNER = load_script(
    "wk_c1_runner_for_verifier",
    REPOSITORY / "scripts" / "benchmark-text-source-wk-c1-screen.py",
)


def validate_preflight(rows: object) -> None:
    if (
        not isinstance(rows, list)
        or len(rows) != 2
        or [row.get("variant") for row in rows if isinstance(row, dict)]
        != list(RUNNER.VARIANTS)
    ):
        raise ValueError("WK-C1 preflight roster differs")
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "variant",
                "source_bytes",
                "transform_bytes",
                "transform_sha256",
                "exact_roundtrip",
                "deterministic_transform",
            }
            or type(row.get("source_bytes")) is not int
            or row["source_bytes"] <= 0
            or type(row.get("transform_bytes")) is not int
            or row["transform_bytes"] <= 0
            or not isinstance(row.get("transform_sha256"), str)
            or len(row["transform_sha256"]) != 64
            or row.get("exact_roundtrip") is not True
            or row.get("deterministic_transform") is not True
        ):
            raise ValueError("WK-C1 preflight evidence differs")


def validate_receipt(
    receipt: dict[str, Any],
    *,
    bindings: dict[str, Any],
    variant: str,
    item_id: str,
    repetition: int,
) -> None:
    if (
        receipt.get("schema_version") != 1
        or receipt.get("bindings") != bindings
        or receipt.get("variant") != variant
        or receipt.get("item_id") != item_id
        or receipt.get("repetition") != repetition
        or receipt.get("passed") is not True
        or receipt.get("exact_roundtrip") is not True
        or receipt.get("error") is not None
        or type(receipt.get("artifact_bytes")) is not int
        or receipt["artifact_bytes"] <= RUNNER.FRAME_HEADER.size
        or not isinstance(receipt.get("artifact_sha256"), str)
        or len(receipt["artifact_sha256"]) != 64
        or type(receipt.get("encode_peak_rss_bytes")) is not int
        or type(receipt.get("decode_peak_rss_bytes")) is not int
        or not isinstance(receipt.get("encode_processes"), list)
        or len(receipt["encode_processes"]) != 3
        or not isinstance(receipt.get("decode_processes"), list)
        or len(receipt["decode_processes"]) != 3
    ):
        raise ValueError("WK-C1 successful receipt differs")
    RUNNER.validate_trial_receipt(
        receipt,
        bindings=bindings,
        variant=variant,
        item={
            "id": item_id,
            "source_bytes": receipt["source_bytes"],
            "source_sha256": receipt["source_sha256"],
        },
        repetition=repetition,
    )
    encode_commands = [row.get("command", []) for row in receipt["encode_processes"]]
    decode_commands = [row.get("command", []) for row in receipt["decode_processes"]]
    if (
        "encode" not in encode_commands[0]
        or variant not in encode_commands[0]
        or "--compress" not in encode_commands[1]
        or "--level=9" not in encode_commands[1]
        or "wrap" not in encode_commands[2]
        or "unwrap" not in decode_commands[0]
        or "--decompress" not in decode_commands[1]
        or "decode" not in decode_commands[2]
    ):
        raise ValueError("WK-C1 process chain differs")
    for process in [*receipt["encode_processes"], *receipt["decode_processes"]]:
        if (
            process.get("returncode") != 0
            or process.get("timed_out") is not False
            or type(process.get("wall_ns")) is not int
            or process["wall_ns"] <= 0
            or type(process.get("peak_rss_bytes")) is not int
            or process["peak_rss_bytes"] < 0
        ):
            raise ValueError("WK-C1 successful process differs")


def validate_resource_smoke(rows: object, config: dict[str, Any]) -> None:
    expected = {
        (variant, item_id)
        for variant in RUNNER.VARIANTS
        for item_id in RUNNER.SCREEN_ITEMS
    }
    if not isinstance(rows, list) or len(rows) != 4:
        raise ValueError("WK-C1 resource smoke roster differs")
    observed = {(row.get("variant"), row.get("item_id")) for row in rows}
    maximum_rss = config["measurement"]["premeasurement_resource_smoke"][
        "maximum_peak_rss_bytes"
    ]
    if observed != expected:
        raise ValueError("WK-C1 resource smoke roster differs")
    for row in rows:
        encode = row.get("encode")
        backend_encode = row.get("backend_encode")
        backend_decode = row.get("backend_decode")
        decode = row.get("decode")
        for process in (encode, backend_encode, backend_decode, decode):
            RUNNER.validate_process_record(process)
        transform_evidence = row.get("transform_file_evidence")
        if (
            not isinstance(encode, dict)
            or not isinstance(backend_encode, dict)
            or not isinstance(backend_decode, dict)
            or not isinstance(decode, dict)
            or row.get("passed") is not True
            or row.get("exact_roundtrip") is not True
            or row.get("error") is not None
            or not isinstance(transform_evidence, dict)
            or type(transform_evidence.get("size_bytes")) is not int
            or transform_evidence["size_bytes"] <= 0
            or not isinstance(transform_evidence.get("sha256"), str)
            or len(transform_evidence["sha256"]) != 64
            or row["maximum_peak_rss_bytes"]
            != max(
                process.get("peak_rss_bytes", -1)
                for process in (encode, backend_encode, backend_decode, decode)
            )
            or row["maximum_peak_rss_bytes"] > maximum_rss
            or any(
                process.get("returncode") != 0 or process.get("timed_out") is not False
                for process in (encode, backend_encode, backend_decode, decode)
            )
            or "--compress" not in backend_encode.get("command", [])
            or "--decompress" not in backend_decode.get("command", [])
        ):
            raise ValueError("WK-C1 resource smoke evidence differs")


def verify(config_path: Path, output: Path) -> dict[str, Any]:
    config_raw, config = RUNNER.read_canonical(config_path)
    RUNNER.validate_config(config)
    _result_raw, result = RUNNER.read_canonical(output / "results.json")
    bindings = result.get("bindings", {})
    if (
        result.get("schema_version") != 1
        or result.get("name")
        != "text-source-wk-c1-recursive-template-columnarization-screen-result-v1"
        or result.get("completed") is not True
        or result.get("all_required_completed") is not True
        or result.get("trial_count") != 8
        or not isinstance(result.get("trial_receipts_manifest_sha256"), str)
        or len(result["trial_receipts_manifest_sha256"]) != 64
        or result.get("measurement") != config["measurement"]
        or result.get("variants") != config["variants"]
        or result.get("screen_boundary") != config["splits"]
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
        or not isinstance(bindings.get("transform_sha256"), str)
        or len(bindings["transform_sha256"]) != 64
        or bindings["transform_sha256"] != RUNNER.sha256_file(RUNNER.DEFAULT_TRANSFORM)
    ):
        raise ValueError("WK-C1 result identity or binding differs")
    validate_preflight(result.get("preflight"))
    validate_resource_smoke(result.get("premeasurement_resource_smoke"), config)
    expected_paths = {
        output / "trials" / variant / f"{item_id}.r{repetition}.json": (
            variant,
            item_id,
            repetition,
        )
        for variant in RUNNER.VARIANTS
        for item_id in RUNNER.SCREEN_ITEMS
        for repetition in range(config["measurement"]["measured_repetitions"])
    }
    observed_paths = set((output / "trials").glob("*/*.json"))
    if len(expected_paths) != 8 or observed_paths != set(expected_paths):
        raise ValueError("WK-C1 trial receipt roster differs")
    trials = []
    for path, (variant, item_id, repetition) in sorted(expected_paths.items()):
        _raw, receipt = RUNNER.read_canonical(path)
        validate_receipt(
            receipt,
            bindings=bindings,
            variant=variant,
            item_id=item_id,
            repetition=repetition,
        )
        trials.append(receipt)
    if result["trial_receipts_manifest_sha256"] != RUNNER.receipt_manifest(
        output, list(expected_paths)
    ):
        raise ValueError("WK-C1 trial receipt manifest binding differs")
    expected_summary = RUNNER.summarize(trials, config)
    if result.get("summary") != expected_summary:
        raise ValueError("WK-C1 decision does not reconstruct from receipts")
    return {
        "verified": True,
        "trial_count": 8,
        "exact_deterministic_item_variant_count": sum(
            row["passed"] for row in expected_summary["item_rows"]
        ),
        "full_signal": expected_summary["full_signal"],
        "full_strong_signal": expected_summary["full_strong_signal"],
        "decision": expected_summary["decision"],
        "axiom_wins": 0,
        "claim_ceiling": result["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = verify(args.config, args.output)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"WK-C1 run verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
