from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .corpus import load_corpus
from .metrics import add_transfer_metrics, median_trials, selector_oracle, summarize
from .models import BenchmarkRun, CodecSpec, CorpusItem, TrialResult


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _worker_environment() -> Dict[str, str]:
    env = dict(os.environ)
    source_root = str(Path(__file__).resolve().parents[1])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = source_root + (os.pathsep + existing if existing else "")
    env["PYTHONHASHSEED"] = "0"
    return env


def _run_worker(
    codec: CodecSpec,
    operation: str,
    source: Path,
    destination: Path,
    telemetry_path: Path,
    timeout_seconds: float,
) -> Tuple[int, Dict[str, Any], str]:
    command = [
        sys.executable,
        "-m",
        "compresslab.worker",
        "--codec",
        codec.id,
        "--operation",
        operation,
        "--source",
        str(source),
        "--destination",
        str(destination),
        "--telemetry",
        str(telemetry_path),
    ]
    start = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            command,
            env=_worker_environment(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = time.perf_counter_ns() - start
    except subprocess.TimeoutExpired:
        return time.perf_counter_ns() - start, {}, f"timeout after {timeout_seconds}s"

    telemetry: Dict[str, Any] = {}
    if telemetry_path.is_file():
        try:
            telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return elapsed, {}, f"invalid telemetry: {exc}"
    if completed.returncode != 0:
        detail = telemetry.get("error") or completed.stderr.strip() or completed.stdout.strip()
        return elapsed, telemetry, f"worker exited {completed.returncode}: {detail}"
    if "error" in telemetry:
        return elapsed, telemetry, telemetry["error"]
    return elapsed, telemetry, ""


def _trial(
    run_id: str,
    item: CorpusItem,
    codec: CodecSpec,
    repetition: int,
    work_dir: Path,
    timeout_seconds: float,
) -> TrialResult:
    prefix = f"{item.id}.{codec.id}.r{repetition}"
    compressed = work_dir / f"{prefix}.compressed"
    restored = work_dir / f"{prefix}.restored"
    compress_telemetry = work_dir / f"{prefix}.compress.json"
    decompress_telemetry = work_dir / f"{prefix}.decompress.json"

    compression_ns, cmeta, error = _run_worker(
        codec, "compress", item.path, compressed, compress_telemetry, timeout_seconds
    )
    if error:
        return _failed_trial(run_id, item, codec, repetition, compression_ns, 0, error)

    decompression_ns, dmeta, error = _run_worker(
        codec, "decompress", compressed, restored, decompress_telemetry, timeout_seconds
    )
    if error:
        return _failed_trial(
            run_id,
            item,
            codec,
            repetition,
            compression_ns,
            decompression_ns,
            error,
            compressed.stat().st_size if compressed.exists() else 0,
            cmeta,
            dmeta,
        )

    restored_sha256 = _hash(restored)
    roundtrip_ok = restored_sha256 == item.sha256
    error = "" if roundtrip_ok else "round-trip SHA-256 mismatch"
    return TrialResult(
        run_id=run_id,
        item_id=item.id,
        item_category=item.category,
        item_split=item.split,
        codec_id=codec.id,
        codec_family=codec.family,
        repetition=repetition,
        original_bytes=item.size_bytes,
        compressed_bytes=compressed.stat().st_size,
        compression_ns=compression_ns,
        decompression_ns=decompression_ns,
        compression_cpu_ns=int(cmeta.get("cpu_ns", 0)),
        decompression_cpu_ns=int(dmeta.get("cpu_ns", 0)),
        compression_peak_rss_bytes=int(cmeta.get("peak_rss_bytes", 0)),
        decompression_peak_rss_bytes=int(dmeta.get("peak_rss_bytes", 0)),
        roundtrip_ok=roundtrip_ok,
        source_sha256=item.sha256,
        restored_sha256=restored_sha256,
        selected_backend=str(cmeta.get("selected_backend", "")),
        selector_ns=int(cmeta.get("selector_ns", 0)),
        selector_stages=int(cmeta.get("selector_stages", 0)),
        selector_sample_bytes=int(cmeta.get("selector_sample_bytes", 0)),
        transform_engine=str(cmeta.get("transform_engine", "")),
        error=error,
    )


def _failed_trial(
    run_id: str,
    item: CorpusItem,
    codec: CodecSpec,
    repetition: int,
    compression_ns: int,
    decompression_ns: int,
    error: str,
    compressed_bytes: int = 0,
    cmeta: Optional[Dict[str, Any]] = None,
    dmeta: Optional[Dict[str, Any]] = None,
) -> TrialResult:
    cmeta = cmeta or {}
    dmeta = dmeta or {}
    return TrialResult(
        run_id=run_id,
        item_id=item.id,
        item_category=item.category,
        item_split=item.split,
        codec_id=codec.id,
        codec_family=codec.family,
        repetition=repetition,
        original_bytes=item.size_bytes,
        compressed_bytes=compressed_bytes,
        compression_ns=compression_ns,
        decompression_ns=decompression_ns,
        compression_cpu_ns=int(cmeta.get("cpu_ns", 0)),
        decompression_cpu_ns=int(dmeta.get("cpu_ns", 0)),
        compression_peak_rss_bytes=int(cmeta.get("peak_rss_bytes", 0)),
        decompression_peak_rss_bytes=int(dmeta.get("peak_rss_bytes", 0)),
        roundtrip_ok=False,
        source_sha256=item.sha256,
        restored_sha256="",
        selected_backend=str(cmeta.get("selected_backend", "")),
        selector_ns=int(cmeta.get("selector_ns", 0)),
        selector_stages=int(cmeta.get("selector_stages", 0)),
        selector_sample_bytes=int(cmeta.get("selector_sample_bytes", 0)),
        transform_engine=str(cmeta.get("transform_engine", "")),
        error=error,
    )


def run_benchmark(
    corpus_root: Path,
    output_dir: Path,
    codecs: Sequence[CodecSpec],
    repetitions: int = 3,
    warmups: int = 1,
    splits: Sequence[str] = ("validation",),
    bandwidths_mbps: Sequence[float] = (10.0, 100.0, 1000.0),
    timeout_seconds: float = 120.0,
    keep_work: bool = False,
) -> BenchmarkRun:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    if not bandwidths_mbps or any(value <= 0 for value in bandwidths_mbps):
        raise ValueError("bandwidths must be positive")

    items = load_corpus(corpus_root, splits)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    work_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=output_dir))
    trial_rows: List[Dict[str, Any]] = []

    try:
        total = len(items) * len(codecs)
        current = 0
        for item in items:
            for codec in codecs:
                current += 1
                print(f"[{current}/{total}] {item.id} × {codec.id}", flush=True)
                for warmup in range(warmups):
                    _trial(
                        run_id, item, codec, -(warmup + 1), work_dir, timeout_seconds
                    )
                for repetition in range(1, repetitions + 1):
                    result = _trial(
                        run_id, item, codec, repetition, work_dir, timeout_seconds
                    )
                    trial_rows.append(result.to_dict())
    finally:
        if not keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)

    valid_rows = [row for row in trial_rows if row["roundtrip_ok"]]
    medians = median_trials(valid_rows)
    for row in medians:
        add_transfer_metrics(row, bandwidths_mbps)
    summary = summarize(medians, bandwidths_mbps)
    oracle = selector_oracle(medians, summary, bandwidths_mbps)
    failures = [
        {
            "item_id": row["item_id"],
            "codec_id": row["codec_id"],
            "repetition": row["repetition"],
            "error": row["error"],
        }
        for row in trial_rows
        if not row["roundtrip_ok"]
    ]

    run = BenchmarkRun(
        schema_version=1,
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        system={
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
            "python_executable": sys.executable,
            "cpu_count": os.cpu_count(),
        },
        config={
            "repetitions": repetitions,
            "warmups": warmups,
            "splits": list(splits),
            "bandwidths_mbps": list(bandwidths_mbps),
            "timeout_seconds": timeout_seconds,
            "timing_scope": "parent wall clock including worker process startup",
            "memory_scope": "worker high-water RSS",
        },
        corpus=[
            {**asdict(item), "path": str(item.path)}
            for item in items
        ],
        codecs=[asdict(codec) for codec in codecs],
        trials=trial_rows,
        medians=medians,
        summary=summary,
        oracle=oracle,
        failures=failures,
    )
    _write_outputs(run, output_dir)
    return run


