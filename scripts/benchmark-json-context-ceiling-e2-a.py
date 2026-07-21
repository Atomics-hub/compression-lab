#!/usr/bin/env python3
"""Run the frozen E2-A JSON context-model block-size memory sweep."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "json-context-ceiling-e2-a-v1.json"
PROTOCOL = (
    ROOT / "docs" / "benchmarks" / "2026-07-21-json-context-ceiling-e2-a-protocol.md"
)
VERIFIER = ROOT / "scripts" / "verify-json-context-ceiling-e2-a.py"
MAX_LOG_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary file: {path}")


def read_json(path: Path) -> dict[str, Any]:
    ordinary(path)
    return json.loads(path.read_bytes())


def packed_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise ValueError("invalid AXE2O string")
    return struct.pack("<H", len(encoded)) + encoded


def axe2o(
    category: str,
    source_manifest_sha256: str,
    method_id: str,
    items: list[dict[str, Any]],
) -> bytes:
    frame = bytearray(b"AXE2O" + bytes([1]))
    frame.extend(packed_string(category))
    frame.extend(bytes.fromhex(source_manifest_sha256))
    frame.extend(struct.pack("<I", len(items)))
    archives: list[bytes] = []
    for item in sorted(items, key=lambda row: row["item_id"]):
        archive = Path(item["archive_absolute"])
        ordinary(archive)
        payload = archive.read_bytes()
        frame.extend(packed_string(item["item_id"]))
        frame.extend(packed_string(method_id))
        frame.extend(struct.pack("<Q", item["source_bytes"]))
        frame.extend(bytes.fromhex(item["source_sha256"]))
        frame.extend(struct.pack("<Q", len(payload)))
        frame.extend(hashlib.sha256(payload).digest())
        archives.append(payload)
    for payload in archives:
        frame.extend(payload)
    return bytes(frame)


def axe1o_size(category: str, trials: list[dict[str, Any]]) -> int:
    total = 5 + 1 + len(packed_string(category)) + 32 + 4
    for trial in sorted(trials, key=lambda row: row["item_id"]):
        rep = trial["repetitions"][0]
        total += (
            len(packed_string(trial["item_id"]))
            + len(packed_string(trial["codec_id"]))
            + 8
            + 32
            + 8
            + 32
            + rep["artifact_bytes"]
        )
    return total


def verify_e1_reference(
    config: dict[str, Any], practical_path: Path, zpaq_path: Path
) -> dict[str, Any]:
    source, frozen = config["source_run"], config["e1_fixed_reference"]
    documents = {}
    for key, path, binding in (
        ("practical", practical_path, source["e1_practical_json_artifact"]),
        ("zpaq", zpaq_path, source["e1_zpaq_json_artifact"]),
    ):
        if sha256_file(path) != binding["result_sha256"]:
            raise ValueError(f"pinned E1 {key} raw result differs")
        document = read_json(path)
        if (
            not document["completed"]
            or document["phase"] != "whole"
            or document["category"] != "json_logs"
            or document["public_validation_accessed"]
            or document["private_holdout_accessed"]
            or document["training_manifest_sha256"]
            != source["training_manifest_sha256"]
            or document["tool_receipt_sha256"] != source["tool_receipt_sha256"]
        ):
            raise ValueError(f"pinned E1 {key} raw result identity differs")
        documents[key] = document
    practical_totals = {}
    for codec_id in ("kanzi-max", "zstd-19-long", "xz-lzma2-9e"):
        trials = [
            row
            for row in documents["practical"]["trials"]
            if row["codec_id"] == codec_id
        ]
        if len(trials) != 3 or not all(
            row["exact"] and row["deterministic"] for row in trials
        ):
            raise ValueError(f"pinned E1 practical roster differs: {codec_id}")
        practical_totals[codec_id] = axe1o_size("json_logs", trials)
    zpaq_trials = documents["zpaq"]["trials"]
    if len(zpaq_trials) != 3 or not all(
        row["codec_id"] == "zpaq-5-m510" and row["exact"] and row["deterministic"]
        for row in zpaq_trials
    ):
        raise ValueError("pinned E1 ZPAQ roster differs")
    zpaq_total = axe1o_size("json_logs", zpaq_trials)
    if (
        min(practical_totals.values()) != frozen["kanzi_complete_bytes"]
        or practical_totals["kanzi-max"] != frozen["kanzi_complete_bytes"]
    ):
        raise ValueError("E1 Kanzi reference does not recompute")
    if zpaq_total != frozen["zpaq_510_complete_bytes"]:
        raise ValueError("E1 ZPAQ reference does not recompute")
    return {
        "practical_complete_bytes": practical_totals,
        "zpaq_510_complete_bytes": zpaq_total,
        "zpaq_510_per_item": [
            {
                "item_id": row["item_id"],
                "artifact_bytes": row["repetitions"][0]["artifact_bytes"],
                "artifact_sha256": row["repetitions"][0]["artifact_sha256"],
            }
            for row in sorted(zpaq_trials, key=lambda value: value["item_id"])
        ],
        "recomputed": True,
    }


def rss_bytes(usage: Any) -> int:
    value = int(usage.ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def bounded_process(
    command: list[str], *, cwd: Path, log_prefix: Path, timeout_seconds: int
) -> dict[str, Any]:
    if not hasattr(os, "wait4") or not hasattr(os, "killpg"):
        raise ValueError("E2-A requires POSIX wait4 and process-group control")
    stdout_path = log_prefix.with_suffix(".stdout")
    stderr_path = log_prefix.with_suffix(".stderr")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        status = usage = None
        timed_out = output_exceeded = False
        while status is None:
            pid, wait_status, sample = os.wait4(process.pid, os.WNOHANG)
            if pid:
                status, usage = wait_status, sample
                break
            timed_out = (time.monotonic_ns() - started) / 1e9 > timeout_seconds
            output_exceeded = (
                stdout_path.stat().st_size > MAX_LOG_BYTES
                or stderr_path.stat().st_size > MAX_LOG_BYTES
            )
            if timed_out or output_exceeded:
                os.killpg(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    pid, wait_status, sample = os.wait4(process.pid, os.WNOHANG)
                    if pid:
                        status, usage = wait_status, sample
                        break
                    time.sleep(0.05)
                if status is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    _pid, status, usage = os.wait4(process.pid, 0)
                break
            time.sleep(0.05)
    assert status is not None and usage is not None
    exit_code = os.waitstatus_to_exitcode(status)
    process.returncode = exit_code
    return {
        "command": command,
        "wall_ns": time.monotonic_ns() - started,
        "cpu_user_ns": int(usage.ru_utime * 1e9),
        "cpu_system_ns": int(usage.ru_stime * 1e9),
        "peak_rss_bytes": rss_bytes(usage),
        "exit_status": exit_code,
        "timed_out": timed_out,
        "output_exceeded": output_exceeded,
        "stdout": file_row(stdout_path),
        "stderr": file_row(stderr_path),
    }


def file_row(path: Path, root: Path | None = None) -> dict[str, Any]:
    ordinary(path)
    return {
        "path": path.relative_to(root).as_posix() if root else str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_inputs(
    config_path: Path, config: dict[str, Any], training: Path, tools: Path
) -> tuple[list[dict[str, Any]], Path]:
    source = config["source_run"]
    recovery = ROOT / source["github_recovery_receipt"]
    if sha256_file(recovery) != source["github_recovery_receipt_sha256"]:
        raise ValueError("pinned GitHub recovery receipt differs")
    publication = config["e1_fixed_reference"]
    publication_path = ROOT / publication["publication_receipt"]
    if sha256_file(publication_path) != publication["publication_receipt_sha256"]:
        raise ValueError("E1 publication receipt differs")
    if (
        read_json(publication_path)["members"]["result.json"]
        != publication["result_member_sha256"]
    ):
        raise ValueError("E1 result member binding differs")
    manifest_path = training / "manifest.json"
    receipt_path = tools / "receipt.json"
    if sha256_file(manifest_path) != source["training_manifest_sha256"]:
        raise ValueError("training manifest differs")
    if sha256_file(receipt_path) != source["tool_receipt_sha256"]:
        raise ValueError("tool receipt differs")
    manifest = read_json(manifest_path)
    if manifest.get("public_validation_accessed") or manifest.get(
        "private_holdout_accessed"
    ):
        raise ValueError("source training artifact crossed an information boundary")
    expected = {row["id"]: row for row in config["items"]}
    actual = {row["id"]: row for row in manifest["items"] if row["id"] in expected}
    if set(actual) != set(expected):
        raise ValueError("allowed item roster differs")
    verified: list[dict[str, Any]] = []
    for item_id in sorted(expected):
        frozen, row = expected[item_id], actual[item_id]
        for key in ("category", "path", "license", "bytes", "sha256"):
            if row[key] != frozen[key]:
                raise ValueError(f"manifest differs for {item_id}: {key}")
        path = training / frozen["path"]
        ordinary(path)
        if (
            path.stat().st_size != frozen["bytes"]
            or sha256_file(path) != frozen["sha256"]
        ):
            raise ValueError(f"allowed item bytes differ: {item_id}")
        verified.append({**frozen, "absolute": str(path.resolve())})
    zpaq = tools / "bin" / "zpaq"
    ordinary(zpaq)
    if sha256_file(zpaq) != source["zpaq_binary_sha256"]:
        raise ValueError("ZPAQ executable differs")
    if not os.access(zpaq, os.X_OK):
        raise ValueError("ZPAQ executable is not executable")
    ordinary(config_path)
    return verified, zpaq.resolve()


def run_trial(
    *,
    config: dict[str, Any],
    method: dict[str, Any],
    item: dict[str, Any],
    repetition: int,
    stage: str,
    zpaq: Path,
    output: Path,
) -> dict[str, Any]:
    slug = f"{stage}/{method['id']}/{item['id']}/r{repetition}"
    archive = output / "archives" / slug / "artifact.zpaq"
    archive.parent.mkdir(parents=True, exist_ok=False)
    logs = output / "logs" / slug
    logs.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="axiom-e2a-") as raw:
        work = Path(raw)
        staged = work / "input.bin"
        shutil.copyfile(item["absolute"], staged)
        os.utime(staged, (946684800, 946684800))
        restored_dir = work / "restored"
        restored_dir.mkdir()
        restored = restored_dir / "input.bin"
        compress_command = [
            str(zpaq),
            "add",
            str(archive),
            "input.bin",
            "-method",
            method["method"],
            "-threads",
            "1",
            "-noattributes",
            "-until",
            "20000101000000",
        ]
        compress = bounded_process(
            compress_command,
            cwd=work,
            log_prefix=logs / "compress",
            timeout_seconds=config["measurement"]["timeout_seconds_per_process"],
        )
        compress["declared_command"] = config["command"]["compress"]
        if (
            compress["exit_status"]
            or compress["timed_out"]
            or compress["output_exceeded"]
        ):
            raise ValueError(f"compression failed: {slug}")
        ordinary(archive)
        decompress_command = [
            str(zpaq),
            "extract",
            str(archive),
            "input.bin",
            "-to",
            str(restored),
            "-force",
            "-threads",
            "1",
            "-noattributes",
        ]
        decompress = bounded_process(
            decompress_command,
            cwd=work,
            log_prefix=logs / "decompress",
            timeout_seconds=config["measurement"]["timeout_seconds_per_process"],
        )
        decompress["declared_command"] = config["command"]["decompress"]
        if (
            decompress["exit_status"]
            or decompress["timed_out"]
            or decompress["output_exceeded"]
        ):
            raise ValueError(f"decompression failed: {slug}")
        ordinary(restored)
        restored_bytes = restored.stat().st_size
        restored_sha256 = sha256_file(restored)
    return {
        "stage": stage,
        "method_id": method["id"],
        "method": method["method"],
        "item_id": item["id"],
        "repetition": repetition,
        "source_bytes": item["bytes"],
        "source_sha256": item["sha256"],
        "archive": file_row(archive, output),
        "compress": normalize_process(compress, output),
        "decompress": normalize_process(decompress, output),
        "restored_bytes": restored_bytes,
        "restored_sha256": restored_sha256,
        "exact": restored_bytes == item["bytes"] and restored_sha256 == item["sha256"],
    }


def normalize_process(process: dict[str, Any], output: Path) -> dict[str, Any]:
    row = dict(process)
    for key in ("stdout", "stderr"):
        path = Path(row[key]["path"])
        row[key] = file_row(path, output)
    return row


def build_container(
    output: Path,
    source_manifest_sha256: str,
    method: dict[str, Any],
    trials: list[dict[str, Any]],
    repetition: int,
) -> dict[str, Any]:
    selected = []
    for trial in trials:
        if trial["method_id"] == method["id"] and trial["repetition"] == repetition:
            selected.append(
                {
                    "item_id": trial["item_id"],
                    "source_bytes": trial["source_bytes"],
                    "source_sha256": trial["source_sha256"],
                    "archive_absolute": str(output / trial["archive"]["path"]),
                }
            )
    if len(selected) != 3:
        raise ValueError(f"incomplete container inputs: {method['id']} r{repetition}")
    data = axe2o(
        "json_logs",
        source_manifest_sha256,
        method["id"],
        selected,
    )
    path = output / "containers" / f"{method['id']}-r{repetition}.axe2o"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return file_row(path, output)


def method_summary(
    config: dict[str, Any],
    method: dict[str, Any],
    trials: list[dict[str, Any]],
    container: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        row
        for row in trials
        if row["method_id"] == method["id"] and row["stage"] == "stage_one"
    ]
    exact = len(rows) == 3 and all(row["exact"] for row in rows)
    compression_rss = max(row["compress"]["peak_rss_bytes"] for row in rows)
    decompression_rss = max(row["decompress"]["peak_rss_bytes"] for row in rows)
    limits = config["measurement"]
    eligible = (
        exact
        and compression_rss <= limits["maximum_compression_peak_rss_bytes"]
        and decompression_rss <= limits["maximum_decompression_peak_rss_bytes"]
    )
    baseline = config["e1_fixed_reference"]["kanzi_complete_bytes"]
    gain_bp = (baseline - container["bytes"]) * 10000 // baseline
    return {
        "method_id": method["id"],
        "maximum_block_mib": method["maximum_block_mib"],
        "complete_container": container,
        "gain_vs_e1_kanzi_basis_points": gain_bp,
        "maximum_compression_peak_rss_bytes": compression_rss,
        "maximum_decompression_peak_rss_bytes": decompression_rss,
        "eligible": eligible,
        "fragile": max(compression_rss, decompression_rss)
        >= config["decision_gates"]["fragile_peak_rss_bytes"],
        "exact": exact,
    }


def collect_file_manifest(output: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "result.json":
            rows.append(file_row(path, output))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, required=True)
    parser.add_argument("--e1-practical-result", type=Path, required=True)
    parser.add_argument("--e1-zpaq-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-commit", required=True)
    args = parser.parse_args()
    config = read_json(args.config)
    if len(args.repository_commit) != 40 or any(
        character not in "0123456789abcdef" for character in args.repository_commit
    ):
        raise SystemExit("E2-A repository commit must be a lowercase 40-hex SHA")
    if args.output.exists():
        raise SystemExit("E2-A output path must not exist")
    args.output.mkdir(parents=True)
    try:
        e1_reference = verify_e1_reference(
            config, args.e1_practical_result, args.e1_zpaq_result
        )
        items, zpaq = verify_inputs(
            args.config, config, args.training_root, args.tool_root
        )
        stage_one = []
        for method in config["methods"]:
            for item in items:
                stage_one.append(
                    run_trial(
                        config=config,
                        method=method,
                        item=item,
                        repetition=1,
                        stage="stage_one",
                        zpaq=zpaq,
                        output=args.output,
                    )
                )
        containers = {
            method["id"]: build_container(
                args.output,
                config["source_run"]["training_manifest_sha256"],
                method,
                stage_one,
                1,
            )
            for method in config["methods"]
        }
        summaries = [
            method_summary(config, method, stage_one, containers[method["id"]])
            for method in config["methods"]
        ]
        eligible = sorted(
            (row for row in summaries if row["eligible"]),
            key=lambda row: (row["complete_container"]["bytes"], row["method_id"]),
        )
        selected = [] if not eligible else [eligible[0]["method_id"]]
        if "zpaq-5-m510" not in selected:
            selected.append("zpaq-5-m510")
        e1_anchor = {row["item_id"]: row for row in e1_reference["zpaq_510_per_item"]}
        observed_anchor = {
            row["item_id"]: row
            for row in stage_one
            if row["method_id"] == "zpaq-5-m510"
        }
        anchor_matched = set(e1_anchor) == set(observed_anchor) and all(
            observed_anchor[item_id]["archive"]["bytes"]
            == e1_anchor[item_id]["artifact_bytes"]
            and observed_anchor[item_id]["archive"]["sha256"]
            == e1_anchor[item_id]["artifact_sha256"]
            for item_id in e1_anchor
        )
        method_by_id = {row["id"]: row for row in config["methods"]}
        confirmation = []
        for method_id in selected:
            for item in items:
                confirmation.append(
                    run_trial(
                        config=config,
                        method=method_by_id[method_id],
                        item=item,
                        repetition=2,
                        stage="confirmation",
                        zpaq=zpaq,
                        output=args.output,
                    )
                )
        confirmation_containers = {
            method_id: build_container(
                args.output,
                config["source_run"]["training_manifest_sha256"],
                method_by_id[method_id],
                confirmation,
                2,
            )
            for method_id in selected
        }
        confirmed = True
        for method_id in selected:
            first = [row for row in stage_one if row["method_id"] == method_id]
            second = [row for row in confirmation if row["method_id"] == method_id]
            first.sort(key=lambda row: row["item_id"])
            second.sort(key=lambda row: row["item_id"])
            confirmed &= all(
                a["archive"]["sha256"] == b["archive"]["sha256"] and b["exact"]
                for a, b in zip(first, second, strict=True)
            )
            confirmed &= (
                containers[method_id]["sha256"]
                == confirmation_containers[method_id]["sha256"]
            )
        best = eligible[0] if eligible else None
        if best is not None:
            bounded_confirmation = [
                row for row in confirmation if row["method_id"] == best["method_id"]
            ]
            confirmed &= (
                max(row["compress"]["peak_rss_bytes"] for row in bounded_confirmation)
                <= config["measurement"]["maximum_compression_peak_rss_bytes"]
            )
            confirmed &= (
                max(row["decompress"]["peak_rss_bytes"] for row in bounded_confirmation)
                <= config["measurement"]["maximum_decompression_peak_rss_bytes"]
            )
        gates = config["decision_gates"]
        if not anchor_matched:
            decision = "refuse_e1_anchor_mismatch"
        elif not confirmed:
            decision = "fail_confirmation"
        elif (
            best is None
            or best["complete_container"]["bytes"]
            >= gates["kill_when_complete_bytes_at_least"]
        ):
            decision = "kill_bounded_level5_lane"
        elif (
            best["complete_container"]["bytes"]
            <= gates["advance_maximum_complete_bytes"]
        ):
            decision = "advance_component_attribution"
        else:
            decision = "permit_one_frozen_refinement"
        result = {
            "schema_version": 1,
            "name": config["name"],
            "completed": True,
            "repository_commit": args.repository_commit,
            "config_sha256": sha256_file(args.config),
            "protocol_sha256": sha256_file(PROTOCOL),
            "runner_sha256": sha256_file(Path(__file__)),
            "verifier_sha256": sha256_file(VERIFIER),
            "source_bindings": config["source_run"],
            "e1_reference": {**e1_reference, "anchor_matched": anchor_matched},
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version,
                "cpu_count": os.cpu_count(),
            },
            "item_verification": [
                {key: value for key, value in item.items() if key != "absolute"}
                for item in items
            ],
            "stage_one_trials": stage_one,
            "confirmation_trials": confirmation,
            "method_summaries": summaries,
            "selected_methods": selected,
            "confirmation_containers": confirmation_containers,
            "decision": {
                "outcome": decision,
                "best_eligible_method": None if best is None else best["method_id"],
                "best_eligible_complete_bytes": None
                if best is None
                else best["complete_container"]["bytes"],
                "best_eligible_gain_basis_points": None
                if best is None
                else best["gain_vs_e1_kanzi_basis_points"],
                "confirmation_passed": confirmed,
            },
            "information_boundary": config["information_boundary"],
            "claim_ceiling": config["claim_ceiling"],
            "file_manifest": collect_file_manifest(args.output),
        }
        (args.output / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
    except Exception as error:
        failure = {
            "schema_version": 1,
            "name": config.get("name"),
            "completed": False,
            "error": str(error),
            "claim_ceiling": config.get("claim_ceiling"),
        }
        (args.output / "failure.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n"
        )
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
