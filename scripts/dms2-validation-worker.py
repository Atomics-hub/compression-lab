#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.dense_matrix_transform import (  # noqa: E402
    selector_stream_compress,
    selector_stream_decompress,
)


resource: Any
try:
    import resource as _resource
except ImportError:  # pragma: no cover - Windows does not expose resource
    resource = None
else:
    resource = _resource


def _rss_bytes(usage: Any) -> int:
    if resource is None:
        return 0
    value = int(usage.ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _peak_rss_bytes() -> int:
    if resource is None:
        return 0
    return _rss_bytes(resource.getrusage(resource.RUSAGE_SELF))


def _cpu_time_ns() -> int:
    if resource is None:
        return time.process_time_ns()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return int((usage.ru_utime + usage.ru_stime) * 1_000_000_000)


def run(
    operation: str,
    source: Path,
    destination: Path,
    *,
    segment_size: int,
    level: int,
    max_output_size: int,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    wall_start = time.perf_counter_ns()
    cpu_start = _cpu_time_ns()
    if operation == "compress":
        with source.open("rb") as input_file, destination.open("wb") as output_file:
            detail = selector_stream_compress(
                input_file,
                output_file,
                segment_size=segment_size,
                level=level,
            )
    elif operation == "decompress":
        with source.open("rb") as input_file, destination.open("wb") as output_file:
            detail = selector_stream_decompress(
                input_file,
                output_file,
                max_output_size=max_output_size,
            )
    else:
        raise ValueError(f"unsupported operation: {operation}")
    return {
        "codec_id": "dms2-stream",
        "operation": operation,
        "wall_ns": time.perf_counter_ns() - wall_start,
        "cpu_ns": _cpu_time_ns() - cpu_start,
        "peak_rss_bytes": _peak_rss_bytes(),
        "input_bytes": source.stat().st_size,
        "output_bytes": destination.stat().st_size,
        "pid": os.getpid(),
        **detail,
    }


def _serve() -> int:
    sys.stdout.write(json.dumps({"ready": True}, sort_keys=True) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("request_id", ""))
            if request.get("command") == "shutdown":
                sys.stdout.write(
                    json.dumps(
                        {"request_id": request_id, "shutdown": True},
                        sort_keys=True,
                    )
                    + "\n"
                )
                sys.stdout.flush()
                return 0
            telemetry = run(
                str(request["operation"]),
                Path(request["source"]),
                Path(request["destination"]),
                segment_size=int(request["segment_size"]),
                level=int(request["level"]),
                max_output_size=int(request["max_output_size"]),
            )
            response = {"request_id": request_id, "telemetry": telemetry}
        except Exception as error:
            response = {
                "request_id": request_id,
                "error": f"{type(error).__name__}: {error}",
            }
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--operation", choices=("compress", "decompress"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--segment-size", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--level", type=int, default=19)
    parser.add_argument("--max-output-size", type=int, default=2 * 1024 * 1024 * 1024)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.server:
        return _serve()
    if not all((args.operation, args.source, args.destination, args.telemetry)):
        raise SystemExit(
            "operation, source, destination, and telemetry are required"
        )
    try:
        telemetry = run(
            args.operation,
            args.source,
            args.destination,
            segment_size=args.segment_size,
            level=args.level,
            max_output_size=args.max_output_size,
        )
    except Exception as error:
        telemetry = {"error": f"{type(error).__name__}: {error}"}
        args.telemetry.write_text(
            json.dumps(telemetry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 1
    args.telemetry.write_text(
        json.dumps(telemetry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
