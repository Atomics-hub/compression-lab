from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def median_trials(trials: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for trial in trials:
        grouped[(trial["item_id"], trial["codec_id"])].append(trial)

    rows: List[Dict[str, Any]] = []
    numeric_fields = (
        "compressed_bytes",
        "compression_ns",
        "decompression_ns",
        "compression_cpu_ns",
        "decompression_cpu_ns",
        "compression_peak_rss_bytes",
        "decompression_peak_rss_bytes",
        "selector_ns",
    )
    for _, group in sorted(grouped.items()):
        base = dict(group[0])
        for field in numeric_fields:
            base[field] = int(median(row.get(field, 0) for row in group))
        base["repetition"] = 0
        original = base["original_bytes"]
        compressed = base["compressed_bytes"]
        base["compressed_percent"] = 100.0 * compressed / original if original else 0.0
        base["savings_percent"] = (
            100.0 * (1.0 - compressed / original) if original else 0.0
        )
        base["compression_mbps"] = _throughput(original, base["compression_ns"])
        base["decompression_mbps"] = _throughput(original, base["decompression_ns"])
        rows.append(base)
    return rows


def add_transfer_metrics(row: Dict[str, Any], bandwidths_mbps: Iterable[float]) -> None:
    for bandwidth in bandwidths_mbps:
        transfer_ns = int(row["compressed_bytes"] * 8 * 1_000 / bandwidth)
        key = f"total_ms_at_{_bandwidth_key(bandwidth)}mbps"
        row[key] = (
            row["compression_ns"] + transfer_ns + row["decompression_ns"]
        ) / 1_000_000.0


def summarize(
    median_rows: Sequence[Dict[str, Any]],
    bandwidths_mbps: Sequence[float],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in median_rows:
        grouped[row["codec_id"]].append(row)

    summary: List[Dict[str, Any]] = []
    for codec_id, rows in sorted(grouped.items()):
        original = sum(row["original_bytes"] for row in rows)
        compressed = sum(row["compressed_bytes"] for row in rows)
        compression_ns = sum(row["compression_ns"] for row in rows)
        decompression_ns = sum(row["decompression_ns"] for row in rows)
        item_failures = sum(not row["roundtrip_ok"] for row in rows)
        entry: Dict[str, Any] = {
            "codec_id": codec_id,
            "codec_family": rows[0]["codec_family"],
            "items": len(rows),
            "roundtrip_failures": item_failures,
            "original_bytes": original,
            "compressed_bytes": compressed,
            "compressed_percent": 100.0 * compressed / original if original else 0.0,
            "savings_percent": 100.0 * (1.0 - compressed / original) if original else 0.0,
            "compression_mbps": _throughput(original, compression_ns),
            "decompression_mbps": _throughput(original, decompression_ns),
            "compression_peak_rss_bytes": max(
                row["compression_peak_rss_bytes"] for row in rows
            ),
            "decompression_peak_rss_bytes": max(
                row["decompression_peak_rss_bytes"] for row in rows
            ),
            "expanded_items": sum(
                row["compressed_bytes"] > row["original_bytes"] for row in rows
            ),
            "selector_time_percent": (
                100.0 * sum(row.get("selector_ns", 0) for row in rows) / compression_ns
                if compression_ns
                else 0.0
            ),
        }
        for bandwidth in bandwidths_mbps:
            transfer_ns = int(compressed * 8 * 1_000 / bandwidth)
            entry[f"total_ms_at_{_bandwidth_key(bandwidth)}mbps"] = (
                compression_ns + transfer_ns + decompression_ns
            ) / 1_000_000.0
        summary.append(entry)

    _mark_pareto(summary)
    return summary


def selector_oracle(
    median_rows: Sequence[Dict[str, Any]],
    summary_rows: Sequence[Dict[str, Any]],
    bandwidths_mbps: Sequence[float],
) -> Dict[str, Any]:
    by_item: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in median_rows:
        by_item[row["item_id"]].append(row)

    size_choices = [min(rows, key=lambda row: row["compressed_bytes"]) for rows in by_item.values()]
    best_fixed_size = min(summary_rows, key=lambda row: row["compressed_bytes"])
    size_bytes = sum(row["compressed_bytes"] for row in size_choices)
    size_counts: Dict[str, int] = defaultdict(int)
    for row in size_choices:
        size_counts[row["codec_id"]] += 1

    bandwidth_results: List[Dict[str, Any]] = []
    for bandwidth in bandwidths_mbps:
        key = f"total_ms_at_{_bandwidth_key(bandwidth)}mbps"
        choices = [min(rows, key=lambda row: row[key]) for rows in by_item.values()]
        oracle_total = sum(row[key] for row in choices)
        best_fixed = min(summary_rows, key=lambda row: row[key])
        counts: Dict[str, int] = defaultdict(int)
        for row in choices:
            counts[row["codec_id"]] += 1
        bandwidth_results.append(
            {
                "bandwidth_mbps": bandwidth,
                "oracle_total_ms": oracle_total,
                "best_fixed_codec": best_fixed["codec_id"],
                "best_fixed_total_ms": best_fixed[key],
                "oracle_gain_percent": (
                    100.0 * (1.0 - oracle_total / best_fixed[key])
                    if best_fixed[key]
                    else 0.0
                ),
                "choice_counts": dict(sorted(counts.items())),
            }
        )

    return {
        "definition": "Per-item zero-cost oracle; an upper bound, not an implementable selector result.",
        "size": {
            "oracle_compressed_bytes": size_bytes,
            "best_fixed_codec": best_fixed_size["codec_id"],
            "best_fixed_compressed_bytes": best_fixed_size["compressed_bytes"],
            "oracle_gain_percent": (
                100.0 * (1.0 - size_bytes / best_fixed_size["compressed_bytes"])
                if best_fixed_size["compressed_bytes"]
                else 0.0
            ),
            "choice_counts": dict(sorted(size_counts.items())),
        },
        "by_bandwidth": bandwidth_results,
    }


def _mark_pareto(rows: List[Dict[str, Any]]) -> None:
    for candidate in rows:
        dominated = any(
            other is not candidate
            and other["compressed_bytes"] <= candidate["compressed_bytes"]
            and other["compression_mbps"] >= candidate["compression_mbps"]
            and other["decompression_mbps"] >= candidate["decompression_mbps"]
            and (
                other["compressed_bytes"] < candidate["compressed_bytes"]
                or other["compression_mbps"] > candidate["compression_mbps"]
                or other["decompression_mbps"] > candidate["decompression_mbps"]
            )
            for other in rows
        )
        candidate["pareto"] = not dominated


def _throughput(byte_count: int, elapsed_ns: int) -> float:
    if byte_count <= 0 or elapsed_ns <= 0:
        return 0.0
    return (byte_count / 1_000_000.0) / (elapsed_ns / 1_000_000_000.0)


def _bandwidth_key(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "_")
