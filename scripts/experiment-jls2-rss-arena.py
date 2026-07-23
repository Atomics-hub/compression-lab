"""Diagnostic JLS2 decoder RSS experiment: allocator behavior and CPU affinity.

The frozen public-validation gate measured the native decoder at 621.3 MiB
peak RSS on Linux, yet only ~50-100 MB of that is source-visible decoded data.

Round 1 (run 29979759484) refuted the MALLOC_ARENA_MAX hypothesis (no effect)
and measured a bit-identical 448.8 MiB floor at 1-3 CPUs with a +214.5 MiB
step at 4 CPUs. A counting-allocator instrumentation of the same decode
measured true peak live bytes at exactly workers x 16 MiB (segment size), so
nearly all of the Linux RSS is retention of freed memory, not live data.

Round 2 (run 29980499529) refuted the glibc dynamic-M_MMAP_THRESHOLD
hypothesis: pinning MALLOC_MMAP_THRESHOLD_=131072 changed nothing (661.3 MiB
at full parallelism, 463.8 MiB at <=3 CPUs, byte-identical to the unpinned
cells). The same binary logic peaks at ~130 MiB on macOS with real file
output, so the excess is Linux-environment-specific but not explained by the
two classic glibc malloc tunables.

Round 3 (run 29980724926) refuted transparent hugepages (THP never vs always:
byte-identical 684.3 MiB) and the GLIBC_TUNABLES spelling (also identical),
and the mmap/munmap trace showed only the FIRST worker batch direct-mmapping
its ~16-20 MiB buffers (and freeing them correctly); later batches allocated
invisibly, i.e. from arena heaps grown via mprotect, which round 3 did not
trace. The measured floors sit at total lifetime allocation churn
(12 segments x ~36 MiB ~= 437 MiB), and the peak is byte-identical at 1 and
3 CPUs and even under strace, so the peak tracks cumulative churn that is
never returned, not concurrency.

Round 4 discriminates the mechanism decisively:
- MALLOC_MMAP_THRESHOLD_=1 (extreme): if this changes nothing, the MALLOC_*
  environment path is provably not reaching the allocator decision, because
  at threshold 1 every allocation would be mmap-backed and freed to the OS;
- MALLOC_TRIM_THRESHOLD_=0: forces aggressive trim on free;
- LD_PRELOAD jemalloc (diagnostic only, never a product dependency): if RSS
  collapses, glibc-malloc retention is proven by substitution;
- output to /dev/shm vs the work directory: controls for any file-writeback
  interaction with the resident accounting;
- strace including mprotect, so arena-heap growth is finally visible.

Diagnostic only: synthetic data, no licensed corpus paths, no product change,
and every cell must reproduce the source bytes exactly or the experiment
fails. Results say nothing about compression quality; they measure allocator
and kernel memory behavior on this decoder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

THP_ENABLED_PATH = Path("/sys/kernel/mm/transparent_hugepage/enabled")
THP_DEFRAG_PATH = Path("/sys/kernel/mm/transparent_hugepage/defrag")

# Each cell: label, extra environment, cpu_limit, thp mode ("keep" leaves the
# host setting untouched), optional tmpfs output, and whether to capture a
# memory-syscall trace. The env value "JEMALLOC" is replaced at runtime with
# an LD_PRELOAD path to the installed jemalloc shared library.
CELLS: tuple[dict[str, object], ...] = (
    {"label": "baseline-all", "env": {}, "cpus": None, "thp": "keep"},
    {"label": "baseline-cpus3", "env": {}, "cpus": 3, "thp": "keep"},
    {
        "label": "mmap-threshold-1-all",
        "env": {"MALLOC_MMAP_THRESHOLD_": "1"},
        "cpus": None,
        "thp": "keep",
    },
    {
        "label": "trim-0-all",
        "env": {"MALLOC_TRIM_THRESHOLD_": "0"},
        "cpus": None,
        "thp": "keep",
    },
    {
        "label": "jemalloc-all",
        "env": {"LD_PRELOAD": "JEMALLOC"},
        "cpus": None,
        "thp": "keep",
    },
    {
        "label": "jemalloc-cpus3",
        "env": {"LD_PRELOAD": "JEMALLOC"},
        "cpus": 3,
        "thp": "keep",
    },
    {
        "label": "output-shm-all",
        "env": {},
        "cpus": None,
        "thp": "keep",
        "output_shm": True,
    },
    {
        "label": "strace-all",
        "env": {},
        "cpus": None,
        "thp": "keep",
        "strace": True,
    },
)


def find_jemalloc() -> str:
    candidates = sorted(
        Path("/usr/lib/x86_64-linux-gnu").glob("libjemalloc.so*")
    ) + sorted(Path("/usr/lib").glob("libjemalloc.so*"))
    if not candidates:
        raise SystemExit("jemalloc cell requested but no libjemalloc.so* is installed")
    return str(candidates[0])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_synthetic_source(path: Path, target_bytes: int) -> None:
    """256-key columnar records in the shape the context-stress fixture uses,
    scaled to a realistic item size. Fully synthetic."""
    keys = [f'"k{index:03d}":'.encode() for index in range(256)]
    written = 0
    record_index = 0
    with path.open("xb") as output:
        while written < target_bytes:
            parts = [b"{"]
            for key_index, key in enumerate(keys):
                if key_index:
                    parts.append(b",")
                parts.append(key)
                parts.append(bytes((48 + (record_index + key_index) % 10,)))
            parts.append(b"}\n")
            record = b"".join(parts)
            output.write(record)
            written += len(record)
            record_index += 1


def read_thp(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def selected_thp(setting: str | None) -> str | None:
    if setting is None:
        return None
    for token in setting.split():
        if token.startswith("[") and token.endswith("]"):
            return token[1:-1]
    return None


def write_thp(mode: str) -> None:
    completed = subprocess.run(
        ["sudo", "tee", str(THP_ENABLED_PATH)],
        input=mode.encode(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "cannot set transparent_hugepage/enabled to"
            f" {mode!r}: {completed.stderr.decode(errors='replace').strip()}"
        )


def glibc_version() -> str | None:
    try:
        completed = subprocess.run(
            ["ldd", "--version"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    first_line = completed.stdout.decode(errors="replace").splitlines()
    return first_line[0] if first_line else None


def decode_cell(
    binary: Path,
    artifact: Path,
    output: Path,
    cell: dict[str, object],
    strace_log: Path | None,
) -> dict[str, object]:
    if output.exists():
        output.unlink()
    environment = dict(os.environ)
    for variable in (
        "MALLOC_ARENA_MAX",
        "MALLOC_MMAP_THRESHOLD_",
        "MALLOC_TRIM_THRESHOLD_",
        "GLIBC_TUNABLES",
        "LD_PRELOAD",
    ):
        environment.pop(variable, None)
    extra_env = cell["env"]
    assert isinstance(extra_env, dict)
    resolved_env = {
        key: find_jemalloc() if value == "JEMALLOC" else value
        for key, value in extra_env.items()
    }
    environment.update(resolved_env)
    cpu_limit = cell["cpus"]

    # Linux-only interfaces, resolved dynamically so type checking stays
    # clean on the non-Linux CI hosts that never run this experiment.
    set_affinity = getattr(os, "sched_setaffinity")
    wait4 = getattr(os, "wait4")

    def limit_affinity() -> None:
        if cpu_limit is not None:
            assert isinstance(cpu_limit, int)
            set_affinity(0, set(range(cpu_limit)))

    command = [str(binary), "decompress", str(artifact), "-o", str(output)]
    if strace_log is not None:
        strace = shutil.which("strace")
        if strace is None:
            raise SystemExit("strace cell requested but strace is not installed")
        command = [
            strace,
            "-f",
            "-e",
            "trace=mmap,munmap,mremap,mprotect,brk,madvise",
            "-o",
            str(strace_log),
        ] + command
    process = subprocess.Popen(
        command,
        env=environment,
        preexec_fn=limit_affinity if cpu_limit is not None else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    _, status, usage = wait4(process.pid, 0)
    stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
    if os.waitstatus_to_exitcode(status) != 0:
        raise SystemExit(f"decode failed ({cell['label']}): {stderr.strip()}")
    peak_raw = usage.ru_maxrss
    peak_bytes = peak_raw * 1024
    return {
        "label": cell["label"],
        "env": resolved_env,
        "output_path": str(output),
        "cpu_limit": cpu_limit,
        "thp_mode_requested": cell["thp"],
        "thp_enabled_at_run": selected_thp(read_thp(THP_ENABLED_PATH)),
        "straced": strace_log is not None,
        "peak_rss_raw": peak_raw,
        "peak_rss_bytes": peak_bytes,
        "peak_rss_mib": round(peak_bytes / 1048576, 1),
        "wall_seconds": round(usage.ru_utime + usage.ru_stime, 2),
        "decoded_sha256": sha256_file(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--source-bytes", type=int, default=200_000_000)
    parser.add_argument("--binary", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    if sys.platform != "linux":
        raise SystemExit(
            "this experiment is Linux-only: the retention behavior is "
            "Linux-specific and non-Linux results do not transfer to the gate"
        )

    work = arguments.work_dir
    work.mkdir(parents=True, exist_ok=False)
    binary = arguments.binary or ROOT / "native" / "target" / "release" / "clab-jls2"
    if not binary.is_file():
        raise SystemExit(f"decoder binary missing: {binary}")

    source = work / "synthetic.jsonl"
    build_synthetic_source(source, arguments.source_bytes)
    source_sha = sha256_file(source)

    sys.path.insert(0, str(ROOT / "src"))
    from compresslab.json_log_codec import compress_file

    artifact = work / "synthetic.jls2"
    compress_file(source, artifact)

    thp_enabled_original = read_thp(THP_ENABLED_PATH)
    thp_selected_original = selected_thp(thp_enabled_original)

    cells = []
    try:
        for cell in CELLS:
            thp_mode = cell["thp"]
            if thp_mode == "never":
                write_thp("never")
            elif thp_mode == "restore":
                if thp_selected_original is not None:
                    write_thp(thp_selected_original)
            elif thp_mode != "keep":
                raise SystemExit(f"unknown thp mode: {thp_mode!r}")
            strace_log = work / "strace-memory.log" if cell.get("strace") else None
            if cell.get("output_shm"):
                decoded_path = Path("/dev/shm") / "clab-arena-decoded.jsonl"
            else:
                decoded_path = work / "decoded.jsonl"
            result = decode_cell(binary, artifact, decoded_path, cell, strace_log)
            if cell.get("output_shm"):
                decoded_path.unlink(missing_ok=True)
            if result["decoded_sha256"] != source_sha:
                raise SystemExit(
                    f"decode mismatch ({cell['label']}):"
                    " decoded bytes differ from the source"
                )
            result["decode_matches_source"] = True
            cells.append(result)
            print(
                f"{str(cell['label']):>20} "
                f"cpus={str(cell['cpus'] or 'all'):>3} "
                f"thp={result['thp_enabled_at_run'] or 'n/a':>7} "
                f"peak={result['peak_rss_mib']:>8} MiB",
                flush=True,
            )
    finally:
        if (
            thp_selected_original is not None
            and read_thp(THP_ENABLED_PATH) != thp_enabled_original
        ):
            write_thp(thp_selected_original)

    report = {
        "schema": "jls2-rss-arena-experiment-v4",
        "jemalloc_path": find_jemalloc(),
        "purpose": (
            "Diagnostic allocator/THP/affinity RSS matrix for the JLS2 native "
            "decoder on synthetic data. Not a gate measurement, not corpus "
            "evidence, and not a compression-quality claim."
        ),
        "platform": sys.platform,
        "cpu_count": os.cpu_count(),
        "glibc_version": glibc_version(),
        "thp_enabled_host": thp_enabled_original,
        "thp_defrag_host": read_thp(THP_DEFRAG_PATH),
        "source_bytes": arguments.source_bytes,
        "source_sha256": source_sha,
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": sha256_file(artifact),
        "binary_sha256": sha256_file(binary),
        "cells": cells,
    }
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
