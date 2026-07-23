#!/usr/bin/env python3
"""Counted-run driver for the H1 loss-decomposition diagnostic.

Development-only prescreen infrastructure (Lane 2, the Pareto moonshot). The
config-driven sweep runner (``scripts/moon-prescreen-runner.py``) only knows how
to drive ``clab-moon-kernel encode``; the loss-decomposition diagnostic is a new
``clab-moon-kernel diagnose-h1`` subcommand, so this thin wrapper drives it while
charging the *same* persistent 160-run cycle budget the runner enforces. It
reuses that runner's ``read_budget`` / ``write_budget`` verbatim, so
``run-budget.json`` is updated byte-for-byte the same way (schema
``moon-prescreen-budget-v1``, incremented once per diagnostic run, capped at
160).

It verifies every snapshot's SHA-256 against both the config and — when a
``references`` file is supplied — the local-references source SHA and size before
reading it, exactly like the sweep runner (helm tightening #1). It makes no
kill/nominate decision and produces only ``development_only_prescreen`` reports.

Usage:
  python scripts/moon-h1-decomposition-run.py CONFIG.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

REPOSITORY = Path(__file__).resolve().parents[1]
RUNNER_SCRIPT = REPOSITORY / "scripts" / "moon-prescreen-runner.py"

CONFIG_SCHEMA = "moon-h1-decomposition-config-v1"
SWEEP_SCHEMA = "moon-h1-decomposition-sweep-v1"
REFERENCES_SCHEMA = "moon-local-references-v1"
EVIDENCE_STAGE = "development_only_prescreen"
DEFAULT_TOP_REGIONS = 16


def _load_runner() -> ModuleType:
    """Load the sweep runner so its budget bookkeeping is reused verbatim."""
    spec = importlib.util.spec_from_file_location(
        "moon_prescreen_runner", RUNNER_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load the prescreen runner: {RUNNER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


class ConfigError(SystemExit):
    """A configuration or integrity failure that refuses the whole run."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    """A validated loss-decomposition run configuration."""

    def __init__(self, path: Path) -> None:
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

        self.budget_state = resolve_path(base, require(raw, "budget_state", "config"))
        self.output_dir = resolve_path(base, require(raw, "output_dir", "config"))

        references = raw.get("references")
        self.references_path = (
            resolve_path(base, references) if references else None
        )

        sse_bucket_bits = int(raw.get("sse_bucket_bits", 17))
        if sse_bucket_bits not in (17, 18):
            raise ConfigError("config 'sse_bucket_bits' must be 17 or 18")
        self.sse_bucket_bits = sse_bucket_bits

        top_regions = int(raw.get("top_regions", DEFAULT_TOP_REGIONS))
        if top_regions < 1:
            raise ConfigError("config 'top_regions' must be positive")
        self.top_regions = top_regions

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


def load_references(path: Optional[Path]) -> Optional[dict]:
    if path is None:
        return None
    raw = load_json(path, "references")
    if raw.get("schema") != REFERENCES_SCHEMA:
        raise ConfigError(
            f"references schema must be '{REFERENCES_SCHEMA}', got {raw.get('schema')!r}"
        )
    snapshots = require(raw, "snapshots", "references")
    if not isinstance(snapshots, dict):
        raise ConfigError("references 'snapshots' must be an object")
    return snapshots


def verify_snapshots(config: Config, references: Optional[dict]) -> None:
    """Refuse before any read unless every snapshot matches its declared SHA
    (and the references source SHA and size, when references are supplied)."""
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
        if references is None:
            continue
        if name not in references:
            raise ConfigError(f"references has no entry for snapshot '{name}'")
        entry = references[name]
        if actual != entry.get("source_sha256"):
            raise ConfigError(
                f"snapshot '{name}' SHA-256 mismatch vs references: "
                f"file {actual} != source_sha256 {entry.get('source_sha256')}"
            )
        if path.stat().st_size != entry.get("source_bytes"):
            raise ConfigError(
                f"snapshot '{name}' size mismatch vs references: "
                f"{path.stat().st_size} != source_bytes {entry.get('source_bytes')}"
            )


def diagnose_command(config: Config, snapshot: dict, report_path: Path) -> list[str]:
    return config.kernel_command + [
        "diagnose-h1",
        "--item-index",
        str(snapshot["item_index"]),
        "--input",
        str(snapshot["path"]),
        "--report-out",
        str(report_path),
        "--sse-bucket-bits",
        str(config.sse_bucket_bits),
        "--top-regions",
        str(config.top_regions),
        "--force",
    ]


def run(config_path: Path) -> dict:
    config = Config(config_path)
    references = load_references(config.references_path)
    verify_snapshots(config, references)

    consumed_before = RUNNER.read_budget(config.budget_state)
    if consumed_before >= RUNNER.RUN_BUDGET_CAP:
        raise RUNNER.BudgetExhausted(
            f"run budget exhausted ({consumed_before}/{RUNNER.RUN_BUDGET_CAP} "
            "consumed); refusing further runs for this cycle"
        )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    consumed = consumed_before
    runs: list[dict] = []
    for snapshot in config.snapshots:
        name = snapshot["name"]
        if consumed >= RUNNER.RUN_BUDGET_CAP:
            runs.append({"snapshot": name, "status": "skipped_budget_cap"})
            continue
        report_path = config.output_dir / f"{name}__h1-loss-decomposition.report.json"
        completed = subprocess.run(diagnose_command(config, snapshot, report_path))
        # Charge the budget for every run we actually dispatched, matching the
        # sweep runner: a run counts whether or not the target exited cleanly.
        consumed += 1
        RUNNER.write_budget(config.budget_state, consumed)
        runs.append(
            {
                "snapshot": name,
                "status": "measured" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "report_path": str(report_path),
            }
        )

    summary = {
        "schema": SWEEP_SCHEMA,
        "evidence_stage": EVIDENCE_STAGE,
        "budget": {
            "consumed_before": consumed_before,
            "consumed_after": consumed,
            "cap": RUNNER.RUN_BUDGET_CAP,
        },
        "runs": runs,
    }
    summary_path = config.output_dir / "decomposition-sweep-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("config", type=Path, help="decomposition run config JSON path")
    arguments = parser.parse_args(argv)
    summary = run(arguments.config)
    consumed = summary["budget"]["consumed_after"]
    measured = sum(1 for entry in summary["runs"] if entry["status"] == "measured")
    print(
        f"decomposition sweep complete: {len(summary['runs'])} runs "
        f"({measured} measured); budget {consumed}/{RUNNER.RUN_BUDGET_CAP}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
