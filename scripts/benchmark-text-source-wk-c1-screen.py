#!/usr/bin/env python3
"""Run the frozen WK-C1 training-only screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import signal
import struct
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Any

try:
    import resource as RESOURCE
except ImportError:  # pragma: no cover - Windows does not expose resource
    RESOURCE = None  # type: ignore[assignment]


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-wk-c1-screen-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_BASELINE_EVIDENCE = (
    REPOSITORY
    / "runs"
    / "text-source-development-baseline-census-v1"
    / "publication"
    / "evidence.json"
)
DEFAULT_KANZI = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
DEFAULT_TRANSFORM = REPOSITORY / "scripts" / "text-source-wk-c1-transform.py"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-wk-c1-screen-v1"
DEFAULT_STRUCTURAL_RESULT = (
    REPOSITORY
    / "runs"
    / "text-source-structural-transform-development-v1"
    / "results.json"
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
DEFAULT_SUCCESSOR_ROUTING = (
    REPOSITORY / "config" / "text-source-successor-routing-v1.json"
)
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
write_json_atomic = COMMON.BASELINE_RUNNER.write_json_atomic
sanitize_process = COMMON.sanitize_process


def _set_process_memory_limit(max_address_bytes: int) -> None:
    """Apply the hard address-space cap where the platform supports it."""
    if RESOURCE is None or sys.platform == "darwin":
        return
    RESOURCE.setrlimit(RESOURCE.RLIMIT_AS, (max_address_bytes, max_address_bytes))


def run_process(
    command: list[str],
    *,
    stdout_path: Path | None,
    timeout_seconds: float,
    max_address_bytes: int,
) -> dict[str, Any]:
    """Run one bounded process in its own session and retain wait4 telemetry.

    Linux and other POSIX platforms with ``resource.RLIMIT_AS`` enforce the
    address-space bound before exec. Darwin cannot safely lower RLIMIT_AS for
    an already-large inherited virtual address space, so macOS explicitly uses
    measured wait4 peak RSS and the caller's fail-closed 4 GiB gate instead.
    Platforms without wait4 are not valid measurement runners.
    """
    if not hasattr(os, "wait4"):
        raise RuntimeError("WK-C1 measurement requires POSIX wait4 telemetry")
    if sys.platform != "darwin" and RESOURCE is None:
        raise RuntimeError("WK-C1 measurement requires POSIX resource-limit support")
    if timeout_seconds <= 0 or max_address_bytes <= 0:
        raise ValueError("WK-C1 process limits must be positive")
    environment = dict(os.environ)
    environment.update(
        {
            "LC_ALL": "C",
            "TZ": "UTC",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
    )
    stdout_file = (
        stdout_path.open("wb") if stdout_path is not None else tempfile.TemporaryFile()
    )
    stderr_file = tempfile.TemporaryFile()
    started = time.perf_counter_ns()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
            preexec_fn=lambda: _set_process_memory_limit(max_address_bytes),
        )
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        while True:
            pid, wait_status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid == process.pid:
                break
            if time.monotonic() >= deadline:
                os.killpg(process.pid, signal.SIGKILL)
                _, wait_status, usage = os.wait4(process.pid, 0)
                timed_out = True
                break
            time.sleep(0.05)
        process.returncode = os.waitstatus_to_exitcode(wait_status)
        peak_rss_bytes = int(usage.ru_maxrss)
        if sys.platform != "darwin":
            peak_rss_bytes *= 1024
        stderr_file.seek(0)
        stderr = stderr_file.read(16384).decode("utf-8", errors="replace")
        if stdout_path is None:
            stdout_file.seek(0)
            stdout = stdout_file.read(16384).decode("utf-8", errors="replace")
        else:
            stdout = "<artifact>"
        return {
            "command": command,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": int((usage.ru_utime + usage.ru_stime) * 1_000_000_000),
            "peak_rss_bytes": peak_rss_bytes,
            "stdout": stdout,
            "stderr": stderr,
        }
    except BaseException:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        raise
    finally:
        stdout_file.close()
        stderr_file.close()


def validate_config(config: dict[str, Any]) -> None:
    expected_bindings = {
        "baseline_public_evidence_sha256": "b28429e3d12542eda21d03d981b9452cba2d4a329252e4876803b62852f1299f",
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
        or [
            (row.get("id"), row.get("columnarize_values"))
            for row in config.get("variants", [])
        ]
        != expected_variants
        or config.get("measurement", {}).get("jobs") != 1
        or config.get("measurement", {}).get("measured_repetitions") != 2
        or config.get("measurement", {}).get("order_seed") != 20260718
        or config.get("measurement", {}).get("timeout_seconds_per_process") != 43200
        or config.get("measurement", {}).get("warmups") != 0
        or config.get("measurement", {}).get("process_memory_limit")
        != {
            "address_space_limit_bytes": 4 * 1024**3,
            "darwin_behavior": "RLIMIT_AS is not lowered; wait4 peak RSS is measured and the same 4 GiB gate fails closed",
            "posix_behavior": "RLIMIT_AS is set before exec and wait4 peak RSS is also measured",
            "unsupported_behavior": "measurement is refused without POSIX wait4 telemetry or resource-limit support",
        }
        or config.get("measurement", {}).get("premeasurement_resource_smoke")
        != {
            "authorized_items_only": list(SCREEN_ITEMS),
            "maximum_peak_rss_bytes": 4 * 1024**3,
            "required_before_candidate_trials": True,
            "backend_encode_and_decode_each_variant": True,
            "transform_encode_and_decode_each_variant": True,
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
    if (
        set(rows) != expected_ids
        or manifest.get("public_validation_accessed") is not False
    ):
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
    baseline_evidence: Path,
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
        "baseline_public_evidence_sha256": baseline_evidence,
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
    _baseline_evidence_raw, baseline_public = read_canonical(baseline_evidence)
    _structural_raw, structural_public = read_canonical(structural_evidence)
    _bwt_raw, bwt_public = read_canonical(bwt_evidence)
    _decision_raw, decision = read_canonical(successor_decision)
    if (
        baseline_public.get("raw_results_sha256") != bindings["baseline_results_sha256"]
        or baseline_public.get("results") != baseline_result
    ):
        raise ValueError("WK-C1 raw census public-evidence provenance differs")
    if (
        baseline_result.get("completed") is not True
        or baseline_result.get("all_required_completed") is not True
        or structural_public.get("structural_results_sha256")
        != bindings["structural_results_sha256"]
        or bwt_public.get("result_sha256") != bindings["bwt_result_sha256"]
        or bwt_public.get("results", {}).get("summary", {}).get("axiom_wins") != 0
        or any(
            row.get("decision") != "reject_raw_bwt_direction_for_track"
            for row in bwt_public.get("results", {})
            .get("summary", {})
            .get("tracks", [])
        )
        or decision.get("name") != "text-source-structural-successor-decision-v1"
        or any(
            row.get("axiom_win") is not False for row in decision.get("decisions", [])
        )
    ):
        raise ValueError("WK-C1 dependency evidence differs")
    structural_rows = {
        row["item_id"]: row["candidate_bytes"]
        for row in structural_public["results"]["summary"]["item_rows"]
        if row.get("variant") == "ts-h1-demux" and row.get("item_id") in SCREEN_ITEMS
    }
    if structural_rows != config["ts_h1_controls"]:
        raise ValueError("WK-C1 two-item TS-H1 control differs")
    baseline_rows = {
        row["item_id"]: row
        for row in baseline_public["results"]["summary"]["item_codec_rows"]
        if row.get("codec_id") == "kanzi-max" and row.get("item_id") in SCREEN_ITEMS
    }
    expected_bytes = {
        "enwikibooks-20260701": 12622786,
        "enwikinews-20260701": 11534002,
    }
    aggregate_bytes = sum(row["artifact_bytes"] for row in baseline_rows.values())
    gate = config["decision"]["track_gate"]
    item_regression_basis_points = int(gate["maximum_item_regression_percent"] * 100)
    derived_item_guards = {
        item_id: complete_bytes * (10_000 + item_regression_basis_points) // 10_000
        for item_id, complete_bytes in expected_bytes.items()
    }
    if (
        set(baseline_rows) != set(SCREEN_ITEMS)
        or any(
            baseline_rows[item_id].get("artifact_bytes") != complete_bytes
            or baseline_rows[item_id].get("passed") is not True
            or baseline_rows[item_id].get("exact_roundtrip") is not True
            or baseline_rows[item_id].get("deterministic_artifact") is not True
            for item_id, complete_bytes in expected_bytes.items()
        )
        or aggregate_bytes != gate["kanzi_max_complete_bytes"]
        or gate["item_maximum_complete_bytes"] != derived_item_guards
        or gate["signal_maximum_complete_bytes"]
        != aggregate_bytes * (10_000 - int(gate["signal_percent"] * 100)) // 10_000
        or gate["strong_maximum_complete_bytes"]
        != aggregate_bytes * (10_000 - int(gate["strong_percent"] * 100)) // 10_000
    ):
        raise ValueError(
            "WK-C1 Kanzi-max control does not reconstruct from census evidence"
        )


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


def repository_commit() -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("WK-C1 screen requires a completely clean commit")
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ValueError("WK-C1 repository commit identity is invalid")
    return commit


def aggregate_processes(processes: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "wall_ns": sum(row["wall_ns"] for row in processes),
        "cpu_ns": sum(row["cpu_ns"] for row in processes),
        "peak_rss_bytes": max((row["peak_rss_bytes"] for row in processes), default=0),
    }


def process_succeeded(process: dict[str, Any]) -> bool:
    return process["returncode"] == 0 and process["timed_out"] is False


def validate_process_record(process: object) -> None:
    if (
        not isinstance(process, dict)
        or set(process)
        != {
            "command",
            "returncode",
            "timed_out",
            "wall_ns",
            "cpu_ns",
            "peak_rss_bytes",
            "stdout",
            "stderr",
        }
        or not isinstance(process.get("command"), list)
        or not all(isinstance(value, str) for value in process["command"])
        or type(process.get("returncode")) is not int
        or not isinstance(process.get("timed_out"), bool)
        or type(process.get("wall_ns")) is not int
        or process["wall_ns"] <= 0
        or type(process.get("cpu_ns")) is not int
        or process["cpu_ns"] < 0
        or type(process.get("peak_rss_bytes")) is not int
        or process["peak_rss_bytes"] < 0
        or not isinstance(process.get("stdout"), str)
        or not isinstance(process.get("stderr"), str)
    ):
        raise ValueError("WK-C1 process record differs")


def run_command_chain(
    commands_to_run: list[list[str]],
    *,
    work: Path,
    timeout_seconds: float,
    max_address_bytes: int,
) -> tuple[list[dict[str, Any]], str | None]:
    records = []
    error = None
    for index, command in enumerate(commands_to_run):
        process = run_process(
            command,
            stdout_path=None,
            timeout_seconds=timeout_seconds,
            max_address_bytes=max_address_bytes,
        )
        records.append(sanitize_process(process, work))
        if process["timed_out"]:
            error = f"process {index} timed out"
            break
        if process["returncode"] != 0:
            error = f"process {index} exited {process['returncode']}"
            break
    return records, error


def resource_smoke(
    *,
    items: list[dict[str, Any]],
    config: dict[str, Any],
    transform: Path,
    kanzi: Path,
) -> list[dict[str, Any]]:
    policy = config["measurement"]["premeasurement_resource_smoke"]
    if [item["id"] for item in items] != policy["authorized_items_only"]:
        raise ValueError("WK-C1 resource smoke item roster differs")
    timeout = config["measurement"]["timeout_seconds_per_process"]
    maximum_rss = policy["maximum_peak_rss_bytes"]
    max_address_bytes = config["measurement"]["process_memory_limit"][
        "address_space_limit_bytes"
    ]
    rows = []
    for variant in VARIANTS:
        for item in items:
            with tempfile.TemporaryDirectory(prefix="wk-c1-smoke-") as raw:
                work = Path(raw)
                transformed = work / "transform.wkc1"
                payload = work / "payload.knz"
                decoded_transform = work / "decoded.wkc1"
                restored = work / "restored.bin"
                encode_command = [
                    sys.executable,
                    str(transform),
                    "encode",
                    variant,
                    item["path"],
                    str(transformed),
                ]
                encode_raw = run_process(
                    encode_command,
                    stdout_path=None,
                    timeout_seconds=timeout,
                    max_address_bytes=max_address_bytes,
                )
                encode = sanitize_process(encode_raw, work)
                backend_encode: dict[str, Any] | None = None
                backend_decode: dict[str, Any] | None = None
                decode: dict[str, Any] | None = None
                error = None
                if not process_succeeded(encode_raw):
                    error = "transform encode smoke failed or timed out"
                elif encode_raw["peak_rss_bytes"] > maximum_rss:
                    error = "transform encode smoke exceeded 4 GiB"
                elif not transformed.is_file():
                    error = "transform encode smoke produced no frame"
                else:
                    backend_encode_command = [
                        str(kanzi),
                        "--compress",
                        "--level=9",
                        "--block=1g",
                        "--jobs=1",
                        "--verbose=0",
                        "--force",
                        f"--input={transformed}",
                        f"--output={payload}",
                    ]
                    backend_encode_raw = run_process(
                        backend_encode_command,
                        stdout_path=None,
                        timeout_seconds=timeout,
                        max_address_bytes=max_address_bytes,
                    )
                    backend_encode = sanitize_process(backend_encode_raw, work)
                    if not process_succeeded(backend_encode_raw):
                        error = "Kanzi encode smoke failed or timed out"
                    elif backend_encode_raw["peak_rss_bytes"] > maximum_rss:
                        error = "Kanzi encode smoke exceeded 4 GiB"
                    elif not payload.is_file():
                        error = "Kanzi encode smoke produced no payload"
                if error is None:
                    backend_decode_command = [
                        str(kanzi),
                        "--decompress",
                        "--jobs=1",
                        "--verbose=0",
                        "--force",
                        f"--input={payload}",
                        f"--output={decoded_transform}",
                    ]
                    backend_decode_raw = run_process(
                        backend_decode_command,
                        stdout_path=None,
                        timeout_seconds=timeout,
                        max_address_bytes=max_address_bytes,
                    )
                    backend_decode = sanitize_process(backend_decode_raw, work)
                    if not process_succeeded(backend_decode_raw):
                        error = "Kanzi decode smoke failed or timed out"
                    elif backend_decode_raw["peak_rss_bytes"] > maximum_rss:
                        error = "Kanzi decode smoke exceeded 4 GiB"
                    elif not decoded_transform.is_file():
                        error = "Kanzi decode smoke produced no transform"
                    elif sha256_file(decoded_transform) != sha256_file(transformed):
                        error = "Kanzi smoke restored transform differs"
                if error is None:
                    decode_command = [
                        sys.executable,
                        str(transform),
                        "decode",
                        str(decoded_transform),
                        str(restored),
                        "--maximum-size",
                        str(item["source_bytes"]),
                    ]
                    decode_raw = run_process(
                        decode_command,
                        stdout_path=None,
                        timeout_seconds=timeout,
                        max_address_bytes=max_address_bytes,
                    )
                    decode = sanitize_process(decode_raw, work)
                    if not process_succeeded(decode_raw):
                        error = "transform decode smoke failed or timed out"
                    elif decode_raw["peak_rss_bytes"] > maximum_rss:
                        error = "transform decode smoke exceeded 4 GiB"
                    elif not restored.is_file():
                        error = "transform decode smoke produced no output"
                    elif restored.stat().st_size != item["source_bytes"]:
                        error = "transform smoke restored size differs"
                    elif sha256_file(restored) != item["source_sha256"]:
                        error = "transform smoke restored digest differs"
                row = {
                    "variant": variant,
                    "item_id": item["id"],
                    "source_bytes": item["source_bytes"],
                    "source_sha256": item["source_sha256"],
                    "transform_file_evidence": (
                        {
                            "size_bytes": transformed.stat().st_size,
                            "sha256": sha256_file(transformed),
                        }
                        if transformed.is_file()
                        else None
                    ),
                    "encode": encode,
                    "backend_encode": backend_encode,
                    "backend_decode": backend_decode,
                    "decode": decode,
                    "maximum_peak_rss_bytes": max(
                        row["peak_rss_bytes"]
                        for row in (encode, backend_encode, backend_decode, decode)
                        if row is not None
                    ),
                    "exact_roundtrip": not error,
                    "passed": not error,
                    "error": error,
                }
                rows.append(row)
                if error:
                    raise ValueError(
                        f"WK-C1 premeasurement resource smoke failed: {error}"
                    )
    return rows


def trial_path(output: Path, variant: str, item_id: str, repetition: int) -> Path:
    return output / "trials" / variant / f"{item_id}.r{repetition}.json"


def receipt_manifest(output: Path, paths: list[Path]) -> str:
    payload = {
        "trials": [
            {
                "path": path.relative_to(output).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in sorted(paths)
        ]
    }
    return sha256_bytes(json_bytes(payload))


def validate_trial_receipt(
    receipt: dict[str, Any],
    *,
    bindings: dict[str, Any],
    variant: str,
    item: dict[str, Any],
    repetition: int,
) -> None:
    if (
        receipt.get("schema_version") != 1
        or receipt.get("bindings") != bindings
        or receipt.get("variant") != variant
        or receipt.get("item_id") != item["id"]
        or receipt.get("track") != "english_wikimedia_wikitext"
        or receipt.get("repetition") != repetition
        or receipt.get("source_bytes") != item["source_bytes"]
        or receipt.get("source_sha256") != item["source_sha256"]
        or not isinstance(receipt.get("encode_processes"), list)
        or not isinstance(receipt.get("decode_processes"), list)
    ):
        raise ValueError("WK-C1 retained trial identity differs")
    encode_processes = receipt["encode_processes"]
    decode_processes = receipt["decode_processes"]
    for process in [*encode_processes, *decode_processes]:
        validate_process_record(process)
    if receipt.get("encode_totals") != aggregate_processes(encode_processes):
        raise ValueError("WK-C1 aggregate encode metrics differ")
    if receipt.get("decode_totals") != aggregate_processes(decode_processes):
        raise ValueError("WK-C1 aggregate decode metrics differ")
    if (
        receipt.get("encode_peak_rss_bytes")
        != receipt["encode_totals"]["peak_rss_bytes"]
    ):
        raise ValueError(
            "WK-C1 aggregate encode RSS differs from primary process peaks"
        )
    if (
        receipt.get("decode_peak_rss_bytes")
        != receipt["decode_totals"]["peak_rss_bytes"]
    ):
        raise ValueError(
            "WK-C1 aggregate decode RSS differs from primary process peaks"
        )
    artifact = receipt.get("artifact_file_evidence")
    transform = receipt.get("transform_file_evidence")
    if receipt.get("passed") is True:
        if (
            len(encode_processes) != 3
            or len(decode_processes) != 3
            or not all(
                process_succeeded(row) for row in [*encode_processes, *decode_processes]
            )
            or receipt.get("exact_roundtrip") is not True
            or receipt.get("error") is not None
            or not isinstance(artifact, dict)
            or receipt.get("artifact_bytes") != artifact.get("size_bytes")
            or receipt.get("artifact_sha256") != artifact.get("sha256")
            or receipt.get("artifact_bytes", 0) <= FRAME_HEADER.size
            or not isinstance(artifact.get("sha256"), str)
            or len(artifact["sha256"]) != 64
            or not isinstance(transform, dict)
            or transform.get("variant") != variant
            or transform.get("complete_transform_bytes")
            != transform.get("header_bytes", 0)
            + transform.get("metadata_bytes", 0)
            + transform.get("value_stream_bytes", 0)
            or not isinstance(transform.get("sha256"), str)
            or len(transform["sha256"]) != 64
        ):
            raise ValueError("WK-C1 successful retained trial differs")
    elif receipt.get("passed") is not False or not isinstance(
        receipt.get("error"), str
    ):
        raise ValueError("WK-C1 failed retained trial differs")


def run_trial(
    *,
    output: Path,
    bindings: dict[str, Any],
    item: dict[str, Any],
    variant: str,
    repetition: int,
    transform: Path,
    kanzi: Path,
    timeout_seconds: float,
    max_address_bytes: int,
) -> dict[str, Any]:
    destination = trial_path(output, variant, item["id"], repetition)
    if destination.exists():
        _raw, retained = read_canonical(destination)
        validate_trial_receipt(
            retained,
            bindings=bindings,
            variant=variant,
            item=item,
            repetition=repetition,
        )
        return retained
    with tempfile.TemporaryDirectory(prefix="wk-c1-trial-") as raw:
        work = Path(raw)
        transformed = work / "transform.wkc1"
        payload = work / "payload.knz"
        artifact = work / "artifact.axwk2"
        extracted = work / "extracted.knz"
        decoded_transform = work / "decoded.wkc1"
        restored = work / "restored.bin"
        encode_commands, decode_commands = commands(
            python=sys.executable,
            runner=Path(__file__).resolve(),
            transform=transform,
            kanzi=kanzi,
            variant=variant,
            source=Path(item["path"]),
            transformed=transformed,
            payload=payload,
            artifact=artifact,
            extracted=extracted,
            decoded_transform=decoded_transform,
            restored=restored,
            source_bytes=item["source_bytes"],
            source_sha256=item["source_sha256"],
        )
        encode_processes, error = run_command_chain(
            encode_commands,
            work=work,
            timeout_seconds=timeout_seconds,
            max_address_bytes=max_address_bytes,
        )
        artifact_evidence = (
            {"size_bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)}
            if artifact.is_file()
            else None
        )
        transform_evidence = (
            {
                **TRANSFORM.inspect_frame(transformed.read_bytes()),
                "sha256": sha256_file(transformed),
            }
            if transformed.is_file()
            else None
        )
        decode_processes: list[dict[str, Any]] = []
        if error is None:
            decode_processes, error = run_command_chain(
                decode_commands,
                work=work,
                timeout_seconds=timeout_seconds,
                max_address_bytes=max_address_bytes,
            )
        if error is None:
            if not restored.is_file():
                error = "inverse chain produced no restored source"
            elif restored.stat().st_size != item["source_bytes"]:
                error = "restored source size differs"
            elif sha256_file(restored) != item["source_sha256"]:
                error = "restored source digest differs"
        receipt = {
            "schema_version": 1,
            "bindings": bindings,
            "variant": variant,
            "item_id": item["id"],
            "track": "english_wikimedia_wikitext",
            "repetition": repetition,
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
            "transform_file_evidence": transform_evidence,
            "artifact_file_evidence": artifact_evidence,
            "artifact_bytes": artifact_evidence["size_bytes"]
            if artifact_evidence
            else None,
            "artifact_sha256": artifact_evidence["sha256"]
            if artifact_evidence
            else None,
            "encode_processes": encode_processes,
            "decode_processes": decode_processes,
            "encode_totals": aggregate_processes(encode_processes),
            "decode_totals": aggregate_processes(decode_processes),
            "encode_peak_rss_bytes": aggregate_processes(encode_processes)[
                "peak_rss_bytes"
            ],
            "decode_peak_rss_bytes": aggregate_processes(decode_processes)[
                "peak_rss_bytes"
            ],
            "exact_roundtrip": error is None,
            "passed": error is None,
            "error": error,
        }
        validate_trial_receipt(
            receipt,
            bindings=bindings,
            variant=variant,
            item=item,
            repetition=repetition,
        )
        write_json_atomic(destination, receipt)
        return receipt


def summarize(trials: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
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
                    max(
                        row.get("encode_peak_rss_bytes", 0),
                        row.get("decode_peak_rss_bytes", 0),
                    )
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
        artifact_bytes = (
            sum(row["artifact_bytes"] for row in selected) if complete else None
        )
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


def benchmark(
    *,
    config_path: Path,
    corpus: Path,
    baseline: Path,
    baseline_evidence: Path,
    kanzi: Path,
    transform: Path,
    structural_result: Path,
    structural_evidence: Path,
    successor_decision: Path,
    successor_routing: Path,
    bwt_result: Path,
    bwt_evidence: Path,
    bwt_receipt: Path,
    output: Path,
) -> Path:
    config_raw, config = read_canonical(config_path)
    validate_config(config)
    commit = repository_commit()
    manifest_raw, items = verify_screen_items(corpus, config)
    if sha256_bytes(manifest_raw) != config["bindings"]["corpus_manifest_sha256"]:
        raise ValueError("WK-C1 corpus manifest binding differs")
    verify_dependencies(
        config=config,
        baseline=baseline,
        baseline_evidence=baseline_evidence,
        kanzi=kanzi,
        structural_result=structural_result,
        structural_evidence=structural_evidence,
        successor_decision=successor_decision,
        successor_routing=successor_routing,
        bwt_result=bwt_result,
        bwt_evidence=bwt_evidence,
        bwt_receipt=bwt_receipt,
    )
    if not transform.is_file():
        raise ValueError("WK-C1 transform is unavailable")
    bindings = {
        "repository_commit": commit,
        "config_sha256": sha256_bytes(config_raw),
        "transform_sha256": sha256_file(transform),
        **config["bindings"],
    }
    preflight_rows = preflight()
    smoke_rows = resource_smoke(
        items=items, config=config, transform=transform, kanzi=kanzi
    )
    items_by_id = {item["id"]: item for item in items}
    trials = []
    for index, (variant, item_id, repetition) in enumerate(schedule(config), start=1):
        print(f"[{index}/8] r{repetition} {item_id} x {variant}", flush=True)
        trials.append(
            run_trial(
                output=output,
                bindings=bindings,
                item=items_by_id[item_id],
                variant=variant,
                repetition=repetition,
                transform=transform,
                kanzi=kanzi,
                timeout_seconds=config["measurement"]["timeout_seconds_per_process"],
                max_address_bytes=config["measurement"]["process_memory_limit"][
                    "address_space_limit_bytes"
                ],
            )
        )
    summary = summarize(trials, config)
    retained_paths = [
        trial_path(output, variant, item_id, repetition)
        for variant in VARIANTS
        for item_id in SCREEN_ITEMS
        for repetition in range(config["measurement"]["measured_repetitions"])
    ]
    result = {
        "schema_version": 1,
        "name": "text-source-wk-c1-recursive-template-columnarization-screen-result-v1",
        "completed": True,
        "all_required_completed": all(row["passed"] for row in trials),
        "trial_count": len(trials),
        "trial_receipts_manifest_sha256": receipt_manifest(output, retained_paths),
        "bindings": bindings,
        "screen_boundary": config["splits"],
        "measurement": config["measurement"],
        "preflight": preflight_rows,
        "premeasurement_resource_smoke": smoke_rows,
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
            raise ValueError("WK-C1 result differs from retained result")
    else:
        write_json_atomic(destination, result)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    run = subparsers.add_parser("run")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    run.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    run.add_argument(
        "--baseline-evidence", type=Path, default=DEFAULT_BASELINE_EVIDENCE
    )
    run.add_argument("--kanzi", type=Path, default=DEFAULT_KANZI)
    run.add_argument("--transform", type=Path, default=DEFAULT_TRANSFORM)
    run.add_argument(
        "--structural-result", type=Path, default=DEFAULT_STRUCTURAL_RESULT
    )
    run.add_argument(
        "--structural-evidence", type=Path, default=DEFAULT_STRUCTURAL_EVIDENCE
    )
    run.add_argument(
        "--successor-decision", type=Path, default=DEFAULT_SUCCESSOR_DECISION
    )
    run.add_argument(
        "--successor-routing", type=Path, default=DEFAULT_SUCCESSOR_ROUTING
    )
    run.add_argument("--bwt-result", type=Path, default=DEFAULT_BWT_RESULT)
    run.add_argument("--bwt-evidence", type=Path, default=DEFAULT_BWT_EVIDENCE)
    run.add_argument("--bwt-receipt", type=Path, default=DEFAULT_BWT_RECEIPT)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
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
        if args.command == "run":
            print(
                benchmark(
                    config_path=args.config,
                    corpus=args.corpus,
                    baseline=args.baseline,
                    baseline_evidence=args.baseline_evidence,
                    kanzi=args.kanzi,
                    transform=args.transform,
                    structural_result=args.structural_result,
                    structural_evidence=args.structural_evidence,
                    successor_decision=args.successor_decision,
                    successor_routing=args.successor_routing,
                    bwt_result=args.bwt_result,
                    bwt_evidence=args.bwt_evidence,
                    bwt_receipt=args.bwt_receipt,
                    output=args.output,
                )
            )
        elif args.command == "preflight":
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
