#!/usr/bin/env python3
"""Run one strict hosted E1 training shard from a frozen offline schedule."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
E1_CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"
MAX_OUTPUT = 1024 * 1024


def verify_execution_barrier(schedule_path: Path, tool_root: Path) -> None:
    """Fail closed on the exact sealed tools and schedule before reading corpus data."""
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify-frontier-headroom-e1-toolchain.py"),
            "--tool-root",
            str(tool_root),
            "--plan",
            str(schedule_path),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary file: {path}")


def packed_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise ValueError("E1 string length differs")
    return struct.pack("<H", len(encoded)) + encoded


def axe1s(
    category: str, item: dict[str, Any], source: Path, ranges: list[dict[str, int]]
) -> bytes:
    payload = bytearray()
    for row in ranges:
        with source.open("rb") as stream:
            stream.seek(row["offset"])
            chunk = stream.read(row["length"])
        if len(chunk) != row["length"]:
            raise ValueError("AXE1S slice is short")
        payload.extend(chunk)
    digest = hashlib.sha256(payload).digest()
    header = bytearray(b"AXE1S" + bytes([1]))
    header.extend(packed_string(category))
    header.extend(packed_string(item["id"]))
    header.extend(struct.pack("<Q", item["bytes"]))
    header.extend(bytes.fromhex(item["sha256"]))
    header.extend(bytes([5]))
    for row in ranges:
        header.extend(struct.pack("<QQ", row["offset"], row["length"]))
    header.extend(struct.pack("<Q", len(payload)))
    header.extend(digest)
    return bytes(header + payload)


def axe1g(
    item: dict[str, Any], segment_bytes: int, choices: list[dict[str, Any]]
) -> bytes:
    frame = bytearray(b"AXE1G" + bytes([1]))
    frame.extend(packed_string(item["id"]))
    frame.extend(struct.pack("<Q", item["bytes"]))
    frame.extend(bytes.fromhex(item["sha256"]))
    frame.extend(struct.pack("<QI", segment_bytes, len(choices)))
    artifacts = []
    for row in choices:
        artifact = Path(row["artifact_path"])
        ordinary(artifact)
        frame.extend(packed_string(row["codec_id"]))
        frame.extend(struct.pack("<Q", row["decoded_bytes"]))
        frame.extend(bytes.fromhex(row["decoded_sha256"]))
        frame.extend(struct.pack("<Q", row["artifact_bytes"]))
        frame.extend(bytes.fromhex(row["artifact_sha256"]))
        artifacts.append(artifact.read_bytes())
    for artifact in artifacts:
        frame.extend(artifact)
    return bytes(frame)


def axe1o_size(category: str, choices: list[dict[str, Any]]) -> int:
    total = 5 + 1 + len(packed_string(category)) + 32 + 4
    for row in sorted(choices, key=lambda value: value["item_id"]):
        total += (
            len(packed_string(row["item_id"]))
            + len(packed_string(row["codec_id"]))
            + 8
            + 32
            + 8
            + 32
            + row["artifact_bytes"]
        )
    return total


def rss_bytes(usage: Any) -> int:
    value = int(usage.ru_maxrss)
    return value if os.uname().sysname == "Darwin" else value * 1024


def bounded_process(
    command: list[str],
    *,
    cwd: Path,
    stdout_path: Path | None,
    timeout_seconds: int,
    log_prefix: Path,
) -> dict[str, Any]:
    if not hasattr(os, "wait4") or not hasattr(os, "killpg"):
        raise ValueError("E1 runner requires wait4 and process-group control")
    stdout_log = log_prefix.with_suffix(".stdout")
    stderr_log = log_prefix.with_suffix(".stderr")
    stdout_target = stdout_path or stdout_log
    started = time.monotonic_ns()
    with stdout_target.open("xb") as stdout, stderr_log.open("xb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        timed_out = output_exceeded = False
        usage = None
        status = None
        while status is None:
            pid, wait_status, sample = os.wait4(process.pid, os.WNOHANG)
            if pid:
                status, usage = wait_status, sample
                break
            elapsed = (time.monotonic_ns() - started) / 1_000_000_000
            output_exceeded = stderr_log.stat().st_size > MAX_OUTPUT or (
                stdout_path is None and stdout_log.stat().st_size > MAX_OUTPUT
            )
            timed_out = elapsed > timeout_seconds
            if timed_out or output_exceeded:
                os.killpg(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    pid, wait_status, sample = os.wait4(process.pid, os.WNOHANG)
                    if pid:
                        status, usage = wait_status, sample
                        break
                    time.sleep(0.05)
                if status is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    _pid, status, usage = os.wait4(process.pid, 0)
                break
            time.sleep(0.05)
    ended = time.monotonic_ns()
    assert status is not None and usage is not None
    exit_code = os.waitstatus_to_exitcode(status)
    process.returncode = exit_code
    return {
        "command": command,
        "wall_ns": ended - started,
        "cpu_user_ns": int(usage.ru_utime * 1_000_000_000),
        "cpu_system_ns": int(usage.ru_stime * 1_000_000_000),
        "peak_rss_bytes": rss_bytes(usage),
        "exit_status": exit_code,
        "timed_out": timed_out,
        "output_exceeded": output_exceeded,
        "stdout_log_bytes": stdout_log.stat().st_size if stdout_log.exists() else 0,
        "stdout_log_path": str(stdout_log) if stdout_log.exists() else None,
        "stdout_log_sha256": sha256_file(stdout_log) if stdout_log.exists() else None,
        "stderr_log_bytes": stderr_log.stat().st_size,
        "stderr_log_path": str(stderr_log),
        "stderr_log_sha256": sha256_file(stderr_log),
    }


def resolve_command(command: list[str], tool_root: Path, work: Path) -> list[str]:
    result = []
    for argument in command:
        argument = argument.replace("$TOOL_ROOT", str(tool_root.resolve()))
        argument = argument.replace("$WORK", str(work.resolve()))
        if "$TOOL_ROOT" in argument or "$WORK" in argument:
            raise ValueError("unresolved E1 execution placeholder")
        result.append(argument)
    return result


def run_repetition(
    task: dict[str, Any],
    source: Path,
    tool_root: Path,
    result_root: Path,
    repetition: int,
    *,
    retained: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    task_slug = task["task_id"].replace("/", "__")
    with tempfile.TemporaryDirectory(prefix=f"e1-{task_slug}-") as raw:
        work = Path(raw)
        staged = work / "input.bin"
        shutil.copyfile(source, staged)
        os.utime(staged, (946684800, 946684800))
        artifact = work / (
            "artifact.zpaq" if task["codec_id"] == "zpaq-5-m510" else "artifact.bin"
        )
        restored = work / "restored.bin"
        restored_dir = work / "restored"
        restored_dir.mkdir()
        log_dir = result_root / "logs" / task_slug / str(repetition)
        log_dir.mkdir(parents=True, exist_ok=False)
        compress_command = resolve_command(task["compress"], tool_root, work)
        compress_stdout = artifact if task["codec_id"] == "xz-lzma2-9e" else None
        compress = bounded_process(
            compress_command,
            cwd=work,
            stdout_path=compress_stdout,
            timeout_seconds=timeout_seconds,
            log_prefix=log_dir / "compress",
        )
        compress["declared_command"] = task["compress"]
        if (
            compress["exit_status"] != 0
            or compress["timed_out"]
            or compress["output_exceeded"]
        ):
            raise ValueError(f"E1 compression failed: {task['task_id']}")
        ordinary(artifact)
        decompress_command = resolve_command(task["decompress"], tool_root, work)
        decompress_stdout = restored if task["codec_id"] == "xz-lzma2-9e" else None
        decompress = bounded_process(
            decompress_command,
            cwd=work,
            stdout_path=decompress_stdout,
            timeout_seconds=timeout_seconds,
            log_prefix=log_dir / "decompress",
        )
        decompress["declared_command"] = task["decompress"]
        if task["codec_id"] == "zpaq-5-m510":
            restored = restored_dir / "input.bin"
        if (
            decompress["exit_status"] != 0
            or decompress["timed_out"]
            or decompress["output_exceeded"]
        ):
            raise ValueError(f"E1 decompression failed: {task['task_id']}")
        ordinary(restored)
        if restored.stat().st_size != source.stat().st_size or sha256_file(
            restored
        ) != sha256_file(source):
            raise ValueError(f"E1 roundtrip differs: {task['task_id']}")
        artifact_digest = sha256_file(artifact)
        retained_path = (
            result_root / "artifacts" / task_slug / f"rep-{repetition}{artifact.suffix}"
        )
        if retained:
            retained_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact, retained_path)
        for process in (compress, decompress):
            for key in ("stdout_log_path", "stderr_log_path"):
                if process[key] is not None:
                    process[key] = (
                        Path(process[key]).relative_to(result_root).as_posix()
                    )
        return {
            "repetition": repetition,
            "warmup": not retained,
            "source_bytes": source.stat().st_size,
            "source_sha256": sha256_file(source),
            "artifact_path": retained_path.relative_to(result_root).as_posix()
            if retained
            else None,
            "artifact_bytes": artifact.stat().st_size,
            "artifact_sha256": artifact_digest,
            "restored_bytes": restored.stat().st_size,
            "restored_sha256": sha256_file(restored),
            "exact": True,
            "compress": compress,
            "decompress": decompress,
        }


def run_task(
    task: dict[str, Any],
    source: Path,
    tool_root: Path,
    result_root: Path,
    e1: dict[str, Any],
) -> dict[str, Any]:
    practical = task["codec_id"] != "zpaq-5-m510"
    warmups = (
        e1["measurement"]["warmups_practical"]
        if practical
        else e1["measurement"]["warmups_zpaq"]
    )
    repetitions = (
        e1["measurement"]["measured_repetitions_practical"]
        if practical
        else e1["measurement"]["measured_repetitions_zpaq"]
    )
    for index in range(warmups):
        run_repetition(
            task,
            source,
            tool_root,
            result_root,
            -1 - index,
            retained=False,
            timeout_seconds=e1["measurement"]["timeout_seconds_per_process"],
        )
    rows = [
        run_repetition(
            task,
            source,
            tool_root,
            result_root,
            index,
            retained=True,
            timeout_seconds=e1["measurement"]["timeout_seconds_per_process"],
        )
        for index in range(repetitions)
    ]
    if len({(row["artifact_bytes"], row["artifact_sha256"]) for row in rows}) != 1:
        raise ValueError(f"E1 artifact is nondeterministic: {task['task_id']}")
    return {
        "task_id": task["task_id"],
        "phase": task["phase"],
        "codec_id": task["codec_id"],
        "item_id": task["item_id"],
        "category": task["category"],
        "repetitions": rows,
        "deterministic": True,
        "exact": True,
    }


def select_tasks(
    schedule: dict[str, Any], phase: str, category: str, codec_group: str
) -> list[dict[str, Any]]:
    if phase == "sample":
        rows = schedule["sample_tasks"]
    else:
        rows = schedule["whole_item_tasks"]
    allowed = (
        {"kanzi-max", "zstd-19-long", "xz-lzma2-9e"}
        if codec_group == "practical"
        else {codec_group}
    )
    selected = [
        row
        for row in rows
        if row["category"] == category and row["codec_id"] in allowed
    ]
    if not selected:
        raise ValueError("E1 shard selection is empty")
    return selected


def whole_choices(
    paths: list[Path], category: str
) -> tuple[bool, dict[str, dict[str, Any]]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for path in paths:
        ordinary(path)
        document = json.loads(path.read_bytes())
        if document["phase"] != "whole" or document["category"] != category:
            continue
        if (
            document["public_validation_accessed"]
            or document["private_holdout_accessed"]
        ):
            raise ValueError("E1 whole result crossed a sealed boundary")
        for trial in document["trials"]:
            if not trial["exact"] or not trial["deterministic"]:
                raise ValueError("E1 whole result is not exact and deterministic")
            rep = trial["repetitions"][0]
            rows[(trial["codec_id"], trial["item_id"])] = {
                "item_id": trial["item_id"],
                "codec_id": trial["codec_id"],
                "decoded_bytes": rep["source_bytes"],
                "decoded_sha256": rep["source_sha256"],
                "artifact_bytes": rep["artifact_bytes"],
                "artifact_sha256": rep["artifact_sha256"],
            }
    codec_ids = ("kanzi-max", "zstd-19-long", "xz-lzma2-9e", "zpaq-5-m510")
    item_ids = sorted({item for _codec, item in rows})
    if not item_ids or any(
        (codec, item) not in rows for codec in codec_ids for item in item_ids
    ):
        raise ValueError("E1 whole-result roster is incomplete")
    single = {
        codec: axe1o_size(category, [rows[(codec, item)] for item in item_ids])
        for codec in codec_ids
    }
    winners = {
        item: min(
            (rows[(codec, item)] for codec in codec_ids),
            key=lambda row: (row["artifact_bytes"], row["codec_id"]),
        )
        for item in item_ids
    }
    oracle_bytes = axe1o_size(category, list(winners.values()))
    best_single = min(single.values())
    gain_bp = (best_single - oracle_bytes) * 10_000 // best_single
    triggered = gain_bp >= 50 or len({row["codec_id"] for row in winners.values()}) >= 2
    return triggered, winners


def run_segment_shard(
    schedule_path: Path,
    manifest_path: Path,
    tool_root: Path,
    output: Path,
    *,
    category: str,
    whole_results: list[Path],
) -> dict[str, Any]:
    for path in (schedule_path, tool_root / "receipt.json"):
        ordinary(path)
    verify_execution_barrier(schedule_path, tool_root)
    ordinary(manifest_path)
    schedule = json.loads(schedule_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    e1 = json.loads(E1_CONFIG.read_bytes())
    if (
        manifest.get("public_validation_accessed") is not False
        or manifest.get("private_holdout_accessed") is not False
    ):
        raise ValueError("E1 manifest crossed a sealed boundary")
    triggered, whole_winners = whole_choices(whole_results, category)
    if output.exists():
        raise ValueError("refusing to replace E1 segment shard output")
    output.mkdir(parents=True)
    trials = []
    containers = []
    if triggered:
        item_map = {row["id"]: row for row in manifest["items"]}
        task_map = {
            (row["codec_id"], row["item_id"]): row
            for row in schedule["whole_item_tasks"]
            if row["category"] == category
        }
        for item_id in sorted(whole_winners):
            item = item_map[item_id]
            source = manifest_path.parent / item["path"]
            ordinary(source)
            if (
                source.stat().st_size != item["bytes"]
                or sha256_file(source) != item["sha256"]
            ):
                raise ValueError(f"E1 training item drifted: {item['id']}")
            choices = []
            segment_size = e1["oracle_routing"]["segment_bytes"]
            with source.open("rb") as stream:
                segment_index = 0
                while chunk := stream.read(segment_size):
                    generated = output / "generated" / item_id
                    generated.mkdir(parents=True, exist_ok=True)
                    segment_source = generated / f"segment-{segment_index}.bin"
                    segment_source.write_bytes(chunk)
                    segment_trials = []
                    for codec_id in e1["oracle_routing"]["segment_codecs"]:
                        base_task = task_map[(codec_id, item_id)]
                        task = {
                            **base_task,
                            "task_id": f"segment/{codec_id}/{item_id}/{segment_index}",
                            "phase": "segment",
                        }
                        trial = run_task(task, segment_source, tool_root, output, e1)
                        trials.append(trial)
                        segment_trials.append(trial)
                    winner = min(
                        segment_trials,
                        key=lambda row: (
                            row["repetitions"][0]["artifact_bytes"],
                            row["codec_id"],
                        ),
                    )
                    rep = winner["repetitions"][0]
                    choices.append(
                        {
                            "codec_id": winner["codec_id"],
                            "decoded_bytes": len(chunk),
                            "decoded_sha256": hashlib.sha256(chunk).hexdigest(),
                            "artifact_bytes": rep["artifact_bytes"],
                            "artifact_sha256": rep["artifact_sha256"],
                            "artifact_path": str(output / rep["artifact_path"]),
                        }
                    )
                    segment_source.unlink()
                    segment_index += 1
            container = axe1g(item, segment_size, choices)
            container_path = output / "containers" / f"{item_id}.axe1g"
            container_path.parent.mkdir(parents=True, exist_ok=True)
            container_path.write_bytes(container)
            containers.append(
                {
                    "item_id": item_id,
                    "path": container_path.relative_to(output).as_posix(),
                    "bytes": len(container),
                    "sha256": hashlib.sha256(container).hexdigest(),
                    "segment_count": len(choices),
                    "choices": [
                        {
                            key: value
                            for key, value in row.items()
                            if key != "artifact_path"
                        }
                        for row in choices
                    ],
                }
            )
    result = {
        "schema_version": 1,
        "name": "frontier-headroom-e1-segment-result-v1",
        "completed": True,
        "phase": "segment",
        "category": category,
        "codec_group": "all",
        "schedule_sha256": sha256_file(schedule_path),
        "training_manifest_sha256": sha256_file(manifest_path),
        "tool_receipt_sha256": sha256_file(tool_root / "receipt.json"),
        "repository_commit": schedule["repository_commit"],
        "triggered": triggered,
        "whole_item_winners": whole_winners,
        "trials": trials,
        "containers": containers,
        "public_validation_accessed": False,
        "private_holdout_accessed": False,
        "claim_ceiling": e1["claim_ceiling"],
    }
    (output / "result.json").write_bytes(json_bytes(result))
    return result


def run_shard(
    schedule_path: Path,
    manifest_path: Path,
    tool_root: Path,
    output: Path,
    *,
    phase: str,
    category: str,
    codec_group: str,
) -> dict[str, Any]:
    for path in (schedule_path, tool_root / "receipt.json"):
        ordinary(path)
    verify_execution_barrier(schedule_path, tool_root)
    ordinary(manifest_path)
    schedule = json.loads(schedule_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    e1 = json.loads(E1_CONFIG.read_bytes())
    if (
        manifest.get("public_validation_accessed") is not False
        or manifest.get("private_holdout_accessed") is not False
    ):
        raise ValueError("E1 manifest crossed a sealed boundary")
    items = {row["id"]: row for row in manifest["items"]}
    base = manifest_path.parent
    selected = select_tasks(schedule, phase, category, codec_group)
    if output.exists():
        raise ValueError("refusing to replace E1 shard output")
    output.mkdir(parents=True)
    trials = []
    generated_inputs: dict[str, dict[str, Any]] = {}
    generated = output / "generated"
    generated.mkdir()
    for task in selected:
        item = items[task["item_id"]]
        source = base / item["path"]
        ordinary(source)
        if (
            source.stat().st_size != item["bytes"]
            or sha256_file(source) != item["sha256"]
        ):
            raise ValueError(f"E1 training item drifted: {item['id']}")
        measured_source = source
        if phase == "sample":
            payload = axe1s(item["category"], item, source, task["ranges"])
            measured_source = generated / f"{item['id']}.axe1s"
            if measured_source.exists():
                if measured_source.read_bytes() != payload:
                    raise ValueError("AXE1S regeneration differs")
            else:
                measured_source.write_bytes(payload)
            generated_inputs[item["id"]] = {
                "item_id": item["id"],
                "path": measured_source.relative_to(output).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        trials.append(run_task(task, measured_source, tool_root, output, e1))
    result = {
        "schema_version": 1,
        "name": "frontier-headroom-e1-shard-result-v1",
        "completed": True,
        "phase": phase,
        "category": category,
        "codec_group": codec_group,
        "schedule_sha256": sha256_file(schedule_path),
        "training_manifest_sha256": sha256_file(manifest_path),
        "tool_receipt_sha256": sha256_file(tool_root / "receipt.json"),
        "repository_commit": schedule["repository_commit"],
        "trials": trials,
        "generated_inputs": [generated_inputs[key] for key in sorted(generated_inputs)],
        "public_validation_accessed": False,
        "private_holdout_accessed": False,
        "claim_ceiling": e1["claim_ceiling"],
    }
    (output / "result.json").write_bytes(json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--phase", choices=("whole", "sample", "segment"), required=True
    )
    parser.add_argument("--category", required=True)
    parser.add_argument("--codec-group", choices=("practical", "zpaq-5-m510"))
    parser.add_argument("--whole-result", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        if args.phase == "segment":
            if args.codec_group is not None or not args.whole_result:
                raise ValueError(
                    "segment phase requires whole results and no codec group"
                )
            result = run_segment_shard(
                args.schedule,
                args.manifest,
                args.tool_root,
                args.output,
                category=args.category,
                whole_results=args.whole_result,
            )
        else:
            if args.codec_group is None:
                raise ValueError("whole/sample phase requires a codec group")
            result = run_shard(
                args.schedule,
                args.manifest,
                args.tool_root,
                args.output,
                phase=args.phase,
                category=args.category,
                codec_group=args.codec_group,
            )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E1 shard failed: {error}") from error
    print(
        json.dumps({"completed": result["completed"], "trials": len(result["trials"])})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
