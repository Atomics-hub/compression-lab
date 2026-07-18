#!/usr/bin/env python3
"""Run one host-scoped slice of the frozen text/source research ceiling."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-research-ceiling-v1"
CHUNK_SIZE = 1024 * 1024
PROCESS_KEYS = {
    "command",
    "returncode",
    "timed_out",
    "wall_ns",
    "cpu_ns",
    "peak_rss_bytes",
    "stdout",
    "stderr",
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load_script(
    "research_ceiling_planner_for_runner",
    REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py",
)
TOOLCHAIN = load_script(
    "research_ceiling_toolchain_for_runner",
    REPOSITORY / "scripts" / "validate-text-source-research-ceiling-toolchain.py",
)
BASELINE_RUNNER = load_script(
    "baseline_runner_for_research_ceiling",
    REPOSITORY / "scripts" / "benchmark-text-source-baselines.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PLANNER.json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = PLANNER.json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def sanitize_process(record: dict[str, Any], work: Path, tools_root: Path) -> dict[str, Any]:
    sanitized = dict(record)
    sanitized["command"] = [
        str(value)
        .replace(str(work), "$WORK")
        .replace(str(tools_root), "$TOOLCHAIN")
        for value in record["command"]
    ]
    return sanitized


def _set_limits(max_address_bytes: int | None, max_file_bytes: int | None) -> None:
    if max_address_bytes is not None:
        resource.setrlimit(resource.RLIMIT_AS, (max_address_bytes, max_address_bytes))
    if max_file_bytes is not None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_bytes, max_file_bytes))


def run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    max_address_bytes: int | None,
    max_file_bytes: int | None = None,
) -> dict[str, Any]:
    if not hasattr(os, "wait4"):
        raise RuntimeError("research runner requires wait4 peak-RSS accounting")
    if timeout_seconds <= 0:
        raise ValueError("process timeout must be positive")
    environment = dict(os.environ)
    environment.update(
        {
            "LC_ALL": "C",
            "TZ": "UTC",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
    )
    stdout_file = tempfile.TemporaryFile()
    stderr_file = tempfile.TemporaryFile()
    started = time.perf_counter_ns()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
            preexec_fn=lambda: _set_limits(max_address_bytes, max_file_bytes),
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
        stdout_file.seek(0)
        stderr_file.seek(0)
        return {
            "command": command,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": int((usage.ru_utime + usage.ru_stime) * 1_000_000_000),
            "peak_rss_bytes": peak_rss_bytes,
            "stdout": stdout_file.read(16384).decode("utf-8", errors="replace"),
            "stderr": stderr_file.read(16384).decode("utf-8", errors="replace"),
        }
    finally:
        stdout_file.close()
        stderr_file.close()


def resolve_profile(
    profile: dict[str, Any], tools_root: Path
) -> tuple[Path | None, str | None]:
    if profile["status"] == "unavailable":
        return None, profile["reason"]
    executable = TOOLCHAIN.safe_file(tools_root, profile["executable"]["path"])
    return executable.resolve(), None


def materialize_command(
    template: list[str], *, executable: Path, work: Path, tools_root: Path
) -> list[str]:
    if not template or any(not isinstance(value, str) or not value for value in template):
        raise ValueError("planned command is invalid")
    return [
        str(executable) if index == 0 else value
        .replace("$WORK", str(work))
        .replace("$TOOLCHAIN", str(tools_root))
        for index, value in enumerate(template)
    ]


def trial_path(output: Path, task: dict[str, Any], repetition: int) -> Path:
    return (
        output
        / "trials"
        / task["profile_id"]
        / f"{task['item_id']}.r{repetition}.json"
    )


def expected_trial_identity(
    task: dict[str, Any], repetition: int, bindings: dict[str, str]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "bindings": bindings,
        "task_id": task["task_id"],
        "profile_id": task["profile_id"],
        "codec_id": task["codec_id"],
        "formal_ceiling_eligible": task["formal_ceiling_eligible"],
        "item_id": task["item_id"],
        "track": task["track"],
        "repetition": repetition,
        "warmup": repetition == 0,
        "source_bytes": task["source_bytes"],
        "source_sha256": task["source_sha256"],
        "counted_side_asset_bytes": task["counted_side_asset_bytes"],
        "counted_side_asset_sha256": task["counted_side_asset_sha256"],
        "second_host_decode_required": task["second_host_decode_required"],
    }


def validate_process(process: object, expected_command: list[str]) -> None:
    if (
        not isinstance(process, dict)
        or set(process) != PROCESS_KEYS
        or process.get("command") != expected_command
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
        or len(process["stdout"].encode("utf-8")) > 65536
        or len(process["stderr"].encode("utf-8")) > 65536
    ):
        raise ValueError("trial process record is invalid")


def validate_existing_trial(
    receipt: dict[str, Any],
    *,
    task: dict[str, Any],
    repetition: int,
    bindings: dict[str, str],
    expected_compression: list[str],
    expected_decompression: list[str],
    family_budget_seconds: float,
    max_address_bytes: int | None,
) -> None:
    identity = expected_trial_identity(task, repetition, bindings)
    expected_keys = set(identity) | {
        "payload_bytes",
        "payload_sha256",
        "complete_artifact_bytes",
        "compression",
        "decompression",
        "exact_roundtrip",
        "within_resource_gate",
        "passed",
        "error",
        "axiom_outcome",
    }
    if set(receipt) != expected_keys or any(
        receipt.get(key) != value for key, value in identity.items()
    ):
        raise ValueError("resumed research trial identity differs")
    validate_process(receipt.get("compression"), expected_compression)
    if receipt.get("decompression") is not None:
        validate_process(receipt["decompression"], expected_decompression)
    payload_record_valid = (
        type(receipt.get("payload_bytes")) is int
        and receipt["payload_bytes"] >= 0
        and PLANNER.BASELINE_PUBLICATION.is_lower_hex(
            receipt.get("payload_sha256"), 64
        )
        and receipt.get("complete_artifact_bytes")
        == receipt["payload_bytes"] + task["counted_side_asset_bytes"]
    )
    payload_valid = payload_record_valid and receipt["payload_bytes"] > 0
    within_resource_gate = max_address_bytes is None or (
        receipt["compression"]["peak_rss_bytes"] <= max_address_bytes
        and (
            receipt.get("decompression") is None
            or receipt["decompression"]["peak_rss_bytes"] <= max_address_bytes
        )
    )
    if receipt.get("passed") is True:
        if (
            not payload_valid
            or receipt.get("exact_roundtrip") is not True
            or receipt.get("within_resource_gate") is not True
            or not within_resource_gate
            or receipt.get("error") is not None
            or receipt.get("axiom_outcome") != "baseline_measurement_only"
            or receipt["compression"]["returncode"] != 0
            or receipt["compression"]["timed_out"]
            or receipt.get("decompression") is None
            or receipt["decompression"]["returncode"] != 0
            or receipt["decompression"]["timed_out"]
        ):
            raise ValueError("resumed successful research trial is invalid")
    elif receipt.get("passed") is False:
        if (
            receipt.get("exact_roundtrip") is not False
            or not isinstance(receipt.get("within_resource_gate"), bool)
            or receipt.get("within_resource_gate") is not within_resource_gate
            or not isinstance(receipt.get("error"), str)
            or not receipt["error"]
            or receipt.get("axiom_outcome") != "untested"
            or ((receipt.get("payload_bytes") is None) != (receipt.get("payload_sha256") is None))
            or (
                receipt.get("payload_bytes") is None
                and receipt.get("complete_artifact_bytes") is not None
            )
            or (receipt.get("payload_bytes") is not None and not payload_record_valid)
        ):
            raise ValueError("resumed failed research trial is invalid")
        compression = receipt["compression"]
        decompression = receipt.get("decompression")
        if compression["timed_out"]:
            expected_errors = {"compression timed out"}
        elif compression["returncode"] != 0:
            expected_errors = {f"compression exited {compression['returncode']}"}
        elif not within_resource_gate and (
            max_address_bytes is not None
            and compression["peak_rss_bytes"] > max_address_bytes
        ):
            expected_errors = {"compression exceeded the host memory gate"}
        elif receipt.get("payload_bytes") is None:
            expected_errors = {"compression produced no ordinary payload"}
        elif receipt["payload_bytes"] == 0:
            expected_errors = {"compression produced an empty payload"}
        elif decompression is None:
            if compression["wall_ns"] < int(family_budget_seconds * 1e9):
                raise ValueError("failed trial omitted decompression before budget exhaustion")
            expected_errors = {"family wall-time budget exhausted after compression"}
        elif decompression["timed_out"]:
            expected_errors = {"decompression timed out"}
        elif decompression["returncode"] != 0:
            expected_errors = {f"decompression exited {decompression['returncode']}"}
        elif not within_resource_gate:
            expected_errors = {"decompression exceeded the host memory gate"}
        else:
            expected_errors = {
                "decompression produced no ordinary output",
                "restored size mismatch",
                "restored digest mismatch",
            }
        if receipt["error"] not in expected_errors:
            raise ValueError("failed research trial error classification is inconsistent")
    else:
        raise ValueError("resumed research trial pass state is invalid")


def _staged_timestamp(value: str) -> int:
    timestamp = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.UTC
    )
    return int(timestamp.timestamp())


def retained_artifact_path(output: Path, task: dict[str, Any]) -> Path:
    return output / "artifacts" / task["profile_id"] / f"{task['item_id']}.bin"


def retain_artifact(source: Path, destination: Path) -> Path:
    source_bytes = source.stat().st_size
    source_sha256 = sha256_file(source)
    if destination.exists():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.stat().st_size != source_bytes
            or sha256_file(destination) != source_sha256
        ):
            raise ValueError(f"retained research artifact differs: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        if (
            temporary.stat().st_size != source_bytes
            or sha256_file(temporary) != source_sha256
        ):
            raise ValueError("retained research artifact copy differs")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def run_trial(
    *,
    output: Path,
    task: dict[str, Any],
    source: Path,
    executable: Path,
    tools_root: Path,
    repetition: int,
    bindings: dict[str, str],
    timeout_seconds: float,
    family_budget_seconds: float,
    max_address_bytes: int | None,
) -> dict[str, Any]:
    destination = trial_path(output, task, repetition)
    if source.is_symlink() or not source.is_file():
        raise ValueError("research source is not an ordinary file")
    if (
        source.stat().st_size != task["source_bytes"]
        or sha256_file(source) != task["source_sha256"]
    ):
        raise ValueError("research source identity differs from the frozen task")
    with tempfile.TemporaryDirectory(prefix="text-source-research-ceiling-") as raw:
        work = Path(raw)
        staged = work / "input.bin"
        payload = work / (
            "artifact.bin" if task["profile_id"] == "zpaq-5-m510" else "payload.bin"
        )
        restored = work / "restored.bin"
        compression_command = materialize_command(
            task["compression_command"],
            executable=executable,
            work=work,
            tools_root=tools_root,
        )
        decompression_command = materialize_command(
            task["decompression_command"],
            executable=executable,
            work=work,
            tools_root=tools_root,
        )
        expected_compression = sanitize_process(
            {"command": compression_command}, work, tools_root
        )["command"]
        expected_decompression = sanitize_process(
            {"command": decompression_command}, work, tools_root
        )["command"]
        if destination.exists():
            receipt = read_canonical_json(destination)
            validate_existing_trial(
                receipt,
                task=task,
                repetition=repetition,
                bindings=bindings,
                expected_compression=expected_compression,
                expected_decompression=expected_decompression,
                family_budget_seconds=family_budget_seconds,
                max_address_bytes=max_address_bytes,
            )
            return receipt

        shutil.copyfile(source, staged)
        if (
            staged.stat().st_size != task["source_bytes"]
            or sha256_file(staged) != task["source_sha256"]
        ):
            raise ValueError("staged research source identity differs")
        if task["staged_input_mtime_utc"] is not None:
            seconds = _staged_timestamp(task["staged_input_mtime_utc"])
            os.utime(staged, (seconds, seconds))
            if int(staged.stat().st_mtime) != seconds:
                raise ValueError("filesystem did not preserve the staged input timestamp")
        operation_timeout = min(timeout_seconds, family_budget_seconds)
        if operation_timeout <= 0:
            raise ValueError("family wall-time budget must be positive before a trial")
        compression = run_process(
            compression_command,
            cwd=work,
            timeout_seconds=operation_timeout,
            max_address_bytes=max_address_bytes,
        )
        error = ""
        decompression: dict[str, Any] | None = None
        payload_bytes: int | None = None
        payload_sha256: str | None = None
        within_resource_gate = (
            max_address_bytes is None
            or compression["peak_rss_bytes"] <= max_address_bytes
        )
        if compression["timed_out"]:
            error = "compression timed out"
        elif compression["returncode"] != 0:
            error = f"compression exited {compression['returncode']}"
        elif not within_resource_gate:
            error = "compression exceeded the host memory gate"
        elif not payload.is_file() or payload.is_symlink():
            error = "compression produced no ordinary payload"
        else:
            payload_bytes = payload.stat().st_size
            payload_sha256 = sha256_file(payload)
            if payload_bytes <= 0:
                error = "compression produced an empty payload"
            elif compression["wall_ns"] >= int(family_budget_seconds * 1e9):
                error = "family wall-time budget exhausted after compression"
            else:
                remaining_seconds = family_budget_seconds - (
                    compression["wall_ns"] / 1e9
                )
                decompression = run_process(
                    decompression_command,
                    cwd=work,
                    timeout_seconds=min(timeout_seconds, remaining_seconds),
                    max_address_bytes=max_address_bytes,
                    max_file_bytes=task["source_bytes"],
                )
                within_resource_gate = within_resource_gate and (
                    max_address_bytes is None
                    or decompression["peak_rss_bytes"] <= max_address_bytes
                )
                if decompression["timed_out"]:
                    error = "decompression timed out"
                elif decompression["returncode"] != 0:
                    error = f"decompression exited {decompression['returncode']}"
                elif not within_resource_gate:
                    error = "decompression exceeded the host memory gate"
                elif not restored.is_file() or restored.is_symlink():
                    error = "decompression produced no ordinary output"
                elif restored.stat().st_size != task["source_bytes"]:
                    error = "restored size mismatch"
                elif sha256_file(restored) != task["source_sha256"]:
                    error = "restored digest mismatch"
        identity = expected_trial_identity(task, repetition, bindings)
        receipt = identity | {
            "payload_bytes": payload_bytes,
            "payload_sha256": payload_sha256,
            "complete_artifact_bytes": (
                payload_bytes + task["counted_side_asset_bytes"]
                if payload_bytes is not None
                else None
            ),
            "compression": sanitize_process(compression, work, tools_root),
            "decompression": (
                sanitize_process(decompression, work, tools_root)
                if decompression is not None
                else None
            ),
            "exact_roundtrip": not error,
            "within_resource_gate": within_resource_gate,
            "passed": not error,
            "error": error or None,
            "axiom_outcome": "baseline_measurement_only" if not error else "untested",
        }
        if repetition == 1 and not error:
            retain_artifact(payload, retained_artifact_path(output, task))
        write_json_atomic(destination, receipt)
        return receipt


def summarize_task(
    task: dict[str, Any],
    trials: list[dict[str, Any]],
    terminal_reason: str | None = None,
) -> dict[str, Any]:
    measured = [row for row in trials if not row["warmup"]]
    complete = len(measured) == 2 and all(row["passed"] for row in measured)
    hashes = {row["payload_sha256"] for row in measured if row["payload_sha256"]}
    sizes = {row["complete_artifact_bytes"] for row in measured if row["complete_artifact_bytes"]}
    deterministic = complete and len(hashes) == 1 and len(sizes) == 1
    portability_status = (
        "pending_second_host_decode"
        if task["second_host_decode_required"]
        else "not_required_by_research_protocol"
    )
    formal_ceiling_admitted = (
        deterministic
        and task["formal_ceiling_eligible"]
        and not task["second_host_decode_required"]
    )
    result = {
        "task_id": task["task_id"],
        "profile_id": task["profile_id"],
        "codec_id": task["codec_id"],
        "item_id": task["item_id"],
        "track": task["track"],
        "formal_ceiling_eligible": task["formal_ceiling_eligible"],
        "source_bytes": task["source_bytes"],
        "measured_repetitions": len(measured),
        "complete": complete,
        "deterministic": deterministic,
        "complete_artifact_bytes": next(iter(sizes)) if deterministic else None,
        "payload_sha256": next(iter(hashes)) if deterministic else None,
        "exact_roundtrip": complete,
        "portability_status": portability_status,
        "formal_ceiling_admitted": formal_ceiling_admitted,
        "execution_status": "measured_exact_deterministic"
        if deterministic
        else "measured_failed_or_nondeterministic",
        "axiom_outcome": "baseline_measurement_only" if deterministic else "untested",
    }
    if terminal_reason is not None:
        result["execution_status"] = "resource_budget_exhausted"
        result["unavailable_reason"] = terminal_reason
        result["complete"] = False
        result["deterministic"] = False
        result["complete_artifact_bytes"] = None
        result["payload_sha256"] = None
        result["exact_roundtrip"] = False
        result["axiom_outcome"] = "untested"
        result["formal_ceiling_admitted"] = False
    return result


def unavailable_task(task: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "profile_id": task["profile_id"],
        "codec_id": task["codec_id"],
        "item_id": task["item_id"],
        "track": task["track"],
        "formal_ceiling_eligible": task["formal_ceiling_eligible"],
        "source_bytes": task["source_bytes"],
        "measured_repetitions": 0,
        "complete": False,
        "deterministic": False,
        "complete_artifact_bytes": None,
        "payload_sha256": None,
        "exact_roundtrip": False,
        "portability_status": (
            "pending_second_host_decode"
            if task["second_host_decode_required"]
            else "not_required_by_research_protocol"
        ),
        "formal_ceiling_admitted": False,
        "execution_status": "unavailable",
        "unavailable_reason": reason,
        "axiom_outcome": "untested",
    }


def retained_artifact_manifest(
    output: Path, paths: set[Path]
) -> tuple[int, str]:
    rows = []
    for path in sorted(paths):
        relative = path.relative_to(output).as_posix()
        rows.append(f"{relative}\0{path.stat().st_size}\0{sha256_file(path)}\n")
    return len(rows), hashlib.sha256("".join(rows).encode("utf-8")).hexdigest()


def build_attempt(
    *,
    plan: dict[str, Any],
    toolchain_receipt: dict[str, Any],
    bindings: dict[str, str],
    profiles: dict[str, dict[str, Any]],
    tasks: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be a positive finite number")
    return {
        "schema_version": 1,
        "name": "text-source-research-ceiling-host-run-v1",
        "completed": False,
        "bindings": bindings,
        "host": toolchain_receipt["host"],
        "measurement_policy": plan["measurement_policy"],
        "timeout_seconds_per_operation": timeout_seconds,
        "profile_ids": list(profiles),
        "task_ids": [row["task_id"] for row in tasks],
        "claim_ceiling": plan["claim_ceiling"],
    }


def validate_output(
    *,
    plan_path: Path,
    toolchain_receipt_path: Path,
    tools_root: Path,
    output: Path,
) -> dict[str, Any]:
    plan = read_canonical_json(plan_path)
    toolchain_receipt = read_canonical_json(toolchain_receipt_path)
    toolchain_validation = TOOLCHAIN.validate(
        plan_path, toolchain_receipt_path, tools_root
    )
    attempt = read_canonical_json(output / "attempt.json")
    results = read_canonical_json(output / "results.json")
    host = toolchain_receipt["host"]
    profiles = {row["profile_id"]: row for row in toolchain_receipt["profiles"]}
    tasks = [row for row in plan["tasks"] if row["host_class"] == host["host_class"]]
    bindings = {
        "plan_sha256": sha256_file(plan_path),
        "toolchain_receipt_sha256": sha256_file(toolchain_receipt_path),
        "corpus_manifest_sha256": plan["bindings"]["corpus_manifest_sha256"],
        "repository_commit": plan["bindings"]["repository_commit"],
    }
    expected_attempt = build_attempt(
        plan=plan,
        toolchain_receipt=toolchain_receipt,
        bindings=bindings,
        profiles=profiles,
        tasks=tasks,
        timeout_seconds=attempt.get("timeout_seconds_per_operation"),
    )
    if attempt != expected_attempt:
        raise ValueError("host attempt differs from the frozen plan and toolchain")

    actual_trial_files: set[Path] = set()
    actual_trial_directories: set[Path] = set()
    trials_root = output / "trials"
    if trials_root.exists():
        if trials_root.is_symlink() or not trials_root.is_dir():
            raise ValueError("trial root is not an ordinary directory")
        for path in trials_root.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"research run contains a symlink: {path}")
            if path.is_file():
                actual_trial_files.add(path)
            elif path.is_dir():
                actual_trial_directories.add(path)
            else:
                raise ValueError(f"research run contains a special file: {path}")

    actual_artifact_files: set[Path] = set()
    actual_artifact_directories: set[Path] = set()
    artifacts_root = output / "artifacts"
    if artifacts_root.exists():
        if artifacts_root.is_symlink() or not artifacts_root.is_dir():
            raise ValueError("artifact root is not an ordinary directory")
        for path in artifacts_root.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"research run contains a symlink: {path}")
            if path.is_file():
                actual_artifact_files.add(path)
            elif path.is_dir():
                actual_artifact_directories.add(path)
            else:
                raise ValueError(f"research run contains a special file: {path}")

    max_address_bytes = None
    if host["host_class"] == "local-macos-18-gib-rss-cap":
        max_address_bytes = int(
            plan["measurement_policy"]["local_peak_rss_cap_gib"] * 1024**3
        )
    family_budget_hours = float(
        plan["measurement_policy"]["maximum_wall_hours_per_family_per_codec"]
    )
    family_budget_seconds = family_budget_hours * 3600.0
    family_wall_seconds: dict[tuple[str, str], float] = {}
    expected_trial_files: set[Path] = set()
    expected_artifact_files: set[Path] = set()
    task_results = []
    trial_count = 0
    for task in tasks:
        profile = profiles[task["profile_id"]]
        executable, unavailable_reason = resolve_profile(profile, tools_root)
        if unavailable_reason is not None:
            task_results.append(unavailable_task(task, unavailable_reason))
            continue
        if executable is None:
            raise ValueError("available profile resolved without an executable")
        work = Path("$WORK")
        compression_command = materialize_command(
            task["compression_command"],
            executable=executable,
            work=work,
            tools_root=tools_root,
        )
        decompression_command = materialize_command(
            task["decompression_command"],
            executable=executable,
            work=work,
            tools_root=tools_root,
        )
        expected_compression = sanitize_process(
            {"command": compression_command}, work, tools_root
        )["command"]
        expected_decompression = sanitize_process(
            {"command": decompression_command}, work, tools_root
        )["command"]
        rows = []
        terminal_reason = None
        family_key = (task["profile_id"], task["track"])
        for repetition in range(3):
            used_seconds = family_wall_seconds.get(family_key, 0.0)
            if family_budget_seconds - used_seconds <= 0:
                terminal_reason = (
                    f"the frozen {family_budget_hours:g}-hour per-family per-codec "
                    "wall budget was exhausted"
                )
                break
            path = trial_path(output, task, repetition)
            if path not in actual_trial_files:
                raise ValueError(f"required research trial receipt is missing: {path}")
            receipt = read_canonical_json(path)
            validate_existing_trial(
                receipt,
                task=task,
                repetition=repetition,
                bindings=bindings,
                expected_compression=expected_compression,
                expected_decompression=expected_decompression,
                family_budget_seconds=(family_budget_seconds - used_seconds),
                max_address_bytes=max_address_bytes,
            )
            if max_address_bytes is not None and (
                receipt["compression"]["peak_rss_bytes"] > max_address_bytes
                or (
                    receipt["decompression"] is not None
                    and receipt["decompression"]["peak_rss_bytes"]
                    > max_address_bytes
                )
            ):
                if receipt["passed"] or receipt["within_resource_gate"]:
                    raise ValueError("over-cap trial is labeled within the resource gate")
            process_seconds = receipt["compression"]["wall_ns"] / 1e9
            if receipt["decompression"] is not None:
                process_seconds += receipt["decompression"]["wall_ns"] / 1e9
            family_wall_seconds[family_key] = used_seconds + process_seconds
            expected_trial_files.add(path)
            rows.append(receipt)
            trial_count += 1
        retained_rows = [
            row for row in rows if row["repetition"] == 1 and row["passed"]
        ]
        if retained_rows:
            retained = retained_artifact_path(output, task)
            if retained not in actual_artifact_files:
                raise ValueError(f"retained research artifact is missing: {retained}")
            retained_row = retained_rows[0]
            if (
                retained.stat().st_size != retained_row["payload_bytes"]
                or sha256_file(retained) != retained_row["payload_sha256"]
            ):
                raise ValueError("retained research artifact identity differs")
            expected_artifact_files.add(retained)
        task_results.append(summarize_task(task, rows, terminal_reason))
    if actual_trial_files != expected_trial_files:
        raise ValueError("research run trial file roster contains extras")
    expected_trial_directories = {
        directory
        for path in expected_trial_files
        for directory in (path.parent,)
    }
    if expected_trial_files:
        expected_trial_directories.add(trials_root)
    if actual_trial_directories | ({trials_root} if trials_root.exists() else set()) != expected_trial_directories:
        raise ValueError("research run trial directory roster contains extras")
    if actual_artifact_files != expected_artifact_files:
        raise ValueError("research run retained artifact roster contains extras")
    expected_artifact_directories = {path.parent for path in expected_artifact_files}
    if expected_artifact_files:
        expected_artifact_directories.add(artifacts_root)
    if actual_artifact_directories | (
        {artifacts_root} if artifacts_root.exists() else set()
    ) != expected_artifact_directories:
        raise ValueError("research run artifact directory roster contains extras")

    artifact_count, artifact_manifest_sha256 = retained_artifact_manifest(
        output, expected_artifact_files
    )

    formal = [row for row in task_results if row["formal_ceiling_eligible"]]
    expected_results = expected_attempt | {
        "completed": True,
        "toolchain_validation": toolchain_validation,
        "trial_count": trial_count,
        "tasks": task_results,
        "all_host_formal_tasks_complete": bool(formal)
        and all(row["formal_ceiling_admitted"] for row in formal),
        "retained_artifact_count": artifact_count,
        "retained_artifact_manifest_sha256": artifact_manifest_sha256,
        "axiom_wins": 0,
    }
    if results != expected_results:
        raise ValueError("host results do not reconstruct from raw receipts")
    expected_top_level = {"attempt.json", "results.json"}
    if expected_trial_files:
        expected_top_level.add("trials")
    if expected_artifact_files:
        expected_top_level.add("artifacts")
    if {path.name for path in output.iterdir()} != expected_top_level or any(
        path.is_symlink()
        or (
            path.name in {"attempt.json", "results.json"}
            and not path.is_file()
        )
        or (path.name == "trials" and not path.is_dir())
        or (path.name == "artifacts" and not path.is_dir())
        for path in output.iterdir()
    ):
        raise ValueError("research run top-level file roster differs")
    return {
        "verified": True,
        "host_id": host["host_id"],
        "host_class": host["host_class"],
        "trial_count": trial_count,
        "task_count": len(task_results),
        "retained_artifact_count": artifact_count,
        "retained_artifact_manifest_sha256": artifact_manifest_sha256,
        "all_host_formal_tasks_complete": expected_results[
            "all_host_formal_tasks_complete"
        ],
        "axiom_wins": 0,
        "results_sha256": sha256_file(output / "results.json"),
    }


def benchmark(
    *,
    plan_path: Path,
    toolchain_receipt_path: Path,
    tools_root: Path,
    corpus: Path,
    output: Path,
    timeout_seconds: float,
) -> Path:
    plan = read_canonical_json(plan_path)
    toolchain_receipt = read_canonical_json(toolchain_receipt_path)
    validation = TOOLCHAIN.validate(plan_path, toolchain_receipt_path, tools_root)
    manifest_path, _manifest, items = BASELINE_RUNNER.verify_manifest(corpus)
    item_map = {item["id"]: item for item in items}
    if sha256_file(manifest_path) != plan["bindings"]["corpus_manifest_sha256"]:
        raise ValueError("development corpus differs from the frozen plan")
    host = toolchain_receipt["host"]
    profiles = {row["profile_id"]: row for row in toolchain_receipt["profiles"]}
    tasks = [row for row in plan["tasks"] if row["host_class"] == host["host_class"]]
    if {row["profile_id"] for row in tasks} != set(profiles):
        raise ValueError("host task roster differs from its toolchain receipt")
    bindings = {
        "plan_sha256": sha256_file(plan_path),
        "toolchain_receipt_sha256": sha256_file(toolchain_receipt_path),
        "corpus_manifest_sha256": sha256_file(manifest_path),
        "repository_commit": plan["bindings"]["repository_commit"],
    }
    output.mkdir(parents=True, exist_ok=True)
    attempt_path = output / "attempt.json"
    attempt = build_attempt(
        plan=plan,
        toolchain_receipt=toolchain_receipt,
        bindings=bindings,
        profiles=profiles,
        tasks=tasks,
        timeout_seconds=timeout_seconds,
    )
    if attempt_path.exists():
        if read_canonical_json(attempt_path) != attempt:
            raise ValueError("existing host attempt differs from this invocation")
    else:
        write_json_atomic(attempt_path, attempt)

    max_address_bytes = None
    if host["host_class"] == "local-macos-18-gib-rss-cap":
        max_address_bytes = int(
            plan["measurement_policy"]["local_peak_rss_cap_gib"] * 1024**3
        )
    task_results = []
    trial_count = 0
    retained_artifacts: set[Path] = set()
    family_budget_hours = float(
        plan["measurement_policy"]["maximum_wall_hours_per_family_per_codec"]
    )
    family_budget_seconds = family_budget_hours * 3600.0
    family_wall_seconds: dict[tuple[str, str], float] = {}
    for task in tasks:
        profile = profiles[task["profile_id"]]
        executable, unavailable_reason = resolve_profile(profile, tools_root)
        if unavailable_reason is not None:
            task_results.append(unavailable_task(task, unavailable_reason))
            continue
        if executable is None:
            raise ValueError("available profile resolved without an executable")
        item = item_map[task["item_id"]]
        if (
            item["source_bytes"] != task["source_bytes"]
            or item["source_sha256"] != task["source_sha256"]
            or item["track"] != task["track"]
        ):
            raise ValueError(f"planned source identity differs: {task['item_id']}")
        rows = []
        terminal_reason = None
        family_key = (task["profile_id"], task["track"])
        for repetition in range(3):
            used_seconds = family_wall_seconds.get(family_key, 0.0)
            remaining_seconds = family_budget_seconds - used_seconds
            if remaining_seconds <= 0:
                terminal_reason = (
                    f"the frozen {family_budget_hours:g}-hour per-family per-codec "
                    "wall budget was exhausted"
                )
                break
            print(
                f"[{trial_count + 1}/{len(tasks) * 3}] r{repetition} "
                f"{task['item_id']} x {task['profile_id']}",
                flush=True,
            )
            rows.append(
                run_trial(
                    output=output,
                    task=task,
                    source=Path(item["path"]),
                    executable=executable,
                    tools_root=tools_root,
                    repetition=repetition,
                    bindings=bindings,
                    timeout_seconds=timeout_seconds,
                    family_budget_seconds=remaining_seconds,
                    max_address_bytes=max_address_bytes,
                )
            )
            process_seconds = rows[-1]["compression"]["wall_ns"] / 1e9
            if rows[-1]["decompression"] is not None:
                process_seconds += rows[-1]["decompression"]["wall_ns"] / 1e9
            family_wall_seconds[family_key] = used_seconds + process_seconds
            trial_count += 1
        if any(row["repetition"] == 1 and row["passed"] for row in rows):
            retained_artifacts.add(retained_artifact_path(output, task))
        task_results.append(summarize_task(task, rows, terminal_reason))
    formal = [row for row in task_results if row["formal_ceiling_eligible"]]
    artifact_count, artifact_manifest_sha256 = retained_artifact_manifest(
        output, retained_artifacts
    )
    results = attempt | {
        "completed": True,
        "toolchain_validation": validation,
        "trial_count": trial_count,
        "tasks": task_results,
        "all_host_formal_tasks_complete": bool(formal)
        and all(row["formal_ceiling_admitted"] for row in formal),
        "retained_artifact_count": artifact_count,
        "retained_artifact_manifest_sha256": artifact_manifest_sha256,
        "axiom_wins": 0,
    }
    results_path = output / "results.json"
    write_json_atomic(results_path, results)
    validate_output(
        plan_path=plan_path,
        toolchain_receipt_path=toolchain_receipt_path,
        tools_root=tools_root,
        output=output,
    )
    return results_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--toolchain-receipt", type=Path, required=True)
    parser.add_argument("--tools-root", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=43_200.0)
    args = parser.parse_args()
    try:
        result = benchmark(
            plan_path=args.plan,
            toolchain_receipt_path=args.toolchain_receipt,
            tools_root=args.tools_root,
            corpus=args.corpus,
            output=args.output,
            timeout_seconds=args.timeout_seconds,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"research-ceiling benchmark failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