def _write_outputs(run: BenchmarkRun, output_dir: Path) -> None:
    payload = run.to_dict()
    (output_dir / "results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if run.summary:
        with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(run.summary[0].keys()))
            writer.writeheader()
            writer.writerows(run.summary)
    (output_dir / "report.md").write_text(_markdown_report(run), encoding="utf-8")


def _markdown_report(run: BenchmarkRun) -> str:
    lines = [
        "# Compression Lab Benchmark",
        "",
        f"- Run: {run.run_id}",
        f"- Generated: {run.generated_at}",
        f"- Trials: {len(run.trials)}",
        f"- Round-trip failures: {len(run.failures)}",
        f"- Timing: {run.config['timing_scope']}",
        "",
        "## Aggregate results",
        "",
        "| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for row in sorted(run.summary, key=lambda value: value["compressed_percent"]):
        lines.append(
            f"| {row['codec_id']} | {row['compressed_percent']:.2f} | "
            f"{row['compression_mbps']:.2f} | {row['decompression_mbps']:.2f} | "
            f"{row['expanded_items']} | {'yes' if row['pareto'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Adaptive-selector opportunity",
            "",
            "The oracle chooses the best measured codec separately for each item with zero",
            "selection cost. It is an upper bound, not a candidate result.",
            "",
            "| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |",
            "|---:|---|---:|---:|---:|",
        ]
    )
    for row in run.oracle["by_bandwidth"]:
        lines.append(
            f"| {row['bandwidth_mbps']:g} Mbps | {row['best_fixed_codec']} | "
            f"{row['best_fixed_total_ms']:.2f} | {row['oracle_total_ms']:.2f} | "
            f"{row['oracle_gain_percent']:.2f}% |"
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Values are comparable only within this run and machine context.",
            "- Parent wall time includes Python worker startup, which intentionally exposes small-file overhead.",
            "- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.",
            "- A private holdout corpus should be stored outside the repository and run only at decision gates.",
            "",
        ]
    )
    if run.failures:
        lines.extend(["## Failures", ""])
        for failure in run.failures:
            lines.append(
                f"- {failure['item_id']} × {failure['codec_id']} "
                f"(r{failure['repetition']}): {failure['error']}"
            )
        lines.append("")
    return "\n".join(lines)
