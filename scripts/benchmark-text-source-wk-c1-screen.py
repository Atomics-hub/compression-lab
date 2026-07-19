#!/usr/bin/env python3
"""Execution scaffold for the frozen WK-C1 training-only screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import struct
import sys
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-wk-c1-screen-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_KANZI = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
DEFAULT_TRANSFORM = REPOSITORY / "scripts" / "text-source-wk-c1-transform.py"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-wk-c1-screen-v1"
DEFAULT_STRUCTURAL_RESULT = (
    REPOSITORY / "runs" / "text-source-structural-transform-development-v1" / "results.json"
)
DEFAULT_STRUCTURAL_EVIDENCE = (
    REPOSITORY
    / "runs"
    / "text-source-structural-transform-development-v1"
    / "publication"
    / "evidence.json"
)
DEFAULT_SUCCESSOR_DECISION = (
    REPOSITORY / "runs" / "text-source-structural-successor-decision-v1.json"
)
DEFAULT_SUCCESSOR_ROUTING = REPOSITORY / "config" / "text-source-successor-routing-v1.json"
DEFAULT_BWT_RESULT = REPOSITORY / "runs" / "text-source-bwt-screen-v1" / "results.json"
DEFAULT_BWT_EVIDENCE = (
    REPOSITORY / "runs" / "text-source-bwt-screen-v1" / "publication" / "evidence.json"
)
DEFAULT_BWT_RECEIPT = (
    REPOSITORY / "runs" / "text-source-bwt-screen-v1" / "publication" / "receipt.json"
)
VARIANTS = ("wk-c1-full-schema-columns", "wk-c1-structure-only")
SCREEN_ITEMS = ("enwikibooks-20260701", "enwikinews-20260701")
FRAME_MAGIC = b"AXWK2"
FRAME_VERSION = 1
BACKEND_KIND = 1
VARIANT_KIND = {VARIANTS[0]: 1, VARIANTS[1]: 2}
FRAME_HEADER = struct.Struct("<5sBBBQ32sQ32s")


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COMMON = load_script(
    "long_range_helpers_for_wk_c1",
    REPOSITORY / "scripts" / "benchmark-text-source-long-range-screen.py",
)
TRANSFORM = load_script("wk_c1_transform_for_runner", DEFAULT_TRANSFORM)
json_bytes = COMMON.json_bytes
sha256_bytes = COMMON.sha256_bytes
sha256_file = COMMON.sha256_file
read_canonical = COMMON.read_canonical


def validate_config(config: dict[str, Any]) -> None:
    expected_bindings = {
        "baseline_results_sha256": "08b66858cc5b7438c3aa134545642a54c8ea434b9c16d86db3ce8cc46122a5bc",
        "bwt_public_evidence_sha256": "ca4706658dab1f23b4becfba80b274b1c57aa488c52fa95e84211c949bfb5eef",
        "bwt_publication_receipt_sha256": "fc15cf05e538a69c0f2a84043d435b51339d937b6771615888de720f9e30c0f0",
        "bwt_result_sha256": "ef0c65b19ba6a7a6d5f3a9c439f5b2a5f9b563dec133862b4225b9490723e9fd",
        "corpus_manifest_sha256": "745ade4b15b1c78439d8f9cc89d8a55065f538f5aac2fc01a9c7fe698487a409",
        "kanzi_binary_sha256": "3c93e96fb108ebf8152e187ef0f830b03952200dc94b449fcec8d158e7474618",
        "structural_public_evidence_sha256": "e7b25f117866983214192183d076ed1cbac74490569653e302308c87ddeb3e97",
        "structural_results_sha256": "92a29a1e184a04293ce04bfdd05f5e7ba7dd0d7f12873edce3d2926c1628db93",
        "successor_decision_sha256": "436521a4ef66c2142058abd2806e86f4c52e208877455dcf9353738849da5a7f",
        "successor_routing_config_sha256": "aacfcafa25363682e001a11f82e002196589ca6cc8855c79b65d4d512077767b",
    }
    expected_variants = [
        ("wk-c1-full-schema-columns", True),
        ("wk-c1-structure-only", False),
    ]
    gate = config.get("decision", {}).get("track_gate", {})
    attribution = config.get("decision", {}).get("attribution", {})
    limits = config.get("scanner_limits", {})
    if (
        config.get("schema_version") != 1
        or config.get("name")
        != "text-source-wk-c1-recursive-template-columnarization-screen-v1"
        or config.get("frozen_before_screen_results") is not True
        or config.get("bindings") != expected_bindings
        or config.get("splits", {}).get("screen_items") != list(SCREEN_ITEMS)
        or config.get("splits", {}).get("reserved_evaluation_not_accessed")
        != ["rust-1.97.1-source", "llvm-22.1.8-source", "enwikiversity-20260701"]
        or [(row.get("id"), row.get("columnarize_values")) for row in config.get("variants", [])]
        != expected_variants
        or config.get("measurement")
        != {
            "jobs": 1,
            "measured_repetitions": 2,
            "order_seed": 20260718,
            "timeout_seconds_per_process": 43200,
            "warmups": 0,
        }
        or limits
        != {
            "maximum_field_bytes": 134217728,
            "maximum_fields_per_template": 1024,
            "maximum_input_bytes": 2147483648,
            "maximum_nesting_depth": 64,
            "maximum_parameter_key_bytes": 4096,
            "maximum_template_name_bytes": 4096,
            "maximum_templates": 1000000,
            "maximum_total_fields": 8000000,
        }
        or gate.get("kanzi_max_complete_bytes") != 24156788
        or gate.get("ts_h1_complete_bytes") != 24155142
        or gate.get("signal_maximum_complete_bytes") != 23915220
        or gate.get("strong_maximum_complete_bytes") != 23673652
        or gate.get("full_maximum_complete_bytes_to_beat_ts_h1_by_one_percent")
        != 23913590
        or gate.get("maximum_peak_rss_bytes") != 4 * 1024**3
        or gate.get("item_maximum_complete_bytes")
        != {"enwikibooks-20260701": 12685899, "enwikinews-20260701": 11591672}
        or attribution.get("full_must_be_smaller_than_structure_only_basis_points")
        != 50
        or config.get("ts_h1_controls")
        != {"enwikibooks-20260701": 12630261, "enwikinews-20260701": 11524881}
        or config.get("decision", {}).get("final_product_gate_reminder")
        != {
            "maximum_complete_bytes_vs_kanzi_max": 22948948,
            "minimum_gain_percent": 5.0,
            "requires_counted_decoder_code_and_state": True,
        }
        or "not Axiom wins" not in config.get("claim_ceiling", "")
    ):
        raise ValueError("WK-C1 config differs from the frozen contract")
    roster = {
        *config["splits"]["screen_items"],
        *config["splits"]["out_of_scope_training_not_accessed"],
        *config["splits"]["reserved_evaluation_not_accessed"],
    }
    if len(roster) != 7:
        raise ValueError("WK-C1 split roster overlaps")


def verify_screen_items(
    corpus: Path, config: dict[str, Any]
) -> tuple[bytes, list[dict[str, Any]]]:
    manifest_raw, manifest = read_canonical(corpus / "manifest.json")
    expected_ids = {
        *config["splits"]["screen_items"],
        *config["splits"]["out_of_scope_training_not_accessed"],
        *config["splits"]["reserved_evaluation_not_accessed"],
    }
    rows = {row.get("source_id"): row for row in manifest.get("items", [])}
    if set(rows) != expected_ids or manifest.get("public_validation_accessed") is not False:
        raise ValueError("WK-C1 development manifest roster or seal differs")
    items = []
    for item_id in SCREEN_ITEMS:
        row = rows[item_id]
        path = corpus / row["bundle_path"]
        if path.stat().st_size != row["bundle_size_bytes"]:
            raise ValueError(f"WK-C1 screen item size differs: {item_id}")
        if sha256_file(path) != row["bundle_sha256"]:
            raise ValueError(f"WK-C1 screen item digest differs: {item_id}")
        items.append(
            {
                "id": item_id,
                "track": "english_wikimedia_wikitext",
                "path": str(path.resolve()),
                "source_bytes": row["bundle_size_bytes"],
                "source_sha256": row["bundle_sha256"],
            }
        )
    return manifest_raw, items


def verify_dependencies(
    *,
    config: dict[str, Any],
    baseline: Path,
    kanzi: Path,
    structural_result: Path,
    structural_evidence: Path,
    successor_decision: Path,
    successor_routing: Path,
    bwt_result: Path,
    bwt_evidence: Path,
    bwt_receipt: Path,
) -> None:
    bindings = config["bindings"]
    paths = {
        "baseline_results_sha256": baseline,
        "kanzi_binary_sha256": kanzi,
        "structural_results_sha256": structural_result,
        "structural_public_evidence_sha256": structural_evidence,
        "successor_decision_sha256": successor_decision,
        "successor_routing_config_sha256": successor_routing,
        "bwt_result_sha256": bwt_result,
        "bwt_public_evidence_sha256": bwt_evidence,
        "bwt_publication_receipt_sha256": bwt_receipt,
    }
    if any(sha256_file(path) != bindings[key] for key, path in paths.items()):
        raise ValueError("WK-C1 dependency binding differs")
    _baseline_raw, baseline_result = read_canonical(baseline)
    _structural_raw, structural_public = read_canonical(structural_evidence)
    _bwt_raw, bwt_public = read_canonical(bwt_evidence)
    _decision_raw, decision = read_canonical(successor_decision)
    if (
        baseline_result.get("completed") is not True
        or baseline_result.get("all_required_completed") is not True
        or structural_public.get("structural_results_sha256")
        != bindings["structural_results_sha256"]
        or bwt_public.get("result_sha256") != bindings["bwt_result_sha256"]
        or bwt_public.get("results", {}).get("summary", {}).get("axiom_wins") != 0
        or any(
            row.get("decision") != "reject_raw_bwt_direction_for_track"
            for row in bwt_public.get("results", {}).get("summary", {}).get("tracks", [])
        )
        or decision.get("name") != "text-source-structural-successor-decision-v1"
        or any(row.get("axiom_win") is not False for row in decision.get("decisions", []))
    ):
        raise ValueError("WK-C1 dependency evidence differs")
    structural_rows = {
        row["item_id"]: row["candidate_bytes"]
        for row in structural_public["results"]["summary"]["item_rows"]
        if row.get("variant") == "ts-h1-demux" and row.get("item_id") in SCREEN_ITEMS
    }
    if structural_rows != config["ts_h1_controls"]:
        raise ValueError("WK-C1 two-item TS-H1 control differs")


def schedule(config: dict[str, Any]) -> list[tuple[str, str, int]]:
    rows = [
        (variant, item, repetition)
        for variant in VARIANTS
        for item in SCREEN_ITEMS
        for repetition in range(config["measurement"]["measured_repetitions"])
    ]
    if len(rows) != 8:
        raise ValueError("WK-C1 schedule must contain exactly eight trials")
    random.Random(config["measurement"]["order_seed"]).shuffle(rows)
    return rows


def commands(
    *,
    python: str,
    runner: Path,
    transform: Path,
    kanzi: Path,
    variant: str,
    source: Path,
    transformed: Path,
    payload: Path,
    artifact: Path,
    extracted: Path,
    decoded_transform: Path,
    restored: Path,
    source_bytes: int,
    source_sha256: str,
) -> tuple[list[list[str]], list[list[str]]]:
    encode_commands = [
        [python, str(transform), "encode", variant, str(source), str(transformed)],
        [
            str(kanzi),
            "--compress",
            "--level=9",
            "--block=1g",
            "--jobs=1",
            "--verbose=0",
            "--force",
            f"--input={transformed}",
            f"--output={payload}",
        ],
        [
            python,
            str(runner),
            "wrap",
            variant,
            str(source),
            str(payload),
            str(artifact),
        ],
    ]
    decode_commands = [
        [
            python,
            str(runner),
            "unwrap",
            variant,
            str(artifact),
            str(extracted),
            "--source-bytes",
            str(source_bytes),
            "--source-sha256",
            source_sha256,
        ],
        [
            str(kanzi),
            "--decompress",
            "--jobs=1",
            "--verbose=0",
            "--force",
            f"--input={extracted}",
            f"--output={decoded_transform}",
        ],
        [
            python,
            str(transform),
            "decode",
            str(decoded_transform),
            str(restored),
            "--maximum-size",
            str(source_bytes),
        ],
    ]
    return encode_commands, decode_commands


def wrap_payload(variant: str, source: Path, payload: Path, destination: Path) -> None:
    if variant not in VARIANT_KIND:
        raise ValueError("unknown AXWK2 variant")
    source_size = source.stat().st_size
    source_sha256 = bytes.fromhex(sha256_file(source))
    payload_size = payload.stat().st_size
    payload_sha256 = bytes.fromhex(sha256_file(payload))
    destination.write_bytes(
        FRAME_HEADER.pack(
            FRAME_MAGIC,
            FRAME_VERSION,
            VARIANT_KIND[variant],
            BACKEND_KIND,
            source_size,
            source_sha256,
            payload_size,
            payload_sha256,
        )
        + payload.read_bytes()
    )


def unwrap_payload(
    variant: str,
    artifact: Path,
    destination: Path,
    *,
    source_bytes: int,
    source_sha256: str,
) -> None:
    destination.unlink(missing_ok=True)
    raw = artifact.read_bytes()
    if len(raw) < FRAME_HEADER.size:
        raise ValueError("truncated AXWK2 header")
    (
        magic,
        version,
        variant_kind,
        backend_kind,
        declared_source_bytes,
        declared_source_sha256,
        payload_bytes,
        payload_sha256,
    ) = FRAME_HEADER.unpack(raw[: FRAME_HEADER.size])
    payload = raw[FRAME_HEADER.size :]
    if (
        magic != FRAME_MAGIC
        or version != FRAME_VERSION
        or variant_kind != VARIANT_KIND.get(variant)
        or backend_kind != BACKEND_KIND
        or declared_source_bytes != source_bytes
        or declared_source_sha256.hex() != source_sha256
        or payload_bytes != len(payload)
        or hashlib.sha256(payload).digest() != payload_sha256
    ):
        raise ValueError("AXWK2 identity, accounting, or payload digest differs")
    destination.write_bytes(payload)


def summarize(
    trials: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    repetitions = config["measurement"]["measured_repetitions"]
    gate = config["decision"]["track_gate"]
    item_rows = []
    for variant in VARIANTS:
        for item_id in SCREEN_ITEMS:
            group = [
                row
                for row in trials
                if row.get("variant") == variant and row.get("item_id") == item_id
            ]
            successful = [row for row in group if row.get("passed") is True]
            sizes = {row["artifact_bytes"] for row in successful}
            digests = {row["artifact_sha256"] for row in successful}
            exact = (
                len(group) == repetitions
                and len(successful) == repetitions
                and all(row.get("exact_roundtrip") is True for row in successful)
                and len(sizes) == 1
                and len(digests) == 1
            )
            artifact_bytes = next(iter(sizes)) if exact else None
            peak = max(
                (
                    max(row.get("encode_peak_rss_bytes", 0), row.get("decode_peak_rss_bytes", 0))
                    for row in group
                ),
                default=0,
            )
            item_rows.append(
                {
                    "variant": variant,
                    "item_id": item_id,
                    "artifact_bytes": artifact_bytes,
                    "artifact_sha256": next(iter(digests)) if exact else None,
                    "exact_roundtrip": exact,
                    "deterministic_artifact": exact,
                    "item_guard_passed": bool(
                        exact
                        and artifact_bytes
                        <= gate["item_maximum_complete_bytes"][item_id]
                    ),
                    "peak_rss_bytes": peak,
                    "resource_limit_passed": bool(
                        exact and peak <= gate["maximum_peak_rss_bytes"]
                    ),
                    "passed": exact,
                }
            )
    variants = []
    for variant in VARIANTS:
        selected = [row for row in item_rows if row["variant"] == variant]
        complete = len(selected) == 2 and all(row["passed"] for row in selected)
        artifact_bytes = sum(row["artifact_bytes"] for row in selected) if complete else None
        variants.append(
            {
                "variant": variant,
                "artifact_bytes": artifact_bytes,
                "complete": complete,
                "item_guard_passed": complete
                and all(row["item_guard_passed"] for row in selected),
                "resource_limit_passed": complete
                and all(row["resource_limit_passed"] for row in selected),
                "gain_vs_kanzi_percent": (
                    (gate["kanzi_max_complete_bytes"] - artifact_bytes)
                    / gate["kanzi_max_complete_bytes"]
                    * 100.0
                    if complete
                    else None
                ),
            }
        )
    by_variant = {row["variant"]: row for row in variants}
    full = by_variant[VARIANTS[0]]
    structure = by_variant[VARIANTS[1]]
    attribution = bool(
        full["complete"]
        and structure["complete"]
        and full["artifact_bytes"] * 10000 <= structure["artifact_bytes"] * 9950
    )
    shared = bool(
        full["complete"]
        and full["item_guard_passed"]
        and full["resource_limit_passed"]
        and full["artifact_bytes"] <= gate["signal_maximum_complete_bytes"]
        and full["artifact_bytes"]
        <= gate["full_maximum_complete_bytes_to_beat_ts_h1_by_one_percent"]
        and attribution
    )
    strong = bool(
        shared and full["artifact_bytes"] <= gate["strong_maximum_complete_bytes"]
    )
    if strong:
        decision = "admit_separately_frozen_wk_c1_codec_prototype"
    elif shared:
        decision = "retain_wk_c1_diagnostic_signal_only"
    else:
        decision = "reject_wk_c1_recursive_template_columnarization"
    return {
        "item_rows": item_rows,
        "variants": variants,
        "full_beats_structure_only_by_half_percent": attribution,
        "full_signal": shared,
        "full_strong_signal": strong,
        "decision": decision,
        "axiom_wins": 0,
    }


def preflight() -> list[dict[str, Any]]:
    fixture = (
        b"lead {{T|a=one|nested={{U|x=[[A|B]]}}}} middle "
        b"{{T|nested={{U|x=C}}|a=two}} <!-- {{raw}} -->"
    )
    rows = []
    for variant in VARIANTS:
        first = TRANSFORM.encode(fixture, variant)
        second = TRANSFORM.encode(fixture, variant)
        if first != second or TRANSFORM.decode(first, len(fixture)) != fixture:
            raise ValueError(f"WK-C1 synthetic preflight failed: {variant}")
        rows.append(
            {
                "variant": variant,
                "source_bytes": len(fixture),
                "transform_bytes": len(first),
                "transform_sha256": sha256_bytes(first),
                "exact_roundtrip": True,
                "deterministic_transform": True,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    wrap = subparsers.add_parser("wrap")
    wrap.add_argument("variant", choices=VARIANTS)
    wrap.add_argument("source", type=Path)
    wrap.add_argument("payload", type=Path)
    wrap.add_argument("destination", type=Path)
    unwrap = subparsers.add_parser("unwrap")
    unwrap.add_argument("variant", choices=VARIANTS)
    unwrap.add_argument("artifact", type=Path)
    unwrap.add_argument("destination", type=Path)
    unwrap.add_argument("--source-bytes", type=int, required=True)
    unwrap.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            print(json.dumps(preflight(), indent=2, sort_keys=True))
        elif args.command == "wrap":
            wrap_payload(args.variant, args.source, args.payload, args.destination)
        else:
            unwrap_payload(
                args.variant,
                args.artifact,
                args.destination,
                source_bytes=args.source_bytes,
                source_sha256=args.source_sha256,
            )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"WK-C1 runner failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
