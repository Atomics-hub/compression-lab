#!/usr/bin/env python3
"""Run the frozen S0 JSON/log native structure-aware development screen.

This is a predeclared development-only model screen, not an exact codec result.
It charges the ten frozen arms on the three licensed CLUE development items,
recomputes every Q24 projection with exact integer arithmetic, and applies the
frozen advance/refine/kill, event-limit, per-item, quarantine, and attribution
gates. Receipts are content-derived and machine-independent; all host-specific
measurements live only in a separate environment section that the verifier
ignores for byte comparisons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-log-native-screen-s0-v1.json"
PROTOCOL = (
    ROOT / "docs" / "benchmarks" / "2026-07-21-json-log-native-screen-s0-protocol.md"
)
DEFAULT_CORPUS = ROOT / "corpora" / "clue-json-log-development-v1"
DEFAULT_OUTPUT = ROOT / "runs" / "json-log-native-screen-s0-v1"
SEGMENT_BYTES = 16_777_216

# Frozen projection and gate constants (mirrored from the constants manifest and
# ledger.rs; the verifier duplicates these independently).
Q24_ONE = 1 << 24
MEBIBYTE = 1 << 20
AGGREGATE_BLOCK_ALLOWANCE = 6_272
AGGREGATE_STREAM_METADATA = 72
FIXED_FRAMING = 4_096
ITEM_STREAM_METADATA = 24
BLOCK_ALLOWANCE_PER_MEBIBYTE = 32
EVENT_LIMIT_PER_RECORD = 96
KANZI_COMPLETE_BYTES = 1_712_149
ADVANCE_MAXIMUM_BYTES = 1_455_326
ADVANCE_MINIMUM_GAIN_BP = 1_500
REFINEMENT_MAXIMUM_BYTES = 1_540_934
FULL_MINUS_M4_MINIMUM_GAIN_BP = 700
REPORT_ATTRIBUTION_BYTES = 8_561
EXACT_BUILD_ATTRIBUTION_BYTES = 17_122
LEDGER_KEYS = (
    "records",
    "modeled_binary_events",
    "modeled_loss_q24",
    "raw_literal_bytes",
)


class ScreenError(Exception):
    """A fail-closed error that aborts the frozen screen with a clear message."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ScreenError(f"expected ordinary file: {path}")


def read_json(path: Path) -> dict[str, Any]:
    ordinary(path)
    return json.loads(path.read_bytes())


