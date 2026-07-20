#!/usr/bin/env python3
"""Aggregate every verified host slice of the text/source research ceiling."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import tempfile
from types import ModuleType
from typing import Any, NamedTuple


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-research-ceiling-v1.json"
HOST_CLASS_ORDER = [
    "local-macos-18-gib-rss-cap",
    "larger-isolated-memory-host",
    "larger-isolated-memory-host-portable-o3-build",
    "authorized-linux-cuda-host-plus-second-host-decode",
]
NNCP_PROFILE = "nncp-3.3-transformer"


class HostRun(NamedTuple):
    toolchain_receipt: Path
    tools_root: Path
    output: Path


class SecondHostRun(NamedTuple):
    toolchain_receipt: Path
    tools_root: Path
    output: Path


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_script(
    "research_ceiling_runner_for_aggregate",
    REPOSITORY / "scripts" / "benchmark-text-source-research-ceiling.py",
)
SECOND_HOST = load_script(
    "research_second_host_for_aggregate",
    REPOSITORY / "scripts" / "verify-text-source-research-second-host-decode.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical_json(path: Path) -> dict[str, Any]:
    return RUNNER.read_canonical_json(path)


def median_int(values: list[int]) -> int | float:
    value = statistics.median(values)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def measured_process_summary(
    output: Path, task: dict[str, Any], summary: dict[str, Any]
) -> dict[str, int | float | None]:
    empty = {
        "compression_wall_ns_median": None,
        "decompression_wall_ns_median": None,
        "compression_cpu_ns_median": None,
        "decompression_cpu_ns_median": None,
        "compression_peak_rss_bytes": None,
        "decompression_peak_rss_bytes": None,
    }
    if not summary["complete"] or not summary["deterministic"]:
        return empty
    receipts = [
        read_canonical_json(RUNNER.trial_path(output, task, repetition))
        for repetition in (1, 2)
    ]
    if any(not row["passed"] or row["decompression"] is None for row in receipts):
        raise ValueError("complete task has an incomplete measured process receipt")
    return {
        "compression_wall_ns_median": median_int(
            [row["compression"]["wall_ns"] for row in receipts]
        ),
        "decompression_wall_ns_median": median_int(
            [row["decompression"]["wall_ns"] for row in receipts]
        ),
        "compression_cpu_ns_median": median_int(
            [row["compression"]["cpu_ns"] for row in receipts]
        ),
        "decompression_cpu_ns_median": median_int(
            [row["decompression"]["cpu_ns"] for row in receipts]
        ),
        "compression_peak_rss_bytes": max(
            row["compression"]["peak_rss_bytes"] for row in receipts
        ),
        "decompression_peak_rss_bytes": max(
            row["decompression"]["peak_rss_bytes"] for row in receipts
        ),
    }


def second_host_fields() -> dict[str, Any]:
    return {
        "second_host_decode_status": "not_required",
        "second_host_decode_wall_ns": None,
        "second_host_decode_cpu_ns": None,
        "second_host_decode_peak_rss_bytes": None,
    }


def apply_second_host(
    row: dict[str, Any], second_summary: dict[str, Any] | None
) -> dict[str, Any]:
    updated = dict(row)
    if row["profile_id"] != NNCP_PROFILE:
        updated.update(second_host_fields())
        return updated
    if second_summary is None:
        updated.update(
            {
                "second_host_decode_status": "pending",
                "second_host_decode_wall_ns": None,
                "second_host_decode_cpu_ns": None,
                "second_host_decode_peak_rss_bytes": None,
            }
        )
        return updated
    exact = second_summary["exact_second_host_decode"]
    process = second_summary.get("decompression")
    updated.update(
        {
            "portability_status": (
                "verified_second_host_decode" if exact else "not_verified"
            ),
            "formal_ceiling_admitted": bool(
                exact
                and row["complete"]
                and row["deterministic"]
                and row["formal_ceiling_eligible"]
            ),
            "second_host_decode_status": "exact" if exact else "failed",
            "second_host_decode_wall_ns": (
                process["wall_ns"] if exact and process is not None else None
            ),
            "second_host_decode_cpu_ns": (
                process["cpu_ns"] if exact and process is not None else None
            ),
            "second_host_decode_peak_rss_bytes": (
                process["peak_rss_bytes"] if exact and process is not None else None
            ),
        }
    )
    return updated


def build_aggregate(
    *,
    plan_path: Path,
    host_runs: list[HostRun],
    second_host_run: SecondHostRun | None,
) -> dict[str, Any]:
    plan = read_canonical_json(plan_path)
    if (
        plan.get("name") != "text-source-research-ceiling-execution-plan-v1"
        or len(plan.get("tasks", [])) != 35
        or plan.get("execution_profile_roster") is None
    ):
        raise ValueError("research-ceiling plan identity is invalid")
    plan_sha256 = sha256_file(plan_path)
    task_plan = {row["task_id"]: row for row in plan["tasks"]}
    if len(task_plan) != 35:
        raise ValueError("research-ceiling task identities are not unique")

    host_records: dict[str, dict[str, Any]] = {}
    task_rows: dict[str, dict[str, Any]] = {}
    primary_nncp: HostRun | None = None
    for host_run in host_runs:
        verification = RUNNER.validate_output(
            plan_path=plan_path,
            toolchain_receipt_path=host_run.toolchain_receipt,
            tools_root=host_run.tools_root,
            output=host_run.output,
        )
        receipt = read_canonical_json(host_run.toolchain_receipt)
        results_path = host_run.output / "results.json"
        results = read_canonical_json(results_path)
        host = receipt["host"]
        host_class = host["host_class"]
        if host_class not in HOST_CLASS_ORDER or host_class in host_records:
            raise ValueError("host-run roster contains an unknown or duplicate class")
        if results["host"] != host or verification["host_id"] != host["host_id"]:
            raise ValueError("host result and toolchain identities differ")
        expected_tasks = [
            row for row in plan["tasks"] if row["host_class"] == host_class
        ]
        summaries = {row["task_id"]: row for row in results["tasks"]}
        if set(summaries) != {row["task_id"] for row in expected_tasks}:
            raise ValueError("host result task roster differs from the plan")
        for task in expected_tasks:
            task_id = task["task_id"]
            if task_id in task_rows:
                raise ValueError("research task is supplied by more than one host")
            summary = summaries[task_id]
            row = dict(summary)
            row.update(measured_process_summary(host_run.output, task, summary))
            row.update(
                {
                    "host_id": host["host_id"],
                    "host_class": host_class,
                    "runner_comparability": (
                        "size is cross-host comparable; speed and RSS are host-scoped"
                    ),
                }
            )
            task_rows[task_id] = row
        host_records[host_class] = {
            "host": host,
            "profile_ids": results["profile_ids"],
            "toolchain_receipt_sha256": sha256_file(host_run.toolchain_receipt),
            "results_sha256": sha256_file(results_path),
            "trial_count": results["trial_count"],
            "retained_artifact_count": results["retained_artifact_count"],
            "retained_artifact_manifest_sha256": results[
                "retained_artifact_manifest_sha256"
            ],
            "all_host_formal_tasks_complete": results[
                "all_host_formal_tasks_complete"
            ],
            "axiom_wins": 0,
        }
        if NNCP_PROFILE in results["profile_ids"]:
            primary_nncp = host_run

    if set(host_records) != set(HOST_CLASS_ORDER) or set(task_rows) != set(task_plan):
        raise ValueError("all four host classes and all 35 tasks are required")

    second_record = None
    second_tasks: dict[str, dict[str, Any]] = {}
    if second_host_run is not None:
        if primary_nncp is None:
            raise ValueError("second-host decode has no primary NNCP host run")
        verification = SECOND_HOST.validate_output(
            plan_path=plan_path,
            primary_output=primary_nncp.output,
            second_toolchain_receipt_path=second_host_run.toolchain_receipt,
            second_tools_root=second_host_run.tools_root,
            output=second_host_run.output,
        )
        results_path = second_host_run.output / "results.json"
        results = read_canonical_json(results_path)
        second_tasks = {row["task_id"]: row for row in results["tasks"]}
        nncp_tasks = [
            row for row in plan["tasks"] if row["profile_id"] == NNCP_PROFILE
        ]
        expected_nncp = {row["task_id"] for row in nncp_tasks}
        if set(second_tasks) != expected_nncp:
            raise ValueError("second-host decode task roster differs from NNCP plan")
        for task in nncp_tasks:
            summary = dict(second_tasks[task["task_id"]])
            if summary["exact_second_host_decode"]:
                receipt = read_canonical_json(
                    SECOND_HOST.receipt_path(second_host_run.output, task)
                )
                summary["decompression"] = receipt["decompression"]
            else:
                summary["decompression"] = None
            second_tasks[task["task_id"]] = summary
        second_record = {
            "primary_host_id": verification["primary_host_id"],
            "second_host_id": verification["second_host_id"],
            "toolchain_receipt_sha256": sha256_file(
                second_host_run.toolchain_receipt
            ),
            "results_sha256": sha256_file(results_path),
            "receipt_count": verification["receipt_count"],
            "all_nncp_second_host_decodes_exact": verification[
                "all_nncp_second_host_decodes_exact"
            ],
            "formal_nncp_ceiling_admitted": verification[
                "formal_nncp_ceiling_admitted"
            ],
            "axiom_wins": 0,
        }

    ordered_tasks = [
        apply_second_host(task_rows[task["task_id"]], second_tasks.get(task["task_id"]))
        for task in plan["tasks"]
    ]
    formal = [row for row in ordered_tasks if row["formal_ceiling_eligible"]]
    if len(formal) != 28:
        raise ValueError("formal research-ceiling task count differs from protocol")
    all_formal = all(row["formal_ceiling_admitted"] for row in formal)
    trial_count = sum(row["trial_count"] for row in host_records.values())
    if type(trial_count) is not int or trial_count < 0:
        raise ValueError("aggregate trial count is invalid")
    return {
        "schema_version": 1,
        "name": "text-source-research-ceiling-aggregate-v1",
        "completed": True,
        "bindings": {
            "plan_sha256": plan_sha256,
            "baseline_results_sha256": plan["bindings"][
                "baseline_results_sha256"
            ],
            "corpus_manifest_sha256": plan["bindings"][
                "corpus_manifest_sha256"
            ],
            "repository_commit": plan["bindings"]["repository_commit"],
        },
        "host_runs": [host_records[host_class] for host_class in HOST_CLASS_ORDER],
        "second_host_decode": second_record,
        "trial_count": trial_count,
        "task_count": len(ordered_tasks),
        "formal_task_count": len(formal),
        "tasks": ordered_tasks,
        "all_formal_ceiling_tasks_admitted": all_formal,
        "research_ceiling_status": (
            "formal_complete" if all_formal else "incomplete_or_unavailable"
        ),
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "axiom_wins": 0,
        "claim_ceiling": (
            "Development baseline evidence only. Exact research-baseline sizes may "
            "bound later Axiom hypotheses, but Axiom remains untested; cross-host speed "
            "and RSS values are descriptive rather than rank-comparable, and no "
            "category-win, world-best, or state-of-the-art claim is supported."
        ),
    }


def validate_aggregate(
    *,
    aggregate_path: Path,
    plan_path: Path,
    host_runs: list[HostRun],
    second_host_run: SecondHostRun | None,
) -> dict[str, Any]:
    observed = read_canonical_json(aggregate_path)
    expected = build_aggregate(
        plan_path=plan_path,
        host_runs=host_runs,
        second_host_run=second_host_run,
    )
    if observed != expected:
        raise ValueError("aggregate does not reconstruct from verified raw host runs")
    return {
        "verified": True,
        "task_count": observed["task_count"],
        "formal_task_count": observed["formal_task_count"],
        "trial_count": observed["trial_count"],
        "all_formal_ceiling_tasks_admitted": observed[
            "all_formal_ceiling_tasks_admitted"
        ],
        "axiom_wins": 0,
        "aggregate_sha256": sha256_file(aggregate_path),
        "claim_ceiling": observed["claim_ceiling"],
    }


def write_immutable(path: Path, payload: dict[str, Any]) -> Path:
    encoded = RUNNER.PLANNER.json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError("refusing to replace a differing research aggregate")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(encoded)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def parse_host_runs(values: list[list[str]]) -> list[HostRun]:
    return [HostRun(*(Path(value) for value in row)) for row in values]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--host-run",
        action="append",
        nargs=3,
        metavar=("TOOLCHAIN_RECEIPT", "TOOLS_ROOT", "OUTPUT"),
        required=True,
    )
    parser.add_argument(
        "--second-host-run",
        nargs=3,
        metavar=("TOOLCHAIN_RECEIPT", "TOOLS_ROOT", "OUTPUT"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    host_runs = parse_host_runs(args.host_run)
    second_host_run = (
        SecondHostRun(*(Path(value) for value in args.second_host_run))
        if args.second_host_run
        else None
    )
    try:
        payload = build_aggregate(
            plan_path=args.plan,
            host_runs=host_runs,
            second_host_run=second_host_run,
        )
        result = write_immutable(args.output, payload)
        validation = validate_aggregate(
            aggregate_path=result,
            plan_path=args.plan,
            host_runs=host_runs,
            second_host_run=second_host_run,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        statistics.StatisticsError,
    ) as error:
        raise SystemExit(f"research-ceiling aggregation failed: {error}") from error
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
