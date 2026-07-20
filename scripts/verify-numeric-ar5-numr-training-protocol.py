#!/usr/bin/env python3
"""Verify the frozen, non-executable AR5/NUM-R training protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from string import Formatter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "numeric-ar5-numr-training-v1.json"
DEFAULT_PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-20-numeric-ar5-numr-training-protocol.md"
)
EXPECTED_CONFIG_SHA256 = "667a6747d12293316080e729e31ec4fe0445f6f45deefbb58ad2c64a545b2530"
EXPECTED_PROTOCOL_SHA256 = "4adfe4f59ac5ee4a5d72a83de31dc7164fb459c4d2bb2b9ba0213f76693927b8"
EXPECTED_TRACKS = [
    "float32_time_series",
    "float64_time_series",
    "float32_dense_matrix",
    "float64_dense_matrix",
    "signed_integer_time_series",
    "unsigned_integer_time_series",
    "signed_integer_dense_matrix",
    "unsigned_integer_dense_matrix",
]
EXPECTED_BASELINES = {
    "fastlanes-alp": (
        "https://github.com/cwida/FastLanes.git",
        "f0edc1020a538f1f8098640fce8347c9ac247a0d",
        "MIT",
    ),
    "fastlanes-integer": (
        "https://github.com/cwida/FastLanes.git",
        "f0edc1020a538f1f8098640fce8347c9ac247a0d",
        "MIT",
    ),
    "chimp-paper": (
        "https://github.com/panagiotisl/chimp.git",
        "320d397157c7e0696b3c64dc1711fc17a3add3da",
        "Apache-2.0",
    ),
    "gorilla-reference-class": (
        "https://github.com/ghilesmeddour/gorilla-time-series-compression.git",
        "093544c6e643aef911ff83527f595bc2d9280ed8",
        "MIT",
    ),
    "blosc2-shuffle-zstd": (
        "https://github.com/Blosc/c-blosc2.git",
        "d52cbeec8afb35ada7ea62f04168e5d970d9c40b",
        "BSD-3-Clause",
    ),
    "blosc2-bytedelta-zstd": (
        "https://github.com/Blosc/c-blosc2.git",
        "d52cbeec8afb35ada7ea62f04168e5d970d9c40b",
        "BSD-3-Clause",
    ),
    "fpzip-exact": (
        "https://github.com/LLNL/fpzip.git",
        "4a539c06d98b1c029b08324a086d4b75689a2b72",
        "BSD-3-Clause",
    ),
    "zstd-19": (
        "https://github.com/facebook/zstd.git",
        "f8745da6ff1ad1e7bab384bd1f9d742439278e99",
        "BSD-3-Clause OR GPL-2.0-only",
    ),
    "brotli-11": (
        "https://github.com/google/brotli.git",
        "028fb5a23661f123017c060daa546b55cf4bde29",
        "MIT",
    ),
    "lz4-12": (
        "https://github.com/lz4/lz4.git",
        "ebb370ca83af193212df4dcbadcc5d87bc0de2f0",
        "BSD-2-Clause",
    ),
    "store": ("in-tree deterministic adapter", None, "MIT"),
}
BASELINE_KEYS = {
    "id",
    "applies_to",
    "repository",
    "revision",
    "license",
    "license_file",
    "binary",
    "build",
    "encode",
    "decode",
    "binary_sha256",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        actual = set(value) if isinstance(value, dict) else set()
        raise ValueError(
            f"{label} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def verify_config(config: dict[str, Any]) -> None:
    exact_keys(
        config,
        {
            "schema_version",
            "name",
            "status",
            "claim_scope",
            "claim_ceiling",
            "measurement_authorized",
            "authorization_blockers",
            "evaluation",
            "tracks",
            "input_contract",
            "block_contract",
            "candidate",
            "cheap_ablations",
            "external_baselines",
            "baseline_artifact_rule",
            "baseline_applicability_rule",
            "toolchain_lock_rule",
            "gates",
            "timing",
            "required_next_artifacts",
            "results",
        },
        "config",
    )
    if config["schema_version"] != 1:
        raise ValueError("schema version must be one")
    if config["name"] != "numeric-ar5-numr-training-v1":
        raise ValueError("protocol name mismatch")
    if config["status"] != "frozen_protocol_only":
        raise ValueError("status must remain protocol-only")
    if config["measurement_authorized"] is not False or config["results"] is not None:
        raise ValueError("protocol must not authorize measurement or contain results")
    if len(config["authorization_blockers"]) != 4:
        raise ValueError("all four fail-closed authorization blockers are required")
    if config["tracks"] != EXPECTED_TRACKS:
        raise ValueError("declared numeric tracks drifted")
    evaluation = config["evaluation"]
    exact_keys(
        evaluation,
        {
            "training",
            "validation",
            "private_holdout",
            "independent_reproduction",
            "forbidden_prior_numeric_validation_families",
        },
        "evaluation",
    )
    if evaluation["validation"] != "sealed_and_unauthorized":
        raise ValueError("validation must remain sealed")
    if evaluation["private_holdout"] != "sealed_and_unauthorized":
        raise ValueError("private holdout must remain sealed")
    if evaluation["forbidden_prior_numeric_validation_families"] != [
        "UCI Gisette",
        "UCI Madelon",
    ]:
        raise ValueError("consumed DMS2 families must remain forbidden")
    inputs = config["input_contract"]
    exact_keys(
        inputs,
        {
            "accepted_dtypes",
            "accepted_endianness",
            "layouts",
            "required_side_metadata",
            "exactness",
            "float_special_values",
            "integer_arithmetic",
            "maximum_item_bytes",
            "minimum_values_per_item",
        },
        "input contract",
    )
    if inputs["accepted_dtypes"] != [
        "float32",
        "float64",
        "int16",
        "int32",
        "int64",
        "uint16",
        "uint32",
        "uint64",
    ]:
        raise ValueError("dtype contract drifted")
    if inputs["accepted_endianness"] != ["little", "big"]:
        raise ValueError("both explicit endian orders are required")
    for token in ("signed zero", "NaN sign/payload/signaling", "subnormal"):
        if token not in inputs["float_special_values"]:
            raise ValueError(f"float exactness omits {token}")
    blocks = config["block_contract"]
    exact_keys(
        blocks,
        {
            "vector_values",
            "superblock_values",
            "stream_chunk_max_bytes",
            "independent_superblocks",
            "random_access_index_accounted",
            "checksum",
            "complete_accounting",
        },
        "block contract",
    )
    if blocks["vector_values"] != 1024 or blocks["superblock_values"] != 65536:
        raise ValueError("vector or superblock boundary drifted")
    if blocks["stream_chunk_max_bytes"] != 64 * 1024 * 1024:
        raise ValueError("stream chunk must remain bounded at 64 MiB")
    if len(blocks["complete_accounting"]) < 10:
        raise ValueError("complete metadata accounting is incomplete")
    candidate = config["candidate"]
    exact_keys(
        candidate,
        {
            "family",
            "float_decimal_origin_recast",
            "predictors",
            "lpc_coefficients",
            "residual_encodings",
            "internal_zstd",
            "fallbacks",
            "selector",
        },
        "candidate",
    )
    if candidate["family"] != "AR5/NUM-R":
        raise ValueError("candidate family mismatch")
    recast = candidate["float_decimal_origin_recast"]
    exact_keys(
        recast,
        {
            "description",
            "float32_exponents",
            "float64_exponents",
            "factor_rule",
            "origin_rule",
            "arithmetic_rule",
            "exceptions",
            "selection",
        },
        "decimal recast",
    )
    if recast["float32_exponents"] != list(range(11)):
        raise ValueError("float32 exponent search drifted")
    if recast["float64_exponents"] != list(range(19)):
        raise ValueError("float64 exponent search drifted")
    for forbidden in ("host floating-point", "fast-math"):
        if forbidden not in recast["arithmetic_rule"]:
            raise ValueError(f"decimal arithmetic rule omits {forbidden}")
    required_predictors = {
        "xor_previous_with_reused_front_and_trailing_zero_window",
        "delta",
        "delta2",
        "integer_lpc_order_1",
        "integer_lpc_order_2",
        "integer_lpc_order_4",
    }
    if not required_predictors.issubset(candidate["predictors"]):
        raise ValueError("required predictors are missing")
    internal_zstd = candidate["internal_zstd"]
    exact_keys(
        internal_zstd,
        {
            "repository",
            "revision",
            "license",
            "level",
            "threads",
            "dictionary",
            "frame_checksum",
            "content_size",
            "long_distance_matching",
            "parameter_lock_rule",
        },
        "internal zstd",
    )
    if (
        internal_zstd["repository"] != EXPECTED_BASELINES["zstd-19"][0]
        or internal_zstd["revision"] != EXPECTED_BASELINES["zstd-19"][1]
        or internal_zstd["license"] != EXPECTED_BASELINES["zstd-19"][2]
        or internal_zstd["level"] != 9
        or internal_zstd["threads"] != 1
        or internal_zstd["dictionary"] != "none"
        or internal_zstd["frame_checksum"] is not True
        or internal_zstd["content_size"] is not True
        or internal_zstd["long_distance_matching"] is not False
    ):
        raise ValueError("candidate internal Zstandard lock drifted")
    if candidate["fallbacks"] != [
        "xor_front_bit",
        "byte_plane_zstd",
        "direct_zstd",
        "store",
    ]:
        raise ValueError("fallback order drifted")
    selector = candidate["selector"]
    exact_keys(
        selector,
        {
            "evidence",
            "rule",
            "maximum_probe_bytes",
            "fallback_expansion_rule",
            "maximum_expansion_over_store_bytes",
            "deterministic",
            "selector_metadata_accounted",
            "analysis_time_counted",
            "temporary_memory_counted",
        },
        "selector",
    )
    if selector["maximum_probe_bytes"] != 64 * 1024 * 1024:
        raise ValueError("selector probe is unbounded")
    if selector["maximum_expansion_over_store_bytes"] != 96:
        raise ValueError("safe store expansion ceiling drifted")
    if not all(
        selector[field]
        for field in (
            "deterministic",
            "selector_metadata_accounted",
            "analysis_time_counted",
            "temporary_memory_counted",
        )
    ):
        raise ValueError("selector overhead or determinism is not fully counted")
    ablations = config["cheap_ablations"]
    if [row["id"] for row in ablations] != [
        "NUM-R0",
        "NUM-R1",
        "AR5-A",
        "AR5-B",
        "NUM-R2",
        "NUM-R3",
        "NUM-R4",
    ]:
        raise ValueError("cheap ablation ladder drifted")
    for index, row in enumerate(ablations):
        exact_keys(row, {"id", "change", "kill_rule"}, f"ablation {index}")
    baselines = config["external_baselines"]
    by_id = {row["id"]: row for row in baselines}
    if len(by_id) != len(baselines) or set(by_id) != set(EXPECTED_BASELINES):
        raise ValueError("baseline roster is incomplete or duplicated")
    for baseline_id, expected in EXPECTED_BASELINES.items():
        row = by_id[baseline_id]
        exact_keys(row, BASELINE_KEYS, f"baseline {baseline_id}")
        allowed_applicability = {
            "all",
            *EXPECTED_TRACKS,
            *config["input_contract"]["accepted_dtypes"],
        }
        if (
            not isinstance(row["applies_to"], list)
            or not row["applies_to"]
            or not set(row["applies_to"]).issubset(allowed_applicability)
        ):
            raise ValueError(f"baseline applicability is invalid: {baseline_id}")
        repository, revision, license_id = expected
        if (row["repository"], row["revision"], row["license"]) != expected:
            raise ValueError(f"baseline identity drifted: {baseline_id}")
        require_nonempty_string(row["license_file"], f"{baseline_id} license file")
        require_nonempty_string(row["binary"], f"{baseline_id} binary")
        require_nonempty_string(row["build"], f"{baseline_id} build command")
        encode = require_nonempty_string(row["encode"], f"{baseline_id} encode")
        decode = require_nonempty_string(row["decode"], f"{baseline_id} decode")
        if "{input}" not in encode or "{output}" not in encode:
            raise ValueError(f"baseline encode command is not exact-path framed: {baseline_id}")
        if "{input}" not in decode or "{output}" not in decode:
            raise ValueError(f"baseline decode command is not exact-path framed: {baseline_id}")
        allowed_placeholders = {
            "input",
            "output",
            "dtype",
            "shape",
            "typesize",
            "timestamps",
        }
        placeholders = {
            field_name
            for command in (encode, decode)
            for _, field_name, _, _ in Formatter().parse(command)
            if field_name is not None
        }
        if not placeholders.issubset(allowed_placeholders):
            raise ValueError(f"baseline command has unknown placeholders: {baseline_id}")
        if row["binary_sha256"] is not None:
            raise ValueError("binary digests must remain null until acquisition lock")
        if revision is not None and (
            not isinstance(revision, str) or len(revision) != 40
        ):
            raise ValueError(f"baseline revision is not a full commit: {baseline_id}")
        if repository != "in-tree deterministic adapter" and not repository.startswith(
            "https://github.com/"
        ):
            raise ValueError(f"baseline repository is not official HTTPS: {baseline_id}")
    track_dtype_families = {
        "float32_time_series": {"float32"},
        "float64_time_series": {"float64"},
        "float32_dense_matrix": {"float32"},
        "float64_dense_matrix": {"float64"},
        "signed_integer_time_series": {"int16", "int32", "int64"},
        "unsigned_integer_time_series": {"uint16", "uint32", "uint64"},
        "signed_integer_dense_matrix": {"int16", "int32", "int64"},
        "unsigned_integer_dense_matrix": {"uint16", "uint32", "uint64"},
    }
    specialist_ids = {
        "fastlanes-alp",
        "fastlanes-integer",
        "chimp-paper",
        "gorilla-reference-class",
        "blosc2-shuffle-zstd",
        "blosc2-bytedelta-zstd",
        "fpzip-exact",
    }
    for track, dtypes in track_dtype_families.items():
        applicable = {
            row["id"]
            for row in baselines
            if "all" in row["applies_to"]
            or track in row["applies_to"]
            or bool(dtypes.intersection(row["applies_to"]))
        }
        if not applicable.intersection(specialist_ids):
            raise ValueError(f"track has no applicable specialist baseline: {track}")
    for baseline_id in ("chimp-paper", "gorilla-reference-class"):
        if "{timestamps}" not in by_id[baseline_id]["encode"]:
            raise ValueError(f"timestamp specialist lacks timestamp input: {baseline_id}")
    applicability = require_nonempty_string(
        config["baseline_applicability_rule"], "baseline applicability rule"
    )
    for token in ("source-provided complete timestamp", "value-only", "synthetic"):
        if token not in applicability:
            raise ValueError(f"baseline applicability rule omits {token}")
    gate_sets = config["gates"]
    exact_keys(
        gate_sets,
        {"training", "future_validation", "future_private_holdout"},
        "gates",
    )
    training = gate_sets["training"]
    exact_keys(
        training,
        {
            "exact_all_items",
            "aggregate_complete_bytes_at_most_fraction_of_strongest_applicable_baseline",
            "each_declared_track_complete_bytes_at_most_fraction_of_strongest_applicable_baseline",
            "maximum_per_item_regression_vs_safe_direct_or_store_fraction",
            "compression_mbps_minimum",
            "decompression_mbps_minimum",
            "compression_speed_fraction_of_fastest_ratio_baseline_minimum",
            "decompression_speed_fraction_of_fastest_ratio_baseline_minimum",
            "peak_rss_bytes_maximum",
            "stream_chunk_bytes_maximum",
            "two_identical_encoded_repetitions",
            "cross_arch_same_encoded_sha256",
            "cross_arch_cross_decode_exact",
            "corruption_and_truncation_suite",
        },
        "training gates",
    )
    if training[
        "aggregate_complete_bytes_at_most_fraction_of_strongest_applicable_baseline"
    ] != 0.94 or training[
        "each_declared_track_complete_bytes_at_most_fraction_of_strongest_applicable_baseline"
    ] != 0.94:
        raise ValueError("training advancement must remain at least 6%")
    future_validation = gate_sets["future_validation"]
    exact_keys(
        future_validation,
        {
            "authorization",
            "aggregate_and_each_track_advancement_fraction",
            "no_tuning_or_rerun",
        },
        "future validation gates",
    )
    future_holdout = gate_sets["future_private_holdout"]
    exact_keys(
        future_holdout,
        {
            "authorization",
            "aggregate_and_each_track_advancement_fraction",
            "threshold_rationale",
            "one_shot",
            "independent_custodian",
        },
        "future private holdout gates",
    )
    if future_validation[
        "aggregate_and_each_track_advancement_fraction"
    ] != 0.06:
        raise ValueError("future validation target must remain 6%")
    if future_holdout[
        "aggregate_and_each_track_advancement_fraction"
    ] != 0.05:
        raise ValueError("private holdout target must remain 5%")
    if future_validation["no_tuning_or_rerun"] is not True:
        raise ValueError("validation must forbid tuning and reruns")
    if (
        future_holdout["one_shot"] is not True
        or future_holdout["independent_custodian"] is not True
    ):
        raise ValueError("private holdout must remain one-shot and independent")
    if training["peak_rss_bytes_maximum"] != 512 * 1024 * 1024:
        raise ValueError("training RSS ceiling drifted")
    timing = config["timing"]
    exact_keys(
        timing,
        {
            "host",
            "process",
            "warmups_per_item_variant",
            "measured_rounds",
            "order",
            "included",
            "excluded",
            "rss",
        },
        "timing",
    )
    if timing["warmups_per_item_variant"] != 1 or timing["measured_rounds"] != 7:
        raise ValueError("timing schedule drifted")
    included = " ".join(timing["included"])
    for term in ("selector probes", "output write", "restored SHA-256"):
        if term not in included:
            raise ValueError(f"runtime accounting omits {term}")
    if len(config["required_next_artifacts"]) != 6:
        raise ValueError("required premeasurement artifacts are incomplete")


def verify_protocol_text(text: str) -> None:
    normalized = " ".join(text.split())
    required = [
        "measurement_authorized: false",
        "Gisette",
        "Madelon",
        "signed zero",
        "NaN payload",
        "integer-rational inverse",
        "XOR/front-bit",
        "delta2",
        "LPC orders 1, 2, and 4",
        "byte-plane",
        "candidate-internal Zstandard",
        "FastLanes",
        "Chimp128",
        "Gorilla",
        "Blosc2",
        "fpzip",
        "at least 6%",
        "5% aggregate and per-track",
        "300 MB/s",
        "1,000 MB/s",
        "512 MiB",
        "64 MiB",
        "cross-decode",
        "No benchmark command in this protocol is currently authorized to run.",
    ]
    missing = [token for token in required if token not in normalized]
    if missing:
        raise ValueError(f"protocol text is missing frozen requirements: {missing}")


def verify(config_path: Path, protocol_path: Path) -> dict[str, Any]:
    with config_path.open(encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be an object")
    verify_config(config)
    verify_protocol_text(protocol_path.read_text(encoding="utf-8"))
    config_digest = sha256_file(config_path)
    protocol_digest = sha256_file(protocol_path)
    if (
        config_path.resolve() == DEFAULT_CONFIG.resolve()
        and config_digest != EXPECTED_CONFIG_SHA256
    ):
        raise ValueError("frozen config SHA-256 drifted")
    if (
        protocol_path.resolve() == DEFAULT_PROTOCOL.resolve()
        and protocol_digest != EXPECTED_PROTOCOL_SHA256
    ):
        raise ValueError("frozen protocol SHA-256 drifted")
    return {
        "schema_version": 1,
        "name": "numeric-ar5-numr-training-protocol-verification-v1",
        "config_sha256": config_digest,
        "protocol_sha256": protocol_digest,
        "measurement_authorized": False,
        "results_present": False,
        "baseline_count": len(config["external_baselines"]),
        "track_count": len(config["tracks"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    args = parser.parse_args()
    result = verify(args.config, args.protocol)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
