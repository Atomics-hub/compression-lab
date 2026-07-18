#!/usr/bin/env python3
"""Verify the frozen incompressible/precompressed development execution plan."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType


REPOSITORY = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load_script(
    "incompressible_precompressed_planner_for_verifier",
    REPOSITORY / "scripts" / "prepare-incompressible-precompressed-execution.py",
)


def verify(
    *, config_path: Path, acquisition_path: Path, plan_path: Path
) -> dict[str, object]:
    config = PLANNER.read_canonical_json(config_path)
    acquisition = PLANNER.read_canonical_json(acquisition_path)
    observed = PLANNER.read_canonical_json(plan_path)
    if (
        observed.get("name")
        != "incompressible-precompressed-development-execution-plan-v1"
        or observed.get("bindings", {}).get("config_sha256")
        != PLANNER.sha256_file(config_path)
        or observed["bindings"].get("licensed_acquisition_sha256")
        != PLANNER.sha256_file(acquisition_path)
    ):
        raise ValueError("development plan binding is invalid")
    expected = PLANNER.build_plan(
        config,
        acquisition,
        config_sha256=PLANNER.sha256_file(config_path),
        acquisition_sha256=PLANNER.sha256_file(acquisition_path),
        repository_commit=observed["bindings"]["repository_commit"],
    )
    if observed != expected:
        raise ValueError("development plan does not reconstruct from frozen inputs")
    generated = [row for row in observed["tasks"] if row["kind"] == "generated"]
    precompressed = [
        row for row in observed["tasks"] if row["kind"] == "precompressed"
    ]
    return {
        "verified": True,
        "task_count": observed["task_count"],
        "generated_task_count": len(generated),
        "precompressed_task_count": len(precompressed),
        "axiom_wins": 0,
        "plan_sha256": PLANNER.sha256_file(plan_path),
        "claim_ceiling": observed["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", nargs="?", type=Path, default=PLANNER.DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=PLANNER.DEFAULT_CONFIG)
    parser.add_argument(
        "--acquisition", type=Path, default=PLANNER.DEFAULT_ACQUISITION
    )
    args = parser.parse_args()
    try:
        result = verify(
            config_path=args.config,
            acquisition_path=args.acquisition,
            plan_path=args.plan,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"incompressible/precompressed plan verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
