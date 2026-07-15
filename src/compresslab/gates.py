from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def evaluate_candidate(
    results: Dict[str, Any],
    gate_config: Dict[str, Any],
    candidate_id: str,
    bandwidth_mbps: float = 100.0,
) -> Dict[str, Any]:
    requirements = gate_config["requirements"]
    candidate_trials = [
        row for row in results["trials"] if row["codec_id"] == candidate_id
    ]
    candidate_medians = [
        row for row in results["medians"] if row["codec_id"] == candidate_id
    ]
    candidate_summary = next(
        (row for row in results["summary"] if row["codec_id"] == candidate_id),
        None,
    )
    if not candidate_trials or not candidate_medians or candidate_summary is None:
        raise ValueError(f"Candidate {candidate_id!r} is absent from the results")

    checks: List[Dict[str, Any]] = []
    roundtrip_failures = sum(not row["roundtrip_ok"] for row in candidate_trials)
    checks.append(
        _check(
            "roundtrip",
            roundtrip_failures <= requirements["roundtrip_failures"],
            roundtrip_failures,
            requirements["roundtrip_failures"],
            "failures",
        )
    )

    expansion_violations = 0
    worst_expansion_bytes = 0
    for row in candidate_medians:
        expansion = row["compressed_bytes"] - row["original_bytes"]
        worst_expansion_bytes = max(worst_expansion_bytes, expansion)
        allowed = (
            requirements["max_frame_overhead_bytes"]
            + row["original_bytes"]
            * requirements["max_expansion_percent_plus_frame"]
            / 100.0
        )
        if expansion > allowed:
            expansion_violations += 1
    checks.append(
        _check(
            "bounded_expansion",
            expansion_violations == 0,
            expansion_violations,
            0,
            "violating items",
            {"worst_expansion_bytes": worst_expansion_bytes},
        )
    )

    selector_time_percent = candidate_summary.get("selector_time_percent", 0.0)
    checks.append(
        _check(
            "selector_overhead",
            selector_time_percent <= requirements["max_selector_time_percent"],
            selector_time_percent,
            requirements["max_selector_time_percent"],
            "percent",
        )
    )

    coverage = _frontier_coverage(
        results["medians"],
        candidate_id,
        bandwidth_mbps,
        requirements["frontier_tolerance_size_percent"],
        requirements["frontier_tolerance_total_time_percent"],
    )
    checks.append(
        _check(
            "frontier_coverage",
            coverage["coverage_percent"]
            >= requirements["target_frontier_coverage_percent"],
            coverage["coverage_percent"],
            requirements["target_frontier_coverage_percent"],
            "percent",
            coverage,
        )
    )

    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "run_id": results["run_id"],
        "bandwidth_mbps": bandwidth_mbps,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "gate_config": gate_config,
    }


def _frontier_coverage(
    medians: Sequence[Dict[str, Any]],
    candidate_id: str,
    bandwidth_mbps: float,
    size_tolerance_percent: float,
    time_tolerance_percent: float,
) -> Dict[str, Any]:
    key = f"total_ms_at_{_bandwidth_key(bandwidth_mbps)}mbps"
    by_item: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in medians:
        by_item[row["item_id"]].append(row)

    details: List[Dict[str, Any]] = []
    for item_id, rows in sorted(by_item.items()):
        candidate = next(
            (row for row in rows if row["codec_id"] == candidate_id),
            None,
        )
        if candidate is None:
            details.append({"item_id": item_id, "covered": False, "reason": "missing"})
            continue
        frontier = _pareto_frontier(rows, key)
        covered = any(
            candidate["compressed_bytes"]
            <= point["compressed_bytes"] * (1.0 + size_tolerance_percent / 100.0)
            and candidate[key]
            <= point[key] * (1.0 + time_tolerance_percent / 100.0)
            for point in frontier
        )
        details.append(
            {
                "item_id": item_id,
                "covered": covered,
                "candidate_compressed_bytes": candidate["compressed_bytes"],
                "candidate_total_ms": candidate[key],
                "frontier_codecs": [row["codec_id"] for row in frontier],
            }
        )
    covered_count = sum(row["covered"] for row in details)
    return {
        "covered_items": covered_count,
        "total_items": len(details),
        "coverage_percent": 100.0 * covered_count / len(details) if details else 0.0,
        "details": details,
    }


def _pareto_frontier(
    rows: Sequence[Dict[str, Any]], time_key: str
) -> List[Dict[str, Any]]:
    return [
        candidate
        for candidate in rows
        if not any(
            other is not candidate
            and other["compressed_bytes"] <= candidate["compressed_bytes"]
            and other[time_key] <= candidate[time_key]
            and (
                other["compressed_bytes"] < candidate["compressed_bytes"]
                or other[time_key] < candidate[time_key]
            )
            for other in rows
        )
    ]


def _check(
    name: str,
    passed: bool,
    actual: Any,
    required: Any,
    unit: str,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "actual": actual,
        "required": required,
        "unit": unit,
        **({"detail": detail} if detail else {}),
    }


def _bandwidth_key(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "_")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_gate_report(report: Dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = [
        f"# Candidate Gate: {report['candidate_id']}",
        "",
        f"- Run: {report['run_id']}",
        f"- Overall: {'PASS' if report['passed'] else 'FAIL'}",
        f"- Evaluation bandwidth: {report['bandwidth_mbps']:g} Mbps",
        "",
        "| Check | Actual | Required | Result |",
        "|---|---:|---:|:---:|",
    ]
    for check in report["checks"]:
        markdown.append(
            f"| {check['name']} | {check['actual']:.3f} {check['unit']} | "
            f"{check['required']:.3f} {check['unit']} | "
            f"{'PASS' if check['passed'] else 'FAIL'} |"
        )
    markdown.extend(
        [
            "",
            "A failed gate is a research result, not a software error. Do not promote the",
            "candidate until every required check passes on the private holdout.",
            "",
        ]
    )
    output.with_suffix(".md").write_text("\n".join(markdown), encoding="utf-8")