def div_ceil(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def payload_bytes(ledger: dict[str, int]) -> int:
    charged = ledger["modeled_loss_q24"] + ledger["raw_literal_bytes"] * 8 * Q24_ONE
    return div_ceil(charged, 8 * Q24_ONE)


def coder_allowance(payload: int) -> int:
    return div_ceil(payload * 5, 1_000)


def project_aggregate(ledger: dict[str, int]) -> dict[str, int]:
    payload = payload_bytes(ledger)
    allowance = coder_allowance(payload)
    return {
        "payload_bytes": payload,
        "coder_allowance_bytes": allowance,
        "block_allowance_bytes": AGGREGATE_BLOCK_ALLOWANCE,
        "stream_metadata_bytes": AGGREGATE_STREAM_METADATA,
        "fixed_framing_bytes": FIXED_FRAMING,
        "complete_bytes": payload
        + allowance
        + AGGREGATE_BLOCK_ALLOWANCE
        + AGGREGATE_STREAM_METADATA
        + FIXED_FRAMING,
    }


def project_item(ledger: dict[str, int], source_bytes: int) -> dict[str, int]:
    payload = payload_bytes(ledger)
    allowance = coder_allowance(payload)
    blocks = div_ceil(source_bytes, MEBIBYTE)
    block_allowance = blocks * BLOCK_ALLOWANCE_PER_MEBIBYTE
    return {
        "payload_bytes": payload,
        "coder_allowance_bytes": allowance,
        "block_allowance_bytes": block_allowance,
        "stream_metadata_bytes": ITEM_STREAM_METADATA,
        "fixed_framing_bytes": FIXED_FRAMING,
        "complete_bytes": payload
        + allowance
        + block_allowance
        + ITEM_STREAM_METADATA
        + FIXED_FRAMING,
    }


def gain_basis_points(complete_bytes: int) -> int:
    # Floor division on the signed difference; Python // already floors, which is
    # the correct i128 floor semantics for negative differences.
    return (KANZI_COMPLETE_BYTES - complete_bytes) * 10_000 // KANZI_COMPLETE_BYTES


def event_limit_passes(ledger: dict[str, int]) -> bool:
    return ledger["modeled_binary_events"] <= EVENT_LIMIT_PER_RECORD * ledger["records"]


def decision_for(complete_bytes: int, gain: int) -> str:
    if complete_bytes <= ADVANCE_MAXIMUM_BYTES and gain >= ADVANCE_MINIMUM_GAIN_BP:
        return "advance"
    if complete_bytes <= REFINEMENT_MAXIMUM_BYTES:
        return "refine_once"
    return "kill"


def attribution_entry(minuend: int, subtrahend: int) -> dict[str, Any]:
    attributed = max(0, minuend - subtrahend)
    return {
        "bytes": attributed,
        "report_threshold_met": attributed >= REPORT_ATTRIBUTION_BYTES,
        "exact_build_threshold_met": attributed >= EXACT_BUILD_ATTRIBUTION_BYTES,
    }


def load_items(config: dict[str, Any], items_config: Path | None) -> list[dict[str, Any]]:
    if items_config is not None:
        raw = read_json(items_config)["items"]
    else:
        raw = config["references"]["items"]
    items: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        for key in ("id", "source_bytes", "source_sha256", "kanzi_single_item_axe1o_bytes"):
            if key not in entry:
                raise ScreenError(f"item {index} missing {key}")
        items.append(
            {
                "index": index,
                "id": entry["id"],
                "source_bytes": int(entry["source_bytes"]),
                "source_sha256": entry["source_sha256"],
                "kanzi_single_item_axe1o_bytes": int(
                    entry["kanzi_single_item_axe1o_bytes"]
                ),
            }
        )
    if not items:
        raise ScreenError("no items to screen")
    return items


def preflight_items(items: list[dict[str, Any]], corpus_dir: Path) -> None:
    for item in items:
        source = corpus_dir / f"{item['id']}.jsonl"
        ordinary(source)
        size = source.stat().st_size
        if size != item["source_bytes"]:
            raise ScreenError(
                f"item {item['id']} byte count differs: {size} != {item['source_bytes']}"
            )
        digest = sha256_file(source)
        if digest != item["source_sha256"]:
            raise ScreenError(f"item {item['id']} SHA-256 differs")


def rss_bytes(usage: Any) -> tuple[int, int]:
    raw = int(usage.ru_maxrss)
    # macOS reports ru_maxrss in bytes; Linux in KiB.
    normalized = raw if platform.system() == "Darwin" else raw * 1024
    return raw, normalized


def encode_arm_item(
    kernel: Path,
    arm: str,
    item: dict[str, Any],
    corpus_dir: Path,
    output_dir: Path,
    segment_bytes: int,
    sse_bucket_bits: int,
) -> dict[str, Any]:
    tape_out = output_dir / "tapes" / arm / f"{item['id']}.tape"
    receipt_out = output_dir / "receipts" / arm / f"{item['id']}.json"
    tape_out.parent.mkdir(parents=True, exist_ok=True)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    if tape_out.exists():
        raise ScreenError(f"stale tape output present: {tape_out}")
    if receipt_out.exists():
        raise ScreenError(f"stale receipt output present: {receipt_out}")
    command = [
        str(kernel),
        "encode",
        "--arm",
        arm,
        "--item-index",
        str(item["index"]),
        "--input",
        str(corpus_dir / f"{item['id']}.jsonl"),
        "--tape-out",
        str(tape_out),
        "--receipt-out",
        str(receipt_out),
        "--segment-bytes",
        str(segment_bytes),
        "--sse-bucket-bits",
        str(sse_bucket_bits),
    ]
    if not hasattr(os, "wait4"):
        raise ScreenError("S0 requires POSIX os.wait4 for peak-RSS capture")
    # Redirect the child's stdout/stderr to temp files in the run scratch area,
    # never to pipes: os.wait4 blocks for the child, and an unread pipe that
    # fills its buffer would deadlock the wait. Unlinked temp files cannot leak.
    started = time.monotonic_ns()
    with (
        tempfile.TemporaryFile(dir=output_dir) as stdout_file,
        tempfile.TemporaryFile(dir=output_dir) as stderr_file,
    ):
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        _pid, status, usage = os.wait4(process.pid, 0)
        stderr_file.seek(0)
        stderr = stderr_file.read()
    exit_code = os.waitstatus_to_exitcode(status)
    wall_ns = time.monotonic_ns() - started
    if exit_code != 0:
        raise ScreenError(
            f"kernel encode failed for {arm}/{item['id']} (exit {exit_code}): "
            f"{stderr.decode('utf-8', 'replace').strip()}"
        )
    ordinary(tape_out)
    ordinary(receipt_out)
    receipt = read_json(receipt_out)
    if int(receipt["sse_bucket_bits"]) != sse_bucket_bits:
        raise ScreenError(
            f"receipt sse_bucket_bits differs for {arm}/{item['id']}: "
            f"{receipt['sse_bucket_bits']} != {sse_bucket_bits}"
        )
    raw_rss, normalized_rss = rss_bytes(usage)
    environment = {
        "arm": arm,
        "item_id": item["id"],
        "wall_ns": wall_ns,
        "cpu_user_ns": int(usage.ru_utime * 1e9),
        "cpu_system_ns": int(usage.ru_stime * 1e9),
        "peak_rss_raw": raw_rss,
        "peak_rss_bytes": normalized_rss,
    }
    return {
        "tape_out": tape_out,
        "receipt_out": receipt_out,
        "receipt": receipt,
        "environment": environment,
    }


def item_ledger(receipt: dict[str, Any]) -> dict[str, int]:
    return {key: int(receipt["ledger"][key]) for key in LEDGER_KEYS}


def build_arm_result(
    arm_meta: dict[str, Any],
    items: list[dict[str, Any]],
    encoded: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    arm = arm_meta["name"]
    per_item: list[dict[str, Any]] = []
    aggregate = dict.fromkeys(LEDGER_KEYS, 0)
    for item in items:
        record = encoded[(arm, item["id"])]
        receipt = record["receipt"]
        if receipt["arm"] != arm or int(receipt["item_index"]) != item["index"]:
            raise ScreenError(f"receipt identity differs for {arm}/{item['id']}")
        if receipt["source_sha256"] != item["source_sha256"]:
            raise ScreenError(f"receipt source SHA differs for {arm}/{item['id']}")
        if not receipt["decode_matches_source"]:
            raise ScreenError(f"receipt decode did not match source for {arm}/{item['id']}")
        if receipt["decoded_sha256"] != item["source_sha256"]:
            raise ScreenError(f"receipt decoded SHA differs for {arm}/{item['id']}")
        ledger = item_ledger(receipt)
        projection = project_item(ledger, item["source_bytes"])
        if projection != {
            key: int(value) for key, value in receipt["item_projection"].items()
        }:
            raise ScreenError(
                f"recomputed item projection disagrees with receipt for {arm}/{item['id']}"
            )
        for key in LEDGER_KEYS:
            aggregate[key] += ledger[key]
        per_item.append(
            {
                "item_index": item["index"],
                "item_id": item["id"],
                "ledger": ledger,
                "item_projection": projection,
                "source_sha256": item["source_sha256"],
                "tape_sha256": receipt["tape_sha256"],
                "decoded_sha256": receipt["decoded_sha256"],
                "segment_interval_bytes": receipt["segment_interval_bytes"],
                "segments": receipt["segments"],
            }
        )
    aggregate_projection = project_aggregate(aggregate)
    return {
        "name": arm,
        "id": arm_meta["id"],
        "decides": arm_meta["decides"],
        "event_limit_applies": arm_meta["event_limit_applies"],
        "per_item": per_item,
        "aggregate_ledger": aggregate,
        "aggregate_projection": aggregate_projection,
        "aggregate_gain_basis_points": gain_basis_points(
            aggregate_projection["complete_bytes"]
        ),
    }


def build_gates(
    arms_by_name: dict[str, dict[str, Any]], items: list[dict[str, Any]]
) -> dict[str, Any]:
    full = arms_by_name["full"]
    full_complete = full["aggregate_projection"]["complete_bytes"]
    full_gain = full["aggregate_gain_basis_points"]

    event_per_item = [event_limit_passes(row["ledger"]) for row in full["per_item"]]
    event_aggregate = event_limit_passes(full["aggregate_ledger"])
    event_passes = all(event_per_item) and event_aggregate

    per_item_rows = []
    for item, row in zip(items, full["per_item"], strict=True):
        complete = row["item_projection"]["complete_bytes"]
        reference = item["kanzi_single_item_axe1o_bytes"]
        per_item_rows.append(
            {
                "item_id": item["id"],
                "complete_bytes": complete,
                "kanzi_reference_bytes": reference,
                "within_reference": complete <= reference,
            }
        )
    per_item_passes = all(row["within_reference"] for row in per_item_rows)

    minus_m4_gain = arms_by_name["full-minus-m4"]["aggregate_gain_basis_points"]
    quarantine = {
        "gain_basis_points": minus_m4_gain,
        "minimum_gain_basis_points": FULL_MINUS_M4_MINIMUM_GAIN_BP,
        "passes": minus_m4_gain >= FULL_MINUS_M4_MINIMUM_GAIN_BP,
        "vocabulary_carried": minus_m4_gain < FULL_MINUS_M4_MINIMUM_GAIN_BP,
    }

    def complete(name: str) -> int:
        return arms_by_name[name]["aggregate_projection"]["complete_bytes"]

    attribution = {
        "m1_bytes": attribution_entry(complete("raw-o3"), complete("m1-chassis")),
        "m2_bytes": attribution_entry(complete("m1-chassis"), complete("m1-m2")),
        "m3_bytes": attribution_entry(complete("full-minus-m3"), full_complete),
        "m4_bytes": attribution_entry(complete("full-minus-m4"), full_complete),
        "m5_bytes": attribution_entry(complete("full-minus-m5"), full_complete),
    }

    decision = decision_for(full_complete, full_gain)
    if not event_passes or not per_item_passes:
        decision = "kill"

    return {
        "decision": decision,
        "full_arm_complete_bytes": full_complete,
        "full_arm_gain_basis_points": full_gain,
        "advance_minimum_gain_basis_points": ADVANCE_MINIMUM_GAIN_BP,
        "advance_minimum_gain_satisfied": full_gain >= ADVANCE_MINIMUM_GAIN_BP,
        "event_gate": {
            "passes": event_passes,
            "per_item": event_per_item,
            "aggregate": event_aggregate,
        },
        "per_item_rule": {
            "passes": per_item_passes,
            "items": per_item_rows,
        },
        "full_minus_m4_quarantine": quarantine,
        "attribution": attribution,
    }


def build_binary(repo_root: Path, skip_build: bool) -> Path:
    native = repo_root / "native"
    binary = native / "target" / "release" / "clab-s0-kernel"
    if not skip_build:
        completed = subprocess.run(
            ["cargo", "build", "--release", "--locked", "--bin", "clab-s0-kernel"],
            cwd=native,
            check=False,
        )
        if completed.returncode != 0:
            raise ScreenError("cargo build of clab-s0-kernel failed")
    ordinary(binary)
    return binary


def toolchain_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for tool in ("rustc", "cargo"):
        completed = subprocess.run(
            [tool, "-V"], check=False, capture_output=True, text=True
        )
        versions[tool] = completed.stdout.strip() if completed.returncode == 0 else ""
    return versions


def write_sha256sums(output_dir: Path, files: list[Path]) -> None:
    lines = []
    for path in sorted(set(files)):
        lines.append(f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}")
    (output_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("base", "refined"), default="base")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--items-config", type=Path, default=None)
    parser.add_argument("--kernel-binary", type=Path, default=None)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--segment-bytes",
        type=int,
        default=SEGMENT_BYTES,
        help="segment snapshot interval (default 16 MiB; overridable for tests)",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    config_path = repo_root / "config" / "json-log-native-screen-s0-v1.json"
    protocol_path = (
        repo_root / "docs" / "benchmarks"
        / "2026-07-21-json-log-native-screen-s0-protocol.md"
    )
    manifest_path = (
        repo_root
        / "config"
        / f"json-log-native-screen-s0-constants-{args.profile}-v1.json"
    )
    base_manifest_path = (
        repo_root / "config" / "json-log-native-screen-s0-constants-base-v1.json"
    )
    refined_manifest_path = (
        repo_root / "config" / "json-log-native-screen-s0-constants-refined-v1.json"
    )
    corpus_dir = (
        args.corpus_dir.resolve()
        if args.corpus_dir is not None
        else (repo_root / "corpora" / "clue-json-log-development-v1")
    )
    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else repo_root
        / "runs"
        / (
            "json-log-native-screen-s0-v1"
            if args.profile == "base"
            else "json-log-native-screen-s0-v1-refined"
        )
    )
    if args.segment_bytes <= 0:
        raise SystemExit("--segment-bytes must be positive")
    if output_dir.exists():
        raise SystemExit(f"S0 output path must not exist: {output_dir}")

    try:
        config = read_json(config_path)
        freeze = config["screen"]["freeze_requirements_before_measurement"]
        if sha256_file(protocol_path) != freeze["protocol_sha256"]:
            raise ScreenError("protocol SHA-256 does not match the frozen config")
        manifest = read_json(manifest_path)
        if manifest["engine_source"]["protocol_sha256"] != freeze["protocol_sha256"]:
            raise ScreenError("constants manifest protocol binding differs")
        # The two manifests must differ only at the two predeclared maxima lines.
        import difflib

        base_lines = base_manifest_path.read_text("utf-8").splitlines()
        refined_lines = refined_manifest_path.read_text("utf-8").splitlines()
        changes = [
            line
            for line in difflib.unified_diff(base_lines, refined_lines, lineterm="")
            if line[:1] in {"+", "-"} and line[:3] not in {"+++", "---"}
        ]
        if changes != [
            '-      "context_table_bytes_maximum": 201326592,',
            '+      "context_table_bytes_maximum": 251658240,',
            '-      "sse_table_bytes_maximum": 16777216,',
            '+      "sse_table_bytes_maximum": 25165824,',
        ]:
            raise ScreenError("constants manifests differ beyond the two frozen maxima")

        # The capacity profile selects the SSE bucket-bit count exactly as the
        # manifest's mixer_and_sse.sse_bucket_bits_rule prescribes: base uses the
        # base bits, refined uses the single predeclared refined bits.
        mixer_and_sse = manifest["mixer_and_sse"]
        sse_bucket_bits = int(
            mixer_and_sse["sse_base_bucket_bits"]
            if args.profile == "base"
            else mixer_and_sse["sse_refined_bucket_bits"]
        )

        items = load_items(config, args.items_config)
        preflight_items(items, corpus_dir)

        if args.kernel_binary is not None:
            kernel = args.kernel_binary.resolve()
            ordinary(kernel)
        else:
            kernel = build_binary(repo_root, args.skip_build)

        arm_order = manifest["arms"]["frozen_order"]
        output_dir.mkdir(parents=True)

        encoded: dict[Any, dict[str, Any]] = {}
        environment_rows: list[dict[str, Any]] = []
        tapes: list[Path] = []
        receipts: list[Path] = []
        for arm_meta in arm_order:
            arm = arm_meta["name"]
            for item in items:
                record = encode_arm_item(
                    kernel,
                    arm,
                    item,
                    corpus_dir,
                    output_dir,
                    args.segment_bytes,
                    sse_bucket_bits,
                )
                encoded[(arm, item["id"])] = record
                environment_rows.append(record["environment"])
                tapes.append(record["tape_out"])
                receipts.append(record["receipt_out"])

        arm_results = [
            build_arm_result(
                {
                    "name": arm_meta["name"],
                    "id": arm_meta["id"],
                    "decides": arm_meta["decides"],
                    "event_limit_applies": arm_meta["event_limit_applies"],
                },
                items,
                encoded,
            )
            for arm_meta in arm_order
        ]
        arms_by_name = {row["name"]: row for row in arm_results}
        gates = build_gates(arms_by_name, items)

        result = {
            "schema_version": 1,
            "name": config["name"],
            "profile": args.profile,
            "evidence_stage": config["evidence_stage"],
            "claim_ceiling": config["claim_ceiling"],
            "bindings": {
                "config_sha256": sha256_file(config_path),
                "protocol_sha256": sha256_file(protocol_path),
                "constants_manifest_sha256": sha256_file(manifest_path),
                "constants_manifest_profile": args.profile,
                "base_constants_manifest_sha256": sha256_file(base_manifest_path),
                "refined_constants_manifest_sha256": sha256_file(refined_manifest_path),
            },
            "segment_interval_bytes": args.segment_bytes,
            "sse_bucket_bits": sse_bucket_bits,
            "items": [
                {
                    "index": item["index"],
                    "id": item["id"],
                    "source_bytes": item["source_bytes"],
                    "source_sha256": item["source_sha256"],
                    "kanzi_single_item_axe1o_bytes": item[
                        "kanzi_single_item_axe1o_bytes"
                    ],
                }
                for item in items
            ],
            "arms": arm_results,
            "gates": gates,
        }
        (output_dir / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        environment = {
            "schema_version": 1,
            "note": "Host-specific measurements; ignored by the verifier for byte comparisons.",
            "profile": args.profile,
            "toolchain": toolchain_versions(),
            "kernel_binary_sha256": sha256_file(kernel),
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version,
                "rss_units_raw": "bytes" if platform.system() == "Darwin" else "kib",
            },
            "measurements": environment_rows,
        }
        (output_dir / "environment.json").write_text(
            json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        write_sha256sums(output_dir, [output_dir / "result.json", *tapes, *receipts])
    except ScreenError as error:
        raise SystemExit(f"S0 screen failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
