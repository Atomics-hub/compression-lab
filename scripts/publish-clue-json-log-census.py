#!/usr/bin/env python3
"""Publish the frozen CLUE-LDS development comparison and gate decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
EXPECTED_CODECS = {
    "jls2",
    "store",
    "lz4-1",
    "gzip-9",
    "bz2-9",
    "zstd-3",
    "zstd-9",
    "zstd-19",
    "brotli-11",
    "lzma-9",
    "7zip-9",
}
MIB = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(
        path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
    )


def speed_result(candidate: float, reference: float) -> str:
    if candidate > reference:
        return f"{candidate / reference:.2f}x faster"
    if candidate < reference:
        return f"{(1.0 - candidate / reference) * 100.0:.1f}% slower"
    return "equal"


def size_gain(reference_bytes: int, candidate_bytes: int) -> float:
    return (reference_bytes - candidate_bytes) * 100.0 / reference_bytes


def build_comparison(results_path: Path) -> dict[str, Any]:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if results.get("schema_version") != 5:
        raise ValueError("CLUE census requires results schema version 5")
    if results.get("failures"):
        raise ValueError("CLUE census contains failed trials")
    if results["config"]["execution_mode"] != "cold-process":
        raise ValueError("CLUE census must use cold-process execution")
    if results["config"]["repetitions"] < 3:
        raise ValueError("CLUE census requires at least three repetitions")

    summaries = {row["codec_id"]: row for row in results["summary"]}
    if set(summaries) != EXPECTED_CODECS:
        raise ValueError("CLUE census codec roster differs from the protocol")
    medians = results["medians"]
    jls2 = summaries["jls2"]
    standard_rows = [row for codec, row in summaries.items() if codec != "jls2"]
    strongest = min(standard_rows, key=lambda row: row["compressed_bytes"])
    family_ids = sorted(
        {row["item_id"] for row in medians if row["codec_id"] == "jls2"}
    )
    family_rows = []
    for item_id in family_ids:
        by_codec = {
            row["codec_id"]: row for row in medians if row["item_id"] == item_id
        }
        candidate = by_codec["jls2"]
        family_standard = min(
            (row for codec, row in by_codec.items() if codec != "jls2"),
            key=lambda row: row["compressed_bytes"],
        )
        family_rows.append(
            {
                "item_id": item_id,
                "original_bytes": candidate["original_bytes"],
                "jls2_bytes": candidate["compressed_bytes"],
                "strongest_standard": family_standard["codec_id"],
                "strongest_standard_bytes": family_standard["compressed_bytes"],
                "jls2_gain_percent": size_gain(
                    family_standard["compressed_bytes"],
                    candidate["compressed_bytes"],
                ),
                "jls2_smallest": candidate["compressed_bytes"]
                < family_standard["compressed_bytes"],
                "jls2_compression_mbps": candidate["compression_mbps"],
                "jls2_decompression_mbps": candidate["decompression_mbps"],
            }
        )

    comparison_rows = []
    for row in sorted(summaries.values(), key=lambda value: value["compressed_bytes"]):
        is_candidate = row["codec_id"] == "jls2"
        comparison_rows.append(
            {
                "codec_id": row["codec_id"],
                "codec_family": row["codec_family"],
                "original_bytes": row["original_bytes"],
                "compressed_bytes": row["compressed_bytes"],
                "ratio": row["original_bytes"] / row["compressed_bytes"],
                "compressed_percent": row["compressed_percent"],
                "jls2_size_gain_percent": (
                    None
                    if is_candidate
                    else size_gain(row["compressed_bytes"], jls2["compressed_bytes"])
                ),
                "jls2_smaller": None
                if is_candidate
                else jls2["compressed_bytes"] < row["compressed_bytes"],
                "compression_mbps": row["compression_mbps"],
                "jls2_compression_result": (
                    "candidate"
                    if is_candidate
                    else speed_result(jls2["compression_mbps"], row["compression_mbps"])
                ),
                "decompression_mbps": row["decompression_mbps"],
                "jls2_decompression_result": (
                    "candidate"
                    if is_candidate
                    else speed_result(
                        jls2["decompression_mbps"], row["decompression_mbps"]
                    )
                ),
                "compression_peak_rss_bytes": row["compression_peak_rss_bytes"],
                "decompression_peak_rss_bytes": row["decompression_peak_rss_bytes"],
                "roundtrip_verified": row["roundtrip_failures"] == 0,
                "comparable_runner": True,
            }
        )

    strongest_gain = size_gain(strongest["compressed_bytes"], jls2["compressed_bytes"])
    gate_results = {
        "complete_11_codec_matrix": len(comparison_rows) == 11,
        "all_99_roundtrips": len(results["trials"]) == 99
        and all(row["roundtrip_ok"] for row in results["trials"]),
        "jls2_smallest_aggregate": all(
            jls2["compressed_bytes"] < row["compressed_bytes"] for row in standard_rows
        ),
        "jls2_smallest_every_family": all(row["jls2_smallest"] for row in family_rows),
        "minimum_5_percent_gain_vs_strongest_standard": strongest_gain >= 5.0,
        "minimum_100_mbps_aggregate_compression": jls2["compression_mbps"] >= 100.0,
        "minimum_250_mbps_aggregate_decompression": jls2["decompression_mbps"] >= 250.0,
        "maximum_512_mib_compression_rss": jls2["compression_peak_rss_bytes"]
        <= 512 * MIB,
        "maximum_512_mib_decompression_rss": jls2["decompression_peak_rss_bytes"]
        <= 512 * MIB,
        "deterministic_jls2_sizes": all(
            len(
                {
                    trial["compressed_bytes"]
                    for trial in results["trials"]
                    if trial["codec_id"] == "jls2" and trial["item_id"] == item_id
                }
            )
            == 1
            for item_id in family_ids
        ),
    }
    category_gate_passed = all(gate_results.values())
    return {
        "schema_version": 1,
        "name": "clue-json-log-development-census-v1",
        "claim_ceiling": (
            "Fresh licensed CLUE-LDS development evidence only; not public "
            "validation, private holdout, independent reproduction, universal, "
            "market-leading, world-best, or state-of-the-art evidence"
        ),
        "result": "passed" if category_gate_passed else "not_passed",
        "decision": (
            "Retain JLS2 as the fresh structured-cloud-event-log ratio baseline. "
            "It wins complete bytes against every tested standard and clears the "
            "aggregate compression and memory gates, but it does not advance to "
            "public validation because the aggregate decompression gate failed."
        ),
        "source": {
            "results_path": str(results_path),
            "results_sha256": sha256_file(results_path),
            "run_id": results["run_id"],
            "generated_at": results["generated_at"],
            "git": results["system"]["git"],
            "platform": results["system"]["platform"],
            "runner": results["config"]["runner"],
            "manifest": results["config"]["corpus_manifest"],
            "repetitions": results["config"]["repetitions"],
            "warmups": results["config"]["warmups"],
            "timing_scope": results["config"]["timing_scope"],
            "memory_scope": results["config"]["memory_scope"],
        },
        "strongest_standard": {
            "codec_id": strongest["codec_id"],
            "compressed_bytes": strongest["compressed_bytes"],
            "jls2_gain_percent": strongest_gain,
        },
        "jls2": {
            "original_bytes": jls2["original_bytes"],
            "compressed_bytes": jls2["compressed_bytes"],
            "ratio": jls2["original_bytes"] / jls2["compressed_bytes"],
            "compression_mbps": jls2["compression_mbps"],
            "decompression_mbps": jls2["decompression_mbps"],
            "compression_peak_rss_bytes": jls2["compression_peak_rss_bytes"],
            "decompression_peak_rss_bytes": jls2["decompression_peak_rss_bytes"],
        },
        "gate_results": gate_results,
        "category_gate_passed": category_gate_passed,
        "family_rows": family_rows,
        "comparison_rows": comparison_rows,
        "codec_versions": {row["id"]: row["version"] for row in results["codecs"]},
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    jls2 = comparison["jls2"]
    strongest = comparison["strongest_standard"]
    lines = [
        "# CLUE-LDS JSON-log development census",
        "",
        "**Outcome: ratio win; complete category gate not passed.** JLS2 is the",
        "smallest complete archive on all three fresh development ranges and is",
        f"**{strongest['jls2_gain_percent']:.2f}% smaller than "
        f"{strongest['codec_id']}** aggregate. It clears the 100 MB/s aggregate",
        "compression and 512 MiB memory gates, but its aggregate decode rate is",
        f"{jls2['decompression_mbps']:.2f} MB/s versus the frozen 250 MB/s gate.",
        "",
        "## Full comparison",
        "",
        "All rows are complete-file, cold-process measurements from the same",
        "manifest-bound runner, with one discarded warmup and three scored trials.",
        "Positive size values mean JLS2 is smaller.",
        "",
        "| Codec | Complete bytes | Ratio | JLS2 size result | Compress MB/s | JLS2 compress result | Decompress MB/s | JLS2 decompress result | Peak RSS C/D MiB | Exact |",
        "| --- | ---: | ---: | --- | ---: | --- | ---: | --- | ---: | :---: |",
    ]
    for row in comparison["comparison_rows"]:
        size_result = (
            "candidate"
            if row["jls2_size_gain_percent"] is None
            else f"{row['jls2_size_gain_percent']:.2f}% smaller"
        )
        lines.append(
            f"| {row['codec_id']} | {row['compressed_bytes']:,} | "
            f"{row['ratio']:.2f}x | {size_result} | "
            f"{row['compression_mbps']:.2f} | "
            f"{row['jls2_compression_result']} | "
            f"{row['decompression_mbps']:.2f} | "
            f"{row['jls2_decompression_result']} | "
            f"{row['compression_peak_rss_bytes'] / MIB:.1f}/"
            f"{row['decompression_peak_rss_bytes'] / MIB:.1f} | "
            f"{'yes' if row['roundtrip_verified'] else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## Family ratio result",
            "",
            "| Development range | Source bytes | JLS2 bytes | Strongest standard | Standard bytes | JLS2 gain |",
            "| --- | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for row in comparison["family_rows"]:
        lines.append(
            f"| {row['item_id']} | {row['original_bytes']:,} | "
            f"{row['jls2_bytes']:,} | {row['strongest_standard']} | "
            f"{row['strongest_standard_bytes']:,} | "
            f"{row['jls2_gain_percent']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Frozen gates",
            "",
            "| Gate | Result |",
            "| --- | :---: |",
        ]
    )
    labels = {
        "complete_11_codec_matrix": "Complete 11-codec matrix",
        "all_99_roundtrips": "99/99 scored round trips exact",
        "jls2_smallest_aggregate": "JLS2 smallest aggregate",
        "jls2_smallest_every_family": "JLS2 smallest on every family",
        "minimum_5_percent_gain_vs_strongest_standard": "At least 5% smaller than strongest standard",
        "minimum_100_mbps_aggregate_compression": "At least 100 MB/s aggregate compression",
        "minimum_250_mbps_aggregate_decompression": "At least 250 MB/s aggregate decompression",
        "maximum_512_mib_compression_rss": "At most 512 MiB compression RSS",
        "maximum_512_mib_decompression_rss": "At most 512 MiB decompression RSS",
        "deterministic_jls2_sizes": "Deterministic JLS2 sizes",
    }
    for key, passed in comparison["gate_results"].items():
        lines.append(f"| {labels[key]} | {'PASS' if passed else 'FAIL'} |")

    lines.extend(
        [
            "",
            "## Decision and claim boundary",
            "",
            comparison["decision"],
            "",
            comparison["claim_ceiling"],
            "",
            f"Runner commit: `{comparison['source']['git']['commit']}`. "
            f"Timing scope: {comparison['source']['timing_scope']}. "
            f"Memory scope: {comparison['source']['memory_scope']}.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    comparison = build_comparison(args.results)
    comparison_path = args.output / "comparison.json"
    readme_path = args.output / "README.md"
    write_json(comparison_path, comparison)
    atomic_write(readme_path, render_markdown(comparison).encode())

    artifacts = {}
    for name in (
        "results.json",
        "summary.csv",
        "report.md",
        "comparison.json",
        "README.md",
    ):
        path = args.output / name
        if not path.is_file():
            raise FileNotFoundError(path)
        artifacts[name] = sha256_file(path)
    receipt = {
        "schema_version": 1,
        "name": "clue-json-log-development-census-v1-receipt",
        "claim_ceiling": comparison["claim_ceiling"],
        "artifacts": artifacts,
        "publisher_source": str(Path(__file__).relative_to(REPOSITORY)),
        "publisher_source_sha256": sha256_file(Path(__file__)),
    }
    write_json(args.output / "receipt.json", receipt)
    print(readme_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
