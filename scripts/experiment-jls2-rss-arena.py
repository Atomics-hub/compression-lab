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

Round 4 (run 29981022229) refuted EVERY allocator hypothesis at once:
LD_PRELOADed jemalloc, MALLOC_MMAP_THRESHOLD_=1, MALLOC_TRIM_THRESHOLD_=0,
and a /dev/shm output were all byte-identical (679.6 MiB at full
parallelism, 484.5 MiB at 3 CPUs). Substituting the entire allocator cannot
produce a byte-identical peak unless the reported peak is not the
decoder's memory at all. The mprotect-inclusive syscall trace settled it:
the decoder maps ~203 MiB of anonymous read-write memory over its whole
life, yet ru_maxrss reports 679.6 MiB — more than three times every page
the process ever made writable.

The remaining explanation is the measurement instrument. On Linux, a child
spawned by fork() from a large parent starts with the parent's resident
pages (copy-on-write) mapped, and at execve the kernel folds the pre-exec
resident watermark into the accounting that wait4 later reports as
ru_maxrss. The experiment's parent is a Python process that just built and
compressed a 200 MB corpus. This also explains the fake "worker-count
step": cells with an affinity limit use preexec_fn, which forces CPython
down the plain-fork path (child inherits the parent's CURRENT resident
size, ~484 MiB), while cells without preexec_fn allow the vfork fast path,
which shares the parent's address space whose historical watermark is the
parent's PEAK (~680 MiB, set during compression). The frozen product gate
measures decoder RSS through the same pattern (a subprocess reaped from a
large Python worker, plus getrusage(RUSAGE_CHILDREN)), so the frozen
621.3 MiB reading is suspect for exactly the same reason.

Round 5 proves the instrument artifact and measures the true decoder RSS:
- tiny-artifact cells: decode a ~1 MB source. If ru_maxrss still reports
  hundreds of MiB, the reading is the parent's footprint, proven.
- GNU-time cells: /usr/bin/time -v execs the decoder from a tiny parent,
  so its fork inheritance is negligible and its reading is clean. The
  wait4 value for the same cell (measuring the tiny time process itself,
  forked from fat Python) stays polluted — both are recorded so the
  contrast is visible in one report.

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
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

GNU_TIME = Path("/usr/bin/time")

# Each cell: label, cpu_limit, which artifact to decode ("main" is the
# 200 MB-source artifact, "tiny" the ~1 MB-source control), and how to
# measure ("wait4" reproduces the round-1..4 instrument; "gnutime" also
# wraps the decoder in /usr/bin/time -v for a clean-parent reading).
CELLS: tuple[dict[str, object], ...] = (
    {"label": "baseline-all", "cpus": None, "artifact": "main", "measure": "wait4"},
    {"label": "baseline-cpus3", "cpus": 3, "artifact": "main", "measure": "wait4"},
    {"label": "gnutime-all", "cpus": None, "artifact": "main", "measure": "gnutime"},
    {"label": "gnutime-cpus3", "cpus": 3, "artifact": "main", "measure": "gnutime"},
    {"label": "tiny-all", "cpus": None, "artifact": "tiny", "measure": "wait4"},
    {"label": "tiny-cpus3", "cpus": 3, "artifact": "tiny", "measure": "wait4"},
    {
        "label": "gnutime-tiny-all",
        "cpus": None,
        "artifact": "tiny",
        "measure": "gnutime",
    },
)


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


def parse_gnu_time_maxrss(report: Path) -> int:
    for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("Maximum resident set size (kbytes):"):
            return int(line.rsplit(":", 1)[1].strip())
    raise SystemExit(f"GNU time report has no max-RSS line: {report}")


def decode_cell(
    binary: Path,
    artifact: Path,
    output: Path,
    cell: dict[str, object],
    time_report: Path | None,
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
    if time_report is not None:
        if not GNU_TIME.is_file():
            raise SystemExit("gnutime cell requested but /usr/bin/time is missing")
        time_report.unlink(missing_ok=True)
        command = [str(GNU_TIME), "-v", "-o", str(time_report)] + command
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
    result: dict[str, object] = {
        "label": cell["label"],
        "cpu_limit": cpu_limit,
        "artifact": cell["artifact"],
        "measure": cell["measure"],
        "wait4_peak_rss_raw": peak_raw,
        "wait4_peak_rss_bytes": peak_bytes,
        "wait4_peak_rss_mib": round(peak_bytes / 1048576, 1),
        "wall_seconds": round(usage.ru_utime + usage.ru_stime, 2),
        "decoded_sha256": sha256_file(output),
    }
    if time_report is not None:
        clean_raw = parse_gnu_time_maxrss(time_report)
        clean_bytes = clean_raw * 1024
        result["clean_peak_rss_raw"] = clean_raw
        result["clean_peak_rss_bytes"] = clean_bytes
        result["clean_peak_rss_mib"] = round(clean_bytes / 1048576, 1)
    return result


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

    sys.path.insert(0, str(ROOT / "src"))
    from compresslab.json_log_codec import compress_file

    sources: dict[str, dict[str, object]] = {}
    for name, size in (("main", arguments.source_bytes), ("tiny", 1_000_000)):
        source = work / f"synthetic-{name}.jsonl"
        build_synthetic_source(source, size)
        artifact = work / f"synthetic-{name}.jls2"
        compress_file(source, artifact)
        sources[name] = {
            "source_bytes": size,
            "source_sha256": sha256_file(source),
            "artifact_path": artifact,
            "artifact_bytes": artifact.stat().st_size,
            "artifact_sha256": sha256_file(artifact),
        }

    cells = []
    for cell in CELLS:
        info = sources[str(cell["artifact"])]
        time_report = (
            work / "gnu-time-report.txt" if cell["measure"] == "gnutime" else None
        )
        artifact_path = info["artifact_path"]
        assert isinstance(artifact_path, Path)
        result = decode_cell(
            binary, artifact_path, work / "decoded.jsonl", cell, time_report
        )
        if result["decoded_sha256"] != info["source_sha256"]:
            raise SystemExit(
                f"decode mismatch ({cell['label']}):"
                " decoded bytes differ from the source"
            )
        result["decode_matches_source"] = True
        cells.append(result)
        clean = result.get("clean_peak_rss_mib")
        print(
            f"{str(cell['label']):>18} "
            f"cpus={str(cell['cpus'] or 'all'):>3} "
            f"artifact={cell['artifact']:>4} "
            f"wait4={result['wait4_peak_rss_mib']:>7} MiB "
            f"clean={clean if clean is not None else '   n/a':>7}"
            f"{' MiB' if clean is not None else ''}",
            flush=True,
        )

    report = {
        "schema": "jls2-rss-arena-experiment-v5",
        "purpose": (
            "Diagnostic RSS-instrument matrix for the JLS2 native decoder on "
            "synthetic data: wait4-from-a-large-parent versus GNU-time-from-a-"
            "tiny-parent, on large and tiny artifacts. Not a gate measurement, "
            "not corpus evidence, and not a compression-quality claim."
        ),
        "platform": sys.platform,
        "cpu_count": os.cpu_count(),
        "glibc_version": glibc_version(),
        "sources": {
            name: {
                key: (str(value) if isinstance(value, Path) else value)
                for key, value in info.items()
            }
            for name, info in sources.items()
        },
        "binary_sha256": sha256_file(binary),
        "cells": cells,
    }
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
