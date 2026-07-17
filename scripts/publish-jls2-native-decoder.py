#!/usr/bin/env python3
"""Publish the frozen standalone JLS2 decoder result and scorecard."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "jls2-native-decoder-v1"
PROTOCOL = ROOT / "docs" / "benchmarks" / "2026-07-17-jls2-native-decoder-protocol.md"
COMPARISON = ROOT / "runs" / "clue-json-log-development-census-v1" / "comparison.json"
BASELINE_COMMIT = "604271cbc89a11c739848f68a7739ed523fb9a1b"
CANDIDATE_COMMIT = "86d86f80dad86735e53829c6009eb29cee0ea324"
CLAIM_CEILING = (
    "Development-only cold-process delivery evidence on the three frozen "
    "CLUE-LDS development ranges; not public validation, private holdout, "
    "independent reproduction, universal, market-leading, world-best, or "
    "state-of-the-art evidence"
)
PUBLICATION_SOURCES = (
    "README.md",
    ".github/workflows/ci.yml",
    ".github/workflows/jls2-native-decoder.yml",
    ".github/workflows/release.yml",
    "native/Cargo.lock",
    "native/Cargo.toml",
    "native/src/jls2.rs",
    "native/src/bin/clab-jls2.rs",
    "scripts/benchmark-jls2-native-decoder.py",
    "scripts/publish-jls2-native-decoder.py",
    "tests/test_jls2_native_decoder.py",
    "tests/test_jls2_native_decoder_benchmark.py",
    "tests/test_jls2_native_decoder_evidence.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def variant(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in result["summary"]["variants"] if row["variant"] == name)


def render_svg(result: dict[str, Any], comparison: dict[str, Any]) -> str:
    baseline = variant(result, "python")
    candidate = variant(result, "native")
    standards = comparison["comparison_rows"]
    width = 1440
    height = 940
    plot_x = 260
    plot_width = 1040
    top = 126
    maximum_rate = 650.0
    target_x = plot_x + 250 / maximum_rate * plot_width
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">JLS2 standalone native decoder development gate and immutable standards size census</title>',
        '<desc id="desc">The standalone native decoder passed all seven 250 megabyte per second rounds. A separate lower panel preserves the complete eleven-codec same-run standards census, including size, compression and decompression speed, memory, exactness, and runner comparability.</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;fill:#24292f}.title{font-size:24px;font-weight:600}.subtitle,.axis,.note{font-size:13px;fill:#57606a}.section{font-size:17px;font-weight:600}.label,.value{font-size:14px}.table{font-size:12px}.header{font-size:11px;font-weight:600;fill:#57606a}.grid{stroke:#d0d7de;stroke-width:1}.target{stroke:#cf222e;stroke-width:2;stroke-dasharray:6 5}.baseline{fill:#8c959f}.candidate{fill:#1f883d}.minimum{fill:#24292f}.line{stroke:#afb8c1;stroke-width:3}.standard{fill:#6e7781}.winner,.pass{fill:#1f883d}.fail{fill:#cf222e}.card{fill:#f6f8fa;stroke:#d0d7de}.divider,.rowline{stroke:#d0d7de}",
        "@media(prefers-color-scheme:dark){text{fill:#f0f6fc}.subtitle,.axis,.note,.header{fill:#8c959f}.grid,.divider,.rowline{stroke:#30363d}.target,.fail{fill:#f85149;stroke:#f85149}.baseline{fill:#6e7681}.candidate,.winner,.pass{fill:#3fb950}.minimum{fill:#f0f6fc}.line{stroke:#484f58}.standard{fill:#8c959f}.card{fill:#161b22;stroke:#30363d}}",
        "</style>",
        '<text class="title" x="24" y="34">Standalone JLS2 decode clears the frozen product gate</text>',
        '<text class="subtitle" x="24" y="58">Top: paired cold-process product paths · 7 rounds × 3 CLUE-LDS development ranges</text>',
        '<text class="subtitle" x="24" y="78">Bottom: immutable 11-codec complete-archive census · every metric uses its original same-run path</text>',
        '<text class="section" x="24" y="112">Cold-process decompression throughput (MB/s, higher is better)</text>',
    ]
    for tick in (0, 100, 200, 300, 400, 500, 600):
        x = plot_x + tick / maximum_rate * plot_width
        output.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + 116}"/>'
        )
        output.append(
            f'<text class="axis" x="{x:.1f}" y="{top + 138}" text-anchor="middle">{tick}</text>'
        )
    output.append(
        f'<line class="target" x1="{target_x:.1f}" y1="{top - 8}" x2="{target_x:.1f}" y2="{top + 116}"/>'
    )
    output.append(
        f'<text class="axis" x="{target_x:.1f}" y="{top - 14}" text-anchor="middle">frozen 250 target</text>'
    )
    for index, (label, row, css) in enumerate(
        (
            ("Pinned lazy Python CLI", baseline, "baseline"),
            ("Standalone native", candidate, "candidate"),
        )
    ):
        median = float(row["median_aggregate_parent_mbps"])
        minimum = float(row["minimum_aggregate_parent_mbps"])
        y = top + index * 58 + 8
        bar_width = median / maximum_rate * plot_width
        minimum_x = plot_x + minimum / maximum_rate * plot_width
        output.extend(
            (
                f'<text class="label" x="24" y="{y + 20}">{html.escape(label)}</text>',
                f'<rect class="{css}" x="{plot_x}" y="{y}" width="{bar_width:.1f}" height="28" rx="4"/>',
                f'<circle class="minimum" cx="{minimum_x:.1f}" cy="{y + 14}" r="5"/>',
                f'<text class="value" x="{plot_x + bar_width + 10:.1f}" y="{y + 20}">{median:.1f} median</text>',
            )
        )
    cards_y = 292
    cards = (
        ("Exact", "48 / 48"),
        ("Rounds ≥250", "7 / 7"),
        ("Paired gain", f"+{candidate['median_paired_improvement_percent']:.2f}%"),
        ("Peak RSS", f"{candidate['peak_rss_bytes'] / (1024 * 1024):.1f} MiB"),
    )
    for index, (label, value) in enumerate(cards):
        x = 24 + index * 342
        output.append(
            f'<rect class="card" x="{x}" y="{cards_y}" width="318" height="66" rx="6"/>'
        )
        output.append(
            f'<text class="note" x="{x + 14}" y="{cards_y + 23}">{label}</text>'
        )
        output.append(
            f'<text class="section" x="{x + 14}" y="{cards_y + 49}">{value}</text>'
        )

    divider_y = 388
    output.append(
        f'<line class="divider" x1="24" y1="{divider_y}" x2="1416" y2="{divider_y}"/>'
    )
    output.append(
        '<text class="section" x="24" y="420">Immutable complete 11-codec standards scorecard</text>'
    )
    output.append(
        '<text class="note" x="24" y="442">Size bars use a log scale. C/D speeds and peak C/D RSS remain the original same-run measurements; native delivery speed above is a separate A/B.</text>'
    )
    min_log = math.log10(min(row["compressed_bytes"] for row in standards))
    max_log = math.log10(max(row["compressed_bytes"] for row in standards))
    row_top = 496
    row_height = 35
    bar_x = 130
    bar_width = 270
    headers = (
        (24, "CODEC"),
        (130, "SIZE (LOG)"),
        (415, "MB · RATIO"),
        (535, "JLS2 SIZE"),
        (655, "C MB/S"),
        (735, "JLS2 C"),
        (855, "D MB/S"),
        (935, "JLS2 D"),
        (1065, "PEAK C/D MIB"),
        (1195, "EXACT"),
        (1260, "RUNNER"),
    )
    for x, label in headers:
        output.append(f'<text class="header" x="{x}" y="470">{label}</text>')
    for index, row in enumerate(standards):
        y = row_top + index * row_height
        position = bar_x + (
            (math.log10(row["compressed_bytes"]) - min_log)
            / (max_log - min_log)
            * bar_width
        )
        css = "winner" if row["codec_id"] == "jls2" else "standard"
        size_result = (
            "candidate"
            if row["codec_id"] == "jls2"
            else f"+{row['jls2_size_gain_percent']:.1f}%"
        )
        compression_result = row["jls2_compression_result"]
        decompression_result = row["jls2_decompression_result"]
        compression_css = (
            "winner"
            if row["codec_id"] == "jls2" or "faster" in compression_result
            and "slower" not in compression_result
            else "fail"
        )
        decompression_css = (
            "winner"
            if row["codec_id"] == "jls2" or "faster" in decompression_result
            and "slower" not in decompression_result
            else "fail"
        )
        peak_c = row["compression_peak_rss_bytes"] / (1024 * 1024)
        peak_d = row["decompression_peak_rss_bytes"] / (1024 * 1024)
        output.extend(
            (
                f'<line class="rowline" x1="24" y1="{y + 15}" x2="1416" y2="{y + 15}"/>',
                f'<text class="label" x="24" y="{y + 5}">{html.escape(row["codec_id"])}</text>',
                f'<line class="line" x1="{bar_x}" y1="{y}" x2="{position:.1f}" y2="{y}"/>',
                f'<circle class="{css}" cx="{position:.1f}" cy="{y}" r="6"/>',
                f'<text class="table" x="415" y="{y + 5}">{row["compressed_bytes"] / 1_000_000:.2f} · {row["ratio"]:.2f}x</text>',
                f'<text class="table winner" x="535" y="{y + 5}">{size_result}</text>',
                f'<text class="table" x="655" y="{y + 5}">{row["compression_mbps"]:.2f}</text>',
                f'<text class="table {compression_css}" x="735" y="{y + 5}">{html.escape(compression_result)}</text>',
                f'<text class="table" x="855" y="{y + 5}">{row["decompression_mbps"]:.2f}</text>',
                f'<text class="table {decompression_css}" x="935" y="{y + 5}">{html.escape(decompression_result)}</text>',
                f'<text class="table" x="1065" y="{y + 5}">{peak_c:.1f}/{peak_d:.1f}</text>',
                f'<text class="table pass" x="1195" y="{y + 5}">{"yes" if row["roundtrip_verified"] else "no"}</text>',
                f'<text class="table pass" x="1260" y="{y + 5}">{"same run" if row["comparable_runner"] else "not comparable"}</text>',
            )
        )
    output.append(
        f'<text class="note" x="24" y="{height - 18}">JLS2 remains 18.08% smaller than Brotli-11 · public-validation ranges unopened · no universal or world-best claim</text>'
    )
    output.append("</svg>")
    return "\n".join(output) + "\n"


def render_readme(
    result: dict[str, Any],
    comparison: dict[str, Any],
    ci_run_id: int,
    release_run_id: int,
) -> str:
    baseline = variant(result, "python")
    candidate = variant(result, "native")

    def product_row(label: str, row: dict[str, Any], paired: str) -> str:
        return (
            f"| {label} | {row['median_aggregate_parent_mbps']:.2f} MB/s | "
            f"{row['minimum_aggregate_parent_mbps']:.2f} MB/s | "
            f"{row['aggregate_cv_percent']:.2f}% | "
            f"{row['rounds_at_or_above_250_mbps']}/7 | {paired} | "
            f"{row['peak_rss_bytes'] / (1024 * 1024):.1f} MiB | yes |"
        )

    lines = [
        "# JLS2 standalone native decoder development gate",
        "",
        "**Outcome: the standalone native decoder passed the frozen development product gate.**",
        "",
        "The complete cold-process product path reached",
        f"**{candidate['median_aggregate_parent_mbps']:.2f} MB/s** median aggregate throughput and never fell below",
        f"**{candidate['minimum_aggregate_parent_mbps']:.2f} MB/s** in any aggregate round. It cleared 250 MB/s in",
        f"**{candidate['rounds_at_or_above_250_mbps']}/7** rounds, restored all 48 scheduled outputs exactly, and used",
        f"**{candidate['peak_rss_bytes'] / (1024 * 1024):.1f} MiB** peak RSS.",
        "",
        "![Standalone JLS2 delivery gate and immutable standards size census](native-decoder-scorecard.svg)",
        "",
        "## Product-path comparison",
        "",
        "| Path | Median | Minimum | CV | Rounds ≥250 | Paired vs Python | Peak RSS | Exact |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
        product_row("Pinned lazy Python CLI", baseline, "—"),
        product_row(
            "Standalone native",
            candidate,
            f"+{candidate['median_paired_improvement_percent']:.2f}%",
        ),
        "",
        "Every standalone family median cleared the target:",
        "",
        "| Frozen range | Median | Minimum |",
        "| --- | ---: | ---: |",
    ]
    for row in candidate["family_rows"]:
        lines.append(
            f"| `{row['family']}` | {row['median_parent_mbps']:.2f} MB/s | "
            f"{row['minimum_parent_mbps']:.2f} MB/s |"
        )
    lines.extend(
        (
            "",
            "## Safety, portability, and packaging",
            "",
            "- complete JLS2/JLF2/JLC1 parsing and nested SHA-256 checks;",
            "- direct, columnar, empty, truncated, corrupt, oversized, trailing-data,",
            "  overwrite, forced-replacement, cleanup, and path-collision coverage;",
            "- same-directory temporary output and atomic publication after full verification;",
            "- bounded segment parallelism and explicit maximum-output enforcement;",
            "- self-contained release binary with bundled zstd and no Python dependency;",
            "- local macOS binary links only to the system `libSystem`;",
            f"- cross-platform CI run [`{ci_run_id}`](https://github.com/Atomics-hub/compression-lab/actions/runs/{ci_run_id}) passed on Linux, macOS, and Windows; and",
            f"- release-artifact run [`{release_run_id}`](https://github.com/Atomics-hub/compression-lab/actions/runs/{release_run_id}) verified the distribution workflow.",
            "",
            "## Standards context",
            "",
            f"JLS2 compressed the immutable {comparison['jls2']['original_bytes'] / 1_000_000:.1f} MB census to",
            f"**{comparison['jls2']['compressed_bytes']:,} bytes** ({comparison['jls2']['ratio']:.2f}x),",
            "18.08% smaller than Brotli-11 and smaller than every tested standard.",
            "No standard codec was rerun in this delivery experiment. The standalone",
            "585.43 MB/s result therefore clears the absolute product gate but is not",
            "inserted into the immutable same-run standards speed table.",
            "",
            "- [Full immutable 11-codec scorecard](../clue-json-log-development-census-v1/README.md)",
            "- [Raw paired trials and machine-readable performance gates](results.json)",
            "- [Frozen protocol](../../docs/benchmarks/2026-07-17-jls2-native-decoder-protocol.md)",
            "- [Artifact receipt](receipt.json)",
            "- [Verified hosted release checksums](release-SHA256SUMS)",
            "",
            "## Evidence boundary",
            "",
            f"- Baseline commit: `{BASELINE_COMMIT}`",
            f"- Candidate implementation commit: `{CANDIDATE_COMMIT}`",
            f"- Candidate binary SHA-256: `{result['native_binary']['sha256']}`",
            "- Schedule: 1 discarded warmup + 7 measured rounds × 3 families × 2 paths",
            "- Exactness: 48/48 scheduled round trips; 42/42 measured",
            "- JLS2 frames: byte-identical to the immutable development census",
            "- Public-validation ranges: unmaterialized and unopened",
            "",
            f"Claim ceiling: **{CLAIM_CEILING}.**",
            "",
        )
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ci-run-id", type=int, required=True)
    parser.add_argument("--release-run-id", type=int, required=True)
    parser.add_argument("--release-checksums", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.input.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    if result["protocol"] != "jls2-standalone-native-decoder-v1":
        raise ValueError("unexpected result protocol")
    if result["baseline_commit"] != BASELINE_COMMIT:
        raise ValueError("baseline commit drift")
    if result["candidate_commit"] != CANDIDATE_COMMIT:
        raise ValueError("candidate commit drift")
    if not result["summary"]["candidate_qualifies_performance"]:
        raise ValueError(
            "standalone candidate did not pass the frozen performance gates"
        )
    if len(result["trials"]) != 48 or not all(
        trial["exact"] for trial in result["trials"]
    ):
        raise ValueError("result must contain 48 exact scheduled trials")
    if comparison["jls2"]["compressed_bytes"] != 3_523_721:
        raise ValueError("immutable standards census drift")
    checksum_lines = [
        line
        for line in args.release_checksums.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(checksum_lines) != 9:
        raise ValueError("verified release manifest must contain exactly 9 artifacts")
    checksum_entries = []
    for line in checksum_lines:
        digest, separator, name = line.partition("  ")
        if (
            separator != "  "
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not name.startswith(("dist/", "standalone/"))
            or ".." in Path(name).parts
        ):
            raise ValueError(f"invalid verified release checksum entry: {line!r}")
        checksum_entries.append((digest, name))
    checksum_names = [name for _, name in checksum_entries]
    if len(set(checksum_names)) != len(checksum_names):
        raise ValueError("verified release manifest contains duplicate artifact names")
    if sum(name.startswith("dist/") for name in checksum_names) != 6:
        raise ValueError("verified release manifest must contain 1 sdist and 5 wheels")
    if sum(name.endswith(".whl") for name in checksum_names) != 5:
        raise ValueError("verified release manifest must contain exactly 5 wheels")
    if sum(
        name.startswith("dist/") and name.endswith(".tar.gz")
        for name in checksum_names
    ) != 1:
        raise ValueError("verified release manifest must contain exactly 1 sdist")
    if sum(name.startswith("standalone/") for name in checksum_names) != 3:
        raise ValueError("verified release manifest must contain 3 standalone archives")

    RUN.mkdir(parents=True, exist_ok=True)
    results_path = RUN / "results.json"
    shutil.copyfile(args.input, results_path)
    chart_path = RUN / "native-decoder-scorecard.svg"
    chart_path.write_text(render_svg(result, comparison), encoding="utf-8")
    readme_path = RUN / "README.md"
    readme_path.write_text(
        render_readme(result, comparison, args.ci_run_id, args.release_run_id),
        encoding="utf-8",
    )
    checksums_path = RUN / "release-SHA256SUMS"
    shutil.copyfile(args.release_checksums, checksums_path)
    receipt = {
        "schema_version": 1,
        "protocol": "jls2-standalone-native-decoder-v1",
        "decision": "standalone-native-decode-development-gate-passed",
        "baseline_commit": BASELINE_COMMIT,
        "candidate_implementation_commit": CANDIDATE_COMMIT,
        "ci": {
            "cross_platform_run_id": args.ci_run_id,
            "cross_platform_conclusion": "success",
            "release_artifact_run_id": args.release_run_id,
            "release_artifact_conclusion": "success",
        },
        "artifacts": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in (
                results_path,
                chart_path,
                readme_path,
                checksums_path,
                PROTOCOL,
                COMPARISON,
            )
        },
        "publication_sources": {
            path: sha256_file(ROOT / path)
            for path in PUBLICATION_SOURCES
            if (ROOT / path).is_file()
        },
        "claim_ceiling": CLAIM_CEILING,
    }
    (RUN / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
