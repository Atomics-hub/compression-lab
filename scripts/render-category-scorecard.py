#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


OUTCOME_MARKERS = {
    "candidate": "—",
    "win": "✅",
    "loss": "❌",
    "mixed": "⚠️",
    "pass": "✅",
    "fail": "❌",
}


def escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def outcome(value: str) -> str:
    kind = value.split(":", 1)[0].strip().lower()
    return f"{OUTCOME_MARKERS.get(kind, '—')} {escape(value)}"


def number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def validate(scorecard: dict[str, Any]) -> None:
    required = {
        "title",
        "category",
        "stage",
        "overall_gate",
        "result_summary",
        "claim_ceiling",
        "evidence",
        "corpus",
        "standards",
        "family_results",
        "gate_results",
        "decision",
    }
    missing = sorted(required - scorecard.keys())
    if missing:
        raise ValueError("scorecard is missing: " + ", ".join(missing))
    standards = scorecard["standards"]
    if not standards or standards[0].get("codec") != "JLS2":
        raise ValueError("the first standard row must be the JLS2 candidate")
    if len({row["codec"] for row in standards}) != len(standards):
        raise ValueError("scorecard codec names must be unique")


def render(scorecard: dict[str, Any]) -> str:
    validate(scorecard)
    gate_marker = "✅" if scorecard["overall_gate"] == "pass" else "❌"
    evidence = scorecard["evidence"]
    corpus = scorecard["corpus"]
    lines = [
        f"# {escape(scorecard['title'])}",
        "",
        "## Decision",
        "",
        f"**Overall frozen gate: {gate_marker} "
        f"{escape(scorecard['overall_gate']).upper()}**",
        "",
        escape(scorecard["result_summary"]),
        "",
        "## Aggregate standards comparison",
        "",
        "| Standard | Complete bytes | Ratio | JLS2 size result | "
        "Compress MB/s | JLS2 compress result | Decompress MB/s | "
        "JLS2 decompress result | Peak memory MiB | Exact |",
        "| --- | ---: | ---: | --- | ---: | --- | ---: | --- | ---: | --- |",
    ]
    for row in scorecard["standards"]:
        lines.append(
            f"| {escape(row['codec'])} {escape(row['setting'])} "
            f"| {row['complete_bytes']:,} "
            f"| {row['compression_ratio']:.2f}x "
            f"| {outcome(row['jls2_size_outcome'])} "
            f"| {number(row['compression_mbps'])} "
            f"| {outcome(row['jls2_compression_outcome'])} "
            f"| {number(row['decompression_mbps'])} "
            f"| {outcome(row['jls2_decompression_outcome'])} "
            f"| {number(row.get('peak_memory_mib'), 1)} "
            f"| {'✅' if row['exact_roundtrip'] else '❌'} |"
        )
    lines.extend(
        [
            "",
            "Speed cells are host-scoped. Measurement basis and comparability:",
            "",
        ]
    )
    for row in scorecard["standards"]:
        lines.append(
            f"- **{escape(row['codec'])}:** "
            f"{escape(row['compression_basis'])}; "
            f"{escape(row['decompression_basis'])}. "
            f"{escape(row['speed_comparability'])}. Memory: "
            f"{escape(row['memory_basis'])}."
        )
    lines.extend(
        [
            "",
            "## Family ratio results",
            "",
            "| Family | Source bytes | JLS2 bytes | vs zstd-9 | "
            "vs Brotli-11 | vs PBC-only |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in scorecard["family_results"]:
        lines.append(
            f"| {escape(row['family'])} | {row['original_bytes']:,} "
            f"| {row['jls2_bytes']:,} "
            f"| {row['gain_vs_zstd9_percent']:+.2f}% "
            f"| {row['gain_vs_brotli11_percent']:+.2f}% "
            f"| {row['gain_vs_pbc_percent']:+.2f}% |"
        )
    lines.extend(
        [
            "",
            "Positive values mean JLS2 is smaller.",
            "",
            "## Frozen gates",
            "",
            "| Gate | Result |",
            "| --- | --- |",
        ]
    )
    for name, passed in scorecard["gate_results"].items():
        label = name.replace("_", " ")
        lines.append(f"| {escape(label)} | {'✅ pass' if passed else '❌ fail'} |")
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            f"- Category: {escape(scorecard['category'])}",
            f"- Stage: {escape(scorecard['stage'])}",
            f"- Families: {', '.join(map(escape, corpus['families']))}",
            f"- Source bytes: {corpus['original_bytes']:,}",
            f"- License: {escape(corpus['license_spdx'])}",
            f"- Runner: {escape(evidence['runner'])}",
            f"- Run: {escape(evidence['github_run_url'])}",
            f"- Workflow commit: `{escape(evidence['workflow_commit'])}`",
            f"- Decision SHA-256: `{escape(evidence['decision_sha256'])}`",
            f"- Private holdout: {escape(corpus['private_holdout'])}",
            "",
            f"Claim ceiling: {escape(scorecard['claim_ceiling'])}",
            "",
            "## Next decision",
            "",
            escape(scorecard["decision"]),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a standardized compression category scorecard"
    )
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scorecard = json.loads(args.scorecard.read_text(encoding="utf-8"))
    rendered = render(scorecard)
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
