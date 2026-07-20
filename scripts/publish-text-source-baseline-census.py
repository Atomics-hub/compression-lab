#!/usr/bin/env python3
"""Publish the complete text/source practical baseline census transparently."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import tempfile
from typing import Any
from xml.sax.saxutils import escape


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
EXPECTED_CODECS = [
    "store",
    "lz4-1",
    "gzip-9",
    "bzip2-9",
    "bzip3-max",
    "zstd-3",
    "zstd-9",
    "zstd-19",
    "zstd-22-ultra",
    "brotli-11",
    "xz-lzma2-9e",
    "7zip-lzma2-9",
    "7zip-ppmd-9",
    "kanzi-max",
    "libbsc-max",
]
EXPECTED_ITEMS = [
    ("cpython-3.14.6-source", "source_code_bundles"),
    ("typescript-6.0.3-source", "source_code_bundles"),
    ("rust-1.97.1-source", "source_code_bundles"),
    ("llvm-22.1.8-source", "source_code_bundles"),
    ("enwikibooks-20260701", "english_wikimedia_wikitext"),
    ("enwikinews-20260701", "english_wikimedia_wikitext"),
    ("enwikiversity-20260701", "english_wikimedia_wikitext"),
]
EXPECTED_TOOLS = [
    "7zz",
    "brotli",
    "bzip2",
    "bzip3",
    "gzip",
    "kanzi",
    "libbsc",
    "lz4",
    "xz",
    "zstd",
]
EXPECTED_COMMANDS = {
    "store": {
        "compression": ["cp", "$SOURCE", "$WORK/artifact.bin"],
        "decompression": ["cp", "$WORK/artifact.bin", "$WORK/restored.bin"],
    },
    "lz4-1": {
        "compression": [
            "lz4",
            "-q",
            "-1",
            "-f",
            "$SOURCE",
            "$WORK/artifact.bin",
        ],
        "decompression": [
            "lz4",
            "-q",
            "-d",
            "-f",
            "$WORK/artifact.bin",
            "$WORK/restored.bin",
        ],
    },
    "gzip-9": {
        "compression": ["gzip", "-n", "-9", "-c", "$SOURCE"],
        "decompression": ["gzip", "-d", "-c", "$WORK/artifact.bin"],
    },
    "bzip2-9": {
        "compression": ["bzip2", "-9", "-c", "$SOURCE"],
        "decompression": ["bzip2", "-d", "-c", "$WORK/artifact.bin"],
    },
    "bzip3-max": {
        "compression": [
            "bzip3",
            "--encode",
            "--block=511",
            "--jobs=1",
            "--stdout",
            "$SOURCE",
        ],
        "decompression": [
            "bzip3",
            "--decode",
            "--stdout",
            "$WORK/artifact.bin",
        ],
    },
    **{
        codec_id: {
            "compression": [
                "zstd",
                "-q",
                "-T1",
                *level,
                "-f",
                "$SOURCE",
                "-o",
                "$WORK/artifact.bin",
            ],
            "decompression": [
                "zstd",
                "-q",
                "-T1",
                "-d",
                "-f",
                "$WORK/artifact.bin",
                "-o",
                "$WORK/restored.bin",
            ],
        }
        for codec_id, level in {
            "zstd-3": ["-3"],
            "zstd-9": ["-9"],
            "zstd-19": ["-19"],
            "zstd-22-ultra": ["--ultra", "-22"],
        }.items()
    },
    "brotli-11": {
        "compression": [
            "brotli",
            "-q",
            "11",
            "-f",
            "-o",
            "$WORK/artifact.bin",
            "$SOURCE",
        ],
        "decompression": [
            "brotli",
            "-d",
            "-f",
            "-o",
            "$WORK/restored.bin",
            "$WORK/artifact.bin",
        ],
    },
    "xz-lzma2-9e": {
        "compression": ["xz", "-T1", "-9e", "-c", "$SOURCE"],
        "decompression": ["xz", "-T1", "-d", "-c", "$WORK/artifact.bin"],
    },
    **{
        codec_id: {
            "compression": [
                "7zz",
                "a",
                "-bd",
                "-bso0",
                "-bsp0",
                "-t7z",
                f"-m0={method}",
                "-mx=9",
                "-mmt=1",
                "$WORK/artifact.bin",
                "$SOURCE",
            ],
            "decompression": [
                "7zz",
                "e",
                "-bd",
                "-bso0",
                "-bsp0",
                "-so",
                "$WORK/artifact.bin",
            ],
        }
        for codec_id, method in {
            "7zip-lzma2-9": "lzma2",
            "7zip-ppmd-9": "PPMd",
        }.items()
    },
    "kanzi-max": {
        "compression": [
            "$REPOSITORY/.baseline-tools/text-source-v1/bin/kanzi",
            "--compress",
            "--level=9",
            "--block=1g",
            "--jobs=1",
            "--verbose=0",
            "--force",
            "--input=$SOURCE",
            "--output=$WORK/artifact.bin",
        ],
        "decompression": [
            "$REPOSITORY/.baseline-tools/text-source-v1/bin/kanzi",
            "--decompress",
            "--jobs=1",
            "--verbose=0",
            "--force",
            "--input=$WORK/artifact.bin",
            "--output=$WORK/restored.bin",
        ],
    },
    "libbsc-max": {
        "compression": [
            "$REPOSITORY/.baseline-tools/text-source-v1/bin/bsc",
            "e",
            "$SOURCE",
            "$WORK/artifact.bin",
            "-b512",
            "-e2",
        ],
        "decompression": [
            "$REPOSITORY/.baseline-tools/text-source-v1/bin/bsc",
            "d",
            "$WORK/artifact.bin",
            "$WORK/restored.bin",
        ],
    },
}
MEASURED_REPETITIONS = 5
WARMUPS = 1
TRACK_LABELS = {
    "source_code_bundles": "Source-code bundles",
    "english_wikimedia_wikitext": "English Wikimedia wikitext",
}
CODEC_LABELS = {
    "store": "Store",
    "lz4-1": "LZ4-1",
    "gzip-9": "gzip-9",
    "bzip2-9": "bzip2-9",
    "bzip3-max": "bzip3-max",
    "zstd-3": "zstd-3",
    "zstd-9": "zstd-9",
    "zstd-19": "zstd-19",
    "zstd-22-ultra": "zstd-22 ultra",
    "brotli-11": "Brotli-11",
    "xz-lzma2-9e": "XZ LZMA2-9e",
    "7zip-lzma2-9": "7-Zip LZMA2-9",
    "7zip-ppmd-9": "7-Zip PPMd-9",
    "kanzi-max": "Kanzi-max",
    "libbsc-max": "libbsc-max",
}
CLAIM_BOUNDARY = (
    "Development practical-baseline evidence only. No Axiom text/source candidate "
    "was entered, research-ceiling codecs remain pending, validation and private "
    "holdout remain sealed, and this result cannot support a category-win, "
    "market-leading, world-best, or state-of-the-art claim."
)


def is_lower_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def expected_commands(codec_id: str, item: dict[str, Any]) -> dict[str, list[str]]:
    extension = {
        "source-bundle-v1": "axsrc",
        "wikimedia-revision-text-v1": "axwkt",
    }[item["format"]]
    source = (
        "$REPOSITORY/corpora/text-source-development-v1/"
        f"{item['id']}.{extension}"
    )
    return {
        phase: [argument.replace("$SOURCE", source) for argument in command]
        for phase, command in EXPECTED_COMMANDS[codec_id].items()
    }


def validate(results: dict[str, Any]) -> None:
    if not isinstance(results, dict):
        raise ValueError("census result must be a JSON object")
    if type(results.get("schema_version")) is not int or results["schema_version"] != 1:
        raise ValueError("unexpected census schema version")
    if results.get("name") != "text-source-development-baseline-census-v1":
        raise ValueError("unexpected census identity")
    if (
        results.get("completed") is not True
        or results.get("all_required_completed") is not True
    ):
        raise ValueError("refusing to publish an incomplete baseline census")
    if results.get("trial_count") != 630:
        raise ValueError("complete census must contain exactly 630 trials")
    bindings = results.get("bindings")
    if not isinstance(bindings, dict) or set(bindings) != {
        "repository_commit",
        "config_sha256",
        "manifest_sha256",
    }:
        raise ValueError("evidence bindings are incomplete")
    if not is_lower_hex(bindings["repository_commit"], 40) or not all(
        is_lower_hex(bindings[key], 64)
        for key in ("config_sha256", "manifest_sha256")
    ):
        raise ValueError("evidence bindings contain an invalid digest")
    repository = results.get("repository")
    if repository != {
        "commit": bindings["repository_commit"],
        "tracked_status": "",
    }:
        raise ValueError("benchmark repository state is inconsistent")
    if results.get("config_path") != "config/text-source-baseline-toolchain-v1.json":
        raise ValueError("benchmark config path differs from frozen protocol")
    if (
        results.get("manifest_path")
        != "corpora/text-source-development-v1/manifest.json"
    ):
        raise ValueError("benchmark manifest path differs from frozen protocol")
    host = results.get("host")
    if (
        not isinstance(host, dict)
        or set(host) != {"platform", "machine", "python", "logical_cpus"}
        or not all(
            isinstance(host[key], str) and host[key]
            for key in ("platform", "machine", "python")
        )
        or type(host["logical_cpus"]) is not int
        or host["logical_cpus"] <= 0
    ):
        raise ValueError("benchmark host identity is incomplete")
    tools = results.get("tools")
    if not isinstance(tools, dict) or list(tools) != EXPECTED_TOOLS:
        raise ValueError("benchmark tool roster differs from frozen protocol")
    for tool_id, tool in tools.items():
        expected_keys = {"binary_sha256", "binary_size_bytes", "version"}
        if tool_id in {"kanzi", "libbsc"}:
            expected_keys.add("commit")
        if (
            not isinstance(tool, dict)
            or set(tool) != expected_keys
            or not is_lower_hex(tool.get("binary_sha256"), 64)
            or type(tool.get("binary_size_bytes")) is not int
            or tool["binary_size_bytes"] <= 0
            or not isinstance(tool.get("version"), str)
            or not tool["version"]
            or (
                "commit" in expected_keys
                and not is_lower_hex(tool.get("commit"), 40)
            )
        ):
            raise ValueError(f"benchmark tool identity is invalid: {tool_id}")
    if results.get("codec_ids") != EXPECTED_CODECS:
        raise ValueError(
            "practical codec roster or order differs from the frozen protocol"
        )
    preflight = results.get("preflight")
    if (
        not isinstance(preflight, list)
        or [row.get("codec_id") for row in preflight] != EXPECTED_CODECS
        or not all(
            type(row.get("source_bytes")) is int
            and row["source_bytes"] > 0
            and type(row.get("artifact_bytes")) is int
            and row["artifact_bytes"] > 0
            and is_lower_hex(row.get("artifact_sha256"), 64)
            and row.get("exact_roundtrip") is True
            for row in preflight
        )
        or len({row["source_bytes"] for row in preflight}) != 1
    ):
        raise ValueError("codec preflight evidence is incomplete")
    items = results.get("items", [])
    if [(item.get("id"), item.get("track")) for item in items] != EXPECTED_ITEMS:
        raise ValueError(
            "development item roster or order differs from the frozen protocol"
        )
    expected_formats = {
        item_id: (
            "source-bundle-v1"
            if track == "source_code_bundles"
            else "wikimedia-revision-text-v1"
        )
        for item_id, track in EXPECTED_ITEMS
    }
    if any(item.get("format") != expected_formats[item["id"]] for item in items):
        raise ValueError("development item format differs from frozen protocol")
    if not all(
        isinstance(item.get("source_bytes"), int)
        and not isinstance(item["source_bytes"], bool)
        and item["source_bytes"] > 0
        and is_lower_hex(item.get("source_sha256"), 64)
        for item in items
    ):
        raise ValueError("development item identity is incomplete")
    tracks = results.get("summary", {}).get("tracks", {})
    if set(tracks) != set(TRACK_LABELS):
        raise ValueError("text/source track roster differs from the frozen protocol")
    rows = results["summary"].get("item_codec_rows", [])
    expected_rows = len(EXPECTED_ITEMS) * len(EXPECTED_CODECS)
    expected_pairs = {
        (codec_id, item_id)
        for codec_id in EXPECTED_CODECS
        for item_id, _track in EXPECTED_ITEMS
    }
    observed_pairs = {(row.get("codec_id"), row.get("item_id")) for row in rows}
    item_map = {item["id"]: item for item in items}
    if (
        len(rows) != expected_rows
        or observed_pairs != expected_pairs
        or not all(
            row.get("passed") is True
            and row.get("exact_roundtrip") is True
            and row.get("deterministic_artifact") is True
            and isinstance(row.get("artifact_bytes"), int)
            and not isinstance(row["artifact_bytes"], bool)
            and row["artifact_bytes"] > 0
            and is_lower_hex(row.get("artifact_sha256"), 64)
            and isinstance(row.get("median_compression_ns"), int)
            and not isinstance(row["median_compression_ns"], bool)
            and row["median_compression_ns"] > 0
            and isinstance(row.get("median_decompression_ns"), int)
            and not isinstance(row["median_decompression_ns"], bool)
            and row["median_decompression_ns"] > 0
            and isinstance(row.get("compression_peak_rss_bytes"), int)
            and not isinstance(row["compression_peak_rss_bytes"], bool)
            and row["compression_peak_rss_bytes"] >= 0
            and isinstance(row.get("decompression_peak_rss_bytes"), int)
            and not isinstance(row["decompression_peak_rss_bytes"], bool)
            and row["decompression_peak_rss_bytes"] >= 0
            and row.get("errors") == []
            for row in rows
        )
    ):
        raise ValueError("item/codec summary is incomplete or contains a failed result")
    if any(
        row.get("track") != item_map[row["item_id"]]["track"]
        or row.get("source_bytes") != item_map[row["item_id"]]["source_bytes"]
        for row in rows
    ):
        raise ValueError("item/codec summary source identity is inconsistent")
    for track_id, track in tracks.items():
        codecs = track.get("codecs", [])
        if [row.get("codec_id") for row in codecs] != EXPECTED_CODECS:
            raise ValueError(
                f"{track_id} codec roster differs from the frozen protocol"
            )
        if not all(row.get("complete") is True for row in codecs):
            raise ValueError(f"{track_id} has an incomplete codec result")
        track_items = [item for item in items if item["track"] == track_id]
        expected_source_bytes = sum(item["source_bytes"] for item in track_items)
        if track.get("source_bytes") != expected_source_bytes:
            raise ValueError(f"{track_id} source-byte aggregate is inconsistent")
        for aggregate in codecs:
            selected = [
                row
                for row in rows
                if row["track"] == track_id and row["codec_id"] == aggregate["codec_id"]
            ]
            expected_artifact_bytes = sum(row["artifact_bytes"] for row in selected)
            expected_compression_ns = sum(
                row["median_compression_ns"] for row in selected
            )
            expected_decompression_ns = sum(
                row["median_decompression_ns"] for row in selected
            )
            expected_values = {
                "source_bytes": expected_source_bytes,
                "artifact_bytes": expected_artifact_bytes,
                "compression_peak_rss_bytes": max(
                    row["compression_peak_rss_bytes"] for row in selected
                ),
                "decompression_peak_rss_bytes": max(
                    row["decompression_peak_rss_bytes"] for row in selected
                ),
            }
            if any(
                aggregate.get(key) != value for key, value in expected_values.items()
            ):
                raise ValueError(
                    f"{track_id}/{aggregate['codec_id']} aggregate is inconsistent"
                )
            expected_floats = {
                "ratio_percent": expected_artifact_bytes
                / expected_source_bytes
                * 100.0,
                "compression_mbps": expected_source_bytes
                / expected_compression_ns
                * 1000.0,
                "decompression_mbps": expected_source_bytes
                / expected_decompression_ns
                * 1000.0,
            }
            observed_floats = {
                key: aggregate.get(key) for key in expected_floats
            }
            if any(
                isinstance(observed_floats[key], bool)
                or not isinstance(observed_floats[key], (int, float))
                or not math.isfinite(float(observed_floats[key]))
                or abs(float(observed_floats[key]) - value) > 1e-9
                for key, value in expected_floats.items()
            ):
                raise ValueError(
                    f"{track_id}/{aggregate['codec_id']} rate is inconsistent"
                )
        expected_leader = min(codecs, key=lambda row: row["artifact_bytes"])
        if track.get("leader") != expected_leader:
            raise ValueError(f"{track_id} ratio leader is inconsistent")


def validate_trial_receipts(results_path: Path, results: dict[str, Any]) -> str:
    validate(results)
    trial_root = results_path.parent / "trials"
    expected_paths = expected_trial_paths()
    observed_paths = (
        {path.relative_to(trial_root) for path in trial_root.glob("*/*.json")}
        if trial_root.is_dir()
        else set()
    )
    if observed_paths != expected_paths:
        missing = len(expected_paths - observed_paths)
        extra = len(observed_paths - expected_paths)
        raise ValueError(
            f"trial receipt roster differs from frozen matrix: {missing} missing, {extra} extra"
        )

    item_map = {item["id"]: item for item in results["items"]}
    summary_map = {
        (row["codec_id"], row["item_id"]): row
        for row in results["summary"]["item_codec_rows"]
    }
    measured_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    receipt_hashes = []
    for relative in sorted(expected_paths, key=str):
        path = trial_root / relative
        raw = path.read_bytes()
        receipt_hashes.append(f"{sha256_bytes(raw)}  {relative.as_posix()}\n")
        row = json.loads(raw)
        if not isinstance(row, dict) or raw != json_bytes(row):
            raise ValueError(f"trial receipt is not canonical JSON: {relative}")
        codec_id = relative.parent.name
        item_id, repetition_text = relative.stem.rsplit(".r", 1)
        repetition = int(repetition_text)
        item = item_map[item_id]
        expected_identity = {
            "schema_version": 1,
            "bindings": results["bindings"],
            "codec_id": codec_id,
            "item_id": item_id,
            "track": item["track"],
            "repetition": repetition,
            "warmup": repetition == 0,
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
            "exact_roundtrip": True,
            "passed": True,
            "error": None,
        }
        if (
            type(row.get("schema_version")) is not int
            or type(row.get("repetition")) is not int
            or not isinstance(row.get("warmup"), bool)
            or row.get("exact_roundtrip") is not True
            or row.get("passed") is not True
            or any(row.get(key) != value for key, value in expected_identity.items())
        ):
            raise ValueError(f"trial receipt identity or integrity failed: {relative}")
        if (
            not isinstance(row.get("artifact_bytes"), int)
            or isinstance(row["artifact_bytes"], bool)
            or row["artifact_bytes"] <= 0
            or not is_lower_hex(row.get("artifact_sha256"), 64)
        ):
            raise ValueError(f"trial receipt artifact record is invalid: {relative}")
        for phase in ("compression", "decompression"):
            process = row.get(phase)
            if (
                not isinstance(process, dict)
                or not isinstance(process.get("command"), list)
                or not process["command"]
                or not all(
                    isinstance(argument, str) and argument
                    for argument in process["command"]
                )
                or type(process.get("returncode")) is not int
                or process["returncode"] != 0
                or process.get("timed_out") is not False
                or not isinstance(process.get("wall_ns"), int)
                or isinstance(process["wall_ns"], bool)
                or process["wall_ns"] <= 0
                or not isinstance(process.get("cpu_ns"), int)
                or isinstance(process["cpu_ns"], bool)
                or process["cpu_ns"] < 0
                or not isinstance(process.get("peak_rss_bytes"), int)
                or isinstance(process["peak_rss_bytes"], bool)
                or process["peak_rss_bytes"] < 0
                or not isinstance(process.get("stdout"), str)
                or not isinstance(process.get("stderr"), str)
            ):
                raise ValueError(f"trial receipt {phase} record is invalid: {relative}")
            if process["command"] != expected_commands(codec_id, item)[phase]:
                raise ValueError(f"trial receipt {phase} command differs: {relative}")
        if repetition > 0:
            measured_groups.setdefault((codec_id, item_id), []).append(row)

    for pair, group in measured_groups.items():
        summary = summary_map[pair]
        sizes = {row["artifact_bytes"] for row in group}
        hashes = {row["artifact_sha256"] for row in group}
        expected_summary = {
            "artifact_bytes": next(iter(sizes)) if len(sizes) == 1 else None,
            "artifact_sha256": next(iter(hashes)) if len(hashes) == 1 else None,
            "median_compression_ns": int(
                statistics.median(row["compression"]["wall_ns"] for row in group)
            ),
            "median_decompression_ns": int(
                statistics.median(row["decompression"]["wall_ns"] for row in group)
            ),
            "compression_peak_rss_bytes": max(
                row["compression"]["peak_rss_bytes"] for row in group
            ),
            "decompression_peak_rss_bytes": max(
                row["decompression"]["peak_rss_bytes"] for row in group
            ),
        }
        if len(group) != MEASURED_REPETITIONS or any(
            summary.get(key) != value for key, value in expected_summary.items()
        ):
            raise ValueError(f"trial receipts do not reproduce summary row: {pair}")
    if set(measured_groups) != set(summary_map):
        raise ValueError("measured trial receipt groups differ from summary matrix")
    return sha256_bytes("".join(receipt_hashes).encode("utf-8"))


def expected_trial_paths() -> set[Path]:
    return {
        Path(codec_id) / f"{item_id}.r{repetition}.json"
        for codec_id in EXPECTED_CODECS
        for item_id, _track in EXPECTED_ITEMS
        for repetition in range(WARMUPS + MEASURED_REPETITIONS)
    }


def stream_commitment(value: str) -> dict[str, Any]:
    raw = value.encode("utf-8")
    if value == "":
        classification = "empty"
    elif value == "<artifact>":
        classification = "artifact-redirection-sentinel"
    else:
        classification = "redacted"
    return {
        "classification": classification,
        "utf8_bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


def public_receipts_manifest_sha256(trials: list[dict[str, Any]]) -> str:
    lines = [
        f"{sha256_bytes(json_bytes(row['receipt']))}  {row['path']}\n"
        for row in trials
    ]
    return sha256_bytes("".join(lines).encode("utf-8"))


def validate_stream_commitment(commitment: object) -> str:
    if (
        not isinstance(commitment, dict)
        or set(commitment) != {"classification", "utf8_bytes", "sha256"}
        or type(commitment.get("utf8_bytes")) is not int
        or commitment["utf8_bytes"] < 0
        or not is_lower_hex(commitment.get("sha256"), 64)
    ):
        raise ValueError("public process-stream commitment is invalid")
    classification = commitment.get("classification")
    known = {
        "empty": "",
        "artifact-redirection-sentinel": "<artifact>",
    }
    if classification in known:
        value = known[classification]
        raw = value.encode("utf-8")
        if (
            commitment["utf8_bytes"] != len(raw)
            or commitment["sha256"] != sha256_bytes(raw)
        ):
            raise ValueError("public process-stream commitment is inconsistent")
        return value
    if classification != "redacted" or commitment["utf8_bytes"] <= 0:
        raise ValueError("public process-stream classification is invalid")
    return "<redacted>"


def validate_public_evidence(evidence: dict[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "name",
        "redaction_policy",
        "raw_results_sha256",
        "raw_trial_receipts_manifest_sha256",
        "public_trial_receipts_manifest_sha256",
        "results",
        "trials",
    }
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_keys
        or type(evidence.get("schema_version")) is not int
        or evidence["schema_version"] != 1
        or evidence.get("name")
        != "text-source-development-practical-baseline-public-evidence-v1"
        or not isinstance(evidence.get("redaction_policy"), str)
        or not evidence["redaction_policy"]
        or not is_lower_hex(evidence.get("raw_results_sha256"), 64)
        or not is_lower_hex(
            evidence.get("raw_trial_receipts_manifest_sha256"), 64
        )
        or not is_lower_hex(
            evidence.get("public_trial_receipts_manifest_sha256"), 64
        )
    ):
        raise ValueError("public evidence identity is invalid")
    results = evidence.get("results")
    validate(results)
    if sha256_bytes(json_bytes(results)) != evidence["raw_results_sha256"]:
        raise ValueError("public evidence results digest is inconsistent")
    trials = evidence.get("trials")
    if (
        not isinstance(trials, list)
        or len(trials) != 630
        or [row.get("path") for row in trials]
        != [path.as_posix() for path in sorted(expected_trial_paths(), key=str)]
        or public_receipts_manifest_sha256(trials)
        != evidence["public_trial_receipts_manifest_sha256"]
    ):
        raise ValueError("public trial-receipt manifest is inconsistent")
    receipt_keys = {
        "schema_version",
        "bindings",
        "codec_id",
        "item_id",
        "track",
        "repetition",
        "warmup",
        "source_bytes",
        "source_sha256",
        "artifact_bytes",
        "artifact_sha256",
        "compression",
        "decompression",
        "exact_roundtrip",
        "passed",
        "error",
    }
    public_process_keys = {
        "command",
        "returncode",
        "timed_out",
        "wall_ns",
        "cpu_ns",
        "peak_rss_bytes",
        "stdout_commitment",
        "stderr_commitment",
    }
    with tempfile.TemporaryDirectory(prefix="text-source-public-evidence-") as raw:
        root = Path(raw)
        results_path = root / "results.json"
        results_path.write_bytes(json_bytes(results))
        for row in trials:
            public = row.get("receipt")
            if not isinstance(public, dict) or set(public) != receipt_keys:
                raise ValueError("public trial receipt field roster is invalid")
            receipt = dict(public)
            for phase in ("compression", "decompression"):
                public_process = public.get(phase)
                if (
                    not isinstance(public_process, dict)
                    or set(public_process) != public_process_keys
                ):
                    raise ValueError("public process field roster is invalid")
                process = dict(public_process)
                process["stdout"] = validate_stream_commitment(
                    process.pop("stdout_commitment")
                )
                process["stderr"] = validate_stream_commitment(
                    process.pop("stderr_commitment")
                )
                receipt[phase] = process
            destination = root / "trials" / row["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(json_bytes(receipt))
        validate_trial_receipts(results_path, results)


def build_public_evidence(
    results_path: Path,
    results: dict[str, Any],
    *,
    raw_results_sha256: str,
    raw_receipts_manifest_sha256: str,
) -> bytes:
    trials = []
    trial_root = results_path.parent / "trials"
    for relative in sorted(expected_trial_paths(), key=str):
        receipt = json.loads((trial_root / relative).read_bytes())
        public = dict(receipt)
        for phase in ("compression", "decompression"):
            process = dict(receipt[phase])
            for stream in ("stdout", "stderr"):
                process[f"{stream}_commitment"] = stream_commitment(
                    process.pop(stream)
                )
            public[phase] = process
        trials.append({"path": relative.as_posix(), "receipt": public})
    evidence = {
        "schema_version": 1,
        "name": "text-source-development-practical-baseline-public-evidence-v1",
        "redaction_policy": (
            "Only process stdout/stderr content is removed. Each stream retains its "
            "UTF-8 byte count, SHA-256 commitment, and empty/artifact/redacted "
            "classification; every decision-bearing identity, command, timing, RSS, "
            "artifact, exactness, and determinism field remains present."
        ),
        "raw_results_sha256": raw_results_sha256,
        "raw_trial_receipts_manifest_sha256": raw_receipts_manifest_sha256,
        "public_trial_receipts_manifest_sha256": public_receipts_manifest_sha256(
            trials
        ),
        "results": results,
        "trials": trials,
    }
    encoded = json_bytes(evidence)
    forbidden_path_markers = (
        b"/Users/",
        b"/private/var/",
        b"/var/folders/",
        b"/tmp/",
    )
    if any(marker in encoded for marker in forbidden_path_markers):
        raise ValueError("public evidence still contains a local absolute path")
    validate_public_evidence(evidence)
    return encoded


def mib(value: int) -> float:
    return value / (1024.0 * 1024.0)


def derive(
    results: dict[str, Any],
    *,
    source_sha256: str,
    trial_receipts_sha256: str = "not-audited-in-memory",
    public_evidence_sha256: str = "not-built-in-memory",
    public_receipts_sha256: str = "not-built-in-memory",
) -> dict[str, Any]:
    validate(results)
    tracks: list[dict[str, Any]] = []
    for track_id in TRACK_LABELS:
        source = results["summary"]["tracks"][track_id]
        source_bytes = int(source["source_bytes"])
        rows = []
        for raw in source["codecs"]:
            artifact_bytes = int(raw["artifact_bytes"])
            rows.append(
                {
                    "codec_id": raw["codec_id"],
                    "codec": CODEC_LABELS[raw["codec_id"]],
                    "source_bytes": source_bytes,
                    "complete_bytes": artifact_bytes,
                    "size_percent": artifact_bytes / source_bytes * 100.0,
                    "compression_ratio": source_bytes / artifact_bytes,
                    "compression_mbps": float(raw["compression_mbps"]),
                    "decompression_mbps": float(raw["decompression_mbps"]),
                    "compression_peak_rss_mib": mib(raw["compression_peak_rss_bytes"]),
                    "decompression_peak_rss_mib": mib(
                        raw["decompression_peak_rss_bytes"]
                    ),
                    "exact_roundtrip": True,
                    "deterministic_artifact": True,
                    "axiom_outcome": "untested",
                }
            )
        leader = min(rows, key=lambda row: row["complete_bytes"])
        for row in rows:
            row["larger_than_leader_percent"] = (
                row["complete_bytes"] / leader["complete_bytes"] - 1.0
            ) * 100.0
            row["ratio_leader"] = row["codec_id"] == leader["codec_id"]
        tracks.append(
            {
                "track_id": track_id,
                "track": TRACK_LABELS[track_id],
                "source_bytes": source_bytes,
                "ratio_leader": leader["codec"],
                "ratio_leader_bytes": leader["complete_bytes"],
                "codecs": rows,
            }
        )

    item_rows = results["summary"]["item_codec_rows"]
    item_leaders = []
    for item in results["items"]:
        eligible = [
            row for row in item_rows if row["item_id"] == item["id"] and row["passed"]
        ]
        leader = min(eligible, key=lambda row: row["artifact_bytes"])
        item_leaders.append(
            {
                "item_id": item["id"],
                "track": TRACK_LABELS[item["track"]],
                "source_bytes": item["source_bytes"],
                "leader": CODEC_LABELS[leader["codec_id"]],
                "leader_bytes": leader["artifact_bytes"],
                "compression_ratio": item["source_bytes"] / leader["artifact_bytes"],
            }
        )

    return {
        "schema_version": 1,
        "name": "text-source-development-practical-baseline-publication-v1",
        "stage": "development practical baseline census",
        "candidate_status": "Axiom text/source specialist untested",
        "results_sha256": source_sha256,
        "trial_receipts_manifest_sha256": trial_receipts_sha256,
        "public_evidence_sha256": public_evidence_sha256,
        "public_trial_receipts_manifest_sha256": public_receipts_sha256,
        "bindings": results["bindings"],
        "host": results["host"],
        "tools": results["tools"],
        "trial_count": results["trial_count"],
        "tracks": tracks,
        "item_leaders": item_leaders,
        "integrity": {
            "all_630_trials_present": True,
            "all_525_measured_roundtrips_exact": True,
            "all_105_item_codec_artifacts_deterministic_across_five_repetitions": True,
            "complete_self_contained_artifact_bytes_counted": True,
            "one_codec_thread": True,
            "same_host_and_runner": True,
            "all_630_public_receipts_decision_complete_and_stream_redacted": True,
        },
        "research_ceiling_pending": ["ZPAQ", "paq8px", "cmix", "NNCP"],
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "claim_ceiling": CLAIM_BOUNDARY,
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Text/source practical baseline census",
        "",
        "![All practical text/source baselines with size, speed, memory, and integrity](comparison.svg)",
        "",
        "**Axiom status: untested in this baseline-only gate.** This census measures the",
        "practical frontier before an Axiom representation is selected; no baseline row",
        "is presented as an Axiom result.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                f"Source bytes: **{track['source_bytes']:,}**. Ratio leader: "
                f"**{track['ratio_leader']}** at **{track['ratio_leader_bytes']:,} bytes**.",
                "",
                "| Codec | Complete bytes | Ratio | Size % | vs leader | Compress MB/s | "
                "Decompress MB/s | Peak RSS C / D MiB | Exact | Deterministic | Axiom result |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | --- |",
            ]
        )
        for row in track["codecs"]:
            delta = (
                "leader"
                if row["ratio_leader"]
                else f"+{row['larger_than_leader_percent']:.2f}%"
            )
            lines.append(
                f"| {'**' if row['ratio_leader'] else ''}{row['codec']}"
                f"{'**' if row['ratio_leader'] else ''} | {row['complete_bytes']:,} | "
                f"{row['compression_ratio']:.2f}x | {row['size_percent']:.2f}% | {delta} | "
                f"{row['compression_mbps']:.2f} | {row['decompression_mbps']:.2f} | "
                f"{row['compression_peak_rss_mib']:.1f} / "
                f"{row['decompression_peak_rss_mib']:.1f} | ✅ | ✅ | untested |"
            )
        lines.append("")

    lines.extend(
        [
            "## Per-item ratio leaders",
            "",
            "| Item | Track | Source bytes | Smallest practical codec | Complete bytes | Ratio |",
            "| --- | --- | ---: | --- | ---: | ---: |",
        ]
    )
    for row in comparison["item_leaders"]:
        lines.append(
            f"| {row['item_id']} | {row['track']} | {row['source_bytes']:,} | "
            f"{row['leader']} | {row['leader_bytes']:,} | {row['compression_ratio']:.2f}x |"
        )
    lines.extend(
        [
            "",
            "## Integrity and comparability",
            "",
            "- 630/630 trials are present: 105 warmups and 525 measured trials.",
            "- Every measured round trip restored the exact source bytes.",
            "- Every item/codec artifact was byte-identical across five measured repetitions.",
            "- Every byte of each complete self-contained artifact is counted.",
            "- All codecs used one thread on the same host with the same cold-process runner.",
            "- Compression and decompression values are medians; RSS is the worst measured child peak.",
            "",
            "## Evidence boundary",
            "",
            f"- Results SHA-256: `{comparison['results_sha256']}`",
            "- Trial-receipt manifest SHA-256: "
            f"`{comparison['trial_receipts_manifest_sha256']}`",
            f"- Public recalculation evidence: [`evidence.json`](evidence.json), SHA-256 "
            f"`{comparison['public_evidence_sha256']}`.",
            "- Public trial-receipt manifest SHA-256: "
            f"`{comparison['public_trial_receipts_manifest_sha256']}`.",
            "- Public evidence retains every decision-bearing field from all 630 trials; "
            "process streams are replaced by byte counts and SHA-256 commitments to avoid "
            "publishing machine-local paths.",
            f"- Benchmark commit: `{comparison['bindings']['repository_commit']}`",
            f"- Config SHA-256: `{comparison['bindings']['config_sha256']}`",
            f"- Manifest SHA-256: `{comparison['bindings']['manifest_sha256']}`",
            f"- Host: {comparison['host']['platform']} ({comparison['host']['machine']})",
            "- Research-ceiling tier still pending: ZPAQ, paq8px, cmix, and NNCP.",
            "- Public validation and private holdout remain sealed and unaccessed.",
            "",
            f"Claim ceiling: **{comparison['claim_ceiling']}**",
            "",
            "## Next decision",
            "",
            "Use the measured per-track and per-item frontier to predeclare the first Axiom",
            "text/source specialist hypotheses. A candidate must then beat the strongest",
            "eligible baseline under a separate exact gate; this census alone is not a win.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    width = 1500
    row_height = 27
    track_height = 92 + row_height * len(EXPECTED_CODECS)
    height = 142 + track_height * len(comparison["tracks"]) + 88
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Text and source practical compression baseline census</title>',
        '<desc id="desc">Two complete same-host tables compare every practical baseline by compressed size, compression and decompression speed, peak memory, exactness, and determinism. Axiom is explicitly untested.</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#172033}",
        ".title{font-size:28px;font-weight:700}.subtitle{font-size:15px;fill:#526078}",
        ".track{font-size:21px;font-weight:700}.head{font-size:12px;font-weight:700;fill:#526078}",
        ".label{font-size:13px}.num{font-size:12px;font-variant-numeric:tabular-nums}",
        ".leader{font-weight:700;fill:#087b52}.note{font-size:13px;fill:#526078}",
        ".grid{stroke:#d8dee9;stroke-width:1}.bar{fill:#aeb8c8}.best{fill:#13a36f}.store{fill:#657189}",
        "</style>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text class="title" x="28" y="40">Text/source practical baseline census</text>',
        '<text class="subtitle" x="28" y="67">Complete artifact bytes · one thread · same host · five measured repetitions · exact + deterministic required</text>',
        '<text class="subtitle" x="28" y="91">Axiom text/source specialist: UNTESTED · development evidence only · lower size % is better</text>',
    ]
    y = 126
    for track in comparison["tracks"]:
        parts.append(
            f'<text class="track" x="28" y="{y}">{escape(track["track"])}</text>'
        )
        parts.append(
            f'<text class="subtitle" x="320" y="{y}">{track["source_bytes"]:,} source bytes · leader {escape(track["ratio_leader"])}</text>'
        )
        y += 30
        headers = [
            (28, "Codec"),
            (205, "Size %"),
            (605, "Complete bytes"),
            (735, "Ratio"),
            (815, "C MB/s"),
            (905, "D MB/s"),
            (1000, "Peak RSS C / D MiB"),
            (1175, "Exact / deterministic"),
            (1365, "Axiom"),
        ]
        for x, label in headers:
            parts.append(f'<text class="head" x="{x}" y="{y}">{escape(label)}</text>')
        y += 17
        for row in track["codecs"]:
            baseline = y + 14
            parts.append(
                f'<line class="grid" x1="28" x2="1470" y1="{y + 23}" y2="{y + 23}"/>'
            )
            css = "leader" if row["ratio_leader"] else "label"
            parts.append(
                f'<text class="{css}" x="28" y="{baseline}">{escape(row["codec"])}</text>'
            )
            bar_width = max(1.0, min(365.0, row["size_percent"] / 100.0 * 365.0))
            bar_class = (
                "best"
                if row["ratio_leader"]
                else ("store" if row["codec_id"] == "store" else "bar")
            )
            parts.append(
                f'<rect class="{bar_class}" x="205" y="{y + 4}" width="{bar_width:.2f}" height="14" rx="3"/>'
            )
            parts.append(
                f'<text class="num" x="578" y="{baseline}" text-anchor="end">{row["size_percent"]:.2f}%</text>'
            )
            parts.append(
                f'<text class="num" x="705" y="{baseline}" text-anchor="end">{row["complete_bytes"]:,}</text>'
            )
            parts.append(
                f'<text class="num" x="790" y="{baseline}" text-anchor="end">{row["compression_ratio"]:.2f}x</text>'
            )
            parts.append(
                f'<text class="num" x="880" y="{baseline}" text-anchor="end">{row["compression_mbps"]:.2f}</text>'
            )
            parts.append(
                f'<text class="num" x="970" y="{baseline}" text-anchor="end">{row["decompression_mbps"]:.2f}</text>'
            )
            parts.append(
                f'<text class="num" x="1145" y="{baseline}" text-anchor="end">{row["compression_peak_rss_mib"]:.1f} / {row["decompression_peak_rss_mib"]:.1f}</text>'
            )
            parts.append(f'<text class="num" x="1260" y="{baseline}">yes / yes</text>')
            parts.append(f'<text class="num" x="1365" y="{baseline}">untested</text>')
            y += row_height
        y += 45
    parts.extend(
        [
            f'<text class="note" x="28" y="{height - 48}">Research-ceiling codecs ZPAQ, paq8px, cmix, and NNCP remain pending; validation and holdout remain sealed.</text>',
            f'<text class="note" x="28" y="{height - 24}">This chart establishes the practical development frontier only. It does not claim an Axiom win or state of the art.</text>',
            "</svg>",
            "",
        ]
    )
    return "\n".join(parts)


def build_artifacts(results_path: Path) -> dict[str, bytes]:
    raw = results_path.read_bytes()
    results = json.loads(raw)
    if not isinstance(results, dict) or raw != json_bytes(results):
        raise ValueError("baseline result is not canonical JSON")
    trial_receipts_sha256 = validate_trial_receipts(results_path, results)
    results_sha256 = sha256_bytes(raw)
    public_evidence = build_public_evidence(
        results_path,
        results,
        raw_results_sha256=results_sha256,
        raw_receipts_manifest_sha256=trial_receipts_sha256,
    )
    public_evidence_payload = json.loads(public_evidence)
    comparison = derive(
        results,
        source_sha256=results_sha256,
        trial_receipts_sha256=trial_receipts_sha256,
        public_evidence_sha256=sha256_bytes(public_evidence),
        public_receipts_sha256=public_evidence_payload[
            "public_trial_receipts_manifest_sha256"
        ],
    )
    artifacts = {
        "evidence.json": public_evidence,
        "comparison.json": json_bytes(comparison),
        "comparison.svg": render_svg(comparison).encode("utf-8"),
        "README.md": render_markdown(comparison).encode("utf-8"),
    }
    receipt = {
        "schema_version": 1,
        "name": "text-source-development-practical-baseline-publication-receipt-v1",
        "results_path": results_path.name,
        "results_sha256": comparison["results_sha256"],
        "trial_receipts_manifest_sha256": trial_receipts_sha256,
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "public_trial_receipts_manifest_sha256": comparison[
            "public_trial_receipts_manifest_sha256"
        ],
        "bindings": comparison["bindings"],
        "artifacts": {
            name: sha256_bytes(payload) for name, payload in artifacts.items()
        },
        "claim_ceiling": comparison["claim_ceiling"],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(results_path: Path, output: Path) -> Path:
    artifacts = build_artifacts(results_path)
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ValueError("refusing non-directory publication destination")
        observed = {path.name for path in output.iterdir()}
        if observed != set(artifacts):
            raise ValueError("refusing publication directory with differing roster")
        for name, expected in artifacts.items():
            path = output / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise ValueError(
                    f"refusing to replace differing publication artifact: {name}"
                )
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="text-source-publication-", dir=output.parent
    ) as raw:
        staging = Path(raw) / "publication"
        staging.mkdir()
        for name, payload in artifacts.items():
            (staging / name).write_bytes(payload)
        staging.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.results.parent / "publication"
    try:
        published = publish(args.results, output)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"text/source publication refused: {error}") from error
    print(published)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
