#!/usr/bin/env python3
"""Publish the immutable CLUE-LDS JLS2 v2 first-score evidence and chart."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
from typing import Any


MIB = 1024 * 1024
DECISION_NAME = "clue-jls2-public-validation-v2-first-score"
BUNDLE_NAME = "clue-jls2-public-validation-v2-first-score-bundle"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(MIB):
            digest.update(chunk)
    return digest.hexdigest()


def format_number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def render_svg(decision: dict[str, Any]) -> str:
    available = [
        row
        for row in decision["comparison_rows"]
        if row["compressed_bytes"] is not None
    ]
    if not available:
        raise ValueError("decision has no available comparison rows")
    maximum = max(int(row["compressed_bytes"]) for row in available)
    left = 170
    chart_width = 820
    row_height = 34
    top = 76
    height = top + len(available) * row_height + 72
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" '
        f'height="{height}" viewBox="0 0 1120 {height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">Atompress JLS2 CLUE-LDS v2 compressed-byte comparison</title>',
        '<desc id="description">Lower bars are better. All available exact-byte '
        "standards and the separately run PBC specialist are included.</desc>",
        '<rect width="1120" height="100%" fill="#0b1020"/>',
        '<text x="28" y="34" fill="#f8fafc" font-family="system-ui,sans-serif" '
        'font-size="22" font-weight="700">Atompress (JLS2) v2 — complete compressed bytes</text>',
        '<text x="28" y="57" fill="#94a3b8" font-family="system-ui,sans-serif" '
        'font-size="13">Lower is better · exact-byte archive accounting · two previously unopened ranges</text>',
    ]
    for index, row in enumerate(available):
        y = top + index * row_height
        name = html.escape(str(row["codec_id"]))
        byte_count = int(row["compressed_bytes"])
        width = max(2.0, byte_count / maximum * chart_width)
        is_candidate = row["role"] == "candidate"
        color = "#22c55e" if is_candidate else "#64748b"
        if row["role"] == "eligible specialist":
            color = "#a78bfa"
        elements.extend(
            [
                f'<text x="{left - 12}" y="{y + 18}" text-anchor="end" '
                f'fill="#e2e8f0" font-family="ui-monospace,monospace" font-size="13">{name}</text>',
                f'<rect x="{left}" y="{y + 4}" width="{width:.2f}" height="20" '
                f'rx="3" fill="{color}"/>',
                f'<text x="{left + width + 8:.2f}" y="{y + 19}" fill="#e2e8f0" '
                f'font-family="ui-monospace,monospace" font-size="12">{byte_count:,}</text>',
            ]
        )
    unavailable = [
        str(row["codec_id"])
        for row in decision["comparison_rows"]
        if row["compressed_bytes"] is None
    ]
    note = "Unavailable/ineligible (not wins): " + ", ".join(unavailable)
    elements.append(
        f'<text x="28" y="{height - 28}" fill="#94a3b8" '
        f'font-family="system-ui,sans-serif" font-size="12">{html.escape(note)}</text>'
    )
    elements.append("</svg>\n")
    return "\n".join(elements)


def render_report(decision: dict[str, Any]) -> str:
    passed = bool(decision["category_gate_passed"])
    aggregate = decision["aggregate"]
    status = "passed" if passed else "not passed"
    lines = [
        "# Atompress (JLS2) CLUE-LDS v2 public-validation first score",
        "",
        f"Status: **{status}**.",
        "",
        (
            "This is the second, separately frozen one-time public validation on two "
            "previously unopened CLUE-LDS ranges. It does not correct, replace, or "
            "reopen the immutable v1 not_passed score."
        ),
        "",
        (
            f"Atompress produced {aggregate['candidate_bytes']:,} bytes on "
            f"{aggregate['original_bytes']:,} source bytes. The strongest eligible "
            f"complete exact-byte result was {aggregate['strongest_eligible_codec']} "
            f"at {aggregate['strongest_eligible_bytes']:,} bytes, a frozen Atompress "
            f"gain of {aggregate['gain_vs_strongest_eligible_percent']:.2f}%."
        ),
        "",
        (
            "Candidate peak RSS is measured through the clean-child instrument: "
            f"cold-process compression peak {aggregate['compression_peak_rss_bytes']:,} "
            f"bytes (shim floor {aggregate['compression_shim_maxrss_bytes']:,} bytes); "
            "standalone decode peak "
            f"{aggregate['standalone_decompression_peak_rss_bytes']:,} bytes "
            f"(shim floor {aggregate['standalone_decompression_shim_maxrss_bytes']:,} bytes)."
        ),
        "",
        "![Complete compressed-byte comparison](comparison.svg)",
        "",
        "## Full transparent comparison",
        "",
        "| Codec | Role | Complete bytes | Ratio | Compress MB/s | Decompress MB/s | Exact | Atompress smaller? | Measurement basis |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in decision["comparison_rows"]:
        smaller = row["candidate_smaller"]
        smaller_text = (
            "candidate"
            if row["role"] == "candidate"
            else (
                "yes"
                if smaller is True
                else "no"
                if smaller is False
                else "not measured"
            )
        )
        exact = row["exact_roundtrip"]
        exact_text = (
            "yes" if exact is True else "no" if exact is False else "unavailable"
        )
        basis = f"{row['size_runner']}; {row['speed_runner']}"
        lines.append(
            f"| {row['codec_id']} | {row['role']} | "
            f"{format_number(row['compressed_bytes'])} | {format_number(row['ratio'])} | "
            f"{format_number(row['compression_mbps'])} | "
            f"{format_number(row['decompression_mbps'])} | {exact_text} | "
            f"{smaller_text} | {basis} |"
        )
    lines.extend(
        [
            "",
            "PBC size uses identical corpus bytes but its speed is contextual because it ran in a separate pinned specialist harness. Unavailable rows are disclosures, not Atompress wins.",
            "",
            "## Family decisions",
            "",
            "| Family | Source bytes | Atompress bytes | Strongest eligible | Eligible bytes | Gain | Passed |",
            "| --- | ---: | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for row in decision["family_rows"]:
        lines.append(
            f"| {row['family']} | {row['original_bytes']:,} | {row['candidate_bytes']:,} | "
            f"{row['strongest_eligible_codec']} | {row['strongest_eligible_bytes']:,} | "
            f"{row['gain_vs_strongest_eligible_percent']:.2f}% | "
            f"{'yes' if row['ratio_gate_passed'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Frozen gates",
            "",
            "| Gate | Result |",
            "| --- | --- |",
        ]
    )
    for name, gate_passed in decision["gate_results"].items():
        lines.append(
            f"| {name.replace('_', ' ')} | {'pass' if gate_passed else 'fail'} |"
        )
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            decision["claim_ceiling"],
            "",
            "The private holdout remains sealed.",
            "",
        ]
    )
    return "\n".join(lines)


def publish(
    *,
    decision_path: Path,
    receipt_path: Path,
    performance_path: Path,
    pbc_path: Path,
    manifest_path: Path,
    gates_path: Path,
    output: Path,
) -> Path:
    if output.exists():
        raise ValueError("refusing to replace an existing first-score publication")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if decision.get("name") != DECISION_NAME:
        raise ValueError("unexpected decision identity")
    expected_sources = {
        "receipt_sha256": receipt_path,
        "performance_sha256": performance_path,
        "pbc_sha256": pbc_path,
        "gates_sha256": gates_path,
    }
    for key, source in expected_sources.items():
        if decision["sources"].get(key) != sha256_file(source):
            raise ValueError(f"decision does not bind {source.name}")

    output.mkdir(parents=True)
    sources = {
        "decision.json": decision_path,
        "receipt.json": receipt_path,
        "performance.json": performance_path,
        "pbc-result.json": pbc_path,
        "validation-manifest.json": manifest_path,
        "gates.json": gates_path,
    }
    artifacts: dict[str, str] = {}
    for name, source in sources.items():
        destination = output / name
        shutil.copyfile(source, destination)
        artifacts[name] = sha256_file(destination)
    (output / "comparison.svg").write_text(render_svg(decision), encoding="utf-8")
    artifacts["comparison.svg"] = sha256_file(output / "comparison.svg")
    (output / "README.md").write_text(render_report(decision), encoding="utf-8")
    artifacts["README.md"] = sha256_file(output / "README.md")
    bundle = {
        "schema_version": 1,
        "name": BUNDLE_NAME,
        "public_brand": "Atompress",
        "technical_codec": "JLS2",
        "status": decision["result"],
        "category_gate_passed": decision["category_gate_passed"],
        "artifacts": artifacts,
        "claim_ceiling": decision["claim_ceiling"],
    }
    bundle_path = output / "bundle.json"
    bundle_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return bundle_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--pbc", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = publish(
            decision_path=args.decision,
            receipt_path=args.receipt,
            performance_path=args.performance,
            pbc_path=args.pbc,
            manifest_path=args.manifest,
            gates_path=args.gates,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise SystemExit(f"CLUE-LDS v2 publication refused: {error}") from error
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
