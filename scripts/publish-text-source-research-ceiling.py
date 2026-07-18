#!/usr/bin/env python3
"""Publish the verified text/source practical and research baseline frontier."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from types import ModuleType
from typing import Any
from xml.sax.saxutils import escape


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_AGGREGATE = REPOSITORY / "runs" / "text-source-research-ceiling-v1.json"
DEFAULT_BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-research-ceiling-publication-v1"
PROFILE_ORDER = [
    "zpaq-5-m510",
    "paq8px-11L-local-screen",
    "paq8px-12L-absolute",
    "cmix-v21-strong-text",
    "nncp-3.3-transformer",
]
PROFILE_LABELS = {
    "zpaq-5-m510": "ZPAQ 7.15 -m510",
    "paq8px-11L-local-screen": "paq8px v216 -11L (context)",
    "paq8px-12L-absolute": "paq8px v216 -12L",
    "cmix-v21-strong-text": "cmix v21 strong-text",
    "nncp-3.3-transformer": "NNCP 3.3 transformer",
}
EXPECTED_FILES = {
    "README.md",
    "comparison.json",
    "comparison.svg",
    "evidence.json",
    "receipt.json",
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGGREGATE = load_script(
    "research_ceiling_aggregate_for_publication",
    REPOSITORY / "scripts" / "aggregate-text-source-research-ceiling.py",
)
BASELINE_VERIFY = load_script(
    "baseline_publication_verifier_for_research_publication",
    REPOSITORY / "scripts" / "verify-text-source-baseline-publication.py",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def finite_nonnegative(value: object) -> bool:
    return (
        type(value) in {int, float}
        and math.isfinite(value)
        and value >= 0
    )


def research_status(rows: list[dict[str, Any]]) -> str:
    statuses = {row["execution_status"] for row in rows}
    profile_id = rows[0]["profile_id"]
    if profile_id == "paq8px-11L-local-screen":
        if all(row["complete"] and row["deterministic"] for row in rows):
            return "measured_context_only"
        if "unavailable" in statuses:
            return "unavailable_context_only"
        return "failed_or_incomplete_context_only"
    if all(row["formal_ceiling_admitted"] for row in rows):
        return "formal_admitted"
    if profile_id == "nncp-3.3-transformer" and all(
        row["complete"] and row["deterministic"] for row in rows
    ):
        return (
            "failed_second_host_decode"
            if "failed" in {row["second_host_decode_status"] for row in rows}
            else "pending_second_host_decode"
        )
    if "unavailable" in statuses:
        return "unavailable"
    if "resource_budget_exhausted" in statuses:
        return "resource_budget_exhausted"
    return "failed_or_incomplete"


def aggregate_research_row(
    profile_id: str, track_id: str, tasks: list[dict[str, Any]]
) -> dict[str, Any]:
    if not tasks or any(
        row["profile_id"] != profile_id or row["track"] != track_id for row in tasks
    ):
        raise ValueError("research profile/track task roster is invalid")
    host_ids = {row["host_id"] for row in tasks}
    host_classes = {row["host_class"] for row in tasks}
    if len(host_ids) != 1 or len(host_classes) != 1:
        raise ValueError("one research profile/track spans multiple primary hosts")
    complete = all(row["complete"] and row["deterministic"] for row in tasks)
    formal = all(row["formal_ceiling_eligible"] for row in tasks)
    admitted = formal and all(row["formal_ceiling_admitted"] for row in tasks)
    source_bytes = sum(row["source_bytes"] for row in tasks)
    complete_bytes = (
        sum(row["complete_artifact_bytes"] for row in tasks) if complete else None
    )
    compression_wall_ns = (
        sum(row["compression_wall_ns_median"] for row in tasks) if complete else None
    )
    decompression_wall_ns = (
        sum(row["decompression_wall_ns_median"] for row in tasks) if complete else None
    )
    if complete and (
        not finite_nonnegative(compression_wall_ns)
        or not finite_nonnegative(decompression_wall_ns)
        or compression_wall_ns == 0
        or decompression_wall_ns == 0
    ):
        raise ValueError("complete research row has invalid measured wall time")
    return {
        "row_id": profile_id,
        "codec": PROFILE_LABELS[profile_id],
        "tier": "research ceiling" if formal else "resource screen",
        "source_bytes": source_bytes,
        "complete_bytes": complete_bytes,
        "compression_ratio": (
            source_bytes / complete_bytes if complete_bytes else None
        ),
        "size_percent": (
            complete_bytes / source_bytes * 100.0 if complete_bytes is not None else None
        ),
        "compression_mbps": (
            source_bytes / (compression_wall_ns / 1e9) / 1_000_000
            if complete
            else None
        ),
        "decompression_mbps": (
            source_bytes / (decompression_wall_ns / 1e9) / 1_000_000
            if complete
            else None
        ),
        "compression_peak_rss_mib": (
            max(row["compression_peak_rss_bytes"] for row in tasks) / 1024**2
            if complete
            else None
        ),
        "decompression_peak_rss_mib": (
            max(row["decompression_peak_rss_bytes"] for row in tasks) / 1024**2
            if complete
            else None
        ),
        "exact_roundtrip": complete,
        "deterministic_artifact": complete,
        "formal_ratio_eligible": admitted,
        "execution_status": research_status(tasks),
        "host_id": next(iter(host_ids)),
        "host_class": next(iter(host_classes)),
        "speed_memory_comparability": "host-scoped only",
        "axiom_outcome": "untested",
        "axiom_beats_this_row": "untested",
    }


def derive(
    *,
    plan: dict[str, Any],
    aggregate: dict[str, Any],
    baseline: dict[str, Any],
    plan_sha256: str,
    aggregate_sha256: str,
    baseline_comparison_sha256: str,
    baseline_receipt_sha256: str,
    evidence_sha256: str = "not-built-in-memory",
) -> dict[str, Any]:
    if (
        aggregate.get("name") != "text-source-research-ceiling-aggregate-v1"
        or aggregate.get("task_count") != 35
        or aggregate.get("formal_task_count") != 28
        or aggregate.get("axiom_wins") != 0
        or aggregate.get("bindings", {}).get("plan_sha256") != plan_sha256
        or plan.get("name") != "text-source-research-ceiling-execution-plan-v1"
        or len(plan.get("tasks", [])) != 35
        or baseline.get("name")
        != "text-source-development-practical-baseline-publication-v1"
        or aggregate["bindings"]["baseline_results_sha256"]
        != baseline["results_sha256"]
    ):
        raise ValueError("research publication inputs have inconsistent identities")
    plan_task_ids = [row["task_id"] for row in plan["tasks"]]
    if [row["task_id"] for row in aggregate["tasks"]] != plan_task_ids:
        raise ValueError("aggregate task order differs from the frozen plan")
    tasks = aggregate["tasks"]
    tracks = []
    for baseline_track in baseline["tracks"]:
        track_id = baseline_track["track_id"]
        source_bytes = baseline_track["source_bytes"]
        rows = []
        for baseline_row in baseline_track["codecs"]:
            if baseline_row["source_bytes"] != source_bytes:
                raise ValueError("practical baseline track source total differs")
            rows.append(
                {
                    "row_id": baseline_row["codec_id"],
                    "codec": baseline_row["codec"],
                    "tier": "practical baseline",
                    "source_bytes": source_bytes,
                    "complete_bytes": baseline_row["complete_bytes"],
                    "compression_ratio": baseline_row["compression_ratio"],
                    "size_percent": baseline_row["size_percent"],
                    "compression_mbps": baseline_row["compression_mbps"],
                    "decompression_mbps": baseline_row["decompression_mbps"],
                    "compression_peak_rss_mib": baseline_row[
                        "compression_peak_rss_mib"
                    ],
                    "decompression_peak_rss_mib": baseline_row[
                        "decompression_peak_rss_mib"
                    ],
                    "exact_roundtrip": True,
                    "deterministic_artifact": True,
                    "formal_ratio_eligible": True,
                    "execution_status": "measured_practical_same_host",
                    "host_id": "practical-census-host",
                    "host_class": (
                        f"{baseline['host']['platform']} / {baseline['host']['machine']}"
                    ),
                    "speed_memory_comparability": "practical rows same-host only",
                    "axiom_outcome": "untested",
                    "axiom_beats_this_row": "untested",
                }
            )
        for profile_id in PROFILE_ORDER:
            profile_tasks = [
                row
                for row in tasks
                if row["profile_id"] == profile_id and row["track"] == track_id
            ]
            research_row = aggregate_research_row(profile_id, track_id, profile_tasks)
            if research_row["source_bytes"] != source_bytes:
                raise ValueError("research and practical track source totals differ")
            rows.append(research_row)
        rows.append(
            {
                "row_id": "axiom-text-source-specialist",
                "codec": "Axiom text/source specialist",
                "tier": "Axiom candidate",
                "source_bytes": source_bytes,
                "complete_bytes": None,
                "compression_ratio": None,
                "size_percent": None,
                "compression_mbps": None,
                "decompression_mbps": None,
                "compression_peak_rss_mib": None,
                "decompression_peak_rss_mib": None,
                "exact_roundtrip": False,
                "deterministic_artifact": False,
                "formal_ratio_eligible": False,
                "execution_status": "untested",
                "host_id": None,
                "host_class": None,
                "speed_memory_comparability": "untested",
                "axiom_outcome": "untested",
                "axiom_beats_this_row": "untested",
            }
        )
        eligible = [
            row
            for row in rows
            if row["formal_ratio_eligible"] and row["complete_bytes"] is not None
        ]
        if not eligible:
            raise ValueError("track has no eligible baseline ratio row")
        leader = min(eligible, key=lambda row: row["complete_bytes"])
        for row in rows:
            row["ratio_leader"] = row["row_id"] == leader["row_id"]
            row["larger_than_leader_percent"] = (
                (row["complete_bytes"] / leader["complete_bytes"] - 1.0) * 100.0
                if row["complete_bytes"] is not None
                else None
            )
        tracks.append(
            {
                "track_id": track_id,
                "track": baseline_track["track"],
                "source_bytes": source_bytes,
                "ratio_leader": leader["codec"],
                "ratio_leader_bytes": leader["complete_bytes"],
                "rows": rows,
            }
        )
    formal_complete = aggregate["all_formal_ceiling_tasks_admitted"]
    return {
        "schema_version": 1,
        "name": "text-source-development-research-frontier-publication-v1",
        "stage": "development practical census plus research ceiling",
        "candidate_status": "Axiom text/source specialist untested",
        "bindings": aggregate["bindings"],
        "plan_sha256": plan_sha256,
        "aggregate_sha256": aggregate_sha256,
        "baseline_comparison_sha256": baseline_comparison_sha256,
        "baseline_receipt_sha256": baseline_receipt_sha256,
        "evidence_sha256": evidence_sha256,
        "research_ceiling_complete": formal_complete,
        "trial_count": aggregate["trial_count"],
        "tracks": tracks,
        "integrity": {
            "all_35_planned_tasks_present": True,
            "formal_task_count": 28,
            "all_formal_tasks_admitted": formal_complete,
            "nncp_distinct_host_decode_status": (
                "verified"
                if aggregate["second_host_decode"] is not None
                and aggregate["second_host_decode"][
                    "all_nncp_second_host_decodes_exact"
                ]
                else "pending_or_unavailable"
            ),
            "complete_artifact_bytes_cross_host_comparable": True,
            "speed_and_rss_host_scoped_only": True,
            "axiom_wins": 0,
        },
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "claim_ceiling": (
            "Development baseline frontier only. Axiom is untested in every row; "
            "unavailable, failed, context-only, or pending research candidates are not "
            "wins, speed and RSS cannot be ranked across host scopes, and this evidence "
            "supports no category-win, world-best, or state-of-the-art claim."
        ),
    }


def build_evidence(
    *,
    plan: dict[str, Any],
    aggregate: dict[str, Any],
    baseline: dict[str, Any],
    baseline_receipt: dict[str, Any],
    plan_sha256: str,
    aggregate_sha256: str,
    baseline_comparison_sha256: str,
    baseline_receipt_sha256: str,
) -> bytes:
    evidence = {
        "schema_version": 1,
        "name": "text-source-development-research-frontier-public-evidence-v1",
        "plan_sha256": plan_sha256,
        "aggregate_sha256": aggregate_sha256,
        "baseline_comparison_sha256": baseline_comparison_sha256,
        "baseline_receipt_sha256": baseline_receipt_sha256,
        "plan": plan,
        "aggregate": aggregate,
        "baseline_comparison": baseline,
        "baseline_receipt": baseline_receipt,
        "evidence_boundary": (
            "This public evidence embeds the frozen plan, verified aggregate, and "
            "checked-in practical comparison. Raw host receipts and retained artifacts "
            "remain bound by their SHA-256 values and are verified by the separate raw "
            "aggregate verifier; Axiom has no measured row here."
        ),
    }
    encoded = json_bytes(evidence)
    if any(
        marker in encoded
        for marker in (b"/Users/", b"/private/var/", b"/var/folders/", b"/tmp/")
    ):
        raise ValueError("research publication evidence contains a local absolute path")
    return encoded


def fmt_number(value: float | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.2f}{suffix}"


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Text/source practical and research baseline frontier",
        "",
        "![Complete size, speed, memory, integrity, and admission status for every tested text/source standard](comparison.svg)",
        "",
        "**Axiom status: untested.** Every `Axiom beats?` cell is therefore `untested`;",
        "no unavailable or failed specialist is counted as a win.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                f"Source bytes: **{track['source_bytes']:,}**. Eligible ratio leader: "
                f"**{track['ratio_leader']}** at **{track['ratio_leader_bytes']:,} bytes**.",
                "",
                "| Tier | Codec/profile | Complete bytes | Ratio | vs leader | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Admission/status | Host scope | Axiom beats? |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | --- | --- | --- |",
            ]
        )
        for row in track["rows"]:
            complete = "—" if row["complete_bytes"] is None else f"{row['complete_bytes']:,}"
            ratio = fmt_number(row["compression_ratio"], "x")
            delta = (
                "—"
                if row["larger_than_leader_percent"] is None
                else (
                    "leader"
                    if row["ratio_leader"]
                    else f"+{row['larger_than_leader_percent']:.2f}%"
                )
            )
            rss = (
                "—"
                if row["compression_peak_rss_mib"] is None
                else f"{row['compression_peak_rss_mib']:.1f} / {row['decompression_peak_rss_mib']:.1f}"
            )
            integrity = "✅ / ✅" if row["exact_roundtrip"] else "— / —"
            host = row["host_class"] or "—"
            lines.append(
                f"| {row['tier']} | {'**' if row['ratio_leader'] else ''}{row['codec']}"
                f"{'**' if row['ratio_leader'] else ''} | {complete} | {ratio} | {delta} | "
                f"{fmt_number(row['compression_mbps'])} | {fmt_number(row['decompression_mbps'])} | "
                f"{rss} | {integrity} | {row['execution_status']} | {host} | "
                f"{row['axiom_beats_this_row']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Comparability and evidence boundary",
            "",
            "- Complete artifact bytes use the identical seven-item development corpus and are cross-host comparable.",
            "- Compression speed, decompression speed, and peak RSS are host-scoped; they are never ranked across host classes.",
            "- paq8px `-11L` is a local context screen and cannot substitute for the formal `-12L` row.",
            "- NNCP is formally admitted only after exact decoding of all seven retained artifacts on a distinct compatible host.",
            "- The embedded evidence binds the plan, all host aggregates, retained-artifact manifests, and the practical census.",
            "- Public validation and private holdout remain sealed and unaccessed.",
            "",
            f"Claim ceiling: **{comparison['claim_ceiling']}**",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    row_height = 25
    track_header = 54
    track_height = track_header + row_height * max(
        len(track["rows"]) for track in comparison["tracks"]
    )
    height = 132 + track_height * len(comparison["tracks"]) + 76
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="{height}" viewBox="0 0 1500 {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Axiom text and source practical and research baseline frontier</title>',
        '<desc id="desc">Every practical and research baseline row reports complete size, compression and decompression speed, peak memory, and admission status. Axiom is untested.</desc>',
        '<rect width="1500" height="100%" fill="#08111f"/>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.h{font-weight:700}.muted{fill:#94a3b8}.good{fill:#34d399}.warn{fill:#fbbf24}.plain{fill:#e2e8f0}</style>',
        '<text x="38" y="42" class="h plain" font-size="25">Text/source baseline frontier — Axiom untested</text>',
        '<text x="38" y="70" class="muted" font-size="14">Bytes compare across hosts. Speed and RSS are host-scoped. Pending/unavailable rows are never wins.</text>',
    ]
    y = 108
    for track in comparison["tracks"]:
        lines.append(
            f'<text x="38" y="{y}" class="h plain" font-size="19">{escape(track["track"])} — leader {escape(track["ratio_leader"])} ({track["ratio_leader_bytes"]:,} B)</text>'
        )
        y += 27
        lines.append(
            f'<text x="38" y="{y}" class="muted" font-size="12">tier / codec</text><text x="575" y="{y}" class="muted" font-size="12">bytes</text><text x="720" y="{y}" class="muted" font-size="12">ratio</text><text x="820" y="{y}" class="muted" font-size="12">C MB/s</text><text x="930" y="{y}" class="muted" font-size="12">D MB/s</text><text x="1040" y="{y}" class="muted" font-size="12">RSS C/D MiB</text><text x="1195" y="{y}" class="muted" font-size="12">status</text>'
        )
        y += 23
        for row in track["rows"]:
            color = (
                "good"
                if row["ratio_leader"]
                else "warn"
                if row["execution_status"] in {"unavailable", "resource_budget_exhausted", "pending_second_host_decode", "failed_or_incomplete"}
                else "plain"
            )
            label = f"{row['tier']} / {row['codec']}"
            complete = "—" if row["complete_bytes"] is None else f"{row['complete_bytes']:,}"
            ratio = fmt_number(row["compression_ratio"], "x")
            rss = (
                "—"
                if row["compression_peak_rss_mib"] is None
                else f"{row['compression_peak_rss_mib']:.1f}/{row['decompression_peak_rss_mib']:.1f}"
            )
            lines.extend(
                [
                    f'<text x="38" y="{y}" class="{color}" font-size="12">{escape(label)}</text>',
                    f'<text x="575" y="{y}" class="{color}" font-size="12">{complete}</text>',
                    f'<text x="720" y="{y}" class="{color}" font-size="12">{ratio}</text>',
                    f'<text x="820" y="{y}" class="{color}" font-size="12">{fmt_number(row["compression_mbps"])}</text>',
                    f'<text x="930" y="{y}" class="{color}" font-size="12">{fmt_number(row["decompression_mbps"])}</text>',
                    f'<text x="1040" y="{y}" class="{color}" font-size="12">{rss}</text>',
                    f'<text x="1195" y="{y}" class="{color}" font-size="12">{escape(row["execution_status"])}</text>',
                ]
            )
            y += row_height
        y += 31
    lines.extend(
        [
            f'<text x="38" y="{height - 39}" class="warn" font-size="13">Claim ceiling: development baselines only; Axiom untested; no category or world-best claim.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def build_artifacts(
    *,
    plan_path: Path,
    aggregate_path: Path,
    baseline_publication: Path,
) -> dict[str, bytes]:
    BASELINE_VERIFY.verify(baseline_publication)
    plan = read_canonical_json(plan_path)
    aggregate = read_canonical_json(aggregate_path)
    baseline_path = baseline_publication / "comparison.json"
    baseline_receipt_path = baseline_publication / "receipt.json"
    baseline = read_canonical_json(baseline_path)
    baseline_receipt = read_canonical_json(baseline_receipt_path)
    digests = {
        "plan_sha256": sha256_file(plan_path),
        "aggregate_sha256": sha256_file(aggregate_path),
        "baseline_comparison_sha256": sha256_file(baseline_path),
        "baseline_receipt_sha256": sha256_file(baseline_receipt_path),
    }
    evidence = build_evidence(
        plan=plan,
        aggregate=aggregate,
        baseline=baseline,
        baseline_receipt=baseline_receipt,
        **digests,
    )
    comparison = derive(
        plan=plan,
        aggregate=aggregate,
        baseline=baseline,
        evidence_sha256=sha256_bytes(evidence),
        **digests,
    )
    artifacts = {
        "evidence.json": evidence,
        "comparison.json": json_bytes(comparison),
        "comparison.svg": render_svg(comparison).encode("utf-8"),
        "README.md": render_markdown(comparison).encode("utf-8"),
    }
    receipt = {
        "schema_version": 1,
        "name": "text-source-development-research-frontier-publication-receipt-v1",
        **digests,
        "evidence_sha256": comparison["evidence_sha256"],
        "artifacts": {
            name: sha256_bytes(payload) for name, payload in artifacts.items()
        },
        "claim_ceiling": comparison["claim_ceiling"],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(
    *, plan_path: Path, aggregate_path: Path, baseline_publication: Path, output: Path
) -> Path:
    artifacts = build_artifacts(
        plan_path=plan_path,
        aggregate_path=aggregate_path,
        baseline_publication=baseline_publication,
    )
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ValueError("refusing non-directory publication destination")
        if {path.name for path in output.iterdir()} != set(artifacts):
            raise ValueError("refusing publication directory with differing roster")
        for name, payload in artifacts.items():
            path = output / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError(f"refusing to replace differing artifact: {name}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="research-publication-", dir=output.parent) as raw:
        staging = Path(raw) / "publication"
        staging.mkdir()
        for name, payload in artifacts.items():
            (staging / name).write_bytes(payload)
        staging.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--aggregate", type=Path, default=DEFAULT_AGGREGATE)
    parser.add_argument(
        "--host-run",
        action="append",
        nargs=3,
        metavar=("TOOLCHAIN_RECEIPT", "TOOLS_ROOT", "OUTPUT"),
        required=True,
        help="repeat once for each of the four declared primary host classes",
    )
    parser.add_argument(
        "--second-host-run",
        nargs=3,
        metavar=("TOOLCHAIN_RECEIPT", "TOOLS_ROOT", "OUTPUT"),
    )
    parser.add_argument(
        "--baseline-publication", type=Path, default=DEFAULT_BASELINE_PUBLICATION
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        host_runs = AGGREGATE.parse_host_runs(args.host_run)
        second_host_run = (
            AGGREGATE.SecondHostRun(
                *(Path(value) for value in args.second_host_run)
            )
            if args.second_host_run
            else None
        )
        AGGREGATE.validate_aggregate(
            aggregate_path=args.aggregate,
            plan_path=args.plan,
            host_runs=host_runs,
            second_host_run=second_host_run,
        )
        result = publish(
            plan_path=args.plan,
            aggregate_path=args.aggregate,
            baseline_publication=args.baseline_publication,
            output=args.output,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"research-frontier publication refused: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
