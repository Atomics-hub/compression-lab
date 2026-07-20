#!/usr/bin/env python3
"""Verify the research-ceiling plan against checked-in config and baseline evidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
DEFAULT_BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load_script(
    "research_ceiling_planner_for_verifier",
    REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py",
)
BASELINE_VERIFIER = load_script(
    "baseline_publication_verifier_for_research_ceiling",
    REPOSITORY / "scripts" / "verify-text-source-baseline-publication.py",
)


def read_canonical_plan(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("research-ceiling plan must be an ordinary file")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PLANNER.json_bytes(value):
        raise ValueError("research-ceiling plan is not canonical JSON")
    return value


def verify(
    plan_path: Path, config_path: Path, baseline_publication: Path
) -> dict[str, Any]:
    baseline_result = BASELINE_VERIFIER.verify(baseline_publication)
    plan = read_canonical_plan(plan_path)
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    baseline_evidence_path = baseline_publication / "evidence.json"
    baseline_evidence_raw = baseline_evidence_path.read_bytes()
    baseline_evidence = json.loads(baseline_evidence_raw)
    if (
        not isinstance(config, dict)
        or not isinstance(baseline_evidence, dict)
        or baseline_result["results_sha256"]
        != baseline_evidence.get("raw_results_sha256")
        or baseline_result["public_evidence_sha256"]
        != PLANNER.sha256_bytes(baseline_evidence_raw)
    ):
        raise ValueError("bound baseline publication is inconsistent")
    bindings = plan.get("bindings")
    if not isinstance(bindings, dict) or not PLANNER.BASELINE_PUBLICATION.is_lower_hex(
        bindings.get("repository_commit"), 40
    ):
        raise ValueError("research-ceiling plan binding is invalid")
    expected = PLANNER.build_plan(
        config,
        baseline_evidence["results"],
        config_sha256=PLANNER.sha256_bytes(config_raw),
        baseline_sha256=baseline_result["results_sha256"],
        repository_commit=bindings["repository_commit"],
    )
    if plan != expected:
        raise ValueError("research-ceiling plan differs from recomputed protocol")
    formal_tasks = [row for row in plan["tasks"] if row["formal_ceiling_eligible"]]
    context_tasks = [row for row in plan["tasks"] if not row["formal_ceiling_eligible"]]
    if len(formal_tasks) != 28 or len(context_tasks) != 7:
        raise ValueError("research-ceiling formal/context task counts are invalid")
    return {
        "verified": True,
        "task_count": len(plan["tasks"]),
        "formal_task_count": len(formal_tasks),
        "context_task_count": len(context_tasks),
        "baseline_results_sha256": baseline_result["results_sha256"],
        "claim_ceiling": plan["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--baseline-publication", type=Path, default=DEFAULT_BASELINE_PUBLICATION
    )
    args = parser.parse_args()
    try:
        result = verify(args.plan, args.config, args.baseline_publication)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"research-ceiling plan verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
