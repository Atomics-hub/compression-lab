from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from statistics import median, stdev
from typing import Any, Dict, List, Sequence

from .gates import frontier_coverage
from .metrics import add_transfer_metrics, summarize


def analyze_stability(
    trials: Sequence[Dict[str, Any]],
    bandwidths_mbps: Sequence[float],
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2000,
) -> Dict[str, Any]:
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence level must be between 0 and 1")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap samples must be at least 100")

    valid = [
        dict(row)
        for row in trials
        if row.get("roundtrip_ok") and int(row.get("repetition", 0)) > 0
    ]
    repetitions = sorted({int(row["repetition"]) for row in valid})
    summaries_by_codec: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    trial_rows_by_repetition: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for repetition in repetitions:
        rows = [row for row in valid if int(row["repetition"]) == repetition]
        for row in rows:
            add_transfer_metrics(row, bandwidths_mbps)
        trial_rows_by_repetition[repetition] = rows
        for summary in summarize(rows, bandwidths_mbps):
            summary["repetition"] = repetition
            summaries_by_codec[summary["codec_id"]].append(summary)

    per_codec: List[Dict[str, Any]] = []
    for codec_id, rows in sorted(summaries_by_codec.items()):
        metric_names = [
            "compressed_percent",
            "compression_mbps",
            "decompression_mbps",
            "compression_cpu_mbps",
            "decompression_cpu_mbps",
            *[
                f"total_ms_at_{_bandwidth_key(bandwidth)}mbps"
                for bandwidth in bandwidths_mbps
            ],
        ]
        metrics = {
            metric: _distribution(
                [float(row[metric]) for row in rows],
                confidence_level,
                bootstrap_samples,
                f"{codec_id}:{metric}",
            )
            for metric in metric_names
        }
        coverage: Dict[str, Any] = {}
        for bandwidth in bandwidths_mbps:
            values = [
                frontier_coverage(
                    trial_rows_by_repetition[repetition],
                    codec_id,
                    bandwidth,
                    5.0,
                    10.0,
                )["coverage_percent"]
                for repetition in repetitions
            ]
            key = f"{_bandwidth_key(bandwidth)}mbps"
            coverage[key] = {
                **_distribution(
                    values,
                    confidence_level,
                    bootstrap_samples,
                    f"{codec_id}:frontier:{key}",
                ),
                "values": values,
                "range_percentage_points": max(values) - min(values) if values else 0.0,
            }
        per_codec.append(
            {
                "codec_id": codec_id,
                "repetitions": len(rows),
                "metrics": metrics,
                "frontier_coverage": coverage,
            }
        )

    return {
        "method": (
            "Per-repetition aggregate distributions; deterministic percentile "
            "bootstrap confidence intervals of the median. Throughput CV uses "
            "sample standard deviation divided by the mean."
        ),
        "confidence_level": confidence_level,
        "bootstrap_samples": bootstrap_samples,
        "frontier_tolerances": {
            "size_percent": 5.0,
            "total_time_percent": 10.0,
        },
        "repetitions": repetitions,
        "per_codec": per_codec,
    }


def _distribution(
    values: Sequence[float],
    confidence_level: float,
    bootstrap_samples: int,
    seed_material: str,
) -> Dict[str, float]:
    if not values:
        return {
            "median": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "cv_percent": 0.0,
            "minimum": 0.0,
            "maximum": 0.0,
        }
    mean = sum(values) / len(values)
    cv = 100.0 * stdev(values) / mean if len(values) > 1 and mean else 0.0
    seed = int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    bootstrap = sorted(
        median(rng.choices(values, k=len(values))) for _ in range(bootstrap_samples)
    )
    tail = (1.0 - confidence_level) / 2.0
    low_index = min(len(bootstrap) - 1, int(tail * len(bootstrap)))
    high_index = min(len(bootstrap) - 1, int((1.0 - tail) * len(bootstrap)))
    return {
        "median": float(median(values)),
        "ci_low": float(bootstrap[low_index]),
        "ci_high": float(bootstrap[high_index]),
        "cv_percent": cv,
        "minimum": min(values),
        "maximum": max(values),
    }


def _bandwidth_key(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "_")
