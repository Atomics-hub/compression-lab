from __future__ import annotations

import csv
from collections import deque
import hashlib
import json
import os
import platform
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .corpus import load_corpus
from .codecs import probe_codec_versions
from .metrics import add_transfer_metrics, median_trials, selector_oracle, summarize
from .models import BenchmarkRun, CodecSpec, CorpusItem, TrialResult
from .stability import analyze_stability


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


class _PersistentWorker:
    def __init__(self, startup_timeout_seconds: float) -> None:
        self._process = subprocess.Popen(
            [sys.executable, "-m", "compresslab.worker", "--server"],
            env=_worker_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._responses: queue.Queue[Optional[str]] = queue.Queue()
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        try:
            ready = self._responses.get(timeout=startup_timeout_seconds)
        except queue.Empty as exc:
            self.close()
            raise RuntimeError("persistent worker readiness timed out") from exc
        if ready is None:
            self.close()
            raise RuntimeError("persistent worker exited before readiness")
        try:
            payload = json.loads(ready)
        except json.JSONDecodeError as exc:
            self.close()
            raise RuntimeError(f"invalid persistent worker readiness: {exc}") from exc
        if payload != {"ready": True}:
            self.close()
            raise RuntimeError(f"unexpected persistent worker readiness: {payload}")

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._responses.put(line)
        self._responses.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr_lines.append(line.rstrip())

    def run(
        self,
        codec: CodecSpec,
        operation: str,
        source: Path,
        destination: Path,
        timeout_seconds: float,
        minimum_duration_ns: int,
        max_iterations: int,
    ) -> Dict[str, Any]:
        request_id = uuid.uuid4().hex
        request = {
            "request_id": request_id,
            "codec": codec.id,
            "operation": operation,
            "source": str(source),
            "destination": str(destination),
            "minimum_duration_ns": minimum_duration_ns,
            "max_iterations": max_iterations,
        }
        if self._process.poll() is not None or self._process.stdin is None:
            raise RuntimeError("persistent worker is not running")
        self._process.stdin.write(json.dumps(request, sort_keys=True) + "\n")
        self._process.stdin.flush()
        try:
            line = self._responses.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError(f"timeout after {timeout_seconds}s") from exc
        if line is None:
            detail = " | ".join(self._stderr_lines)
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"persistent worker exited without a response{suffix}")
        response = json.loads(line)
        if response.get("request_id") != request_id:
            raise RuntimeError("persistent worker response ID mismatch")
        return response

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                if self._process.stdin is not None:
                    self._process.stdin.write(
                        json.dumps({"request_id": "shutdown", "command": "shutdown"})
                        + "\n"
                    )
                    self._process.stdin.flush()
                self._process.wait(timeout=1.0)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self._process.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=1.0)
        self._reader.join(timeout=1.0)
        self._stderr_reader.join(timeout=1.0)
        for stream in (
            self._process.stdin,
            self._process.stdout,
            self._process.stderr,
        ):
            if stream is not None and not stream.closed:
                stream.close()


