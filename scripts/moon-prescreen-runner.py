#!/usr/bin/env python3
"""Config-driven prescreen sweep runner for the moonshot cycle-1 H1 floor arm.

Development-only prescreen infrastructure (Lane 2, the Pareto moonshot). For
each (snapshot x arm) it runs `clab-moon-kernel encode` through the clean
child peak-RSS instrument (`scripts/measure-clean-rss.py`, PR #77), captures
the kernel receipt's projected complete bytes and the clean peak RSS, and
records the cycle-1 draft metric tuple plus the arm's preregistered kill line
and the reference-binary pins. It makes NO kill/nominate decision: it only
produces receipts a later report reads. Everything is `development_only_prescreen`.

Corpora are synthetic or pinned public snapshots supplied by config path; this
runner never reads `corpora/` or any licensed development item, and it verifies
every snapshot's SHA-256 against both the config and the local-references file
before using it (helm tightening #1). A persistent counter enforces the 160
arm-run cycle budget, and any run whose clean peak RSS exceeds 512 MiB or whose
wall time exceeds 600 s is recorded as `killed_by_budget` with partial data
rather than crashing the sweep (helm tightening #5).

Usage:
  python scripts/moon-prescreen-runner.py CONFIG.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_MEASURE_SCRIPT = REPOSITORY / "scripts" / "measure-clean-rss.py"

CONFIG_SCHEMA = "moon-prescreen-runner-config-v1"
REFERENCES_SCHEMA = "moon-local-references-v1"
RUN_RECEIPT_SCHEMA = "moon-prescreen-run-receipt-v1"
SWEEP_SCHEMA = "moon-prescreen-sweep-v1"
BUDGET_SCHEMA = "moon-prescreen-budget-v1"
EVIDENCE_STAGE = "development_only_prescreen"

# Hard cycle budget and per-run limits (helm tightening #5).
RUN_BUDGET_CAP = 160
PEAK_RSS_LIMIT_BYTES = 512 * 1024 * 1024
WALL_LIMIT_SECONDS = 600.0
# Grace beyond the wall limit before the wrapper subprocess is force-killed.
WALL_TIMEOUT_GRACE_SECONDS = 30.0

# Preregistered per-arm kill lines (cycle-1 draft section 2). Echoed verbatim
# into every receipt so a later kill/nominate report is mechanical. These are
# data strings, not decisions: the runner computes ratios but never claims a
# kill or a nomination.
KILL_LINES = {
    "h1-floor": (
        "Kill if projected complete bytes exceed 1.10x local zpaq -m5 -B16 on at "
        "least two public snapshots at <=256 MiB declared state, OR peak decode "
        "RSS exceeds 512 MiB."
    ),
    # The draft wrote this baseline as "max(H1-alone, H5/M3-alone)"; helm
    # deferred H5, so M3 is the cycle-1 reuse baseline and the line names M3
    # alone. Intentional recorded simplification, not a drift.
    "h6-hybrid": (
        "Kill if the hybrid does not beat max(H1-alone, M3-alone) by >= 3% on the "
        "public set."
    ),
    # Draft cycle-1 §2-H8 ("Kill if the frozen mixer loses to the adaptive
    # mixer by > 2% on the unseen month"), phrased mechanically. Byte-identical
    # to the kernel's H8_KILL_CRITERION.
    "h8-static-mixer": (
        "Kill if frozen-mixer complete bytes exceed 1.02x adaptive H1 complete "
        "bytes on the unseen month."
    ),
}


class ConfigError(SystemExit):
    """A configuration or integrity failure that must refuse the whole run."""


class BudgetExhausted(SystemExit):
    """The persistent run budget is fully consumed; refuse further runs."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path, what: str) -> dict:
    if not path.is_file():
        raise ConfigError(f"{what} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{what} is not valid JSON ({path}): {error}") from error
    if not isinstance(value, dict):
        raise ConfigError(f"{what} must be a JSON object: {path}")
    return value


