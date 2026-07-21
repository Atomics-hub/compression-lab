#!/usr/bin/env python3
"""Render the standardized E2-A development result chart and readme."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path


MIB = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def render_svg(result: dict, output: Path) -> None:
    baseline = 1712149
    rows = [("E1 Kanzi-max", baseline, None, None)] + [
        (
            row["method_id"],
            row["complete_container"]["bytes"],
            row["maximum_compression_peak_rss_bytes"],
            row["maximum_decompression_peak_rss_bytes"],
        )
        for row in result["method_summaries"]
    ]
    width, height = 1000, 135 + 72 * len(rows)
    max_bytes = max(row[1] for row in rows)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1020"/>',
        "<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;fill:#edf2ff}.muted{fill:#a9b4d0}.title{font-size:23px;font-weight:700}.label{font-size:15px}.value{font-size:14px}</style>",
        '<text x="36" y="42" class="title">Axiom E2-A — JSON context ceiling under 460 MiB</text>',
        '<text x="36" y="68" class="muted">Development-only · complete framed bytes · lower is better</text>',
    ]
    for index, (label, size, compress_rss, decode_rss) in enumerate(rows):
        y = 108 + index * 72
        bar = int(610 * size / max_bytes)
        color = "#8aa4ff" if index == 0 else "#52d6a5"
        parts.append(f'<text x="36" y="{y}" class="label">{html.escape(label)}</text>')
        parts.append(
            f'<rect x="250" y="{y - 18}" width="{bar}" height="22" rx="4" fill="{color}"/>'
        )
        parts.append(f'<text x="{270 + bar}" y="{y}" class="value">{size:,} B</text>')
        if compress_rss is not None:
            parts.append(
                f'<text x="250" y="{y + 25}" class="muted value">RSS C {compress_rss / MIB:.1f} MiB · D {decode_rss / MIB:.1f} MiB</text>'
            )
    parts.append("</svg>")
    output.write_text("\n".join(parts) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    chart = args.output / "comparison.svg"
    render_svg(result, chart)
    best = result["decision"]["best_eligible_method"] or "none"
    best_bytes = result["decision"]["best_eligible_complete_bytes"]
    rows = []
    for row in result["method_summaries"]:
        rows.append(
            f"| {row['method_id']} | {row['maximum_block_mib']} MiB | {row['complete_container']['bytes']:,} | "
            f"{row['gain_vs_e1_kanzi_basis_points'] / 100:.2f}% | {row['maximum_compression_peak_rss_bytes'] / MIB:.1f} MiB | "
            f"{row['maximum_decompression_peak_rss_bytes'] / MIB:.1f} MiB | {'yes' if row['eligible'] else 'no'} |"
        )
    readme = f"""# E2-A JSON context-ceiling result

![Complete-byte and memory comparison](comparison.svg)

Evidence stage: **development-only diagnostic**. Decision: **{result["decision"]["outcome"]}**.
Best memory-eligible method: **{best}**{f" at {best_bytes:,} complete bytes" if best_bytes is not None else ""}.

| Method | Max block | Complete bytes | Gain vs E1 Kanzi | Compress RSS | Decode RSS | <=460 MiB both |
|---|---:|---:|---:|---:|---:|:---:|
| E1 Kanzi-max | 1 GiB | 1,712,149 | reference | 1,526.7 MiB* | 1,526.7 MiB* | no* |
{chr(10).join(rows)}

`*` E1's published peak is a cross-phase same-run context value, not a same-run E2 speed/RSS comparison. E2 timing is contextual only.

This result used only the three previously consumed CLUE development items. It is not an unseen score, candidate win, private holdout, independent reproduction, practical-speed result, or state-of-the-art claim. Both prior public-validation families remain consumed; a future candidate requires a newly frozen lineage-distinct corpus.

Result SHA-256: `{sha256_file(args.result)}`.
"""
    (args.output / "README.md").write_text(readme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