class _PersistentWorkerPool:
    def __init__(self, startup_timeout_seconds: float) -> None:
        self._startup_timeout_seconds = startup_timeout_seconds
        self._workers: Dict[str, _PersistentWorker] = {}

    def run(
        self,
        codec: CodecSpec,
        operation: str,
        source: Path,
        destination: Path,
        timeout_seconds: float,
        minimum_duration_ns: int = 0,
        max_iterations: int = 1,
    ) -> Tuple[int, Dict[str, Any], str]:
        try:
            worker = self._workers.get(codec.id)
            if worker is None:
                worker = _PersistentWorker(self._startup_timeout_seconds)
                self._workers[codec.id] = worker
        except (queue.Empty, RuntimeError, OSError) as exc:
            return 0, {}, f"persistent worker startup failed: {exc}"

        start = time.perf_counter_ns()
        try:
            response = worker.run(
                codec,
                operation,
                source,
                destination,
                timeout_seconds,
                minimum_duration_ns,
                max_iterations,
            )
            elapsed = time.perf_counter_ns() - start
        except (TimeoutError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            elapsed = time.perf_counter_ns() - start
            worker.close()
            self._workers.pop(codec.id, None)
            return elapsed, {}, str(exc)
        telemetry = response.get("telemetry", {})
        error = str(response.get("error", telemetry.get("error", "")))
        iterations = max(1, int(telemetry.get("batch_iterations", 1)))
        telemetry["batch_total_parent_ns"] = elapsed
        return int(elapsed / iterations), telemetry, error

    def close(self) -> None:
        for worker in self._workers.values():
            worker.close()
        self._workers.clear()


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
    order_index: int,
    work_dir: Path,
    timeout_seconds: float,
    worker_pool: Optional[_PersistentWorkerPool] = None,
    minimum_duration_ns: int = 0,
    max_batch_iterations: int = 1,
) -> TrialResult:
    prefix = f"{item.id}.{codec.id}.r{repetition}"
    compressed = work_dir / f"{prefix}.compressed"
    restored = work_dir / f"{prefix}.restored"
    compress_telemetry = work_dir / f"{prefix}.compress.json"
    decompress_telemetry = work_dir / f"{prefix}.decompress.json"

    if worker_pool is None:
        compression_ns, cmeta, error = _run_worker(
            codec, "compress", item.path, compressed, compress_telemetry, timeout_seconds
        )
    else:
        compression_ns, cmeta, error = worker_pool.run(
            codec,
            "compress",
            item.path,
            compressed,
            timeout_seconds,
            minimum_duration_ns,
            max_batch_iterations,
        )
    if error:
        return _failed_trial(
            run_id, item, codec, repetition, order_index, compression_ns, 0, error
        )

    if worker_pool is None:
        decompression_ns, dmeta, error = _run_worker(
            codec, "decompress", compressed, restored, decompress_telemetry, timeout_seconds
        )
    else:
        decompression_ns, dmeta, error = worker_pool.run(
            codec,
            "decompress",
            compressed,
            restored,
            timeout_seconds,
            minimum_duration_ns,
            max_batch_iterations,
        )
    if error:
        return _failed_trial(
            run_id,
            item,
            codec,
            repetition,
            order_index,
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
        order_index=order_index,
        original_bytes=item.size_bytes,
        compressed_bytes=compressed.stat().st_size,
        compression_ns=compression_ns,
        decompression_ns=decompression_ns,
        compression_cpu_ns=int(cmeta.get("cpu_ns", 0)),
        decompression_cpu_ns=int(dmeta.get("cpu_ns", 0)),
        compression_peak_rss_bytes=int(cmeta.get("peak_rss_bytes", 0)),
        decompression_peak_rss_bytes=int(dmeta.get("peak_rss_bytes", 0)),
        compression_worker_pid=int(cmeta.get("pid", 0)),
        decompression_worker_pid=int(dmeta.get("pid", 0)),
        compression_batch_iterations=int(cmeta.get("batch_iterations", 1)),
        decompression_batch_iterations=int(dmeta.get("batch_iterations", 1)),
        compression_batch_total_worker_ns=int(
            cmeta.get("batch_total_worker_wall_ns", cmeta.get("wall_ns", 0))
        ),
        decompression_batch_total_worker_ns=int(
            dmeta.get("batch_total_worker_wall_ns", dmeta.get("wall_ns", 0))
        ),
        compression_batch_target_met=bool(cmeta.get("batch_target_met", True)),
        decompression_batch_target_met=bool(dmeta.get("batch_target_met", True)),
        roundtrip_ok=roundtrip_ok,
        source_sha256=item.sha256,
        restored_sha256=restored_sha256,
        selected_backend=str(cmeta.get("selected_backend", "")),
        selector_ns=int(cmeta.get("selector_ns", 0)),
        selector_stages=int(cmeta.get("selector_stages", 0)),
        selector_sample_bytes=int(cmeta.get("selector_sample_bytes", 0)),
        sample_ratio=float(cmeta.get("sample_ratio", 0.0)),
        transformed_sample_ratio=float(cmeta.get("transformed_sample_ratio", 0.0)),
        selector_reason=str(cmeta.get("selector_reason", "")),
        segment_count=int(cmeta.get("segment_count", 0)),
        candidate_segment_count=int(cmeta.get("candidate_segment_count", 0)),
        transformed_segments=int(cmeta.get("transformed_segments", 0)),
        stored_segments=int(cmeta.get("stored_segments", 0)),
        structured_text_segments=int(cmeta.get("structured_text_segments", 0)),
        structured_dictionary_tokens=int(
            cmeta.get("structured_dictionary_tokens", 0)
        ),
        structured_candidate_count=int(cmeta.get("structured_candidate_count", 0)),
        transform_engine=str(cmeta.get("transform_engine", "")),
        codec_engine=str(cmeta.get("codec_engine", "")),
        error=error,
    )