def require(mapping: dict, key: str, what: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{what} is missing required key '{key}'")
    return mapping[key]


def resolve_path(base: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (base / candidate)


class Config:
    """A validated runner configuration."""

    def __init__(self, path: Path) -> None:
        raw_bytes = path.read_bytes()
        self.sha256 = sha256_bytes(raw_bytes)
        raw = load_json(path, "config")
        if raw.get("schema") != CONFIG_SCHEMA:
            raise ConfigError(
                f"config schema must be '{CONFIG_SCHEMA}', got {raw.get('schema')!r}"
            )
        base = path.resolve().parent

        kernel_command = require(raw, "kernel_command", "config")
        if isinstance(kernel_command, str):
            kernel_command = [kernel_command]
        if not isinstance(kernel_command, list) or not kernel_command:
            raise ConfigError(
                "config 'kernel_command' must be a non-empty list or string"
            )
        self.kernel_command = [str(part) for part in kernel_command]

        measure = raw.get("measure_rss_script")
        self.measure_script = (
            resolve_path(base, measure) if measure else DEFAULT_MEASURE_SCRIPT
        )
        if not self.measure_script.is_file():
            raise ConfigError(f"measure_rss_script not found: {self.measure_script}")

        self.references_path = resolve_path(base, require(raw, "references", "config"))
        self.budget_state = resolve_path(base, require(raw, "budget_state", "config"))
        self.output_dir = resolve_path(base, require(raw, "output_dir", "config"))

        arms = require(raw, "arms", "config")
        if not isinstance(arms, list) or not arms:
            raise ConfigError("config 'arms' must be a non-empty list")
        for arm in arms:
            if arm not in KILL_LINES:
                raise ConfigError(
                    f"unknown arm '{arm}': no preregistered kill line "
                    f"(known: {sorted(KILL_LINES)})"
                )
        self.arms = [str(arm) for arm in arms]

        snapshots = require(raw, "snapshots", "config")
        if not isinstance(snapshots, list) or not snapshots:
            raise ConfigError("config 'snapshots' must be a non-empty list")
        self.snapshots = []
        for index, snapshot in enumerate(snapshots):
            name = str(require(snapshot, "name", "snapshot"))
            snapshot_path = resolve_path(base, require(snapshot, "path", "snapshot"))
            sha = str(require(snapshot, "sha256", "snapshot"))
            item_index = int(snapshot.get("item_index", index))
            if not 0 <= item_index <= 255:
                raise ConfigError(f"snapshot '{name}' item_index must be 0..255")
            self.snapshots.append(
                {
                    "name": name,
                    "path": snapshot_path,
                    "sha256": sha,
                    "item_index": item_index,
                }
            )


class References:
    """The validated local-references file (schema moon-local-references-v1)."""

    def __init__(self, path: Path) -> None:
        raw = load_json(path, "references")
        if raw.get("schema") != REFERENCES_SCHEMA:
            raise ConfigError(
                f"references schema must be '{REFERENCES_SCHEMA}', got {raw.get('schema')!r}"
            )
        self.sha256 = sha256_bytes(path.read_bytes())
        self.kanzi = self._binary(raw, "kanzi")
        self.zpaq = self._binary(raw, "zpaq")
        snapshots = require(raw, "snapshots", "references")
        if not isinstance(snapshots, dict):
            raise ConfigError("references 'snapshots' must be an object")
        self.snapshots = snapshots

    @staticmethod
    def _binary(raw: dict, key: str) -> dict:
        entry = require(raw, key, "references")
        for field in ("path", "sha256", "version", "args"):
            require(entry, field, f"references '{key}'")
        return entry

    def snapshot(self, name: str) -> dict:
        if name not in self.snapshots:
            raise ConfigError(f"references has no entry for snapshot '{name}'")
        entry = self.snapshots[name]
        for field in (
            "source_bytes",
            "source_sha256",
            "kanzi_max_bytes",
            "kanzi_seconds",
            "zpaq_m54_bytes",
            "zpaq_seconds",
        ):
            require(entry, field, f"references snapshot '{name}'")
        return entry


def verify_snapshots(config: Config, references: References) -> dict:
    """Verify every snapshot file against both the config and the references
    SHA-256 before any arm runs. Refuses on any mismatch."""
    verified = {}
    for snapshot in config.snapshots:
        name = snapshot["name"]
        path = snapshot["path"]
        if not path.is_file():
            raise ConfigError(f"snapshot '{name}' file not found: {path}")
        actual = sha256_file(path)
        if actual != snapshot["sha256"]:
            raise ConfigError(
                f"snapshot '{name}' SHA-256 mismatch vs config: "
                f"file {actual} != declared {snapshot['sha256']}"
            )
        reference = references.snapshot(name)
        if actual != reference["source_sha256"]:
            raise ConfigError(
                f"snapshot '{name}' SHA-256 mismatch vs references: "
                f"file {actual} != source_sha256 {reference['source_sha256']}"
            )
        size = path.stat().st_size
        if size != reference["source_bytes"]:
            raise ConfigError(
                f"snapshot '{name}' size mismatch vs references: "
                f"file {size} != source_bytes {reference['source_bytes']}"
            )
        verified[name] = reference
    return verified


def read_budget(state_path: Path) -> int:
    if not state_path.is_file():
        return 0
    raw = load_json(state_path, "budget state")
    return int(raw.get("runs_consumed", 0))


def write_budget(state_path: Path, consumed: int) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema": BUDGET_SCHEMA,
                "runs_consumed": consumed,
                "cap": RUN_BUDGET_CAP,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def execute_encode(
    config: Config,
    snapshot: dict,
    arm: str,
    tape_path: Path,
    kernel_receipt_path: Path,
    rss_report_path: Path,
) -> tuple[dict, Optional[dict]]:
    """Run the kernel encode through the clean-RSS instrument. Returns the
    clean-RSS report (always) and the kernel receipt (None if it was not
    written). Never raises on a failed target: failure is data."""
    # The clean-RSS instrument reaps the child with os.wait4, which POSIX
    # provides and Windows does not. Fail closed with a clear message rather
    # than mismeasure the sweep.
    if not hasattr(os, "wait4"):
        raise ConfigError(
            "the prescreen runner requires POSIX os.wait4 for clean peak-RSS "
            "measurement (scripts/measure-clean-rss.py); this platform lacks it"
        )
    kernel_command = config.kernel_command + [
        "encode",
        "--arm",
        arm,
        "--item-index",
        str(snapshot["item_index"]),
        "--input",
        str(snapshot["path"]),
        "--tape-out",
        str(tape_path),
        "--receipt-out",
        str(kernel_receipt_path),
        "--force",
    ]
    measure_command = [
        sys.executable,
        str(config.measure_script),
        "--json-out",
        str(rss_report_path),
        "--",
    ] + kernel_command

    started = time.perf_counter_ns()
    timed_out = False
    try:
        subprocess.run(
            measure_command,
            timeout=WALL_LIMIT_SECONDS + WALL_TIMEOUT_GRACE_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
    fallback_wall_ns = time.perf_counter_ns() - started

    if rss_report_path.is_file() and not timed_out:
        report = json.loads(rss_report_path.read_text(encoding="utf-8"))
    else:
        report = {
            "maxrss_bytes": None,
            "shim_maxrss_bytes": None,
            "wall_ns": fallback_wall_ns,
            "exit_code": 124 if timed_out else 1,
        }
    report["timed_out"] = timed_out

    kernel_receipt = None
    if kernel_receipt_path.is_file():
        try:
            kernel_receipt = json.loads(kernel_receipt_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            kernel_receipt = None
    return report, kernel_receipt


def classify_run(
    report: dict, kernel_receipt: Optional[dict]
) -> tuple[str, Optional[str]]:
    """Assign a run status and kill reason from the measurement and receipt.
    Never claims prescreen kill/nominate; only budget bookkeeping."""
    if report.get("timed_out"):
        return "killed_by_budget", "wall_timeout"
    if kernel_receipt is None or report.get("exit_code") not in (0, None):
        return "encode_failed", "encode_nonzero_exit"
    wall_ns = report.get("wall_ns")
    if wall_ns is not None and wall_ns / 1e9 > WALL_LIMIT_SECONDS:
        return "killed_by_budget", "wall_over_600_s"
    peak = report.get("maxrss_bytes")
    if peak is not None and peak > PEAK_RSS_LIMIT_BYTES:
        return "killed_by_budget", "peak_rss_over_512_mib"
    return "measured", None


def _ratio(numerator: Optional[int], denominator: Any) -> Optional[float]:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def assemble_receipt(
    references: References,
    snapshot_name: str,
    arm: str,
    reference_entry: dict,
    report: dict,
    kernel_receipt: Optional[dict],
    run_index: int,
) -> dict:
    """Build one run receipt (the cycle-1 draft metric tuple plus pins and the
    echoed kill line). Pure: no I/O, deterministic from its inputs."""
    status, kill_reason = classify_run(report, kernel_receipt)

    complete_bytes = None
    decode_matches = None
    declared_state = None
    if kernel_receipt is not None:
        projection = kernel_receipt.get("item_projection", {})
        complete_bytes = projection.get("complete_bytes")
        decode_matches = kernel_receipt.get("decode_matches_source")
        declared_state = kernel_receipt.get("declared_model_state_bytes")

    wall_ns = report.get("wall_ns")
    wall_seconds = None if wall_ns is None else wall_ns / 1e9
    ratio_zpaq = _ratio(complete_bytes, reference_entry["zpaq_m54_bytes"])

    return {
        "schema": RUN_RECEIPT_SCHEMA,
        "evidence_stage": EVIDENCE_STAGE,
        "snapshot": snapshot_name,
        "arm": arm,
        "run_index": run_index,
        "status": status,
        "kill_reason": kill_reason,
        "projected_complete_bytes": complete_bytes,
        "ratio_vs_local_kanzi": _ratio(
            complete_bytes, reference_entry["kanzi_max_bytes"]
        ),
        "ratio_vs_local_zpaq16": ratio_zpaq,
        "peak_rss_bytes": report.get("maxrss_bytes"),
        "rss_shim_floor_bytes": report.get("shim_maxrss_bytes"),
        "wall_seconds": wall_seconds,
        "decode_matches": decode_matches,
        "declared_model_state_bytes": declared_state,
        "predicted_kill_criterion": KILL_LINES[arm],
        "references": {
            "snapshot_source_bytes": reference_entry["source_bytes"],
            "snapshot_source_sha256": reference_entry["source_sha256"],
            "kanzi": {
                "path": references.kanzi["path"],
                "sha256": references.kanzi["sha256"],
                "version": references.kanzi["version"],
                "args": references.kanzi["args"],
                "max_bytes": reference_entry["kanzi_max_bytes"],
                "seconds": reference_entry["kanzi_seconds"],
            },
            "zpaq": {
                "path": references.zpaq["path"],
                "sha256": references.zpaq["sha256"],
                "version": references.zpaq["version"],
                "args": references.zpaq["args"],
                "m54_bytes": reference_entry["zpaq_m54_bytes"],
                "seconds": reference_entry["zpaq_seconds"],
            },
        },
    }


def sweep(
    config: Config,
    references: References,
    verified: dict,
    execute: Callable[..., tuple[dict, Optional[dict]]] = execute_encode,
) -> dict:
    """Run every (snapshot x arm), enforcing the persistent budget, writing one
    receipt per run and a sweep summary. Returns the summary dict."""
    consumed_before = read_budget(config.budget_state)
    if consumed_before >= RUN_BUDGET_CAP:
        raise BudgetExhausted(
            f"run budget exhausted ({consumed_before}/{RUN_BUDGET_CAP} consumed); "
            "refusing further arm-runs for this cycle"
        )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    consumed = consumed_before
    runs: list[dict] = []

    for snapshot in config.snapshots:
        for arm in config.arms:
            name = snapshot["name"]
            if consumed >= RUN_BUDGET_CAP:
                runs.append(
                    {
                        "snapshot": name,
                        "arm": arm,
                        "status": "skipped_budget_cap",
                        "receipt_path": None,
                    }
                )
                continue

            tape_path = config.output_dir / f"{name}__{arm}.tape"
            kernel_receipt_path = (
                config.output_dir / f"{name}__{arm}.kernel-receipt.json"
            )
            rss_report_path = config.output_dir / f"{name}__{arm}.rss.json"
            report, kernel_receipt = execute(
                config,
                snapshot,
                arm,
                tape_path,
                kernel_receipt_path,
                rss_report_path,
            )
            consumed += 1
            receipt = assemble_receipt(
                references,
                name,
                arm,
                verified[name],
                report,
                kernel_receipt,
                run_index=consumed,
            )
            receipt_path = config.output_dir / f"{name}__{arm}.receipt.json"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_budget(config.budget_state, consumed)
            runs.append(
                {
                    "snapshot": name,
                    "arm": arm,
                    "status": receipt["status"],
                    "receipt_path": str(receipt_path),
                }
            )

    summary = {
        "schema": SWEEP_SCHEMA,
        "evidence_stage": EVIDENCE_STAGE,
        "config_sha256": config.sha256,
        "references_sha256": references.sha256,
        "budget": {
            "consumed_before": consumed_before,
            "consumed_after": consumed,
            "cap": RUN_BUDGET_CAP,
        },
        "runs": runs,
    }
    summary_path = config.output_dir / "sweep-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def run(config_path: Path) -> dict:
    config = Config(config_path)
    references = References(config.references_path)
    verified = verify_snapshots(config, references)
    return sweep(config, references, verified)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("config", type=Path, help="runner config JSON path")
    arguments = parser.parse_args(argv)
    summary = run(arguments.config)
    consumed = summary["budget"]["consumed_after"]
    measured = sum(1 for entry in summary["runs"] if entry["status"] == "measured")
    print(
        f"prescreen sweep complete: {len(summary['runs'])} runs "
        f"({measured} measured); budget {consumed}/{RUN_BUDGET_CAP}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
