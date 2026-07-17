#!/usr/bin/env python3
"""Publish the frozen JLS2 cold-start result and comparison chart."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "jls2-cold-start-v1"
PROTOCOL = ROOT / "docs" / "benchmarks" / "2026-07-17-jls2-cold-start-protocol.md"
BASELINE_COMMIT = "5778b86c1bb9d9b842afd17afb3b3456f02b0cf1"
PRODUCT_SOURCES = (
    "src/compresslab/__init__.py",
    "src/compresslab/_constants.py",
    "src/compresslab/api.py",
    "src/compresslab/cli.py",
    "src/compresslab/experimental.py",
    "src/compresslab/worker.py",
    "tests/test_lazy_imports.py",
    "scripts/benchmark-jls2-cold-start.py",
    "scripts/publish-jls2-cold-start.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def summary_row(result: dict[str, Any], variant: str, mode: str) -> dict[str, Any]:
    return next(
        row
        for row in result["summary"]["summaries"]
        if row["variant"] == variant and row["mode"] == mode
    )


def render_svg(result: dict[str, Any]) -> str:
    rows = [
        ("CLI baseline", summary_row(result, "baseline", "cli"), "baseline"),
        ("CLI lazy", summary_row(result, "candidate", "cli"), "candidate"),
        ("Worker baseline", summary_row(result, "baseline", "worker"), "baseline"),
        ("Worker lazy", summary_row(result, "candidate", "worker"), "candidate"),
    ]
    width = 1080
    height = 360
    plot_x = 210
    plot_width = 720
    plot_top = 108
    row_height = 48
    maximum = 300.0
    target_x = plot_x + 250 / maximum * plot_width
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">JLS2 cold-process decode before and after lazy imports</title>',
        '<desc id="desc">Baseline and lazy-loading median decode throughput for the CLI and benchmark worker. The lazy candidate remains below the frozen 250 megabyte per second target and is rejected.</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;fill:#24292f}.title{font-size:22px;font-weight:500}.subtitle,.axis,.note{font-size:13px;fill:#57606a}.label,.value{font-size:15px}.grid{stroke:#d0d7de;stroke-width:1}.target{stroke:#cf222e;stroke-width:2;stroke-dasharray:6 5}.baseline{fill:#8c959f}.candidate{fill:#bf8700}.minimum{fill:#24292f}",
        "@media(prefers-color-scheme:dark){text{fill:#f0f6fc}.subtitle,.axis,.note{fill:#8c959f}.grid{stroke:#30363d}.target{stroke:#f85149}.baseline{fill:#6e7681}.candidate{fill:#d29922}.minimum{fill:#f0f6fc}}",
        "</style>",
        '<text class="title" x="22" y="30">Lazy loading helps, but the 250 MB/s gate stays open</text>',
        '<text class="subtitle" x="22" y="54">Fresh processes · 7 rounds × 3 CLUE-LDS development ranges · parent wall clock</text>',
        '<text class="subtitle" x="22" y="76">Bars = median aggregate throughput · dots = minimum round · higher is better</text>',
    ]
    for tick in (0, 50, 100, 150, 200, 250, 300):
        x = plot_x + tick / maximum * plot_width
        output.append(
            f'<line class="grid" x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_top + len(rows) * row_height}"/>'
        )
        output.append(
            f'<text class="axis" x="{x:.1f}" y="{plot_top + len(rows) * row_height + 24}" text-anchor="middle">{tick}</text>'
        )
    output.append(
        f'<line class="target" x1="{target_x:.1f}" y1="{plot_top - 8}" x2="{target_x:.1f}" y2="{plot_top + len(rows) * row_height}"/>'
    )
    output.append(
        f'<text class="axis" x="{target_x:.1f}" y="{plot_top - 14}" text-anchor="middle">frozen target</text>'
    )
    for index, (label, row, css_class) in enumerate(rows):
        median = float(row["median_aggregate_parent_mbps"])
        minimum = float(row["minimum_aggregate_parent_mbps"])
        y = plot_top + index * row_height + 8
        bar_width = median / maximum * plot_width
        minimum_x = plot_x + minimum / maximum * plot_width
        output.append(
            f'<text class="label" x="22" y="{y + 18}">{html.escape(label)}</text>'
        )
        output.append(
            f'<rect class="{css_class}" x="{plot_x}" y="{y}" width="{bar_width:.1f}" height="24" rx="3"/>'
        )
        output.append(
            f'<circle class="minimum" cx="{minimum_x:.1f}" cy="{y + 12}" r="4"/>'
        )
        output.append(
            f'<text class="value" x="{plot_x + bar_width + 9:.1f}" y="{y + 18}">{median:.1f}</text>'
        )
    output.append(
        f'<text class="note" x="22" y="{height - 18}">96/96 exact · frames unchanged · candidate rejected · standards census unchanged</text>'
    )
    output.append("</svg>")
    return "\n".join(output) + "\n"


def render_readme(result: dict[str, Any], candidate_commit: str) -> str:
    baseline_cli = summary_row(result, "baseline", "cli")
    candidate_cli = summary_row(result, "candidate", "cli")
    baseline_worker = summary_row(result, "baseline", "worker")
    candidate_worker = summary_row(result, "candidate", "worker")
    probes = result["probes"]

    def probe_row(name: str, label: str) -> str:
        baseline = float(probes[name]["baseline"]["median_ms"])
        candidate = float(probes[name]["candidate"]["median_ms"])
        improvement = (1 - candidate / baseline) * 100
        return (
            f"| {label} | {baseline:.2f} ms | {candidate:.2f} ms | "
            f"{improvement:.2f}% faster |"
        )

    def product_row(label: str, row: dict[str, Any], paired: str) -> str:
        rss = (
            "—"
            if not row["peak_rss_bytes"]
            else f"{row['peak_rss_bytes'] / (1024 * 1024):.1f} MiB"
        )
        return (
            f"| {label} | {row['median_aggregate_parent_mbps']:.2f} MB/s | "
            f"{row['minimum_aggregate_parent_mbps']:.2f} MB/s | "
            f"{row['aggregate_cv_percent']:.2f}% | "
            f"{row['rounds_at_or_above_250_mbps']}/7 | {paired} | {rss} | yes |"
        )

    lines = [
        "# JLS2 cold-start delivery development gate",
        "",
        "**Outcome: lazy loading retained as a product improvement; frozen decode gate failed.**",
        "",
        "Lazy imports sharply reduced package and command startup, and improved the real",
        f"CLI's paired aggregate median by **{candidate_cli['median_paired_improvement_percent']:.2f}%**.",
        "They did not make cold-process delivery reliable enough: the candidate CLI",
        f"cleared 250 MB/s in **{candidate_cli['rounds_at_or_above_250_mbps']}/7** rounds and the worker in",
        f"**{candidate_worker['rounds_at_or_above_250_mbps']}/7**. The next justified experiment is a standalone/native",
        "JLS2 decoder, not further Python import tuning.",
        "",
        "![JLS2 cold-process CLI and worker decode comparison](cold-start-scorecard.svg)",
        "",
        "## Product-path comparison",
        "",
        "| Path | Median | Minimum | CV | Rounds ≥250 | Paired vs baseline | Peak RSS | Exact |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
        product_row("CLI baseline", baseline_cli, "—"),
        product_row(
            "CLI lazy",
            candidate_cli,
            f"{candidate_cli['median_paired_improvement_percent']:+.2f}%",
        ),
        product_row("Worker baseline", baseline_worker, "—"),
        product_row(
            "Worker lazy",
            candidate_worker,
            f"{candidate_worker['median_paired_improvement_percent']:+.2f}%",
        ),
        "",
        "The candidate failed the all-rounds, all-family-medians, and worker paired-improvement gates.",
        "Both candidate paths remained within the 20% CV limit; worker peak RSS remained below 512 MiB.",
        "",
        "## Startup characterization",
        "",
        "| Probe | Baseline median | Lazy median | Change |",
        "| --- | ---: | ---: | ---: |",
        probe_row("python-pass", "Python process floor"),
        probe_row("import-compresslab", "Import `compresslab`"),
        probe_row("cli-version", "CLI `--version`"),
        probe_row("worker-help", "Worker `--help`"),
        "",
        "## Standards context",
        "",
        "No standard codec was rerun in this product-delivery A/B. JLS2 compressed bytes",
        "remain **3,523,721** (57.77x), so the immutable same-run 11-codec census remains",
        "authoritative: JLS2 is 18.08% smaller than Brotli-11 on this development corpus,",
        "with the previously published 109.90 / 116.43 MB/s compression/decompression",
        "census measurements. Do not substitute the A/B numbers above into that standards",
        "chart because the runner and schedule differ.",
        "",
        "- [Full 11-codec standards scorecard](../clue-json-log-development-census-v1/README.md)",
        "- [Raw paired trials and machine-readable gates](results.json)",
        "- [Frozen protocol](../../docs/benchmarks/2026-07-17-jls2-cold-start-protocol.md)",
        "- [Artifact receipt](receipt.json)",
        "",
        "## Evidence boundary",
        "",
        f"- Baseline commit: `{BASELINE_COMMIT}`",
        f"- Candidate product commit: `{candidate_commit}`",
        f"- Platform: `{result['platform']}`; Python `{result['python'].splitlines()[0]}`",
        "- Schedule: 1 discarded warmup + 7 measured rounds × 3 families × 2 paths × 2 source trees",
        "- Exactness: 96/96 total round trips; 84/84 measured",
        "- Complete JLS2 frames: 3,523,721 bytes aggregate and byte-identical",
        "- Public-validation ranges: unmaterialized and unopened",
        "",
        f"Claim ceiling: **{result['claim_ceiling']}**.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    args = parser.parse_args()
    result = json.loads(args.input.read_text(encoding="utf-8"))
    if result["protocol"] != "jls2-cold-start-v1":
        raise ValueError("unexpected result protocol")
    if result["summary"]["candidate_qualifies"]:
        raise ValueError("publisher is frozen for the rejected first result")
    if len(result["trials"]) != 96 or not all(
        trial["exact"] for trial in result["trials"]
    ):
        raise ValueError("result must contain 96 exact trials")

    RUN.mkdir(parents=True, exist_ok=True)
    results_path = RUN / "results.json"
    shutil.copyfile(args.input, results_path)
    chart_path = RUN / "cold-start-scorecard.svg"
    chart_path.write_text(render_svg(result), encoding="utf-8")
    readme_path = RUN / "README.md"
    readme_path.write_text(
        render_readme(result, args.candidate_commit), encoding="utf-8"
    )
    receipt = {
        "schema_version": 1,
        "protocol": "jls2-cold-start-v1",
        "decision": "lazy-loading-retained-decode-gate-failed",
        "baseline_commit": BASELINE_COMMIT,
        "candidate_product_commit": args.candidate_commit,
        "artifacts": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in (results_path, chart_path, readme_path, PROTOCOL)
        },
        "publication_sources": {
            path: sha256_file(ROOT / path)
            for path in PRODUCT_SOURCES
            if (ROOT / path).is_file()
        },
        "claim_ceiling": result["claim_ceiling"],
    }
    (RUN / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
