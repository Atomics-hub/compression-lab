#!/usr/bin/env python3
"""Independently verify a frozen E2-A result and optionally re-decode archives."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "json-context-ceiling-e2-a-v1.json"
PROTOCOL = (
    ROOT / "docs" / "benchmarks" / "2026-07-21-json-context-ceiling-e2-a-protocol.md"
)
RUNNER = ROOT / "scripts" / "benchmark-json-context-ceiling-e2-a.py"


def require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys differ")


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


def build_axe2o(
    category: str,
    source_manifest_sha256: str,
    method_id: str,
    trials: list[dict[str, Any]],
    result_root: Path,
) -> bytes:
    frame = bytearray(b"AXE2O" + bytes([1]))
    frame.extend(packed_string(category))
    frame.extend(bytes.fromhex(source_manifest_sha256))
    frame.extend(struct.pack("<I", len(trials)))
    payloads = []
    for trial in sorted(trials, key=lambda row: row["item_id"]):
        archive = result_root / trial["archive"]["path"]
        ordinary(archive)
        payload = archive.read_bytes()
        frame.extend(packed_string(trial["item_id"]))
        frame.extend(packed_string(method_id))
        frame.extend(struct.pack("<Q", trial["source_bytes"]))
        frame.extend(bytes.fromhex(trial["source_sha256"]))
        frame.extend(struct.pack("<Q", len(payload)))
        frame.extend(hashlib.sha256(payload).digest())
        payloads.append(payload)
    return bytes(frame) + b"".join(payloads)


def axe1o_size(category: str, trials: list[dict[str, Any]]) -> int:
    total = 5 + 1 + len(packed_string(category)) + 32 + 4
    for trial in sorted(trials, key=lambda row: row["item_id"]):
        rep = trial["repetitions"][0]
        total += len(packed_string(trial["item_id"]))
        total += len(packed_string(trial["codec_id"])) + 8 + 32 + 8 + 32
        total += rep["artifact_bytes"]
    return total


def recompute_e1_reference(
    config: dict[str, Any], practical_path: Path, zpaq_path: Path
) -> dict[str, Any]:
    source, frozen = config["source_run"], config["e1_fixed_reference"]
    documents = {}
    for key, path, binding in (
        ("practical", practical_path, source["e1_practical_json_artifact"]),
        ("zpaq", zpaq_path, source["e1_zpaq_json_artifact"]),
    ):
        if sha256_file(path) != binding["result_sha256"]:
            raise ValueError(f"E1 {key} raw result differs")
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
            raise ValueError(f"E1 {key} identity differs")
        documents[key] = document
    practical = {}
    for codec_id in ("kanzi-max", "zstd-19-long", "xz-lzma2-9e"):
        trials = [
            row
            for row in documents["practical"]["trials"]
            if row["codec_id"] == codec_id
        ]
        if len(trials) != 3 or not all(
            row["exact"] and row["deterministic"] for row in trials
        ):
            raise ValueError("E1 practical roster differs")
        practical[codec_id] = axe1o_size("json_logs", trials)
    zpaq_trials = documents["zpaq"]["trials"]
    if len(zpaq_trials) != 3 or not all(
        row["codec_id"] == "zpaq-5-m510" and row["exact"] and row["deterministic"]
        for row in zpaq_trials
    ):
        raise ValueError("E1 ZPAQ roster differs")
    zpaq_total = axe1o_size("json_logs", zpaq_trials)
    if (
        min(practical.values()) != frozen["kanzi_complete_bytes"]
        or practical["kanzi-max"] != frozen["kanzi_complete_bytes"]
    ):
        raise ValueError("E1 Kanzi total differs")
    if zpaq_total != frozen["zpaq_510_complete_bytes"]:
        raise ValueError("E1 ZPAQ total differs")
    return {
        "practical_complete_bytes": practical,
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


def verify_file_row(row: dict[str, Any], root: Path) -> Path:
    require_keys(row, {"path", "bytes", "sha256"}, "file receipt")
    path_text = row["path"]
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts or path_text != path.as_posix():
        raise ValueError(f"unsafe result path: {path_text}")
    resolved = root / path
    ordinary(resolved)
    if (
        resolved.stat().st_size != row["bytes"]
        or sha256_file(resolved) != row["sha256"]
    ):
        raise ValueError(f"bound file differs: {path_text}")
    return resolved


def verify_trial(
    trial: dict[str, Any],
    *,
    config: dict[str, Any],
    item: dict[str, Any],
    method: dict[str, Any],
    result_root: Path,
    zpaq: Path,
) -> None:
    require_keys(
        trial,
        {
            "stage",
            "method_id",
            "method",
            "item_id",
            "repetition",
            "source_bytes",
            "source_sha256",
            "archive",
            "compress",
            "decompress",
            "restored_bytes",
            "restored_sha256",
            "exact",
        },
        "trial",
    )
    if (
        trial["method"] != method["method"]
        or trial["source_bytes"] != item["bytes"]
        or trial["source_sha256"] != item["sha256"]
    ):
        raise ValueError("trial frozen identity differs")
    verify_file_row(trial["archive"], result_root)
    expected_base = (
        f"{trial['stage']}/{trial['method_id']}/{trial['item_id']}"
        f"/r{trial['repetition']}"
    )
    if trial["archive"]["path"] != f"archives/{expected_base}/artifact.zpaq":
        raise ValueError("archive path differs")
    for phase in ("compress", "decompress"):
        process = trial[phase]
        require_keys(
            process,
            {
                "command",
                "declared_command",
                "wall_ns",
                "cpu_user_ns",
                "cpu_system_ns",
                "peak_rss_bytes",
                "exit_status",
                "timed_out",
                "output_exceeded",
                "stdout",
                "stderr",
            },
            f"{phase} process",
        )
        if (
            process["exit_status"] != 0
            or process["timed_out"]
            or process["output_exceeded"]
        ):
            raise ValueError(f"unsuccessful {phase} receipt")
        if (
            not isinstance(process["peak_rss_bytes"], int)
            or process["peak_rss_bytes"] <= 0
        ):
            raise ValueError(f"invalid {phase} RSS")
        if not isinstance(process["wall_ns"], int) or process["wall_ns"] <= 0:
            raise ValueError(f"invalid {phase} time")
        verify_file_row(process["stdout"], result_root)
        verify_file_row(process["stderr"], result_root)
        if process["declared_command"] != config["command"][phase]:
            raise ValueError(f"{phase} declared command differs")
        if process["stdout"]["path"] != f"logs/{expected_base}/{phase}.stdout":
            raise ValueError(f"{phase} stdout path differs")
        if process["stderr"]["path"] != f"logs/{expected_base}/{phase}.stderr":
            raise ValueError(f"{phase} stderr path differs")
    compress = trial["compress"]["command"]
    if (
        Path(compress[0]).name != "zpaq"
        or compress[1] != "add"
        or not Path(compress[2]).as_posix().endswith(trial["archive"]["path"])
        or compress[3:]
        != [
            "input.bin",
            "-method",
            method["method"],
            "-threads",
            "1",
            "-noattributes",
            "-until",
            "20000101000000",
        ]
    ):
        raise ValueError("compression command differs")
    decompress = trial["decompress"]["command"]
    if (
        Path(decompress[0]).name != "zpaq"
        or decompress[1] != "extract"
        or decompress[2] != compress[2]
        or decompress[3] != "input.bin"
        or decompress[4] != "-to"
        or Path(decompress[5]).name != "input.bin"
        or decompress[6:] != ["-force", "-threads", "1", "-noattributes"]
    ):
        raise ValueError("decompression command differs")
    if (
        trial["restored_bytes"] != item["bytes"]
        or trial["restored_sha256"] != item["sha256"]
        or not trial["exact"]
    ):
        raise ValueError("trial exactness differs")


def recheck_decode(
    trial: dict[str, Any], *, item: dict[str, Any], result_root: Path, zpaq: Path
) -> None:
    archive = result_root / trial["archive"]["path"]
    with tempfile.TemporaryDirectory(prefix="axiom-e2a-verify-") as raw:
        destination = Path(raw) / "input.bin"
        subprocess.run(
            [
                str(zpaq),
                "extract",
                str(archive),
                "input.bin",
                "-to",
                str(destination),
                "-force",
                "-threads",
                "1",
                "-noattributes",
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=21600,
        )
        restored = destination
        ordinary(restored)
        if (
            restored.stat().st_size != item["bytes"]
            or sha256_file(restored) != item["sha256"]
        ):
            raise ValueError("independent archive decode differs")


def verify(
    config_path: Path,
    result_path: Path,
    training_root: Path,
    tool_root: Path,
    e1_practical_result: Path,
    e1_zpaq_result: Path,
    expected_repository_commit: str,
    recheck_decodes: bool,
) -> dict[str, Any]:
    config, result = read_json(config_path), read_json(result_path)
    result_root = result_path.parent
    require_keys(result, set(config["required_result_sections"]), "top-level result")
    if (
        not result["completed"]
        or result["name"] != config["name"]
        or result["claim_ceiling"] != config["claim_ceiling"]
        or result["repository_commit"] != expected_repository_commit
    ):
        raise ValueError("result identity differs")
    if result["config_sha256"] != sha256_file(config_path) or result[
        "protocol_sha256"
    ] != sha256_file(PROTOCOL):
        raise ValueError("protocol binding differs")
    if result["runner_sha256"] != sha256_file(RUNNER) or result[
        "verifier_sha256"
    ] != sha256_file(Path(__file__)):
        raise ValueError("executable binding differs")
    if (
        result["source_bindings"] != config["source_run"]
        or result["information_boundary"] != config["information_boundary"]
    ):
        raise ValueError("source or information boundary differs")
    e1_reference = recompute_e1_reference(config, e1_practical_result, e1_zpaq_result)
    if (
        sha256_file(training_root / "manifest.json")
        != config["source_run"]["training_manifest_sha256"]
    ):
        raise ValueError("training manifest differs")
    if (
        sha256_file(tool_root / "receipt.json")
        != config["source_run"]["tool_receipt_sha256"]
    ):
        raise ValueError("tool receipt differs")
    zpaq = (tool_root / "bin" / "zpaq").resolve()
    ordinary(zpaq)
    if sha256_file(zpaq) != config["source_run"]["zpaq_binary_sha256"]:
        raise ValueError("ZPAQ binary differs")
    item_by_id = {row["id"]: row for row in config["items"]}
    method_by_id = {row["id"]: row for row in config["methods"]}
    if result["item_verification"] != sorted(
        config["items"], key=lambda row: row["id"]
    ):
        raise ValueError("verified item roster differs")
    for item in config["items"]:
        source = training_root / item["path"]
        ordinary(source)
        if (
            source.stat().st_size != item["bytes"]
            or sha256_file(source) != item["sha256"]
        ):
            raise ValueError("allowed source bytes differ")
    manifest_rows = result["file_manifest"]
    if len({row["path"] for row in manifest_rows}) != len(manifest_rows):
        raise ValueError("duplicate file manifest path")
    result_members = list(result_root.rglob("*"))
    if any(path.is_symlink() for path in result_members):
        raise ValueError("result directory contains a symlink")
    expected_files = sorted(
        path.relative_to(result_root).as_posix()
        for path in result_members
        if path.is_file() and path.name != "result.json"
    )
    if sorted(row["path"] for row in manifest_rows) != expected_files:
        raise ValueError("result directory roster differs")
    for row in manifest_rows:
        verify_file_row(row, result_root)
    stage_one = result["stage_one_trials"]
    if len(stage_one) != len(config["items"]) * len(config["methods"]):
        raise ValueError("stage-one trial count differs")
    seen = set()
    for trial in stage_one:
        key = (
            trial["method_id"],
            trial["item_id"],
            trial["repetition"],
            trial["stage"],
        )
        if key in seen or trial["repetition"] != 1 or trial["stage"] != "stage_one":
            raise ValueError("stage-one schedule differs")
        seen.add(key)
        verify_trial(
            trial,
            config=config,
            item=item_by_id[trial["item_id"]],
            method=method_by_id[trial["method_id"]],
            result_root=result_root,
            zpaq=zpaq,
        )
        if recheck_decodes:
            recheck_decode(
                trial,
                item=item_by_id[trial["item_id"]],
                result_root=result_root,
                zpaq=zpaq,
            )
    limits = config["measurement"]
    baseline = config["e1_fixed_reference"]["kanzi_complete_bytes"]
    summaries = []
    for method in config["methods"]:
        trials = [row for row in stage_one if row["method_id"] == method["id"]]
        data = build_axe2o(
            "json_logs",
            config["source_run"]["training_manifest_sha256"],
            method["id"],
            trials,
            result_root,
        )
        container = result_root / "containers" / f"{method['id']}-r1.axe2o"
        ordinary(container)
        if container.read_bytes() != data:
            raise ValueError("AXE2O container differs")
        container_row = {
            "path": container.relative_to(result_root).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        compression_rss = max(row["compress"]["peak_rss_bytes"] for row in trials)
        decompression_rss = max(row["decompress"]["peak_rss_bytes"] for row in trials)
        summaries.append(
            {
                "method_id": method["id"],
                "maximum_block_mib": method["maximum_block_mib"],
                "complete_container": container_row,
                "gain_vs_e1_kanzi_basis_points": (baseline - len(data))
                * 10000
                // baseline,
                "maximum_compression_peak_rss_bytes": compression_rss,
                "maximum_decompression_peak_rss_bytes": decompression_rss,
                "eligible": compression_rss
                <= limits["maximum_compression_peak_rss_bytes"]
                and decompression_rss <= limits["maximum_decompression_peak_rss_bytes"],
                "fragile": max(compression_rss, decompression_rss)
                >= config["decision_gates"]["fragile_peak_rss_bytes"],
                "exact": True,
            }
        )
    if result["method_summaries"] != summaries:
        raise ValueError("method summaries differ")
    eligible = sorted(
        (row for row in summaries if row["eligible"]),
        key=lambda row: (row["complete_container"]["bytes"], row["method_id"]),
    )
    selected = [] if not eligible else [eligible[0]["method_id"]]
    if "zpaq-5-m510" not in selected:
        selected.append("zpaq-5-m510")
    if result["selected_methods"] != selected:
        raise ValueError("confirmation selection differs")
    confirmation = result["confirmation_trials"]
    if len(confirmation) != len(selected) * len(config["items"]):
        raise ValueError("confirmation trial count differs")
    confirmation_passed = True
    confirmation_seen = {
        (row["method_id"], row["item_id"], row["repetition"], row["stage"])
        for row in confirmation
    }
    confirmation_expected = {
        (method_id, item_id, 2, "confirmation")
        for method_id in selected
        for item_id in item_by_id
    }
    if confirmation_seen != confirmation_expected or len(confirmation_seen) != len(
        confirmation
    ):
        raise ValueError("confirmation schedule differs")
    for method_id in selected:
        first = sorted(
            (row for row in stage_one if row["method_id"] == method_id),
            key=lambda row: row["item_id"],
        )
        second = sorted(
            (row for row in confirmation if row["method_id"] == method_id),
            key=lambda row: row["item_id"],
        )
        if len(second) != 3:
            raise ValueError("confirmation roster differs")
        for trial in second:
            if trial["stage"] != "confirmation" or trial["repetition"] != 2:
                raise ValueError("confirmation schedule differs")
            verify_trial(
                trial,
                config=config,
                item=item_by_id[trial["item_id"]],
                method=method_by_id[method_id],
                result_root=result_root,
                zpaq=zpaq,
            )
        confirmation_passed &= all(
            a["archive"]["sha256"] == b["archive"]["sha256"]
            for a, b in zip(first, second, strict=True)
        )
        data = build_axe2o(
            "json_logs",
            config["source_run"]["training_manifest_sha256"],
            method_id,
            second,
            result_root,
        )
        container = result_root / "containers" / f"{method_id}-r2.axe2o"
        ordinary(container)
        if container.read_bytes() != data:
            raise ValueError("confirmation AXE2O differs")
        expected_row = {
            "path": container.relative_to(result_root).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if result["confirmation_containers"][method_id] != expected_row:
            raise ValueError("confirmation container receipt differs")
        confirmation_passed &= (
            result["confirmation_containers"][method_id]["sha256"]
            == next(row for row in summaries if row["method_id"] == method_id)[
                "complete_container"
            ]["sha256"]
        )
    best = eligible[0] if eligible else None
    if best is not None:
        bounded_confirmation = [
            row for row in confirmation if row["method_id"] == best["method_id"]
        ]
        confirmation_passed &= (
            max(row["compress"]["peak_rss_bytes"] for row in bounded_confirmation)
            <= limits["maximum_compression_peak_rss_bytes"]
        )
        confirmation_passed &= (
            max(row["decompress"]["peak_rss_bytes"] for row in bounded_confirmation)
            <= limits["maximum_decompression_peak_rss_bytes"]
        )
    gates = config["decision_gates"]
    e1_by_item = {row["item_id"]: row for row in e1_reference["zpaq_510_per_item"]}
    observed_anchor = {
        row["item_id"]: row for row in stage_one if row["method_id"] == "zpaq-5-m510"
    }
    anchor_matched = set(e1_by_item) == set(observed_anchor) and all(
        observed_anchor[item_id]["archive"]["bytes"]
        == e1_by_item[item_id]["artifact_bytes"]
        and observed_anchor[item_id]["archive"]["sha256"]
        == e1_by_item[item_id]["artifact_sha256"]
        for item_id in e1_by_item
    )
    expected_reference = {**e1_reference, "anchor_matched": anchor_matched}
    if result["e1_reference"] != expected_reference:
        raise ValueError("E1 reference or anchor differs")
    if not anchor_matched:
        outcome = "refuse_e1_anchor_mismatch"
    elif not confirmation_passed:
        outcome = "fail_confirmation"
    elif (
        best is None
        or best["complete_container"]["bytes"]
        >= gates["kill_when_complete_bytes_at_least"]
    ):
        outcome = "kill_bounded_level5_lane"
    elif best["complete_container"]["bytes"] <= gates["advance_maximum_complete_bytes"]:
        outcome = "advance_component_attribution"
    else:
        outcome = "permit_one_frozen_refinement"
    expected_decision = {
        "outcome": outcome,
        "best_eligible_method": None if best is None else best["method_id"],
        "best_eligible_complete_bytes": None
        if best is None
        else best["complete_container"]["bytes"],
        "best_eligible_gain_basis_points": None
        if best is None
        else best["gain_vs_e1_kanzi_basis_points"],
        "confirmation_passed": confirmation_passed,
    }
    if result["decision"] != expected_decision:
        raise ValueError("decision differs")
    return expected_decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, required=True)
    parser.add_argument("--e1-practical-result", type=Path, required=True)
    parser.add_argument("--e1-zpaq-result", type=Path, required=True)
    parser.add_argument("--expected-repository-commit", required=True)
    parser.add_argument("--recheck-decodes", action="store_true")
    args = parser.parse_args()
    try:
        decision = verify(
            args.config,
            args.result,
            args.training_root,
            args.tool_root,
            args.e1_practical_result,
            args.e1_zpaq_result,
            args.expected_repository_commit,
            args.recheck_decodes,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E2-A verification failed: {error}") from error
    print(json.dumps({"verified": True, "decision": decision}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
