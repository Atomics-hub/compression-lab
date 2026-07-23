"""Diagnostic JLS2 decoder RSS experiment: allocator arenas and CPU affinity.

The frozen public-validation gate measured the native decoder at 621.3 MiB
peak RSS on Linux, yet only ~50-100 MB of that is source-visible decoded data.
The leading hypothesis is glibc per-thread malloc-arena retention from the
segment worker pool. This experiment decodes one fully synthetic JLS2
artifact under a matrix of MALLOC_ARENA_MAX values and CPU-affinity limits
(available_parallelism honors affinity on Linux, which bounds the worker pool
without any code change) and records ru_maxrss for every cell.

Diagnostic only: synthetic data, no licensed corpus paths, no product change,
and every cell must reproduce the source bytes exactly or the experiment
fails. Results say nothing about compression quality; they measure allocator
behavior on this decoder.
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

ARENA_VALUES: tuple[str | None, ...] = (None, "2")
CPU_LIMITS: tuple[int | None, ...] = (None, 3, 2, 1)


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


def decode_cell(
    binary: Path,
    artifact: Path,
    output: Path,
    arena: str | None,
    cpu_limit: int | None,
) -> dict[str, object]:
    if output.exists():
        output.unlink()
    environment = dict(os.environ)
    environment.pop("MALLOC_ARENA_MAX", None)
    if arena is not None:
        environment["MALLOC_ARENA_MAX"] = arena

    # Linux-only interfaces, resolved dynamically so type checking stays
    # clean on the non-Linux CI hosts that never run this experiment.
    set_affinity = getattr(os, "sched_setaffinity")
    wait4 = getattr(os, "wait4")

    def limit_affinity() -> None:
        if cpu_limit is not None:
            set_affinity(0, set(range(cpu_limit)))

    process = subprocess.Popen(
        [str(binary), "decompress", str(artifact), "-o", str(output)],
        env=environment,
        preexec_fn=limit_affinity if cpu_limit is not None else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    _, status, usage = wait4(process.pid, 0)
    stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
    if os.waitstatus_to_exitcode(status) != 0:
        raise SystemExit(
            f"decode failed (arena={arena}, cpus={cpu_limit}): {stderr.strip()}"
        )
    peak_raw = usage.ru_maxrss
    peak_bytes = peak_raw * 1024
    return {
        "malloc_arena_max": arena,
        "cpu_limit": cpu_limit,
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
            "this experiment is Linux-only: the arena hypothesis is "
            "glibc-specific and non-Linux results do not transfer to the gate"
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

    cells = []
    for cpu_limit in CPU_LIMITS:
        for arena in ARENA_VALUES:
            cell = decode_cell(
                binary, artifact, work / "decoded.jsonl", arena, cpu_limit
            )
            if cell["decoded_sha256"] != source_sha:
                raise SystemExit(
                    f"decode mismatch (arena={arena}, cpus={cpu_limit}):"
                    " decoded bytes differ from the source"
                )
            cell["decode_matches_source"] = True
            cells.append(cell)
            print(
                f"arena={arena or 'unset':>5} cpus={cpu_limit or 'all':>3} "
                f"peak={cell['peak_rss_mib']:>8} MiB",
                flush=True,
            )

    report = {
        "schema": "jls2-rss-arena-experiment-v1",
        "purpose": (
            "Diagnostic allocator/affinity RSS matrix for the JLS2 native "
            "decoder on synthetic data. Not a gate measurement, not corpus "
            "evidence, and not a compression-quality claim."
        ),
        "platform": sys.platform,
        "cpu_count": os.cpu_count(),
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
