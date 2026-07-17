#!/usr/bin/env python3
"""Render the README compressed-size chart from the frozen CLUE census."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs" / "clue-json-log-development-census-v1" / "comparison.json"
OUTPUT = ROOT / "docs" / "assets" / "clue-json-log-compressed-size.svg"
README = ROOT / "README.md"
TABLE_START = "<!-- clue-scorecard:start -->"
TABLE_END = "<!-- clue-scorecard:end -->"
EXCLUDED = {"store"}
LABELS = {
    "jls2": "JLS2",
    "brotli-11": "Brotli-11",
    "zstd-19": "zstd-19",
    "bz2-9": "bzip2-9",
    "lzma-9": "LZMA-9",
    "7zip-9": "7-Zip-9",
    "zstd-9": "zstd-9",
    "zstd-3": "zstd-3",
    "gzip-9": "gzip-9",
    "lz4-1": "LZ4-1",
}


def load_rows() -> list[dict[str, object]]:
    comparison = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = comparison["comparison_rows"]
    rows.sort(key=lambda row: row["compressed_bytes"])
    return rows


def render_table(rows: list[dict[str, object]]) -> str:
    lines = [
        "| Codec | Complete bytes | Ratio | JLS2 smaller by | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for row in rows:
        codec_id = str(row["codec_id"])
        label = LABELS.get(codec_id, codec_id.title())
        bytes_text = f"{int(row['compressed_bytes']):,}"
        ratio_text = f"{float(row['ratio']):.2f}x"
        if codec_id == "jls2":
            label = f"**{label}**"
            bytes_text = f"**{bytes_text}**"
            ratio_text = f"**{ratio_text}**"
            gain_text = "—"
        else:
            gain_text = f"**{float(row['jls2_size_gain_percent']):.2f}%**"
        compression = f"{float(row['compression_mbps']):.2f}"
        decompression = f"{float(row['decompression_mbps']):.2f}"
        compression_rss = float(row["compression_peak_rss_bytes"]) / (1024 * 1024)
        decompression_rss = float(row["decompression_peak_rss_bytes"]) / (1024 * 1024)
        exact = "yes" if row["roundtrip_verified"] else "no"
        lines.append(
            f"| {label} | {bytes_text} | {ratio_text} | {gain_text} | "
            f"{compression} | {decompression} | {compression_rss:.1f} / "
            f"{decompression_rss:.1f} | {exact} |"
        )
    return "\n".join(lines)


def render_chart(rows: list[dict[str, object]]) -> str:
    rows = [row for row in rows if row["codec_id"] not in EXCLUDED]

    width = 1080
    height = 106 + len(rows) * 46 + 62
    label_x = 22
    plot_x = 170
    plot_width = 700
    max_bytes = max(row["compressed_bytes"] for row in rows)
    tick_values = (0, 2, 4, 6, 8, 10, 12, 14)
    chart: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Compressed size on CLUE-LDS structured JSON event logs</title>',
        '<desc id="desc">Horizontal bar chart. JLS2 is smallest at 3.52 megabytes, 18.08 percent smaller than Brotli-11 at 4.30 megabytes. Lower is better.</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;fill:#24292f}",
        ".title{font-size:22px;font-weight:500}.subtitle,.axis{font-size:14px;fill:#57606a}.label,.value{font-size:15px}.value{font-variant-numeric:tabular-nums}.grid{stroke:#d0d7de;stroke-width:1}.bar{fill:#8c959f}.candidate{fill:#1f883d}",
        "@media(prefers-color-scheme:dark){text{fill:#f0f6fc}.subtitle,.axis{fill:#8c959f}.grid{stroke:#30363d}.bar{fill:#6e7681}.candidate{fill:#3fb950}}",
        "</style>",
        '<text class="title" x="22" y="30">Compressed size on fresh CLUE-LDS JSON logs</text>',
        '<text class="subtitle" x="22" y="54">Complete archive MB · lower is better · Store (203.58 MB) omitted from scale</text>',
        '<text class="subtitle" x="22" y="76">JLS2 is 18.08% smaller than the closest tested standard, Brotli-11</text>',
    ]

    plot_top = 96
    plot_bottom = plot_top + len(rows) * 46
    for tick in tick_values:
        x = plot_x + (tick * 1_000_000 / max_bytes) * plot_width
        chart.append(
            f'<line class="grid" x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_bottom}"/>'
        )
        chart.append(
            f'<text class="axis" x="{x:.1f}" y="{plot_bottom + 26}" text-anchor="middle">{tick}</text>'
        )

    for index, row in enumerate(rows):
        codec_id = row["codec_id"]
        label = html.escape(LABELS.get(codec_id, codec_id))
        megabytes = row["compressed_bytes"] / 1_000_000
        y = plot_top + index * 46 + 8
        bar_width = (row["compressed_bytes"] / max_bytes) * plot_width
        bar_class = "candidate" if codec_id == "jls2" else "bar"
        chart.append(f'<text class="label" x="{label_x}" y="{y + 18}">{label}</text>')
        chart.append(
            f'<rect class="{bar_class}" x="{plot_x}" y="{y}" width="{bar_width:.1f}" height="24" rx="3"/>'
        )
        chart.append(
            f'<text class="value" x="{plot_x + bar_width + 10:.1f}" y="{y + 18}">{megabytes:.2f} MB</text>'
        )

    chart.append(
        f'<text class="axis" x="{plot_x + plot_width / 2:.1f}" y="{plot_bottom + 52}" text-anchor="middle">Complete compressed size (MB)</text>'
    )
    chart.append("</svg>")
    return "\n".join(chart) + "\n"


def render_readme(readme: str, table: str) -> str:
    prefix, separator, remainder = readme.partition(TABLE_START)
    if not separator:
        raise ValueError(f"missing README marker: {TABLE_START}")
    _, separator, suffix = remainder.partition(TABLE_END)
    if not separator:
        raise ValueError(f"missing README marker: {TABLE_END}")
    return f"{prefix}{TABLE_START}\n\n{table}\n\n{TABLE_END}{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the checked-in README scorecard or SVG is stale",
    )
    args = parser.parse_args()

    rows = load_rows()
    chart = render_chart(rows)
    current_readme = README.read_text(encoding="utf-8")
    readme = render_readme(current_readme, render_table(rows))
    if args.check:
        stale = []
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != chart:
            stale.append(str(OUTPUT.relative_to(ROOT)))
        if current_readme != readme:
            stale.append(str(README.relative_to(ROOT)))
        if stale:
            raise SystemExit(
                "stale generated benchmark presentation: " + ", ".join(stale)
            )
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(chart, encoding="utf-8")
    README.write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
