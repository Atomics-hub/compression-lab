#!/usr/bin/env python3
"""Run the frozen TS-H1/TS-H2 structural representation probe."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab import text_source_transform  # noqa: E402


DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_TOOLS = REPOSITORY / ".baseline-tools" / "text-source-v1"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-structural-transform-development-v1"
FRAME_HEADER = struct.Struct("<5sBBQQ32s32s")
FRAME_MAGIC = b"AXTP2"
VARIANT_KIND = {"ts-h1-demux": 1, "ts-h2-extension-lanes": 2}
BACKEND_KIND = {"kanzi-max": 1}
REPETITIONS = 2
ORDER_SEED = 20260718
TIMEOUT_SECONDS = 43_200.0
GIB = 1024**3


def load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASELINE_PUBLICATION = load_script(
    "text_source_baseline_publication_for_structural_runner",
    REPOSITORY / "scripts" / "publish-text-source-baseline-census.py",
)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
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


def repository_state() -> dict[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked:
        raise ValueError("structural transform probe requires a clean commit")
    return {"commit": commit, "tracked_status": tracked}


def load_inputs(
    baseline_path: Path, corpus: Path, tools_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    BASELINE_PUBLICATION.validate_trial_receipts(baseline_path, baseline)
    if (
        baseline.get("name") != "text-source-development-baseline-census-v1"
        or not baseline.get("completed")
        or not baseline.get("all_required_completed")
        or baseline.get("trial_count") != 630
    ):
        raise ValueError("complete 630-trial practical baseline is required")
    item_rows = baseline.get("summary", {}).get("item_codec_rows", [])
    if len(item_rows) != 105 or not all(
        row.get("passed") is True
        and row.get("exact_roundtrip") is True
        and row.get("deterministic_artifact") is True
        for row in item_rows
    ):
        raise ValueError("baseline item/codec exactness or determinism is incomplete")
    for track in baseline["summary"]["tracks"].values():
        if len(track.get("codecs", [])) != 15 or not all(
            row.get("complete") is True for row in track["codecs"]
        ):
            raise ValueError("baseline track completeness is invalid")
        leader = track.get("leader")
        if leader is None or leader.get("codec_id") != "kanzi-max":
            raise ValueError(
                "probe currently requires kanzi-max to be each practical leader"
            )

    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline_items = {item["id"]: item for item in baseline["items"]}
    raw_rows = {
        row["item_id"]: row
        for row in baseline["summary"]["item_codec_rows"]
        if row["codec_id"] == "kanzi-max"
    }
    items = []
    for row in manifest["items"]:
        item_id = row["source_id"]
        if item_id not in baseline_items or item_id not in raw_rows:
            raise ValueError(f"baseline lacks Kanzi row for {item_id}")
        path = corpus / row["bundle_path"]
        if (
            path.stat().st_size != row["bundle_size_bytes"]
            or file_digest(path) != row["bundle_sha256"]
        ):
            raise ValueError(f"development item identity mismatch: {item_id}")
        items.append(
            {
                "id": item_id,
                "path": str(path.resolve()),
                "format": row["format"],
                "track": baseline_items[item_id]["track"],
                "source_bytes": row["bundle_size_bytes"],
                "source_sha256": row["bundle_sha256"],
                "baseline_bytes": raw_rows[item_id]["artifact_bytes"],
                "baseline_compression_peak_rss_bytes": raw_rows[item_id][
                    "compression_peak_rss_bytes"
                ],
                "baseline_decompression_peak_rss_bytes": raw_rows[item_id][
                    "decompression_peak_rss_bytes"
                ],
            }
        )

    kanzi = tools_root / "bin" / "kanzi"
    expected_binary = baseline["tools"]["kanzi"]["binary_sha256"]
    if not kanzi.is_file() or file_digest(kanzi) != expected_binary:
        raise ValueError("Kanzi binary differs from completed baseline toolchain")
    return baseline, items, kanzi.resolve()


def run_process(command: list[str], *, timeout_seconds: float) -> dict[str, Any]:
    if not hasattr(os, "wait4"):
        raise RuntimeError("structural probe requires wait4 peak-RSS accounting")
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
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
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
        stdout.seek(0)
        stderr.seek(0)
        peak_rss = int(usage.ru_maxrss)
        if sys.platform != "darwin":
            peak_rss *= 1024
        return {
            "command": [
                str(value).replace(str(REPOSITORY), "$REPOSITORY") for value in command
            ],
            "returncode": process.returncode,
            "timed_out": timed_out,
            "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": int((usage.ru_utime + usage.ru_stime) * 1_000_000_000),
            "peak_rss_bytes": peak_rss,
            "stdout": stdout.read(16_384).decode("utf-8", errors="replace"),
            "stderr": stderr.read(16_384).decode("utf-8", errors="replace"),
        }


def sanitize_process_record(record: dict[str, Any], work: Path) -> dict[str, Any]:
    def sanitize(value: str) -> str:
        sanitized = value.replace(str(REPOSITORY), "$REPOSITORY").replace(
            str(work), "$WORK"
        )
        if "$REPOSITORY" in sanitized or "$WORK" in sanitized:
            sanitized = sanitized.replace("\\", "/")
        return sanitized

    sanitized = dict(record)
    sanitized["command"] = [sanitize(value) for value in record["command"]]
    sanitized["stdout"] = sanitize(record["stdout"])
    sanitized["stderr"] = sanitize(record["stderr"])
    if (
        record["command"]
        and Path(record["command"][0]).resolve() == Path(sys.executable).resolve()
    ):
        sanitized["command"][0] = "python"
    elif sanitized["command"] and sanitized["command"][0].startswith("/"):
        sanitized["command"][0] = Path(sanitized["command"][0]).name
    return sanitized


def worker_encode(source: Path, transformed: Path, variant: str) -> None:
    data = source.read_bytes()
    if variant == "ts-h1-demux":
        encoded = text_source_transform.encode(data, source_extension_lanes=False)
    elif variant == "ts-h2-extension-lanes":
        if not data.startswith(text_source_transform.SOURCE_MAGIC):
            raise ValueError("TS-H2 only accepts source-bundle-v1")
        encoded = text_source_transform.encode(data, source_extension_lanes=True)
    else:
        raise ValueError(f"unsupported transform variant: {variant}")
    transformed.write_bytes(encoded)


def worker_decode(transformed: Path, restored: Path, maximum_size: int) -> None:
    restored.write_bytes(
        text_source_transform.decode(
            transformed.read_bytes(), max_output_size=maximum_size
        )
    )


def build_frame(
    destination: Path,
    *,
    variant: str,
    backend: str,
    source_bytes: int,
    source_sha256: str,
    payload: Path,
) -> None:
    header = FRAME_HEADER.pack(
        FRAME_MAGIC,
        VARIANT_KIND[variant],
        BACKEND_KIND[backend],
        source_bytes,
        payload.stat().st_size,
        bytes.fromhex(source_sha256),
        bytes.fromhex(file_digest(payload)),
    )
    with destination.open("wb") as output, payload.open("rb") as source:
        output.write(header)
        while chunk := source.read(1024 * 1024):
            output.write(chunk)


def extract_frame(
    frame: Path,
    payload: Path,
    *,
    expected_variant: str,
    expected_backend: str,
) -> dict[str, Any]:
    payload.unlink(missing_ok=True)
    try:
        with frame.open("rb") as source:
            header = source.read(FRAME_HEADER.size)
            if len(header) != FRAME_HEADER.size:
                raise ValueError("candidate frame header is truncated")
            (
                magic,
                kind,
                backend_kind,
                source_bytes,
                payload_bytes,
                source_digest,
                payload_digest,
            ) = FRAME_HEADER.unpack(header)
            if (
                magic != FRAME_MAGIC
                or kind != VARIANT_KIND[expected_variant]
                or backend_kind != BACKEND_KIND[expected_backend]
            ):
                raise ValueError("candidate frame identity mismatch")
            if payload_bytes != frame.stat().st_size - FRAME_HEADER.size:
                raise ValueError("candidate frame payload length mismatch")
            observed_payload_digest = hashlib.sha256()
            with payload.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    observed_payload_digest.update(chunk)
            if observed_payload_digest.digest() != payload_digest:
                raise ValueError("candidate frame payload SHA-256 mismatch")
    except BaseException:
        payload.unlink(missing_ok=True)
        raise
    return {
        "source_bytes": source_bytes,
        "source_sha256": source_digest.hex(),
        "payload_bytes": payload_bytes,
        "payload_sha256": payload_digest.hex(),
        "backend": expected_backend,
    }


def worker_wrap(
    variant: str,
    backend: str,
    source_bytes: int,
    source_sha256: str,
    payload: Path,
    frame: Path,
) -> None:
    build_frame(
        frame,
        variant=variant,
        backend=backend,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        payload=payload,
    )


def worker_unwrap(
    variant: str,
    backend: str,
    source_bytes: int,
    source_sha256: str,
    frame: Path,
    payload: Path,
) -> None:
    info = extract_frame(
        frame,
        payload,
        expected_variant=variant,
        expected_backend=backend,
    )
    if info["source_bytes"] != source_bytes or info["source_sha256"] != source_sha256:
        payload.unlink(missing_ok=True)
        raise ValueError("candidate frame source identity mismatch")


def trial_path(output: Path, variant: str, item_id: str, repetition: int) -> Path:
    return output / "trials" / variant / f"{item_id}.r{repetition}.json"


def variants_for(item: dict[str, Any]) -> list[str]:
    variants = ["ts-h1-demux"]
    if item["format"] == "source-bundle-v1":
        variants.append("ts-h2-extension-lanes")
    return variants


def process_commands(
    item: dict[str, Any], variant: str, kanzi: Path, work: Path
) -> dict[str, list[list[str]]]:
    script = str(Path(__file__).resolve())
    python = str(Path(sys.executable).resolve())
    source = str(item["path"])
    backend = str(kanzi)
    source_bytes = str(item["source_bytes"])
    source_sha256 = item["source_sha256"]
    return {
        "compression": [
            [
                python,
                script,
                "--worker-encode",
                variant,
                source,
                str(work / "transformed.bin"),
            ],
            [
                backend,
                "--compress",
                "--level=9",
                "--block=1g",
                "--jobs=1",
                "--verbose=0",
                "--force",
                f"--input={work / 'transformed.bin'}",
                f"--output={work / 'payload.knz'}",
            ],
            [
                python,
                script,
                "--worker-wrap",
                variant,
                "kanzi-max",
                source_bytes,
                source_sha256,
                str(work / "payload.knz"),
                str(work / "candidate.axtp"),
            ],
        ],
        "decompression": [
            [
                python,
                script,
                "--worker-unwrap",
                variant,
                "kanzi-max",
                source_bytes,
                source_sha256,
                str(work / "candidate.axtp"),
                str(work / "extracted.knz"),
            ],
            [
                backend,
                "--decompress",
                "--jobs=1",
                "--verbose=0",
                "--force",
                f"--input={work / 'extracted.knz'}",
                f"--output={work / 'decoded-transform.bin'}",
            ],
            [
                python,
                script,
                "--worker-decode",
                source_bytes,
                str(work / "decoded-transform.bin"),
                str(work / "restored.bin"),
            ],
        ],
    }


def expected_process_commands(
    item: dict[str, Any], variant: str, kanzi: Path
) -> dict[str, list[list[str]]]:
    work = Path("$WORK")
    raw = process_commands(item, variant, kanzi, work)
    return {
        phase: [
            sanitize_process_record(
                {"command": command, "stdout": "", "stderr": ""}, work
            )["command"]
            for command in commands
        ]
        for phase, commands in raw.items()
    }


def validate_existing_trial(
    existing: dict[str, Any],
    *,
    bindings: dict[str, str],
    item: dict[str, Any],
    variant: str,
    repetition: int,
    expected_commands: dict[str, list[list[str]]],
    destination: Path,
) -> None:
    expected = {
        "schema_version": 1,
        "bindings": bindings,
        "variant": variant,
        "item_id": item["id"],
        "track": item["track"],
        "repetition": repetition,
        "warmup": repetition == 0,
        "source_bytes": item["source_bytes"],
        "source_sha256": item["source_sha256"],
        "baseline_codec": "kanzi-max",
        "baseline_bytes": item["baseline_bytes"],
    }
    if (
        type(existing.get("schema_version")) is not int
        or type(existing.get("repetition")) is not int
        or not isinstance(existing.get("warmup"), bool)
        or any(existing.get(key) != value for key, value in expected.items())
    ):
        raise ValueError(f"resumed transform trial identity mismatch: {destination}")
    processes = existing.get("processes")
    if not isinstance(processes, dict) or set(processes) != {
        "compression",
        "decompression",
    }:
        raise ValueError(
            f"resumed transform trial process record is invalid: {destination}"
        )
    if (
        existing.get("passed") is not True
        or existing.get("exact_roundtrip") is not True
        or existing.get("error") is not None
        or type(existing.get("transformed_bytes")) is not int
        or existing["transformed_bytes"] <= 0
        or type(existing.get("backend_payload_bytes")) is not int
        or existing["backend_payload_bytes"] <= 0
        or type(existing.get("candidate_bytes")) is not int
        or existing.get("candidate_bytes")
        != FRAME_HEADER.size + existing["backend_payload_bytes"]
        or not is_sha256(existing.get("candidate_sha256"))
    ):
        raise ValueError(f"resumed transform trial outcome is invalid: {destination}")
    for phase in ("compression", "decompression"):
        records = processes[phase]
        if not isinstance(records, list) or len(records) != 3:
            raise ValueError(
                f"resumed transform trial {phase} process count is invalid: "
                f"{destination}"
            )
        for index, process in enumerate(records):
            if (
                not isinstance(process, dict)
                or type(process.get("returncode")) is not int
                or process["returncode"] != 0
                or process.get("timed_out") is not False
                or type(process.get("wall_ns")) is not int
                or process["wall_ns"] <= 0
                or type(process.get("cpu_ns")) is not int
                or process["cpu_ns"] < 0
                or type(process.get("peak_rss_bytes")) is not int
                or process["peak_rss_bytes"] < 0
                or not isinstance(process.get("command"), list)
                or not process["command"]
                or not all(
                    isinstance(value, str) and value for value in process["command"]
                )
                or not isinstance(process.get("stdout"), str)
                or not isinstance(process.get("stderr"), str)
                or process.get("command") != expected_commands[phase][index]
            ):
                raise ValueError(
                    f"resumed transform trial {phase} process is invalid: {destination}"
                )
        wall_key = f"{phase}_wall_ns"
        rss_key = f"{phase}_peak_rss_bytes"
        if existing.get(wall_key) != sum(record["wall_ns"] for record in records):
            raise ValueError(
                f"resumed transform trial {phase} wall accounting is invalid: "
                f"{destination}"
            )
        if existing.get(rss_key) != max(record["peak_rss_bytes"] for record in records):
            raise ValueError(
                f"resumed transform trial {phase} RSS accounting is invalid: "
                f"{destination}"
            )


def run_trial(
    *,
    output: Path,
    item: dict[str, Any],
    variant: str,
    repetition: int,
    kanzi: Path,
    bindings: dict[str, str],
) -> dict[str, Any]:
    destination = trial_path(output, variant, item["id"], repetition)
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        validate_existing_trial(
            existing,
            bindings=bindings,
            item=item,
            variant=variant,
            repetition=repetition,
            expected_commands=expected_process_commands(item, variant, kanzi),
            destination=destination,
        )
        return existing
    with tempfile.TemporaryDirectory(prefix="text-source-structural-") as raw:
        work = Path(raw)

        def run(command: list[str]) -> dict[str, Any]:
            return sanitize_process_record(
                run_process(command, timeout_seconds=TIMEOUT_SECONDS), work
            )

        transformed = work / "transformed.bin"
        payload = work / "payload.knz"
        frame = work / "candidate.axtp"
        restored = work / "restored.bin"
        commands = process_commands(item, variant, kanzi, work)
        compression_processes: list[dict[str, Any]] = []
        decompression_processes: list[dict[str, Any]] = []
        encode_process = run(commands["compression"][0])
        compression_processes.append(encode_process)
        error = None
        if encode_process["timed_out"] or encode_process["returncode"] != 0:
            error = "transform encode failed"
        if error is None:
            compression = run(commands["compression"][1])
            compression_processes.append(compression)
            if compression["timed_out"] or compression["returncode"] != 0:
                error = "backend compression failed"
        if error is None:
            wrap_process = run(commands["compression"][2])
            compression_processes.append(wrap_process)
            if wrap_process["timed_out"] or wrap_process["returncode"] != 0:
                error = "candidate envelope construction failed"
        if error is None:
            unwrap_process = run(commands["decompression"][0])
            decompression_processes.append(unwrap_process)
            if unwrap_process["timed_out"] or unwrap_process["returncode"] != 0:
                error = "candidate envelope extraction failed"
        if error is None:
            decompression = run(commands["decompression"][1])
            decompression_processes.append(decompression)
            if decompression["timed_out"] or decompression["returncode"] != 0:
                error = "backend decompression failed"
        if error is None:
            decode_process = run(commands["decompression"][2])
            decompression_processes.append(decode_process)
            if decode_process["timed_out"] or decode_process["returncode"] != 0:
                error = "transform decode failed"
        exact = (
            error is None
            and restored.is_file()
            and restored.stat().st_size == item["source_bytes"]
            and file_digest(restored) == item["source_sha256"]
        )
        if not exact and error is None:
            error = "restored bytes differ from source"
        row = {
            "schema_version": 1,
            "bindings": bindings,
            "variant": variant,
            "item_id": item["id"],
            "track": item["track"],
            "repetition": repetition,
            "warmup": repetition == 0,
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
            "baseline_codec": "kanzi-max",
            "baseline_bytes": item["baseline_bytes"],
            "transformed_bytes": transformed.stat().st_size
            if transformed.is_file()
            else None,
            "backend_payload_bytes": payload.stat().st_size
            if payload.is_file()
            else None,
            "candidate_bytes": frame.stat().st_size if frame.is_file() else None,
            "candidate_sha256": file_digest(frame) if frame.is_file() else None,
            "compression_wall_ns": (
                sum(process["wall_ns"] for process in compression_processes)
                if len(compression_processes) == 3
                else None
            ),
            "decompression_wall_ns": (
                sum(process["wall_ns"] for process in decompression_processes)
                if len(decompression_processes) == 3
                else None
            ),
            "compression_peak_rss_bytes": max(
                (process["peak_rss_bytes"] for process in compression_processes),
                default=0,
            ),
            "decompression_peak_rss_bytes": max(
                (process["peak_rss_bytes"] for process in decompression_processes),
                default=0,
            ),
            "processes": {
                "compression": compression_processes,
                "decompression": decompression_processes,
            },
            "exact_roundtrip": exact,
            "passed": exact,
            "error": error,
        }
        write_json_atomic(destination, row)
        return row


def summarize(
    trials: list[dict[str, Any]], items: list[dict[str, Any]]
) -> dict[str, Any]:
    measured = [row for row in trials if not row["warmup"]]
    rows = []
    for item in items:
        for variant in variants_for(item):
            group = [
                row
                for row in measured
                if row["item_id"] == item["id"] and row["variant"] == variant
            ]
            complete = len(group) == REPETITIONS and all(row["passed"] for row in group)
            sizes = {
                row["candidate_bytes"]
                for row in group
                if row["candidate_bytes"] is not None
            }
            digests = {
                row["candidate_sha256"] for row in group if row["candidate_sha256"]
            }
            deterministic = complete and len(sizes) == 1 and len(digests) == 1
            candidate_bytes = next(iter(sizes)) if deterministic else None
            gain = (
                (item["baseline_bytes"] - candidate_bytes)
                / item["baseline_bytes"]
                * 100.0
                if candidate_bytes is not None
                else None
            )
            resource_pass = complete and all(
                row["compression_peak_rss_bytes"]
                <= item["baseline_compression_peak_rss_bytes"] + 2 * GIB
                and row["decompression_peak_rss_bytes"]
                <= item["baseline_decompression_peak_rss_bytes"] + 2 * GIB
                for row in group
            )
            rows.append(
                {
                    "item_id": item["id"],
                    "track": item["track"],
                    "variant": variant,
                    "source_bytes": item["source_bytes"],
                    "baseline_bytes": item["baseline_bytes"],
                    "candidate_bytes": candidate_bytes,
                    "gain_vs_kanzi_percent": gain,
                    "median_compression_ns": (
                        int(
                            statistics.median(
                                row["compression_wall_ns"] for row in group
                            )
                        )
                        if complete
                        else None
                    ),
                    "median_decompression_ns": (
                        int(
                            statistics.median(
                                row["decompression_wall_ns"] for row in group
                            )
                        )
                        if complete
                        else None
                    ),
                    "compression_peak_rss_bytes": max(
                        (row["compression_peak_rss_bytes"] for row in group), default=0
                    ),
                    "decompression_peak_rss_bytes": max(
                        (row["decompression_peak_rss_bytes"] for row in group),
                        default=0,
                    ),
                    "exact_roundtrip": complete,
                    "deterministic_artifact": deterministic,
                    "resource_pass": resource_pass,
                    "passed": deterministic and resource_pass,
                }
            )
    tracks = {}
    for track in sorted({item["track"] for item in items}):
        variants = sorted({row["variant"] for row in rows if row["track"] == track})
        summaries = []
        for variant in variants:
            selected = [
                row
                for row in rows
                if row["track"] == track and row["variant"] == variant
            ]
            complete = bool(selected) and all(row["passed"] for row in selected)
            baseline_bytes = sum(row["baseline_bytes"] for row in selected)
            candidate_bytes = (
                sum(row["candidate_bytes"] for row in selected) if complete else None
            )
            gain = (
                (baseline_bytes - candidate_bytes) / baseline_bytes * 100.0
                if candidate_bytes is not None
                else None
            )
            minimum_item_gain = (
                min(row["gain_vs_kanzi_percent"] for row in selected)
                if complete
                else None
            )
            if variant == "ts-h1-demux":
                hypothesis_gate = (
                    complete and gain >= 0.5 and minimum_item_gain >= -0.25
                )
            else:
                hypothesis_gate = complete and gain >= 2.0 and minimum_item_gain >= -0.5
            final_admission = complete and gain >= 3.0 and minimum_item_gain >= -0.5
            summaries.append(
                {
                    "variant": variant,
                    "baseline_bytes": baseline_bytes,
                    "candidate_bytes": candidate_bytes,
                    "gain_vs_kanzi_percent": gain,
                    "minimum_item_gain_percent": minimum_item_gain,
                    "complete": complete,
                    "hypothesis_gate_passed": hypothesis_gate,
                    "final_specialist_admission_passed": final_admission,
                }
            )
        tracks[track] = summaries
    return {"item_rows": rows, "tracks": tracks}


def benchmark(
    baseline_path: Path, corpus: Path, tools_root: Path, output: Path
) -> Path:
    repository = repository_state()
    baseline, items, kanzi = load_inputs(baseline_path, corpus, tools_root)
    bindings = {
        "repository_commit": repository["commit"],
        "baseline_results_sha256": file_digest(baseline_path),
        "corpus_manifest_sha256": file_digest(corpus / "manifest.json"),
        "kanzi_binary_sha256": file_digest(kanzi),
    }
    output.mkdir(parents=True, exist_ok=True)
    attempt_path = output / "attempt.json"
    pairs = [(item, variant) for item in items for variant in variants_for(item)]
    expected_attempt = {
        "schema_version": 1,
        "name": "text-source-structural-transform-development-v1",
        "completed": False,
        "bindings": bindings,
        "baseline_commit": baseline["bindings"]["repository_commit"],
        "backend": "kanzi-max",
        "backend_setting": ["--level=9", "--block=1g", "--jobs=1"],
        "repetitions": REPETITIONS,
        "warmups": 1,
        "order_seed": ORDER_SEED,
        "items": [
            {key: value for key, value in item.items() if key != "path"}
            for item in items
        ],
        "claim_ceiling": "Development structural representation probe only; no category, product, market-leading, world-best, or state-of-the-art claim.",
    }
    if attempt_path.exists():
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        if attempt != expected_attempt:
            raise ValueError("existing structural probe attempt differs from protocol")
    else:
        attempt = expected_attempt
        write_json_atomic(attempt_path, attempt)

    trials = []
    total = len(pairs) * (REPETITIONS + 1)
    progress = 0
    for repetition in range(REPETITIONS + 1):
        ordered = list(pairs)
        random.Random(ORDER_SEED + repetition).shuffle(ordered)
        for item, variant in ordered:
            progress += 1
            print(
                f"[{progress}/{total}] r{repetition} {item['id']} x {variant}",
                flush=True,
            )
            trials.append(
                run_trial(
                    output=output,
                    item=item,
                    variant=variant,
                    repetition=repetition,
                    kanzi=kanzi,
                    bindings=bindings,
                )
            )
    summary = summarize(trials, items)
    result = attempt | {
        "completed": True,
        "trial_count": len(trials),
        "all_required_completed": all(row["passed"] for row in summary["item_rows"]),
        "summary": summary,
    }
    result_path = output / "results.json"
    write_json_atomic(result_path, result)
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--worker-encode", nargs=3, metavar=("VARIANT", "SOURCE", "OUTPUT")
    )
    parser.add_argument(
        "--worker-decode", nargs=3, metavar=("MAXIMUM", "SOURCE", "OUTPUT")
    )
    parser.add_argument(
        "--worker-wrap",
        nargs=6,
        metavar=("VARIANT", "BACKEND", "SIZE", "SHA256", "PAYLOAD", "FRAME"),
    )
    parser.add_argument(
        "--worker-unwrap",
        nargs=6,
        metavar=("VARIANT", "BACKEND", "SIZE", "SHA256", "FRAME", "PAYLOAD"),
    )
    args = parser.parse_args()
    try:
        if args.worker_encode:
            variant, source, destination = args.worker_encode
            worker_encode(Path(source), Path(destination), variant)
            return 0
        if args.worker_decode:
            maximum, source, destination = args.worker_decode
            worker_decode(Path(source), Path(destination), int(maximum))
            return 0
        if args.worker_wrap:
            variant, backend, size, sha256, payload, frame = args.worker_wrap
            worker_wrap(variant, backend, int(size), sha256, Path(payload), Path(frame))
            return 0
        if args.worker_unwrap:
            variant, backend, size, sha256, frame, payload = args.worker_unwrap
            worker_unwrap(
                variant, backend, int(size), sha256, Path(frame), Path(payload)
            )
            return 0
        result = benchmark(args.baseline, args.corpus, args.tools, args.output)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"structural transform probe failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
