"""Clean child peak-RSS measurement: wait4 from a deliberately tiny parent.

The 2026-07-23 instrument diagnostic
(docs/benchmarks/2026-07-23-jls2-rss-instrument-diagnostic.md, PR #75) proved
that wait4's ru_maxrss for a child spawned from a large parent reports the
parent's resident footprint, not the child's: the pre-execve resident
watermark of the forked (or vfork-shared) address space is folded into the
child's accounting. Any peak-RSS gate scored through a subprocess reaped
directly from a large Python process inherits that bias.

This tool removes the bias structurally instead of correcting for it: the
large caller spawns a minimal re-executed interpreter (the shim), and the
shim - whose own resident footprint is a few MiB - spawns and reaps the
target with os.wait4. The reading is the high-water mark of
max(shim-at-fork, target), so it is exact for any target whose true peak
exceeds the shim's few-MiB floor, and the shim's own measured peak is
recorded in every report as the explicit bias bound. The bias direction is
upward only: the reading can never undercount the target.

Usage:
  python scripts/measure-clean-rss.py --json-out REPORT.json -- COMMAND [ARG...]

The target inherits stdin/stdout/stderr, so callers redirect exactly as they
would for the target itself. The tool exits with the target's exit code.

Not itself a gate: adopting this instrument for any frozen benchmark is a
protocol decision recorded in that benchmark's own documents.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def rss_raw_to_bytes(raw: int) -> int:
    if sys.platform == "darwin":
        return raw
    return raw * 1024


def run_shim(report_path: str, command: list[str]) -> int:
    import resource

    started = time.perf_counter_ns()
    process = subprocess.Popen(command)
    _, wait_status, usage = os.wait4(process.pid, 0)
    wall_ns = time.perf_counter_ns() - started
    exit_code = os.waitstatus_to_exitcode(wait_status)
    shim_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {
        "schema": "clean-rss-measurement-v1",
        "command": command,
        "exit_code": exit_code,
        "platform": sys.platform,
        "maxrss_raw": usage.ru_maxrss,
        "maxrss_bytes": rss_raw_to_bytes(usage.ru_maxrss),
        "shim_maxrss_bytes": rss_raw_to_bytes(shim_raw),
        "wall_ns": wall_ns,
        "user_seconds": usage.ru_utime,
        "system_seconds": usage.ru_stime,
    }
    Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return exit_code


def measure(command: list[str], json_out: Path) -> int:
    if not hasattr(os, "wait4"):
        raise SystemExit("clean RSS measurement requires os.wait4")
    if not command:
        raise SystemExit("no command given")
    shim_command = [
        sys.executable,
        "-S",
        "-E",
        os.path.abspath(__file__),
        "--shim-report",
        str(json_out),
        "--",
    ] + command
    completed = subprocess.run(shim_command, check=False)
    if not json_out.is_file():
        raise SystemExit(
            f"shim exited {completed.returncode} without writing {json_out}"
        )
    return completed.returncode


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--shim-report":
        try:
            separator = sys.argv.index("--")
        except ValueError:
            raise SystemExit("shim invocation is missing the -- separator")
        return run_shim(sys.argv[2], sys.argv[separator + 1 :])

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    exit_code = measure(command, arguments.json_out)
    report = json.loads(arguments.json_out.read_text(encoding="utf-8"))
    print(
        f"clean peak RSS: {report['maxrss_bytes']:,} bytes "
        f"({report['maxrss_bytes'] / 1048576:.1f} MiB); "
        f"shim floor {report['shim_maxrss_bytes'] / 1048576:.1f} MiB; "
        f"exit {report['exit_code']}",
        file=sys.stderr,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
