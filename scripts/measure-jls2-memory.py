#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.experimental import (  # noqa: E402
    compress_json_log_file,
    decompress_json_log_file,
)
from compresslab.json_log_codec import (  # noqa: E402
    MAX_COMPRESSION_SEGMENT_WORKERS,
    MAX_DECOMPRESSION_SEGMENT_WORKERS,
)


MAX_RSS_PATTERN = re.compile(r"^\s*(\d+)\s+maximum resident set size\s*$")
PEAK_FOOTPRINT_PATTERN = re.compile(r"^\s*(\d+)\s+peak memory footprint\s*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git_state() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"commit": commit, "dirty": dirty}


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def parse_time_output(stderr: str) -> dict[str, int]:
    maximum_resident_set = None
    peak_memory_footprint = None
    for line in stderr.splitlines():
        if match := MAX_RSS_PATTERN.match(line):
            maximum_resident_set = int(match.group(1))
        elif match := PEAK_FOOTPRINT_PATTERN.match(line):
            peak_memory_footprint = int(match.group(1))
    if maximum_resident_set is None:
        raise RuntimeError("/usr/bin/time did not report maximum resident set")
    result = {"maximum_resident_set_bytes": maximum_resident_set}
    if peak_memory_footprint is not None:
        result["peak_memory_footprint_bytes"] = peak_memory_footprint
    return result


def measure_worker(
    mode: str,
    source: Path,
    destination: Path,
    *,
    segment_size: int,
    max_output_size: int,
) -> dict[str, int]:
    command = [
        "/usr/bin/time",
        "-l",
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-mode",
        mode,
        "--source",
        str(source),
        "--destination",
        str(destination),
        "--segment-size",
        str(segment_size),
        "--max-output-size",
        str(max_output_size),
    ]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{mode} memory worker failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return parse_time_output(completed.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure complete JLS2 child-process peak memory"
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--accepted", type=Path)
    parser.add_argument("--gates", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--worker-mode",
        choices=("compress", "decompress"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--destination", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--segment-size",
        type=int,
        default=16 * 1024 * 1024,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-output-size",
        type=int,
        default=2 * 1024**3,
        help=argparse.SUPPRESS,
    )
    return parser


def run_worker(args: argparse.Namespace) -> int:
    if args.source is None or args.destination is None:
        raise SystemExit("worker source and destination are required")
    if args.worker_mode == "compress":
        compress_json_log_file(
            args.source,
            args.destination,
            segment_size=args.segment_size,
        )
    elif args.worker_mode == "decompress":
        decompress_json_log_file(
            args.source,
            args.destination,
            max_output_size=args.max_output_size,
        )
    else:
        raise AssertionError(args.worker_mode)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.worker_mode is not None:
        return run_worker(args)
    if None in (args.manifest, args.accepted, args.gates, args.output):
        raise SystemExit(
            "manifest, accepted, gates, and output are required"
        )

    manifest_path: Path = args.manifest
    accepted_path: Path = args.accepted
    gates_path: Path = args.gates
    output_path: Path = args.output
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    accepted_payload = json.loads(
        accepted_path.read_text(encoding="utf-8")
    )
    accepted = {
        row["family"]: row for row in accepted_payload["rows"]
    }
    gates = json.loads(gates_path.read_text(encoding="utf-8"))
    requirements = gates["requirements"]
    repository = git_state()
    if requirements["require_clean_commit"] and repository["dirty"]:
        raise SystemExit("memory measurement requires a clean commit")
    compression_workers_passed = (
        MAX_COMPRESSION_SEGMENT_WORKERS
        <= requirements["maximum_compression_segment_workers"]
    )
    decompression_workers_passed = (
        MAX_DECOMPRESSION_SEGMENT_WORKERS
        <= requirements["maximum_decompression_segment_workers"]
    )

    rows = []
    with tempfile.TemporaryDirectory(
        prefix="compression-lab-jls2-memory-"
    ) as directory:
        work = Path(directory)
        for item in manifest["items"]:
            family = item["family"]
            source = Path(item["path"])
            if source.stat().st_size != item["size_bytes"]:
                raise ValueError(f"corpus size mismatch: {source}")
            if sha256_file(source) != item["sha256"]:
                raise ValueError(f"corpus digest mismatch: {source}")

            encoded = work / f"{family}.jls2"
            restored = work / f"{family}.restored"
            compression_memory = measure_worker(
                "compress",
                source,
                encoded,
                segment_size=requirements["segment_target_bytes"],
                max_output_size=item["size_bytes"],
            )
            if encoded.stat().st_size != accepted[family]["encoded_bytes"]:
                raise RuntimeError(
                    f"accepted encoded size mismatch for {family}"
                )
            if sha256_file(encoded) != accepted[family]["encoded_sha256"]:
                raise RuntimeError(
                    f"accepted encoded digest mismatch for {family}"
                )

            decompression_memory = measure_worker(
                "decompress",
                encoded,
                restored,
                segment_size=requirements["segment_target_bytes"],
                max_output_size=item["size_bytes"],
            )
            if restored.stat().st_size != item["size_bytes"]:
                raise RuntimeError(f"restored size mismatch for {family}")
            if sha256_file(restored) != item["sha256"]:
                raise RuntimeError(f"restored digest mismatch for {family}")

            ceiling = requirements["maximum_resident_set_bytes"]
            row = {
                "family": family,
                "original_bytes": item["size_bytes"],
                "encoded_bytes": encoded.stat().st_size,
                "compression": {
                    **compression_memory,
                    "gate_passed": (
                        compression_memory["maximum_resident_set_bytes"]
                        <= ceiling
                    ),
                },
                "decompression": {
                    **decompression_memory,
                    "gate_passed": (
                        decompression_memory["maximum_resident_set_bytes"]
                        <= ceiling
                    ),
                },
            }
            rows.append(row)
            encoded.unlink()
            restored.unlink()

    payload = {
        "schema_version": 1,
        "claim_ceiling": (
            "local complete-product peak-memory development evidence only; "
            "validation remains sealed"
        ),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "accepted_path": str(accepted_path),
        "accepted_sha256": sha256_file(accepted_path),
        "gates_path": str(gates_path),
        "gates_sha256": sha256_file(gates_path),
        "git": repository,
        "measurement_tool": "/usr/bin/time -l",
        "pipeline_limits": {
            "compression_segment_workers": (
                MAX_COMPRESSION_SEGMENT_WORKERS
            ),
            "compression_segment_workers_gate_passed": (
                compression_workers_passed
            ),
            "decompression_segment_workers": (
                MAX_DECOMPRESSION_SEGMENT_WORKERS
            ),
            "decompression_segment_workers_gate_passed": (
                decompression_workers_passed
            ),
        },
        "rows": rows,
        "all_families_passed": (
            compression_workers_passed
            and decompression_workers_passed
            and all(
                row[operation]["gate_passed"]
                for row in rows
                for operation in ("compression", "decompression")
            )
        ),
    }
    write_output(output_path, payload)
    return 0 if payload["all_families_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