def _failed_trial(
    run_id: str,
    item: CorpusItem,
    codec: CodecSpec,
    repetition: int,
    order_index: int,
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
        order_index=order_index,
        original_bytes=item.size_bytes,
        compressed_bytes=compressed_bytes,
        compression_ns=compression_ns,
        decompression_ns=decompression_ns,
        compression_cpu_ns=int(cmeta.get("cpu_ns", 0)),
        decompression_cpu_ns=int(dmeta.get("cpu_ns", 0)),
        compression_peak_rss_bytes=int(cmeta.get("peak_rss_bytes", 0)),
        decompression_peak_rss_bytes=int(dmeta.get("peak_rss_bytes", 0)),
        compression_worker_pid=int(cmeta.get("pid", 0)),
        decompression_worker_pid=int(dmeta.get("pid", 0)),
        compression_batch_iterations=int(cmeta.get("batch_iterations", 1)),
        decompression_batch_iterations=int(dmeta.get("batch_iterations", 1)),
        compression_batch_total_worker_ns=int(
            cmeta.get("batch_total_worker_wall_ns", cmeta.get("wall_ns", 0))
        ),
        decompression_batch_total_worker_ns=int(
            dmeta.get("batch_total_worker_wall_ns", dmeta.get("wall_ns", 0))
        ),
        compression_batch_target_met=bool(cmeta.get("batch_target_met", False)),
        decompression_batch_target_met=bool(dmeta.get("batch_target_met", False)),
        roundtrip_ok=False,
        source_sha256=item.sha256,
        restored_sha256="",
        selected_backend=str(cmeta.get("selected_backend", "")),
        selector_ns=int(cmeta.get("selector_ns", 0)),
        selector_stages=int(cmeta.get("selector_stages", 0)),
        selector_sample_bytes=int(cmeta.get("selector_sample_bytes", 0)),
        sample_ratio=float(cmeta.get("sample_ratio", 0.0)),
        transformed_sample_ratio=float(cmeta.get("transformed_sample_ratio", 0.0)),
        selector_reason=str(cmeta.get("selector_reason", "")),
        segment_count=int(cmeta.get("segment_count", 0)),
        candidate_segment_count=int(cmeta.get("candidate_segment_count", 0)),
        transformed_segments=int(cmeta.get("transformed_segments", 0)),
        stored_segments=int(cmeta.get("stored_segments", 0)),
        structured_text_segments=int(cmeta.get("structured_text_segments", 0)),
        structured_dictionary_tokens=int(
            cmeta.get("structured_dictionary_tokens", 0)
        ),
        structured_candidate_count=int(cmeta.get("structured_candidate_count", 0)),
        transform_engine=str(cmeta.get("transform_engine", "")),
        codec_engine=str(cmeta.get("codec_engine", "")),
        error=error,
    )


