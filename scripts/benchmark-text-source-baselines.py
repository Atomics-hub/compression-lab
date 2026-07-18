#!/usr/bin/env python3
"""Run the resumable practical baseline census on text/source development bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-baseline-toolchain-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_TOOLS = REPOSITORY / ".baseline-tools" / "text-source-v1"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-development-baseline-census-v1"
CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def repository_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY).as_posix()
    except ValueError:
        return path.name


def sanitize_process_record(record: dict[str, Any], work: Path) -> dict[str, Any]:
    sanitized = dict(record)
    sanitized["command"] = [
        str(value).replace(str(REPOSITORY), "$REPOSITORY").replace(str(work), "$WORK")
        for value in record["command"]
    ]
    if sanitized["command"] and sanitized["command"][0].startswith("/"):
        sanitized["command"][0] = Path(sanitized["command"][0]).name
    return sanitized


def repository_state() -> dict[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"commit": commit, "tracked_status": tracked}


def verify_manifest(corpus: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = [
        "cpython-3.14.6-source",
        "typescript-6.0.3-source",
        "rust-1.97.1-source",
        "llvm-22.1.8-source",
        "enwikibooks-20260701",
        "enwikinews-20260701",
        "enwikiversity-20260701",
    ]
    if [row.get("source_id") for row in manifest.get("items", [])] != expected:
        raise ValueError("development manifest roster or order mismatch")
    if manifest.get("public_validation_accessed"):
        raise ValueError("development manifest reports validation access")
    items: list[dict[str, Any]] = []
    for row in manifest["items"]:
        path = corpus / row["bundle_path"]
        if path.stat().st_size != row["bundle_size_bytes"]:
            raise ValueError(f"development item size mismatch: {row['source_id']}")
        if file_digest(path) != row["bundle_sha256"]:
            raise ValueError(f"development item digest mismatch: {row['source_id']}")
        items.append(
            {
                "id": row["source_id"],
                "track": (
                    "source_code_bundles"
                    if row["format"] == "source-bundle-v1"
                    else "english_wikimedia_wikitext"
                ),
                "format": row["format"],
                "path": str(path.resolve()),
                "source_bytes": row["bundle_size_bytes"],
                "source_sha256": row["bundle_sha256"],
            }
        )
    return manifest_path, manifest, items


def tool_version(path: str, arguments: list[str]) -> str:
    completed = subprocess.run(
        [path, *arguments], capture_output=True, text=True, check=False
    )
    return (completed.stdout + completed.stderr).strip()


def resolve_tools(
    config: dict[str, Any], config_path: Path, tools_root: Path
) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for entry in config["host_tools"]:
        executable = shutil.which(entry["executable"])
        if executable is None:
            raise ValueError(f"required host tool is unavailable: {entry['name']}")
        version = tool_version(executable, entry["version_arguments"])
        if entry["expected_version_substring"] not in version:
            raise ValueError(
                f"{entry['name']} version differs from frozen expectation: {version}"
            )
        path = Path(executable).resolve()
        resolved[entry["name"]] = {
            "path": str(path),
            "version": version,
            "binary_sha256": file_digest(path),
            "binary_size_bytes": path.stat().st_size,
        }

    receipt_path = tools_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["config_sha256"] != file_digest(config_path):
        raise ValueError("source-built baseline receipt/config mismatch")
    for build in receipt["builds"]:
        path = Path(build["binary_path"])
        if not path.is_file() or file_digest(path) != build["binary_sha256"]:
            raise ValueError(f"source-built binary identity mismatch: {build['name']}")
        probe_arguments = ["--help"] if build["name"] == "kanzi" else []
        version = tool_version(str(path), probe_arguments)
        if build["version"] not in version:
            raise ValueError(f"source-built version mismatch: {build['name']}")
        resolved[build["name"]] = {
            "path": str(path.resolve()),
            "version": version,
            "binary_sha256": build["binary_sha256"],
            "binary_size_bytes": build["binary_size_bytes"],
            "commit": build["commit"],
        }
    return resolved


def codec_commands(
    codec_id: str,
    tools: dict[str, dict[str, Any]],
    source: Path,
    artifact: Path,
    restored: Path,
) -> tuple[list[str], Path | None, list[str], Path | None]:
    def tool(name: str) -> str:
        return str(tools[name]["path"])

    if codec_id == "store":
        return (
            ["/bin/cp", str(source), str(artifact)],
            None,
            [
                "/bin/cp",
                str(artifact),
                str(restored),
            ],
            None,
        )
    if codec_id == "lz4-1":
        return (
            [tool("lz4"), "-q", "-1", "-f", str(source), str(artifact)],
            None,
            [
                tool("lz4"),
                "-q",
                "-d",
                "-f",
                str(artifact),
                str(restored),
            ],
            None,
        )
    if codec_id == "gzip-9":
        return (
            [tool("gzip"), "-n", "-9", "-c", str(source)],
            artifact,
            [
                tool("gzip"),
                "-d",
                "-c",
                str(artifact),
            ],
            restored,
        )
    if codec_id == "bzip2-9":
        return (
            [tool("bzip2"), "-9", "-c", str(source)],
            artifact,
            [
                tool("bzip2"),
                "-d",
                "-c",
                str(artifact),
            ],
            restored,
        )
    if codec_id == "bzip3-max":
        return (
            [
                tool("bzip3"),
                "--encode",
                "--block=511",
                "--jobs=1",
                "--stdout",
                str(source),
            ],
            artifact,
            [tool("bzip3"), "--decode", "--stdout", str(artifact)],
            restored,
        )
    if codec_id.startswith("zstd-"):
        level = {
            "zstd-3": ["-3"],
            "zstd-9": ["-9"],
            "zstd-19": ["-19"],
            "zstd-22-ultra": ["--ultra", "-22"],
        }[codec_id]
        return (
            [
                tool("zstd"),
                "-q",
                "-T1",
                *level,
                "-f",
                str(source),
                "-o",
                str(artifact),
            ],
            None,
            [
                tool("zstd"),
                "-q",
                "-T1",
                "-d",
                "-f",
                str(artifact),
                "-o",
                str(restored),
            ],
            None,
        )
    if codec_id == "brotli-11":
        return (
            [
                tool("brotli"),
                "-q",
                "11",
                "-f",
                "-o",
                str(artifact),
                str(source),
            ],
            None,
            [
                tool("brotli"),
                "-d",
                "-f",
                "-o",
                str(restored),
                str(artifact),
            ],
            None,
        )
    if codec_id == "xz-lzma2-9e":
        return (
            [tool("xz"), "-T1", "-9e", "-c", str(source)],
            artifact,
            [
                tool("xz"),
                "-T1",
                "-d",
                "-c",
                str(artifact),
            ],
            restored,
        )
    if codec_id.startswith("7zip-"):
        method = "lzma2" if codec_id == "7zip-lzma2-9" else "PPMd"
        return (
            [
                tool("7zz"),
                "a",
                "-bd",
                "-bso0",
                "-bsp0",
                "-t7z",
                f"-m0={method}",
                "-mx=9",
                "-mmt=1",
                str(artifact),
                str(source),
            ],
            None,
            [
                tool("7zz"),
                "e",
                "-bd",
                "-bso0",
                "-bsp0",
                "-so",
                str(artifact),
            ],
            restored,
        )
    if codec_id == "kanzi-max":
        return (
            [
                tool("kanzi"),
                "--compress",
                "--level=9",
                "--block=1g",
                "--jobs=1",
                "--verbose=0",
                "--force",
                f"--input={source}",
                f"--output={artifact}",
            ],
            None,
            [
                tool("kanzi"),
                "--decompress",
                "--jobs=1",
                "--verbose=0",
                "--force",
                f"--input={artifact}",
                f"--output={restored}",
            ],
            None,
        )
    if codec_id == "libbsc-max":
        return (
            [tool("libbsc"), "e", str(source), str(artifact), "-b512", "-e2"],
            None,
            [
                tool("libbsc"),
                "d",
                str(artifact),
                str(restored),
            ],
            None,
        )
    raise ValueError(f"unsupported practical codec: {codec_id}")


def run_process(
    command: list[str],
    *,
    stdout_path: Path | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not hasattr(os, "wait4"):
        raise RuntimeError("baseline runner requires wait4 peak-RSS accounting")
    environment = dict(os.environ)
    environment.update(
        {
            "LC_ALL": "C",
            "TZ": "UTC",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
    )
    started = time.perf_counter_ns()
    stdout_file = (
        stdout_path.open("wb") if stdout_path is not None else tempfile.TemporaryFile()
    )
    stderr_file = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
        )
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        while True:
            pid, wait_status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid == process.pid:
                break
            if time.monotonic() >= deadline:
                os.kill(process.pid, signal.SIGKILL)
                _, wait_status, usage = os.wait4(process.pid, 0)
                timed_out = True
                break
            time.sleep(0.05)
        process.returncode = os.waitstatus_to_exitcode(wait_status)
        wall_ns = time.perf_counter_ns() - started
        peak_rss_bytes = int(usage.ru_maxrss)
        if sys.platform != "darwin":
            peak_rss_bytes *= 1024
        stderr_file.seek(0)
        stderr = stderr_file.read(16384).decode("utf-8", errors="replace")
        if stdout_path is None:
            stdout_file.seek(0)
            stdout = stdout_file.read(16384).decode("utf-8", errors="replace")
        else:
            stdout = "<artifact>"
        return {
            "command": command,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "wall_ns": wall_ns,
            "cpu_ns": int((usage.ru_utime + usage.ru_stime) * 1_000_000_000),
            "peak_rss_bytes": peak_rss_bytes,
            "stdout": stdout,
            "stderr": stderr,
        }
    finally:
        stdout_file.close()
        stderr_file.close()


def trial_path(output: Path, codec_id: str, item_id: str, repetition: int) -> Path:
    return output / "trials" / codec_id / f"{item_id}.r{repetition}.json"


def validate_existing_trial(
    existing: dict[str, Any],
    *,
    bindings: dict[str, str],
    codec_id: str,
    item: dict[str, Any],
    repetition: int,
    tools: dict[str, dict[str, Any]],
    destination: Path,
) -> None:
    expected = {
        "schema_version": 1,
        "bindings": bindings,
        "codec_id": codec_id,
        "item_id": item["id"],
        "track": item["track"],
        "repetition": repetition,
        "warmup": repetition == 0,
        "source_bytes": item["source_bytes"],
        "source_sha256": item["source_sha256"],
    }
    receipt_keys = {
        "schema_version",
        "bindings",
        "codec_id",
        "item_id",
        "track",
        "repetition",
        "warmup",
        "source_bytes",
        "source_sha256",
        "artifact_bytes",
        "artifact_sha256",
        "compression",
        "decompression",
        "exact_roundtrip",
        "passed",
        "error",
    }
    if (
        set(existing) != receipt_keys
        or type(existing.get("schema_version")) is not int
        or type(existing.get("repetition")) is not int
        or not isinstance(existing.get("warmup"), bool)
        or any(existing.get(key) != value for key, value in expected.items())
    ):
        raise ValueError(f"resumed trial identity mismatch: {destination}")

    work = Path("$WORK")
    compress, _compress_stdout, decompress, _decompress_stdout = codec_commands(
        codec_id,
        tools,
        Path(item["path"]),
        work / "artifact.bin",
        work / "restored.bin",
    )
    expected_commands = {
        "compression": sanitize_process_record({"command": compress}, work)["command"],
        "decompression": sanitize_process_record({"command": decompress}, work)[
            "command"
        ],
    }

    def validate_process(phase: str, process: object) -> None:
        if (
            not isinstance(process, dict)
            or set(process)
            != {
                "command",
                "returncode",
                "timed_out",
                "wall_ns",
                "cpu_ns",
                "peak_rss_bytes",
                "stdout",
                "stderr",
            }
            or process.get("command") != expected_commands[phase]
            or type(process.get("returncode")) is not int
            or not isinstance(process.get("timed_out"), bool)
            or type(process.get("wall_ns")) is not int
            or process["wall_ns"] <= 0
            or type(process.get("cpu_ns")) is not int
            or process["cpu_ns"] < 0
            or type(process.get("peak_rss_bytes")) is not int
            or process["peak_rss_bytes"] < 0
            or not isinstance(process.get("stdout"), str)
            or not isinstance(process.get("stderr"), str)
        ):
            raise ValueError(f"resumed trial {phase} record is invalid: {destination}")

    validate_process("compression", existing.get("compression"))
    decompression = existing.get("decompression")
    if decompression is not None:
        validate_process("decompression", decompression)
    artifact_bytes = existing.get("artifact_bytes")
    artifact_sha256 = existing.get("artifact_sha256")
    artifact_valid = (
        type(artifact_bytes) is int
        and artifact_bytes > 0
        and is_sha256(artifact_sha256)
    )
    if existing.get("passed") is True:
        if (
            existing.get("exact_roundtrip") is not True
            or existing.get("error") is not None
            or not artifact_valid
            or decompression is None
            or existing["compression"]["returncode"] != 0
            or existing["compression"]["timed_out"] is not False
            or decompression["returncode"] != 0
            or decompression["timed_out"] is not False
        ):
            raise ValueError(f"resumed trial successful outcome is invalid: {destination}")
    elif existing.get("passed") is False:
        if (
            existing.get("exact_roundtrip") is not False
            or not isinstance(existing.get("error"), str)
            or not existing["error"]
            or ((artifact_bytes is None) != (artifact_sha256 is None))
            or (artifact_bytes is not None and not artifact_valid)
        ):
            raise ValueError(f"resumed trial failed outcome is invalid: {destination}")
    else:
        raise ValueError(f"resumed trial pass state is invalid: {destination}")


def preflight_codecs(
    codec_ids: list[str],
    tools: dict[str, dict[str, Any]],
    timeout_seconds: float = 300.0,
) -> list[dict[str, Any]]:
    fixture = (
        b"def compress(value):\n    return value if value else b''\n" * 4096
        + bytes(range(256)) * 256
    )
    rows = []
    with tempfile.TemporaryDirectory(prefix="text-source-baseline-preflight-") as raw:
        root = Path(raw)
        source = root / "fixture.bin"
        source.write_bytes(fixture)
        expected = hashlib.sha256(fixture).hexdigest()
        for index, codec_id in enumerate(codec_ids):
            work = root / str(index)
            work.mkdir()
            artifact = work / "artifact.bin"
            restored = work / "restored.bin"
            compress, compress_stdout, decompress, decompress_stdout = codec_commands(
                codec_id, tools, source, artifact, restored
            )
            compression = run_process(
                compress,
                stdout_path=compress_stdout,
                timeout_seconds=timeout_seconds,
            )
            if compression["timed_out"] or compression["returncode"] != 0:
                raise ValueError(
                    f"{codec_id} compression preflight failed: {compression}"
                )
            if not artifact.is_file():
                raise ValueError(
                    f"{codec_id} compression preflight produced no artifact"
                )
            decompression = run_process(
                decompress,
                stdout_path=decompress_stdout,
                timeout_seconds=timeout_seconds,
            )
            if decompression["timed_out"] or decompression["returncode"] != 0:
                raise ValueError(
                    f"{codec_id} decompression preflight failed: {decompression}"
                )
            exact = restored.is_file() and file_digest(restored) == expected
            if not exact:
                raise ValueError(f"{codec_id} preflight round trip is inexact")
            rows.append(
                {
                    "codec_id": codec_id,
                    "source_bytes": len(fixture),
                    "artifact_bytes": artifact.stat().st_size,
                    "artifact_sha256": file_digest(artifact),
                    "exact_roundtrip": True,
                }
            )
    return rows


def run_trial(
    *,
    output: Path,
    codec_id: str,
    item: dict[str, Any],
    repetition: int,
    tools: dict[str, dict[str, Any]],
    timeout_seconds: float,
    bindings: dict[str, str],
) -> dict[str, Any]:
    destination = trial_path(output, codec_id, item["id"], repetition)
    if destination.exists():
        raw = destination.read_bytes()
        existing = json.loads(raw)
        if (
            not isinstance(existing, dict)
            or raw
            != (json.dumps(existing, indent=2, sort_keys=True) + "\n").encode("utf-8")
        ):
            raise ValueError(f"resumed trial is not canonical JSON: {destination}")
        validate_existing_trial(
            existing,
            bindings=bindings,
            codec_id=codec_id,
            item=item,
            repetition=repetition,
            tools=tools,
            destination=destination,
        )
        return existing
    with tempfile.TemporaryDirectory(prefix="text-source-baseline-") as raw:
        work = Path(raw)
        artifact = work / "artifact.bin"
        restored = work / "restored.bin"
        source = Path(item["path"])
        compress, compress_stdout, decompress, decompress_stdout = codec_commands(
            codec_id, tools, source, artifact, restored
        )
        compression = run_process(
            compress, stdout_path=compress_stdout, timeout_seconds=timeout_seconds
        )
        error = ""
        decompression: dict[str, Any] | None = None
        if compression["timed_out"]:
            error = "compression timed out"
        elif compression["returncode"] != 0:
            error = f"compression exited {compression['returncode']}"
        elif not artifact.is_file():
            error = "compression produced no artifact"
        else:
            artifact_size = artifact.stat().st_size
            artifact_sha256 = file_digest(artifact)
            decompression = run_process(
                decompress,
                stdout_path=decompress_stdout,
                timeout_seconds=timeout_seconds,
            )
            if decompression["timed_out"]:
                error = "decompression timed out"
            elif decompression["returncode"] != 0:
                error = f"decompression exited {decompression['returncode']}"
            elif not restored.is_file():
                error = "decompression produced no output"
            elif restored.stat().st_size != item["source_bytes"]:
                error = "restored size mismatch"
            elif file_digest(restored) != item["source_sha256"]:
                error = "restored digest mismatch"
        row = {
            "schema_version": 1,
            "bindings": bindings,
            "codec_id": codec_id,
            "item_id": item["id"],
            "track": item["track"],
            "repetition": repetition,
            "warmup": repetition == 0,
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
            "artifact_bytes": artifact_size if artifact.is_file() else None,
            "artifact_sha256": artifact_sha256 if artifact.is_file() else None,
            "compression": sanitize_process_record(compression, work),
            "decompression": (
                sanitize_process_record(decompression, work)
                if decompression is not None
                else None
            ),
            "exact_roundtrip": not error,
            "passed": not error,
            "error": error or None,
        }
        write_json_atomic(destination, row)
        return row


def summarize(
    trials: list[dict[str, Any]],
    codec_ids: list[str],
    items: list[dict[str, Any]],
    repetitions: int,
) -> dict[str, Any]:
    measured = [row for row in trials if not row["warmup"]]
    rows = []
    for codec_id in codec_ids:
        for item in items:
            group = [
                row
                for row in measured
                if row["codec_id"] == codec_id and row["item_id"] == item["id"]
            ]
            passed = len(group) == repetitions and all(row["passed"] for row in group)
            artifact_hashes = {
                row["artifact_sha256"] for row in group if row["artifact_sha256"]
            }
            artifact_sizes = {
                row["artifact_bytes"]
                for row in group
                if row["artifact_bytes"] is not None
            }
            deterministic = (
                passed and len(artifact_hashes) == 1 and len(artifact_sizes) == 1
            )
            rows.append(
                {
                    "codec_id": codec_id,
                    "item_id": item["id"],
                    "track": item["track"],
                    "source_bytes": item["source_bytes"],
                    "artifact_bytes": next(iter(artifact_sizes))
                    if len(artifact_sizes) == 1
                    else None,
                    "artifact_sha256": next(iter(artifact_hashes))
                    if len(artifact_hashes) == 1
                    else None,
                    "median_compression_ns": (
                        int(
                            statistics.median(
                                row["compression"]["wall_ns"] for row in group
                            )
                        )
                        if passed
                        else None
                    ),
                    "median_decompression_ns": (
                        int(
                            statistics.median(
                                row["decompression"]["wall_ns"] for row in group
                            )
                        )
                        if passed
                        else None
                    ),
                    "compression_peak_rss_bytes": max(
                        (row["compression"]["peak_rss_bytes"] for row in group),
                        default=0,
                    ),
                    "decompression_peak_rss_bytes": max(
                        (
                            row["decompression"]["peak_rss_bytes"]
                            for row in group
                            if row["decompression"] is not None
                        ),
                        default=0,
                    ),
                    "exact_roundtrip": passed,
                    "deterministic_artifact": deterministic,
                    "passed": passed and deterministic,
                    "errors": sorted({row["error"] for row in group if row["error"]}),
                }
            )
    tracks: dict[str, Any] = {}
    for track in sorted({item["track"] for item in items}):
        track_items = [item for item in items if item["track"] == track]
        source_bytes = sum(item["source_bytes"] for item in track_items)
        codec_rows = []
        for codec_id in codec_ids:
            selected = [
                row
                for row in rows
                if row["track"] == track and row["codec_id"] == codec_id
            ]
            complete = len(selected) == len(track_items) and all(
                row["passed"] for row in selected
            )
            artifact_bytes = (
                sum(row["artifact_bytes"] for row in selected) if complete else None
            )
            compression_ns = (
                sum(row["median_compression_ns"] for row in selected)
                if complete
                else None
            )
            decompression_ns = (
                sum(row["median_decompression_ns"] for row in selected)
                if complete
                else None
            )
            codec_rows.append(
                {
                    "codec_id": codec_id,
                    "source_bytes": source_bytes,
                    "artifact_bytes": artifact_bytes,
                    "ratio_percent": (
                        artifact_bytes / source_bytes * 100.0 if complete else None
                    ),
                    "compression_mbps": (
                        source_bytes / compression_ns * 1000.0 if complete else None
                    ),
                    "decompression_mbps": (
                        source_bytes / decompression_ns * 1000.0 if complete else None
                    ),
                    "compression_peak_rss_bytes": max(
                        (row["compression_peak_rss_bytes"] for row in selected),
                        default=0,
                    ),
                    "decompression_peak_rss_bytes": max(
                        (row["decompression_peak_rss_bytes"] for row in selected),
                        default=0,
                    ),
                    "complete": complete,
                }
            )
        completed = [row for row in codec_rows if row["complete"]]
        leader = (
            min(completed, key=lambda row: row["artifact_bytes"]) if completed else None
        )
        tracks[track] = {
            "source_bytes": source_bytes,
            "leader": leader,
            "codecs": codec_rows,
        }
    return {"item_codec_rows": rows, "tracks": tracks}


def benchmark(
    *,
    config_path: Path,
    corpus: Path,
    tools_root: Path,
    output: Path,
) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    policy = config["measurement_policy"]
    repository = repository_state()
    if repository["tracked_status"]:
        raise ValueError("baseline census requires a clean tracked commit")
    manifest_path, _manifest, items = verify_manifest(corpus)
    tools = resolve_tools(config, config_path, tools_root)
    preflight = preflight_codecs(config["practical_codec_ids"], tools)
    config_sha256 = file_digest(config_path)
    manifest_sha256 = file_digest(manifest_path)
    bindings = {
        "repository_commit": repository["commit"],
        "config_sha256": config_sha256,
        "manifest_sha256": manifest_sha256,
    }
    output.mkdir(parents=True, exist_ok=True)
    attempt_path = output / "attempt.json"
    if attempt_path.exists():
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        if attempt["bindings"] != bindings:
            raise ValueError("existing census attempt binding mismatch")
    else:
        attempt = {
            "schema_version": 1,
            "name": "text-source-development-baseline-census-v1",
            "completed": False,
            "bindings": bindings,
            "claim_ceiling": policy["claim_ceiling"],
            "repository": repository,
            "config_path": repository_relative(config_path),
            "manifest_path": repository_relative(manifest_path),
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "logical_cpus": os.cpu_count(),
            },
            "tools": {
                name: {key: value for key, value in row.items() if key != "path"}
                for name, row in tools.items()
            },
            "preflight": preflight,
            "codec_ids": config["practical_codec_ids"],
            "items": [
                {key: value for key, value in item.items() if key != "path"}
                for item in items
            ],
        }
        write_json_atomic(attempt_path, attempt)

    repetitions = int(policy["repetitions"])
    codec_ids = config["practical_codec_ids"]
    pairs = [(codec_id, item) for codec_id in codec_ids for item in items]
    trials = []
    total = len(pairs) * (repetitions + int(policy["warmups"]))
    progress = 0
    for repetition in range(0, repetitions + 1):
        ordered = list(pairs)
        random.Random(int(policy["order_seed"]) + repetition).shuffle(ordered)
        for codec_id, item in ordered:
            progress += 1
            print(
                f"[{progress}/{total}] r{repetition} {item['id']} x {codec_id}",
                flush=True,
            )
            trials.append(
                run_trial(
                    output=output,
                    codec_id=codec_id,
                    item=item,
                    repetition=repetition,
                    tools=tools,
                    timeout_seconds=float(policy["timeout_seconds_per_operation"]),
                    bindings=bindings,
                )
            )
    summary = summarize(trials, codec_ids, items, repetitions)
    result = attempt | {
        "completed": True,
        "trial_count": len(trials),
        "all_required_completed": all(
            row["complete"]
            for track in summary["tracks"].values()
            for row in track["codecs"]
        ),
        "summary": summary,
    }
    result_path = output / "results.json"
    write_json_atomic(result_path, result)
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = benchmark(
            config_path=args.config,
            corpus=args.corpus,
            tools_root=args.tools,
            output=args.output,
        )
    except (
        KeyError,
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"baseline census failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
