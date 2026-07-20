#!/usr/bin/env python3
"""Run and verify NNCP retained artifacts on a distinct second host."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import shutil
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_PRIMARY = REPOSITORY / "runs" / "text-source-research-ceiling-nncp-primary-v1"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-research-ceiling-nncp-second-host-v1"
PROFILE_ID = "nncp-3.3-transformer"
HOST_CLASS = "authorized-linux-cuda-host-plus-second-host-decode"


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_script(
    "research_ceiling_runner_for_second_host",
    REPOSITORY / "scripts" / "benchmark-text-source-research-ceiling.py",
)
PLANNER = RUNNER.PLANNER
TOOLCHAIN = RUNNER.TOOLCHAIN


def sha256_file(path: Path) -> str:
    return RUNNER.sha256_file(path)


def read_canonical_json(path: Path) -> dict[str, Any]:
    return RUNNER.read_canonical_json(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    RUNNER.write_json_atomic(path, payload)


def primary_tasks(
    plan_path: Path, primary_output: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], set[Path]]:
    plan = read_canonical_json(plan_path)
    results = read_canonical_json(primary_output / "results.json")
    tasks = [task for task in plan["tasks"] if task["profile_id"] == PROFILE_ID]
    if (
        len(tasks) != 7
        or results.get("completed") is not True
        or results.get("bindings", {}).get("plan_sha256") != sha256_file(plan_path)
        or results.get("host", {}).get("host_class") != HOST_CLASS
        or results.get("profile_ids") != [PROFILE_ID]
        or results.get("axiom_wins") != 0
        or results.get("all_host_formal_tasks_complete") is not False
    ):
        raise ValueError("primary NNCP host result identity is invalid")
    result_tasks = {row["task_id"]: row for row in results.get("tasks", [])}
    if set(result_tasks) != {task["task_id"] for task in tasks}:
        raise ValueError("primary NNCP task roster differs from the frozen plan")
    artifacts = set()
    for task in tasks:
        row = result_tasks[task["task_id"]]
        if (
            row.get("complete") is not True
            or row.get("deterministic") is not True
            or row.get("exact_roundtrip") is not True
            or row.get("portability_status") != "pending_second_host_decode"
            or row.get("formal_ceiling_admitted") is not False
            or type(row.get("complete_artifact_bytes")) is not int
            or row["complete_artifact_bytes"] <= 0
            or not PLANNER.BASELINE_PUBLICATION.is_lower_hex(
                row.get("payload_sha256"), 64
            )
        ):
            raise ValueError(f"primary NNCP task is not ready: {task['task_id']}")
        artifact = RUNNER.retained_artifact_path(primary_output, task)
        if (
            artifact.is_symlink()
            or not artifact.is_file()
            or artifact.stat().st_size != row["complete_artifact_bytes"]
            or sha256_file(artifact) != row["payload_sha256"]
        ):
            raise ValueError(f"primary NNCP artifact identity differs: {task['task_id']}")
        artifacts.add(artifact)
    count, manifest_sha256 = RUNNER.retained_artifact_manifest(
        primary_output, artifacts
    )
    if (
        count != results.get("retained_artifact_count")
        or manifest_sha256 != results.get("retained_artifact_manifest_sha256")
    ):
        raise ValueError("primary NNCP retained artifact manifest differs")
    return plan, tasks, results, artifacts


def receipt_path(output: Path, task: dict[str, Any]) -> Path:
    return output / "receipts" / f"{task['item_id']}.json"


def identity(
    *,
    task: dict[str, Any],
    artifact: Path,
    bindings: dict[str, str],
    second_host: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "bindings": bindings,
        "task_id": task["task_id"],
        "profile_id": PROFILE_ID,
        "item_id": task["item_id"],
        "track": task["track"],
        "source_bytes": task["source_bytes"],
        "source_sha256": task["source_sha256"],
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": sha256_file(artifact),
        "second_host": second_host,
    }


def validate_receipt(
    receipt: dict[str, Any],
    *,
    expected_identity: dict[str, Any],
    expected_command: list[str],
    remaining_budget_seconds: float,
) -> None:
    keys = set(expected_identity) | {
        "decompression",
        "restored_bytes",
        "restored_sha256",
        "within_family_budget",
        "exact_roundtrip",
        "passed",
        "error",
        "axiom_outcome",
    }
    if set(receipt) != keys or any(
        receipt.get(key) != value for key, value in expected_identity.items()
    ):
        raise ValueError("second-host decode receipt identity differs")
    RUNNER.validate_process(receipt.get("decompression"), expected_command)
    process = receipt["decompression"]
    within_budget = process["wall_ns"] <= int(remaining_budget_seconds * 1e9)
    if receipt.get("within_family_budget") is not within_budget:
        raise ValueError("second-host budget classification differs")
    digest_valid = PLANNER.BASELINE_PUBLICATION.is_lower_hex(
        receipt.get("restored_sha256"), 64
    )
    if receipt.get("passed") is True:
        if (
            process["timed_out"]
            or process["returncode"] != 0
            or not within_budget
            or receipt.get("restored_bytes") != receipt["source_bytes"]
            or receipt.get("restored_sha256") != receipt["source_sha256"]
            or not digest_valid
            or receipt.get("exact_roundtrip") is not True
            or receipt.get("error") is not None
            or receipt.get("axiom_outcome") != "baseline_portability_evidence_only"
        ):
            raise ValueError("successful second-host decode receipt is invalid")
        return
    if (
        receipt.get("passed") is not False
        or receipt.get("exact_roundtrip") is not False
        or not isinstance(receipt.get("error"), str)
        or not receipt["error"]
        or receipt.get("axiom_outcome") != "untested"
        or (
            receipt.get("restored_bytes") is None
            and receipt.get("restored_sha256") is not None
        )
        or (
            receipt.get("restored_bytes") is not None
            and (
                type(receipt["restored_bytes"]) is not int
                or receipt["restored_bytes"] < 0
                or not digest_valid
            )
        )
    ):
        raise ValueError("failed second-host decode receipt is invalid")
    if process["timed_out"]:
        expected_errors = {"second-host decompression timed out"}
    elif process["returncode"] != 0:
        expected_errors = {f"second-host decompression exited {process['returncode']}"}
    elif not within_budget:
        expected_errors = {"second-host family wall-time budget exhausted"}
    elif receipt.get("restored_bytes") is None:
        expected_errors = {"second-host decompression produced no ordinary output"}
    elif receipt["restored_bytes"] != receipt["source_bytes"]:
        expected_errors = {"second-host restored size mismatch"}
    elif receipt["restored_sha256"] != receipt["source_sha256"]:
        expected_errors = {"second-host restored digest mismatch"}
    else:
        raise ValueError("failed second-host receipt restored the exact source")
    if receipt["error"] not in expected_errors:
        raise ValueError("second-host failure classification is inconsistent")


def run_decode(
    *,
    output: Path,
    task: dict[str, Any],
    artifact: Path,
    executable: Path,
    tools_root: Path,
    bindings: dict[str, str],
    second_host: dict[str, Any],
    timeout_seconds: float,
    remaining_budget_seconds: float,
) -> dict[str, Any]:
    destination = receipt_path(output, task)
    with tempfile.TemporaryDirectory(prefix="nncp-second-host-decode-") as raw:
        work = Path(raw)
        payload = work / "payload.bin"
        restored = work / "restored.bin"
        shutil.copyfile(artifact, payload)
        if (
            payload.stat().st_size != artifact.stat().st_size
            or sha256_file(payload) != sha256_file(artifact)
        ):
            raise ValueError("second-host staged artifact identity differs")
        command = RUNNER.materialize_command(
            task["decompression_command"],
            executable=executable,
            work=work,
            tools_root=tools_root,
        )
        expected_command = RUNNER.sanitize_process(
            {"command": command}, work, tools_root
        )["command"]
        expected_identity = identity(
            task=task,
            artifact=artifact,
            bindings=bindings,
            second_host=second_host,
        )
        if destination.exists():
            receipt = read_canonical_json(destination)
            validate_receipt(
                receipt,
                expected_identity=expected_identity,
                expected_command=expected_command,
                remaining_budget_seconds=remaining_budget_seconds,
            )
            return receipt
        process = RUNNER.run_process(
            command,
            cwd=work,
            timeout_seconds=min(timeout_seconds, remaining_budget_seconds),
            max_address_bytes=None,
            max_file_bytes=task["source_bytes"],
        )
        within_budget = process["wall_ns"] <= int(remaining_budget_seconds * 1e9)
        restored_bytes = None
        restored_sha256 = None
        error = ""
        if process["timed_out"]:
            error = "second-host decompression timed out"
        elif process["returncode"] != 0:
            error = f"second-host decompression exited {process['returncode']}"
        elif not within_budget:
            error = "second-host family wall-time budget exhausted"
        elif restored.is_symlink() or not restored.is_file():
            error = "second-host decompression produced no ordinary output"
        else:
            restored_bytes = restored.stat().st_size
            restored_sha256 = sha256_file(restored)
            if restored_bytes != task["source_bytes"]:
                error = "second-host restored size mismatch"
            elif restored_sha256 != task["source_sha256"]:
                error = "second-host restored digest mismatch"
        receipt = expected_identity | {
            "decompression": RUNNER.sanitize_process(process, work, tools_root),
            "restored_bytes": restored_bytes,
            "restored_sha256": restored_sha256,
            "within_family_budget": within_budget,
            "exact_roundtrip": not error,
            "passed": not error,
            "error": error or None,
            "axiom_outcome": (
                "baseline_portability_evidence_only" if not error else "untested"
            ),
        }
        write_json_atomic(destination, receipt)
        return receipt


def task_summary(task: dict[str, Any], receipt: dict[str, Any] | None, reason: str | None = None) -> dict[str, Any]:
    passed = receipt is not None and receipt["passed"]
    return {
        "task_id": task["task_id"],
        "item_id": task["item_id"],
        "track": task["track"],
        "source_bytes": task["source_bytes"],
        "artifact_bytes": receipt["artifact_bytes"] if receipt else None,
        "artifact_sha256": receipt["artifact_sha256"] if receipt else None,
        "exact_second_host_decode": passed,
        "portability_status": "verified_second_host_decode" if passed else "not_verified",
        "formal_ceiling_admitted": passed,
        "execution_status": "decoded_exactly" if passed else "unavailable_or_failed",
        "reason": reason if reason is not None else (receipt["error"] if receipt else None),
        "axiom_outcome": "baseline_portability_evidence_only" if passed else "untested",
    }


def build_attempt(
    *,
    bindings: dict[str, str],
    primary_host: dict[str, Any],
    second_host: dict[str, Any],
    timeout_seconds: float,
    tasks: list[dict[str, Any]],
    family_budget_hours: float,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout must be a positive finite number")
    return {
        "schema_version": 1,
        "name": "text-source-research-nncp-second-host-decode-v1",
        "completed": False,
        "bindings": bindings,
        "primary_host": primary_host,
        "second_host": second_host,
        "timeout_seconds_per_operation": timeout_seconds,
        "maximum_wall_hours_per_track": family_budget_hours,
        "task_ids": [task["task_id"] for task in tasks],
        "claim_ceiling": (
            "NNCP portability evidence only; this is not an Axiom result or win."
        ),
    }


def execute(
    *,
    plan_path: Path,
    primary_output: Path,
    second_toolchain_receipt_path: Path,
    second_tools_root: Path,
    output: Path,
    timeout_seconds: float,
) -> Path:
    plan, tasks, primary_results, artifacts = primary_tasks(plan_path, primary_output)
    second_receipt = read_canonical_json(second_toolchain_receipt_path)
    validation = TOOLCHAIN.validate(
        plan_path, second_toolchain_receipt_path, second_tools_root
    )
    if (
        second_receipt["host"]["host_class"] != HOST_CLASS
        or second_receipt["host"]["host_id"] == primary_results["host"]["host_id"]
        or len(second_receipt["profiles"]) != 1
        or second_receipt["profiles"][0]["profile_id"] != PROFILE_ID
        or second_receipt["profiles"][0]["status"] != "available"
    ):
        raise ValueError("second NNCP host/toolchain identity is invalid or not distinct")
    executable, unavailable = RUNNER.resolve_profile(
        second_receipt["profiles"][0], second_tools_root
    )
    if executable is None or unavailable is not None:
        raise ValueError("second NNCP host has no available executable")
    bindings = {
        "plan_sha256": sha256_file(plan_path),
        "primary_results_sha256": sha256_file(primary_output / "results.json"),
        "primary_artifact_manifest_sha256": primary_results[
            "retained_artifact_manifest_sha256"
        ],
        "second_toolchain_receipt_sha256": sha256_file(
            second_toolchain_receipt_path
        ),
    }
    family_budget_hours = float(
        plan["measurement_policy"]["maximum_wall_hours_per_family_per_codec"]
    )
    attempt = build_attempt(
        bindings=bindings,
        primary_host=primary_results["host"],
        second_host=second_receipt["host"],
        timeout_seconds=timeout_seconds,
        tasks=tasks,
        family_budget_hours=family_budget_hours,
    )
    output.mkdir(parents=True, exist_ok=True)
    attempt_path = output / "attempt.json"
    if attempt_path.exists():
        if read_canonical_json(attempt_path) != attempt:
            raise ValueError("existing second-host attempt differs")
    else:
        write_json_atomic(attempt_path, attempt)
    artifact_map = {
        task["task_id"]: RUNNER.retained_artifact_path(primary_output, task)
        for task in tasks
    }
    if set(artifact_map.values()) != artifacts:
        raise ValueError("primary artifact map differs from the frozen NNCP task roster")
    budget_seconds = family_budget_hours * 3600.0
    used: dict[str, float] = {}
    summaries = []
    receipt_count = 0
    for task in tasks:
        remaining = budget_seconds - used.get(task["track"], 0.0)
        if remaining <= 0:
            summaries.append(
                task_summary(task, None, "second-host track wall budget exhausted")
            )
            continue
        receipt = run_decode(
            output=output,
            task=task,
            artifact=artifact_map[task["task_id"]],
            executable=executable,
            tools_root=second_tools_root,
            bindings=bindings,
            second_host=second_receipt["host"],
            timeout_seconds=timeout_seconds,
            remaining_budget_seconds=remaining,
        )
        used[task["track"]] = used.get(task["track"], 0.0) + (
            receipt["decompression"]["wall_ns"] / 1e9
        )
        summaries.append(task_summary(task, receipt))
        receipt_count += 1
    all_exact = len(summaries) == 7 and all(
        row["exact_second_host_decode"] for row in summaries
    )
    result = attempt | {
        "completed": True,
        "toolchain_validation": validation,
        "receipt_count": receipt_count,
        "tasks": summaries,
        "all_nncp_second_host_decodes_exact": all_exact,
        "formal_nncp_ceiling_admitted": all_exact,
        "axiom_wins": 0,
    }
    result_path = output / "results.json"
    write_json_atomic(result_path, result)
    validate_output(
        plan_path=plan_path,
        primary_output=primary_output,
        second_toolchain_receipt_path=second_toolchain_receipt_path,
        second_tools_root=second_tools_root,
        output=output,
    )
    return result_path


def validate_output(
    *,
    plan_path: Path,
    primary_output: Path,
    second_toolchain_receipt_path: Path,
    second_tools_root: Path,
    output: Path,
) -> dict[str, Any]:
    plan, tasks, primary_results, artifacts = primary_tasks(plan_path, primary_output)
    second_receipt = read_canonical_json(second_toolchain_receipt_path)
    validation = TOOLCHAIN.validate(
        plan_path, second_toolchain_receipt_path, second_tools_root
    )
    if (
        second_receipt["host"]["host_class"] != HOST_CLASS
        or second_receipt["host"]["host_id"] == primary_results["host"]["host_id"]
        or second_receipt["profiles"][0]["profile_id"] != PROFILE_ID
        or second_receipt["profiles"][0]["status"] != "available"
    ):
        raise ValueError("second NNCP host/toolchain identity is invalid or not distinct")
    executable, unavailable = RUNNER.resolve_profile(
        second_receipt["profiles"][0], second_tools_root
    )
    if executable is None or unavailable is not None:
        raise ValueError("second NNCP host has no available executable")
    attempt = read_canonical_json(output / "attempt.json")
    results = read_canonical_json(output / "results.json")
    bindings = {
        "plan_sha256": sha256_file(plan_path),
        "primary_results_sha256": sha256_file(primary_output / "results.json"),
        "primary_artifact_manifest_sha256": primary_results[
            "retained_artifact_manifest_sha256"
        ],
        "second_toolchain_receipt_sha256": sha256_file(
            second_toolchain_receipt_path
        ),
    }
    family_budget_hours = float(
        plan["measurement_policy"]["maximum_wall_hours_per_family_per_codec"]
    )
    expected_attempt = build_attempt(
        bindings=bindings,
        primary_host=primary_results["host"],
        second_host=second_receipt["host"],
        timeout_seconds=attempt.get("timeout_seconds_per_operation"),
        tasks=tasks,
        family_budget_hours=family_budget_hours,
    )
    if attempt != expected_attempt:
        raise ValueError("second-host attempt differs from its bindings")
    receipts_root = output / "receipts"
    actual_files = set()
    actual_dirs = set()
    if receipts_root.exists():
        if receipts_root.is_symlink() or not receipts_root.is_dir():
            raise ValueError("second-host receipt root is invalid")
        for path in receipts_root.rglob("*"):
            if path.is_symlink():
                raise ValueError("second-host output contains a symlink")
            if path.is_file():
                actual_files.add(path)
            elif path.is_dir():
                actual_dirs.add(path)
            else:
                raise ValueError("second-host output contains a special file")
    artifact_map = {
        task["task_id"]: RUNNER.retained_artifact_path(primary_output, task)
        for task in tasks
    }
    if set(artifact_map.values()) != artifacts:
        raise ValueError("primary artifact map differs")
    budget_seconds = family_budget_hours * 3600.0
    used: dict[str, float] = {}
    summaries = []
    expected_files = set()
    for task in tasks:
        remaining = budget_seconds - used.get(task["track"], 0.0)
        if remaining <= 0:
            summaries.append(
                task_summary(task, None, "second-host track wall budget exhausted")
            )
            continue
        path = receipt_path(output, task)
        if path not in actual_files:
            raise ValueError(f"second-host decode receipt is missing: {path}")
        artifact = artifact_map[task["task_id"]]
        work = Path("$WORK")
        command = RUNNER.materialize_command(
            task["decompression_command"],
            executable=executable,
            work=work,
            tools_root=second_tools_root,
        )
        expected_command = RUNNER.sanitize_process(
            {"command": command}, work, second_tools_root
        )["command"]
        receipt = read_canonical_json(path)
        validate_receipt(
            receipt,
            expected_identity=identity(
                task=task,
                artifact=artifact,
                bindings=bindings,
                second_host=second_receipt["host"],
            ),
            expected_command=expected_command,
            remaining_budget_seconds=remaining,
        )
        used[task["track"]] = used.get(task["track"], 0.0) + (
            receipt["decompression"]["wall_ns"] / 1e9
        )
        summaries.append(task_summary(task, receipt))
        expected_files.add(path)
    if actual_files != expected_files or actual_dirs:
        raise ValueError("second-host receipt file roster contains extras")
    all_exact = len(summaries) == 7 and all(
        row["exact_second_host_decode"] for row in summaries
    )
    expected_results = expected_attempt | {
        "completed": True,
        "toolchain_validation": validation,
        "receipt_count": len(expected_files),
        "tasks": summaries,
        "all_nncp_second_host_decodes_exact": all_exact,
        "formal_nncp_ceiling_admitted": all_exact,
        "axiom_wins": 0,
    }
    if results != expected_results:
        raise ValueError("second-host result does not reconstruct from receipts")
    expected_top = {"attempt.json", "results.json"}
    if expected_files:
        expected_top.add("receipts")
    if {path.name for path in output.iterdir()} != expected_top or any(
        path.is_symlink() for path in output.iterdir()
    ):
        raise ValueError("second-host top-level file roster differs")
    return {
        "verified": True,
        "primary_host_id": primary_results["host"]["host_id"],
        "second_host_id": second_receipt["host"]["host_id"],
        "receipt_count": len(expected_files),
        "all_nncp_second_host_decodes_exact": all_exact,
        "formal_nncp_ceiling_admitted": all_exact,
        "axiom_wins": 0,
        "results_sha256": sha256_file(output / "results.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--primary-output", type=Path, default=DEFAULT_PRIMARY)
    parser.add_argument("--second-toolchain-receipt", type=Path, required=True)
    parser.add_argument("--second-tools-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=43_200.0)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_only:
            result = validate_output(
                plan_path=args.plan,
                primary_output=args.primary_output,
                second_toolchain_receipt_path=args.second_toolchain_receipt,
                second_tools_root=args.second_tools_root,
                output=args.output,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                execute(
                    plan_path=args.plan,
                    primary_output=args.primary_output,
                    second_toolchain_receipt_path=args.second_toolchain_receipt,
                    second_tools_root=args.second_tools_root,
                    output=args.output,
                    timeout_seconds=args.timeout_seconds,
                )
            )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"second-host NNCP decode failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
