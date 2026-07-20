#!/usr/bin/env python3
"""Verify the frozen E1 frontier-headroom plan without opening corpus bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-20-frontier-headroom-oracle-census-e1-protocol.md"
)
EXPECTED_MANIFESTS = {
    "runs/clue-json-log-development-acquisition-v1.json": "4ecfb62d40c3a72ef6a5946c014bf957666935d38fc3bf83912df9a40e1a66ff",
    "runs/text-source-development-acquisition-v1.json": "5c5c3b5ad9c83847801ca3d330c17350bbc34a17063368b8c5f42fe44f60ab98",
    "config/tabular-corpus-v1.json": "a72f6faee6b638bfe481d225766c77f3ef6bd54b419d7e676e66f15d8dc5741e",
    "config/tabular-successor-corpus-v1.json": "f2ede2a954f46413a4d6fd87692523e4d1e93d69ed4248af1da66dc2dd800e24",
}
EXPECTED_CODEC_IDS = (
    "kanzi-max",
    "zstd-19-long",
    "xz-lzma2-9e",
    "zpaq-5-m510",
)
PRACTICAL_CODEC_IDS = EXPECTED_CODEC_IDS[:3]
EXPECTED_ITEM_CATEGORIES = {
    "clue-early-development": "json_logs",
    "clue-middle-development": "json_logs",
    "clue-late-development": "json_logs",
    "cpython-3.14.6-source": "source_code_bundles",
    "typescript-6.0.3-source": "source_code_bundles",
    "enwikibooks-20260701": "english_wikimedia_wikitext",
    "enwikinews-20260701": "english_wikimedia_wikitext",
    "uci-autouniv-au2": "tabular_records",
    "uci-bike-sharing-hour": "tabular_records",
    "uci-appliances-energy": "tabular_records",
    "uci-seoul-bike": "tabular_records",
    "uci-covertype": "numeric_matrices_timeseries",
    "uci-facebook-comment-volume-v4": "numeric_matrices_timeseries",
    "uci-gas-sensor-raw": "numeric_matrices_timeseries",
    "uci-semeion": "numeric_matrices_timeseries",
    "uci-optdigits-train": "numeric_matrices_timeseries",
    "uci-multiple-features-pixels": "numeric_matrices_timeseries",
}
EXPECTED_BINARY_SHA256 = {
    "kanzi-max": "3c93e96fb108ebf8152e187ef0f830b03952200dc94b449fcec8d158e7474618",
    "zstd-19-long": "aff8169fb421bb925fb16c44a7e0143fa2c7a941dc45cce76b15062a2ce54917",
    "xz-lzma2-9e": "995c8e2f72446f0d0e3a29f6c3d52286cfecedfc4ffb2b42d25c3ce1ad77034c",
    "zpaq-5-m510": "c54e06fca84580951509656c8b938b594727014acd3fddabcff787d021d032e8",
}
EXPECTED_COMMANDS = {
    "kanzi-max": {
        "compress": [
            "$KANZI",
            "--compress",
            "--level=9",
            "--block=1g",
            "--jobs=1",
            "--verbose=0",
            "--force",
            "--input=$INPUT",
            "--output=$ARTIFACT",
        ],
        "decompress": [
            "$KANZI",
            "--decompress",
            "--jobs=1",
            "--verbose=0",
            "--force",
            "--input=$ARTIFACT",
            "--output=$RESTORED",
        ],
    },
    "zstd-19-long": {
        "compress": [
            "$ZSTD",
            "-19",
            "--long=31",
            "-T1",
            "--no-progress",
            "--force",
            "-o",
            "$ARTIFACT",
            "$INPUT",
        ],
        "decompress": [
            "$ZSTD",
            "--decompress",
            "--long=31",
            "-T1",
            "--no-progress",
            "--force",
            "-o",
            "$RESTORED",
            "$ARTIFACT",
        ],
    },
    "xz-lzma2-9e": {
        "compress": [
            "$XZ",
            "--compress",
            "--format=xz",
            "--check=crc64",
            "--lzma2=preset=9e",
            "--threads=1",
            "--keep",
            "--stdout",
            "$INPUT",
        ],
        "decompress": ["$XZ", "--decompress", "--threads=1", "--stdout", "$ARTIFACT"],
    },
    "zpaq-5-m510": {
        "compress": [
            "$ZPAQ",
            "add",
            "$ARTIFACT",
            "input.bin",
            "-method",
            "510",
            "-threads",
            "1",
            "-noattributes",
            "-until",
            "20000101000000",
        ],
        "decompress": [
            "$ZPAQ",
            "extract",
            "$ARTIFACT",
            "input.bin",
            "-to",
            "$RESTORED_DIRECTORY",
            "-force",
            "-threads",
            "1",
            "-noattributes",
        ],
    },
}
TOP_LEVEL_KEYS = {
    "schema_version",
    "name",
    "declared_at",
    "frozen_before_measurement",
    "objective",
    "claim_ceiling",
    "manifest_bindings",
    "information_boundary",
    "items",
    "excluded_categories",
    "codecs",
    "measurement",
    "sample_ceiling",
    "oracle_routing",
    "commercial_speed_tiers",
    "calculations",
    "decision_gates",
    "required_result_sections",
    "result_schema",
}
EXPECTED_DECISION_GATES = {
    "advance_item_selector": "Per-item oracle gain >=100 basis points in a category, with at least two winning codecs, all exact/deterministic, and no excluded bytes accessed.",
    "advance_segment_selector": "Net bounded-segment oracle gain >=200 basis points in a category after all AXE1G overhead, with positive net gain on at least two items and no item more than 50 basis points larger than its equally framed whole fallback.",
    "advance_representation_research": "Feasible sample ceiling is >=300 basis points smaller than best practical on at least two categories, or >=500 basis points on one category, with exact deterministic decodes and all side state counted.",
    "reject_routing_lane": "Reject selector-only work for a category when per-item gain <50 basis points and bounded-segment gain <100 basis points; an untriggered optional segment stage contributes exactly 0 basis points.",
    "declare_practical_frontier_saturated": "Diagnostic only when routing is rejected and feasible sample ceiling gap <100 basis points; this does not prove a global or theoretical frontier.",
    "product_gate_unchanged": "No E1 outcome is a product or Axiom win. Category candidates still require >=5% unseen complete-byte advantage plus frozen speed, memory, integrity, streaming, portability, holdout, and independent-reproduction gates.",
}
EXPECTED_RESULT_SCHEMA = {
    "top_level_keys": [
        "schema_version",
        "name",
        "completed",
        "config_sha256",
        "protocol_sha256",
        "runner_sha256",
        "verifier_sha256",
        "repository_commit",
        "tool_lock",
        "host",
        "item_verification",
        "whole_item_trials",
        "sample_manifest",
        "sample_trials",
        "optional_segment_trials",
        "category_summaries",
        "speed_tiers",
        "sealed_split_status",
        "decision",
        "claim_ceiling",
    ],
    "process_keys": [
        "codec_id",
        "phase",
        "item_id",
        "repetition",
        "source_bytes",
        "artifact_path",
        "artifact_bytes",
        "artifact_sha256",
        "command",
        "wall_ns",
        "cpu_user_ns",
        "cpu_system_ns",
        "peak_rss_bytes",
        "exit_status",
        "timed_out",
        "restored_bytes",
        "restored_sha256",
        "exact",
        "deterministic",
    ],
    "whole_item_trial_keys": [
        "item_id",
        "category",
        "codec_id",
        "source_bytes",
        "repetitions",
    ],
    "sample_manifest_item_keys": [
        "item_id",
        "category",
        "source_bytes",
        "source_sha256",
        "ranges",
        "sampled_payload_bytes",
        "sampled_payload_sha256",
        "axe1s_bytes",
        "axe1s_sha256",
    ],
    "segment_trial_keys": [
        "item_id",
        "category",
        "segment_index",
        "offset",
        "decoded_bytes",
        "decoded_sha256",
        "codec_id",
        "artifact_bytes",
        "artifact_sha256",
        "repetitions",
    ],
    "binding_rule": "Every result path must be relative, normalized, unique, non-symlink, inside the immutable result directory, and paired with exact byte length and SHA-256. The verifier rejects missing, extra, duplicate, absolute, parent-traversal, symlink, unbound manifest, receipt, artifact, log, or side-state files.",
    "summary_rule": "The verifier recomputes every item, category, sample, oracle, overhead, speed, RSS, tier, and decision value exclusively from schema-valid bound raw receipts and rejects any mismatch or unavailable value represented as zero.",
    "speed_summary_rule": "For each category, codec, and repetition, join exactly one successful compress and one successful decompress process receipt per declared category item by item_id and repetition; require source_bytes to match the frozen item, map compress.wall_ns to encode_wall_ns and decompress.wall_ns to decode_wall_ns, reject missing or extra items and phases, then apply speed_tier_attainment.",
}
EXPECTED_SPEED_TIER_ATTAINMENT = "For each category and codec, each measured repetition aggregate compression or decompression throughput is sum(decoded source bytes) / sum(primary process wall nanoseconds) * 1000. The reported category scalar is the minimum repetition aggregate, never a mean or best item; peak RSS is the maximum direct-process wait4 peak across every item and repetition. A tier requires exact deterministic output and all three frozen compression, decompression, and RSS thresholds."
EXPECTED_SPEED_TIER_HOST_LOCK = "AC versus battery, low-power mode, and thermal-pressure state are required telemetry. CPU governor, frequency, and turbo state are recorded when exposed and their platform-level absence alone does not refuse a tier. Refuse commercial speed-tier classification if required telemetry is unavailable, AC/battery or thermal state changes, or low-power mode is enabled; ratio evidence may remain admissible."


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary JSON file: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} has unexpected fields")
    return value


def require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return value


def manifest_items() -> dict[str, dict[str, Any]]:
    """Read tracked declarations only; never resolve or open a corpus path."""
    clue = read_json(ROOT / "runs" / "clue-json-log-development-acquisition-v1.json")
    text = read_json(ROOT / "runs" / "text-source-development-acquisition-v1.json")
    tabular = read_json(ROOT / "config" / "tabular-corpus-v1.json")
    successor = read_json(ROOT / "config" / "tabular-successor-corpus-v1.json")
    rows: dict[str, dict[str, Any]] = {}
    for row in clue["items"]:
        rows[row["id"]] = {"bytes": row["size_bytes"], "sha256": row["sha256"]}
    for row in text["items"]:
        rows[row["source_id"]] = {
            "bytes": row["bundle_size_bytes"],
            "sha256": row["bundle_sha256"],
        }
    for document in (tabular, successor):
        for row in document["development"]:
            rows[row["id"]] = {
                "bytes": row["selected_item_bytes"],
                "sha256": row["selected_item_sha256"],
            }
    return rows


def sample_ranges(
    size: int, basis_points: int = 500, strata: int = 5
) -> list[tuple[int, int]]:
    if type(size) is not int or size <= 0 or basis_points != 500 or strata != 5:
        raise ValueError("E1 sample inputs differ from the frozen policy")
    budget = size * basis_points // 10_000
    base, remainder = divmod(budget, strata)
    lengths = [base + (index < remainder) for index in range(strata)]
    ranges = [
        ((size - length) * index // (strata - 1), length)
        for index, length in enumerate(lengths)
    ]
    previous_end = 0
    for offset, length in ranges:
        if length <= 0 or offset < previous_end or offset + length > size:
            raise ValueError("E1 sample ranges overlap or exceed the item")
        previous_end = offset + length
    if sum(length for _offset, length in ranges) != budget:
        raise ValueError("E1 sample budget differs")
    return ranges


def string_bytes(value: str) -> int:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65_535:
        raise ValueError("E1 container string length differs")
    return 2 + len(encoded)


def axe1o_bytes(category: str, choices: list[dict[str, Any]]) -> int:
    if not choices:
        raise ValueError("AXE1O requires at least one item")
    total = 5 + 1 + string_bytes(category) + 32 + 4
    seen = set()
    for row in sorted(choices, key=lambda value: value["item_id"]):
        require_keys(
            row,
            {
                "item_id",
                "codec_id",
                "decoded_bytes",
                "decoded_sha256",
                "artifact_bytes",
                "artifact_sha256",
            },
            "AXE1O choice",
        )
        if row["item_id"] in seen:
            raise ValueError("AXE1O item is duplicated")
        seen.add(row["item_id"])
        require_sha256(row["decoded_sha256"], "AXE1O decoded digest")
        require_sha256(row["artifact_sha256"], "AXE1O artifact digest")
        if type(row["decoded_bytes"]) is not int or row["decoded_bytes"] <= 0:
            raise ValueError("AXE1O decoded size differs")
        if type(row["artifact_bytes"]) is not int or row["artifact_bytes"] <= 0:
            raise ValueError("AXE1O artifact size differs")
        total += (
            string_bytes(row["item_id"])
            + string_bytes(row["codec_id"])
            + 8
            + 32
            + 8
            + 32
            + row["artifact_bytes"]
        )
    return total


def axe1g_bytes(item_id: str, segments: list[dict[str, Any]]) -> int:
    if not segments:
        raise ValueError("AXE1G requires at least one segment")
    total = 5 + 1 + string_bytes(item_id) + 8 + 32 + 8 + 4
    for index, row in enumerate(segments):
        require_keys(
            row,
            {
                "segment_index",
                "codec_id",
                "decoded_bytes",
                "decoded_sha256",
                "artifact_bytes",
                "artifact_sha256",
            },
            "AXE1G segment",
        )
        if row["segment_index"] != index:
            raise ValueError("AXE1G segment order differs")
        require_sha256(row["decoded_sha256"], "AXE1G decoded digest")
        require_sha256(row["artifact_sha256"], "AXE1G artifact digest")
        if type(row["decoded_bytes"]) is not int or row["decoded_bytes"] <= 0:
            raise ValueError("AXE1G decoded size differs")
        if type(row["artifact_bytes"]) is not int or row["artifact_bytes"] <= 0:
            raise ValueError("AXE1G artifact size differs")
        total += string_bytes(row["codec_id"]) + 8 + 32 + 8 + 32 + row["artifact_bytes"]
    return total


def gain_basis_points(reference: int, candidate: int, *, clamp: bool = False) -> int:
    if (
        type(reference) is not int
        or type(candidate) is not int
        or reference <= 0
        or candidate <= 0
    ):
        raise ValueError("E1 gain bytes must be positive integers")
    gain = (reference - candidate) * 10_000 // reference
    return max(0, gain) if clamp else gain


def attained_speed_tiers(
    config: dict[str, Any],
    *,
    compression_mbps: float,
    decompression_mbps: float,
    peak_rss_bytes: int,
) -> list[str]:
    if compression_mbps <= 0 or decompression_mbps <= 0 or peak_rss_bytes < 0:
        raise ValueError("E1 commercial speed metric differs")
    return [
        tier["id"]
        for tier in config["commercial_speed_tiers"]
        if compression_mbps >= tier["minimum_compression_mbps"]
        and decompression_mbps >= tier["minimum_decompression_mbps"]
        and peak_rss_bytes <= tier["maximum_peak_rss_bytes"]
    ]


def aggregate_category_metrics(
    repetitions: list[dict[str, Any]], *, expected_item_ids: set[str]
) -> dict[str, float | int]:
    """Compute conservative category speed/RSS from complete repetition rows."""
    if not repetitions:
        raise ValueError("E1 category repetitions are absent")
    if not expected_item_ids:
        raise ValueError("E1 expected category item roster is absent")
    compression: list[float] = []
    decompression: list[float] = []
    peak_rss = 0
    for repetition in repetitions:
        require_keys(repetition, {"repetition", "items"}, "E1 category repetition")
        rows = repetition["items"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("E1 category repetition items are absent")
        item_ids: set[str] = set()
        source_bytes = encode_wall_ns = decode_wall_ns = 0
        for row in rows:
            require_keys(
                row,
                {
                    "item_id",
                    "source_bytes",
                    "encode_wall_ns",
                    "decode_wall_ns",
                    "peak_rss_bytes",
                },
                "E1 category metric row",
            )
            if row["item_id"] in item_ids:
                raise ValueError("E1 category metric item is duplicated")
            item_ids.add(row["item_id"])
            for field in ("source_bytes", "encode_wall_ns", "decode_wall_ns"):
                if type(row[field]) is not int or row[field] <= 0:
                    raise ValueError(f"E1 category metric {field} differs")
            if type(row["peak_rss_bytes"]) is not int or row["peak_rss_bytes"] <= 0:
                raise ValueError("E1 category metric RSS differs")
            source_bytes += row["source_bytes"]
            encode_wall_ns += row["encode_wall_ns"]
            decode_wall_ns += row["decode_wall_ns"]
            peak_rss = max(peak_rss, row["peak_rss_bytes"])
        if item_ids != expected_item_ids:
            raise ValueError("E1 category repetition item roster differs")
        compression.append(source_bytes / encode_wall_ns * 1000)
        decompression.append(source_bytes / decode_wall_ns * 1000)
    return {
        "compression_mbps": min(compression),
        "decompression_mbps": min(decompression),
        "peak_rss_bytes": peak_rss,
    }


def segment_gate_basis_points(
    *, triggered: bool, measured_basis_points: int | None
) -> int:
    """Make an untriggered optional segment screen decision-complete."""
    if triggered:
        if type(measured_basis_points) is not int:
            raise ValueError("E1 triggered segment gain is absent")
        return measured_basis_points
    if measured_basis_points is not None:
        raise ValueError("E1 untriggered segment gain must be absent")
    return 0


def validate(config: dict[str, Any]) -> dict[str, Any]:
    require_keys(config, TOP_LEVEL_KEYS, "E1 config")
    if (
        config["schema_version"] != 1
        or config["name"] != "frontier-headroom-oracle-routing-census-e1-v1"
        or config["declared_at"] != "2026-07-20"
        or config["frozen_before_measurement"] is not True
        or "training-only" not in config["claim_ceiling"].lower()
        or "not an Axiom candidate" not in config["claim_ceiling"]
    ):
        raise ValueError("E1 identity or claim ceiling differs")
    if config["manifest_bindings"] != EXPECTED_MANIFESTS:
        raise ValueError("E1 manifest bindings differ")
    for relative, expected in EXPECTED_MANIFESTS.items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"E1 tracked manifest drifted: {relative}")

    declared = config["items"]
    if not isinstance(declared, list) or len(declared) != 17:
        raise ValueError("E1 item roster must contain exactly 17 items")
    manifest = manifest_items()
    seen = set()
    categories: dict[str, int] = {}
    sample_bytes = 0
    for row in declared:
        require_keys(
            row, {"id", "category", "source", "license", "bytes", "sha256"}, "E1 item"
        )
        if row["id"] in seen or row["source"] not in EXPECTED_MANIFESTS:
            raise ValueError("E1 item identity or source differs")
        seen.add(row["id"])
        require_sha256(row["sha256"], f"E1 item {row['id']} digest")
        if manifest.get(row["id"]) != {"bytes": row["bytes"], "sha256": row["sha256"]}:
            raise ValueError(
                f"E1 item does not reconstruct from tracked declaration: {row['id']}"
            )
        if EXPECTED_ITEM_CATEGORIES.get(row["id"]) != row["category"]:
            raise ValueError(f"E1 item category differs: {row['id']}")
        if not isinstance(row["license"], str) or not row["license"]:
            raise ValueError("E1 item license is absent")
        categories[row["category"]] = categories.get(row["category"], 0) + 1
        ranges = sample_ranges(
            row["bytes"],
            config["sample_ceiling"]["maximum_sample_basis_points_per_item"],
            config["sample_ceiling"]["strata"],
        )
        sample_bytes += sum(length for _offset, length in ranges)
    expected_categories = {
        "json_logs": 3,
        "source_code_bundles": 2,
        "english_wikimedia_wikitext": 2,
        "tabular_records": 4,
        "numeric_matrices_timeseries": 6,
    }
    if categories != expected_categories:
        raise ValueError("E1 category roster differs")
    forbidden = {
        "clue-validation-a",
        "clue-validation-b",
        "rust-1.97.1-source",
        "llvm-22.1.8-source",
        "enwikiversity-20260701",
        "uci-metropt3",
        "uci-electricity-load",
        "uci-oulad-student-vle",
        "uci-character-font-ocrb",
        "uci-student-dropout",
        "uci-room-occupancy",
        "uci-gisette-train",
        "uci-madelon-train",
    }
    if seen & forbidden:
        raise ValueError("E1 roster includes reserved or validation data")

    codecs = config["codecs"]
    if (
        not isinstance(codecs, list)
        or tuple(row.get("id") for row in codecs) != EXPECTED_CODEC_IDS
    ):
        raise ValueError("E1 codec roster differs")
    for row in codecs:
        codec_id = row["id"]
        require_sha256(row.get("binary_sha256"), f"E1 {codec_id} binary")
        if row["binary_sha256"] != EXPECTED_BINARY_SHA256[codec_id]:
            raise ValueError(f"E1 {codec_id} binary identity differs")
        if {
            "compress": row.get("compress"),
            "decompress": row.get("decompress"),
        } != EXPECTED_COMMANDS[codec_id]:
            raise ValueError(f"E1 {codec_id} command differs")
    zpaq = codecs[-1]
    if (
        zpaq.get("binary_receipt_sha256")
        != "a6a80ee8acf3e2d5a645546da20335d45e4657e133451db9ee8dc2db46b210c6"
        or zpaq.get("source_archive_sha256")
        != "e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418"
        or zpaq.get("staged_input_name") != "input.bin"
        or zpaq.get("staged_input_mtime_utc") != "2000-01-01T00:00:00Z"
        or zpaq.get("artifact_path_policy")
        != "Each measured repetition uses a fresh nonexistent path ending exactly in .zpaq; retained or preexisting archives are forbidden because add appends."
    ):
        raise ValueError("E1 ZPAQ reproducibility policy differs")

    measurement = config["measurement"]
    if (
        measurement.get("jobs") != 1
        or measurement.get("warmups_practical") != 1
        or measurement.get("measured_repetitions_practical") != 3
        or measurement.get("warmups_zpaq") != 0
        or measurement.get("measured_repetitions_zpaq") != 2
        or measurement.get("require_posix_wait4_peak_rss") is not True
        or measurement.get("require_exact_roundtrip_every_decode") is not True
        or measurement.get("require_identical_complete_artifact_sha256_all_repetitions")
        is not True
        or measurement.get("speed_tier_attainment") != EXPECTED_SPEED_TIER_ATTAINMENT
        or measurement.get("speed_tier_host_lock") != EXPECTED_SPEED_TIER_HOST_LOCK
    ):
        raise ValueError("E1 measurement policy differs")
    sample = config["sample_ceiling"]
    if (
        sample.get("selected_profile") != "zpaq-5-m510"
        or sample.get("maximum_sample_basis_points_per_item") != 500
        or sample.get("strata") != 5
        or sample.get("advanced_profiles_not_admitted")
        != ["paq8px-v216-12L", "cmix-v21-strong-text"]
        or "not an absolute" not in sample.get("claim", "")
        or "magic[5]=AXE1S" not in sample.get("binary_layout", "")
        or "stratum-count u8=5" not in sample.get("binary_layout", "")
        or "offset u64 and length u64" not in sample.get("binary_layout", "")
    ):
        raise ValueError("E1 feasible ceiling policy differs")
    oracle = config["oracle_routing"]
    if (
        oracle.get("segment_trigger")
        != "Run the bounded-segment oracle only when per-item oracle gain is at least 0.50% or at least two items in the category have different winning codecs."
        or oracle.get("segment_bytes") != 16_777_216
        or oracle.get("segment_codecs") != list(EXPECTED_CODEC_IDS)
        or "AXE1O" not in oracle.get("binary_layout", "")
        or "AXE1G" not in oracle.get("binary_layout", "")
        or "upper bound" not in oracle.get("safe_upper_bound", "")
        or oracle.get("whole_fallback_framing")
        != "The equally framed whole fallback is AXE1G with segment-count u32=1, segment-size equal to the full item size, and one complete whole-item codec artifact, then the same outer AXE1O category framing used by the segmented route."
    ):
        raise ValueError("E1 oracle policy differs")
    expected_tiers = [
        ("interactive", 100.0, 500.0, 536_870_912),
        ("balanced", 25.0, 250.0, 1_073_741_824),
        ("archival", 2.0, 100.0, 4_294_967_296),
    ]
    if [
        (
            row.get("id"),
            row.get("minimum_compression_mbps"),
            row.get("minimum_decompression_mbps"),
            row.get("maximum_peak_rss_bytes"),
        )
        for row in config["commercial_speed_tiers"]
    ] != expected_tiers:
        raise ValueError("E1 commercial speed tiers differ")
    if config["decision_gates"] != EXPECTED_DECISION_GATES:
        raise ValueError("E1 decision gates differ")
    if config["required_result_sections"] != [
        "tool_lock",
        "host",
        "item_verification",
        "whole_item_trials",
        "sample_manifest",
        "sample_trials",
        "optional_segment_trials",
        "category_summaries",
        "speed_tiers",
        "sealed_split_status",
        "decision",
        "claim_ceiling",
    ]:
        raise ValueError("E1 result section roster differs")
    if config["result_schema"] != EXPECTED_RESULT_SCHEMA:
        raise ValueError("E1 result schema differs")
    protocol = PROTOCOL.read_text(encoding="utf-8")
    for phrase in (
        "No E1 codec invocation, sample, segment,",
        "Only the 17 exact licensed development items",
        "never more than 5%",
        "Hindsight oracles are upper bounds",
        "No E1 outcome is an Axiom win",
        "does not rerun codecs, rehash sealed corpus bytes, or remeasure RSS",
    ):
        if phrase not in protocol:
            raise ValueError(f"E1 protocol boundary is absent: {phrase}")
    return {
        "verified": True,
        "offline_plan_only": True,
        "item_count": len(declared),
        "category_item_counts": categories,
        "whole_item_codec_count": len(codecs),
        "stratified_sample_bytes": sample_bytes,
        "maximum_sample_basis_points": 500,
        "public_validation_accessed": False,
        "private_holdout_accessed": False,
        "measurements_exist": False,
        "axiom_wins": 0,
        "claim_ceiling": config["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        config = read_json(args.config)
        result = validate(config)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"E1 plan verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