def _system_state(label: str, include_thermal_signal: bool = False) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "label": label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        state["load_average_1m_5m_15m"] = list(os.getloadavg())
    except (AttributeError, OSError):
        state["load_average_1m_5m_15m"] = []
    if include_thermal_signal and sys.platform == "darwin" and shutil.which("pmset"):
        try:
            completed = subprocess.run(
                ["pmset", "-g", "therm"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            state["thermal_signal"] = completed.stdout.strip() or completed.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            state["thermal_signal"] = f"unavailable: {exc}"
    return state


def _git_state() -> Dict[str, Any]:
    repository = Path(__file__).resolve().parents[2]

    def command(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    status = command("status", "--porcelain")
    return {
        "commit": command("rev-parse", "HEAD"),
        "branch": command("branch", "--show-current"),
        "dirty": bool(status),
    }


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
    execution_mode: str = "cold-process",
    order_seed: int = 20260715,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2000,
    minimum_trial_time_ms: float = 0.0,
    max_batch_iterations: int = 4096,
) -> BenchmarkRun:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    if not bandwidths_mbps or any(value <= 0 for value in bandwidths_mbps):
        raise ValueError("bandwidths must be positive")
    if execution_mode not in {"cold-process", "persistent-worker"}:
        raise ValueError("execution mode must be cold-process or persistent-worker")
    if minimum_trial_time_ms < 0:
        raise ValueError("minimum trial time cannot be negative")
    if max_batch_iterations < 1:
        raise ValueError("maximum batch iterations must be at least 1")
    if minimum_trial_time_ms > 0 and execution_mode != "persistent-worker":
        raise ValueError("calibrated batching requires persistent-worker mode")

    minimum_duration_ns = int(minimum_trial_time_ms * 1_000_000)

    codecs = probe_codec_versions(codecs)
    items = load_corpus(corpus_root, splits)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    work_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=output_dir))
    trial_rows: List[Dict[str, Any]] = []
    system_states = [_system_state("run-start", include_thermal_signal=True)]
    worker_pool = (
        _PersistentWorkerPool(min(timeout_seconds, 30.0))
        if execution_mode == "persistent-worker"
        else None
    )
    pairs = [(item, codec) for item in items for codec in codecs]
    rng = random.Random(order_seed)

    try:
        for warmup in range(1, warmups + 1):
            sequence = list(pairs)
            rng.shuffle(sequence)
            system_states.append(_system_state(f"warmup-{warmup}-start"))
            print(f"[warmup {warmup}/{warmups}] {len(sequence)} shuffled pairs", flush=True)
            for order_index, (item, codec) in enumerate(sequence, start=1):
                _trial(
                    run_id,
                    item,
                    codec,
                    -warmup,
                    order_index,
                    work_dir,
                    timeout_seconds,
                    worker_pool,
                )
            system_states.append(_system_state(f"warmup-{warmup}-end"))

        total = len(pairs) * repetitions
        current = 0
        for repetition in range(1, repetitions + 1):
            sequence = list(pairs)
            rng.shuffle(sequence)
            system_states.append(_system_state(f"repetition-{repetition}-start"))
            print(
                f"[repetition {repetition}/{repetitions}] {len(sequence)} shuffled pairs",
                flush=True,
            )
            for order_index, (item, codec) in enumerate(sequence, start=1):
                current += 1
                print(f"[{current}/{total}] {item.id} × {codec.id}", flush=True)
                result = _trial(
                    run_id,
                    item,
                    codec,
                    repetition,
                    order_index,
                    work_dir,
                    timeout_seconds,
                    worker_pool,
                    minimum_duration_ns,
                    max_batch_iterations,
                )
                trial_rows.append(result.to_dict())
            system_states.append(_system_state(f"repetition-{repetition}-end"))
    finally:
        if worker_pool is not None:
            worker_pool.close()
        system_states.append(_system_state("run-end", include_thermal_signal=True))
        if not keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)

    valid_rows = [row for row in trial_rows if row["roundtrip_ok"]]
    medians = median_trials(valid_rows)
    for row in medians:
        add_transfer_metrics(row, bandwidths_mbps)
    summary = summarize(medians, bandwidths_mbps)
    oracle = selector_oracle(medians, summary, bandwidths_mbps)
    stability = analyze_stability(
        trial_rows,
        bandwidths_mbps,
        confidence_level=confidence_level,
        bootstrap_samples=bootstrap_samples,
    )
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
        schema_version=4,
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        system={
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
            "python_executable": sys.executable,
            "cpu_count": os.cpu_count(),
            "state_samples": system_states,
            "git": _git_state(),
        },
        config={
            "repetitions": repetitions,
            "warmups": warmups,
            "splits": list(splits),
            "bandwidths_mbps": list(bandwidths_mbps),
            "timeout_seconds": timeout_seconds,
            "execution_mode": execution_mode,
            "order_seed": order_seed,
            "trial_order": "deterministic shuffle within every warmup and repetition block",
            "confidence_level": confidence_level,
            "bootstrap_samples": bootstrap_samples,
            "minimum_trial_time_ms": minimum_trial_time_ms,
            "max_batch_iterations": max_batch_iterations,
            "timing_scope": (
                "parent wall clock including worker process startup"
                if execution_mode == "cold-process"
                else (
                    "parent wall clock per operation excluding Python worker startup; "
                    "includes amortized IPC and file I/O, with measured operations "
                    f"batched to {minimum_trial_time_ms:g} ms or "
                    f"{max_batch_iterations} iterations"
                )
            ),
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
        stability=stability,
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
    confidence_percent = 100.0 * run.stability["confidence_level"]
    lines.extend(
        [
            "",
            "## Repeatability",
            "",
            f"Intervals are {confidence_percent:g}% deterministic percentile-bootstrap confidence intervals of the per-repetition median.",
            "",
            "| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in run.stability["per_codec"]:
        compression = row["metrics"]["compression_mbps"]
        decompression = row["metrics"]["decompression_mbps"]
        frontier = row["frontier_coverage"].get("100mbps")
        frontier_range = (
            f"{frontier['range_percentage_points']:.2f} pp"
            if frontier is not None
            else "n/a"
        )
        lines.append(
            f"| {row['codec_id']} | {compression['median']:.2f} "
            f"({compression['ci_low']:.2f}–{compression['ci_high']:.2f}) | "
            f"{compression['cv_percent']:.2f}% | "
            f"{decompression['cv_percent']:.2f}% | {frontier_range} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Values are comparable only within this run and machine context.",
            f"- Timing scope: {run.config['timing_scope']}.",
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
