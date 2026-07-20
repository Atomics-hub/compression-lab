#!/usr/bin/env python3
"""Build the frozen incompressible/precompressed development corpus atomically."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any, Iterator
import zipfile
import zlib


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "incompressible-precompressed-development-plan-v1.json"
DEFAULT_SOURCE_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_TOOLS = REPOSITORY / ".baseline-tools" / "text-source-v1"
DEFAULT_OUTPUT = REPOSITORY / "corpora" / "incompressible-precompressed-development-v1"
CHUNK_SIZE = 1024 * 1024
PROCESS_KEYS = {"command", "returncode", "stdout", "stderr"}
TOOL_FOR_PROFILE = {
    "gzip-9": "gzip",
    "bzip2-9": "bzip2",
    "zstd-19": "zstd",
    "brotli-11": "brotli",
    "xz-lzma2-9e": "xz",
}
TEXT_PATTERN = (
    b"Axiom incompressible safety gate: selector evidence must stay bounded, "
    b"and a wrong guess must fall back to the complete store frame.\n"
)
_COUNTER_BLOCK: bytes | None = None


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load_script(
    "incompressible_precompressed_planner_for_builder",
    REPOSITORY / "scripts" / "prepare-incompressible-precompressed-execution.py",
)
PLAN_VERIFY = load_script(
    "incompressible_precompressed_plan_verifier_for_builder",
    REPOSITORY / "scripts" / "verify-incompressible-precompressed-plan.py",
)
BASELINE = load_script(
    "text_source_baseline_tools_for_incompressible_builder",
    REPOSITORY / "scripts" / "benchmark-text-source-baselines.py",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return PLANNER.json_bytes(payload)


def sha256_file(path: Path) -> str:
    return PLANNER.sha256_file(path)


def read_canonical_json(path: Path) -> dict[str, Any]:
    return PLANNER.read_canonical_json(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def stream_commitment(payload: bytes) -> dict[str, Any]:
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def is_stream_commitment(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"bytes", "sha256"}
        and type(value["bytes"]) is int
        and value["bytes"] >= 0
        and is_sha256(value["sha256"])
    )


def shake_block(domain: str, item_id: str, counter: int, size: int) -> bytes:
    if counter < 0 or counter >= 1 << 64 or size < 0 or size > CHUNK_SIZE:
        raise ValueError("counter-mode SHAKE block request is outside protocol")
    seed = (
        domain.encode("utf-8")
        + b"\x00"
        + item_id.encode("utf-8")
        + struct.pack("<Q", counter)
    )
    return hashlib.shake_256(seed).digest(size)


def counter_pattern(size: int) -> bytes:
    global _COUNTER_BLOCK
    if size < 0 or size > CHUNK_SIZE:
        raise ValueError("counter-pattern block size is outside protocol")
    if _COUNTER_BLOCK is None:
        unit = b"".join(struct.pack("<I", value) for value in range(65_536))
        _COUNTER_BLOCK = unit * (CHUNK_SIZE // len(unit))
    return _COUNTER_BLOCK[:size]


def repeated(pattern: bytes, size: int) -> bytes:
    if not pattern or size < 0 or size > CHUNK_SIZE:
        raise ValueError("repeated-pattern block request is invalid")
    return (pattern * (size // len(pattern) + 1))[:size]


def deceptive_kind(layout: str, block_index: int) -> str:
    if block_index < 0 or block_index >= 64:
        raise ValueError("deceptive block index is outside protocol")
    quarter = block_index // 16
    orders = {
        "random-first": ["random", "zero", "text", "counter"],
        "random-middle": ["zero", "text", "random", "counter"],
        "random-last": ["zero", "text", "counter", "random"],
    }
    if layout in orders:
        return orders[layout][quarter]
    if layout == "alternating-random-zero-1mib":
        return "random" if block_index % 2 == 0 else "zero"
    if layout == "sampler-blind-spots":
        if block_index in {0, 31, 32, 63}:
            return "text"
        return "random" if block_index % 2 else "counter"
    raise ValueError(f"unsupported deceptive layout: {layout}")


def generated_chunks(task: dict[str, Any]) -> Iterator[bytes]:
    generation = task["generation"]
    planned = task["planned_bytes"]
    algorithm = generation["algorithm"]
    remaining = planned
    block_index = 0
    while remaining:
        size = min(generation.get("block_bytes", CHUNK_SIZE), remaining)
        if size <= 0 or size > CHUNK_SIZE:
            raise ValueError("generated task block size is invalid")
        if algorithm in {
            "counter-mode-shake256-v1",
            "magic-spoofed-counter-mode-shake256-v1",
        }:
            block = shake_block(
                generation["domain"], generation["item_id"], block_index, size
            )
            if algorithm == "magic-spoofed-counter-mode-shake256-v1" and block_index == 0:
                prefix = bytes.fromhex(generation["magic_prefix_hex"])
                if len(prefix) > len(block):
                    raise ValueError("magic prefix exceeds the first generated block")
                block = prefix + block[len(prefix) :]
        elif algorithm == "deceptive-region-order-v1":
            kind = deceptive_kind(generation["layout"], block_index)
            if kind == "random":
                block = shake_block(
                    generation["domain"], task["item_id"], block_index, size
                )
            elif kind == "zero":
                block = b"\x00" * size
            elif kind == "text":
                block = repeated(TEXT_PATTERN, size)
            elif kind == "counter":
                block = counter_pattern(size)
            else:
                raise ValueError("deceptive block kind is invalid")
        else:
            raise ValueError(f"unsupported generated algorithm: {algorithm}")
        yield block
        remaining -= len(block)
        block_index += 1


def expected_generated_identity(task: dict[str, Any]) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    for chunk in generated_chunks(task):
        digest.update(chunk)
        total += len(chunk)
    if total != task["planned_bytes"]:
        raise ValueError("generated recipe byte count differs from plan")
    return total, digest.hexdigest()


def generated_receipt(task: dict[str, Any], item_path: Path, plan_sha256: str) -> dict[str, Any]:
    expected_bytes, expected_sha256 = expected_generated_identity(task)
    if (
        item_path.stat().st_size != expected_bytes
        or sha256_file(item_path) != expected_sha256
    ):
        raise ValueError(f"generated item identity differs: {task['task_id']}")
    return {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-item-v1",
        "plan_sha256": plan_sha256,
        "task_id": task["task_id"],
        "family_id": task["family_id"],
        "kind": "generated",
        "item_id": task["item_id"],
        "path": f"items/{task['output_filename']}",
        "bytes": expected_bytes,
        "sha256": expected_sha256,
        "license": task["license"],
        "generation": task["generation"],
        "exact_generation_size": True,
        "execution_status": "generated_and_byte_verified",
        "axiom_outcome": "untested",
    }


def materialize_generated(
    *, work: Path, task: dict[str, Any], plan_sha256: str
) -> dict[str, Any]:
    item_path = work / "items" / task["output_filename"]
    receipt_path = work / "receipts" / f"{task['task_id']}.json"
    if item_path.exists() or receipt_path.exists():
        if not item_path.is_file() or item_path.is_symlink() or not receipt_path.is_file() or receipt_path.is_symlink():
            raise ValueError(f"resumed generated task is incomplete: {task['task_id']}")
        observed = read_canonical_json(receipt_path)
        expected = generated_receipt(task, item_path, plan_sha256)
        if observed != expected:
            raise ValueError(f"resumed generated task differs: {task['task_id']}")
        return observed
    item_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    partial = item_path.with_name(f".{item_path.name}.partial")
    partial.unlink(missing_ok=True)
    try:
        with partial.open("xb") as output:
            for chunk in generated_chunks(task):
                output.write(chunk)
        if partial.stat().st_size != task["planned_bytes"]:
            raise ValueError("generated item size differs from plan")
        partial.replace(item_path)
        receipt = generated_receipt(task, item_path, plan_sha256)
        if not receipt["exact_generation_size"]:
            raise ValueError("generated item failed its size gate")
        write_json_atomic(receipt_path, receipt)
        return receipt
    except BaseException:
        partial.unlink(missing_ok=True)
        if not receipt_path.exists():
            item_path.unlink(missing_ok=True)
        raise


def zip_compress(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo("input.bin", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 0
    info.external_attr = 0x20
    info.extra = b""
    info.comment = b""
    info._compresslevel = 9
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b""
        with archive.open(info, "w") as member, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, member, CHUNK_SIZE)


def zip_decompress(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        if len(infos) != 1:
            raise ValueError("ZIP derivative must contain exactly one member")
        if archive.comment:
            raise ValueError("ZIP derivative metadata differs from protocol")
        info = infos[0]
        if (
            info.filename != "input.bin"
            or info.is_dir()
            or info.compress_type != zipfile.ZIP_DEFLATED
            or info.date_time != (1980, 1, 1, 0, 0, 0)
            or info.create_system != 0
            or info.external_attr != 0x20
            or info.internal_attr != 0
            or info.extra
            or info.comment
        ):
            raise ValueError("ZIP derivative metadata differs from protocol")
        with archive.open(info, "r") as member, destination.open("xb") as output:
            shutil.copyfileobj(member, output, CHUNK_SIZE)


def safe_tool_records(tools_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if BASELINE.DEFAULT_CONFIG.is_symlink() or not BASELINE.DEFAULT_CONFIG.is_file():
        raise ValueError("frozen baseline config is not an ordinary file")
    baseline_config = json.loads(BASELINE.DEFAULT_CONFIG.read_bytes())
    if not isinstance(baseline_config, dict):
        raise ValueError("frozen baseline config is not a JSON object")
    resolved = BASELINE.resolve_tools(
        baseline_config, BASELINE.DEFAULT_CONFIG, tools_root
    )
    paths: dict[str, dict[str, Any]] = {}
    public: dict[str, dict[str, Any]] = {}
    for tool_id in sorted(set(TOOL_FOR_PROFILE.values())):
        row = resolved[tool_id]
        path = Path(row["path"])
        if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
            raise ValueError(f"precompression tool is not an ordinary executable: {tool_id}")
        paths[tool_id] = row
        public[tool_id] = {
            "version": row["version"],
            "binary_size_bytes": row["binary_size_bytes"],
            "binary_sha256": row["binary_sha256"],
        }
    python_path = Path(sys.executable).resolve()
    public["python-zipfile"] = {
        "python": sys.version.split()[0],
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        "executable_size_bytes": python_path.stat().st_size,
        "executable_sha256": sha256_file(python_path),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    public["corpus-builder"] = {
        "implementation": "CPython",
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "stream_chunk_bytes": CHUNK_SIZE,
    }
    return paths, public


def substitute_command(
    template: list[str],
    *,
    profile_id: str,
    tools: dict[str, dict[str, Any]],
    source: Path,
    payload: Path,
    restored: Path,
) -> list[str]:
    values = {
        "$SOURCE": str(source),
        "$PAYLOAD": str(payload),
        "$RESTORED": str(restored),
        "$PYTHON": sys.executable,
        "$RUNNER": str(Path(__file__).resolve()),
    }
    command = []
    for index, argument in enumerate(template):
        if index == 0 and argument in TOOL_FOR_PROFILE.values():
            argument = str(tools[argument]["path"])
        else:
            for marker, value in values.items():
                argument = argument.replace(marker, value)
        command.append(argument)
    expected_tool = TOOL_FOR_PROFILE.get(profile_id)
    if expected_tool is not None and command[0] != str(tools[expected_tool]["path"]):
        raise ValueError("precompression command tool differs from profile")
    return command


def run_process(
    command: list[str], *, stdout_path: Path | None, timeout_seconds: float
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update({"LC_ALL": "C", "TZ": "UTC", "OMP_NUM_THREADS": "1"})
    output_file = stdout_path.open("xb") if stdout_path is not None else subprocess.PIPE
    try:
        process = subprocess.run(
            command,
            cwd=REPOSITORY,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output_file,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    finally:
        if stdout_path is not None:
            output_file.close()
    stdout = b"" if stdout_path is not None else process.stdout
    return {
        "command": command,
        "returncode": process.returncode,
        "stdout": stream_commitment(stdout),
        "stderr": stream_commitment(process.stderr),
    }


def same_file_identity(left: Path, right: Path) -> bool:
    return (
        left.stat().st_size == right.stat().st_size
        and sha256_file(left) == sha256_file(right)
    )


def sanitize_process(
    process: dict[str, Any],
    *,
    template: list[str],
) -> dict[str, Any]:
    if set(process) != PROCESS_KEYS:
        raise ValueError("precompression process field roster differs")
    return process | {"command": template}


def precompressed_receipt(
    *,
    task: dict[str, Any],
    item_path: Path,
    plan_sha256: str,
    tools_public: dict[str, dict[str, Any]],
    compression: dict[str, Any],
    decompression: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, Any]:
    profile_id = task["precompression_profile_id"]
    tool_id = TOOL_FOR_PROFILE.get(profile_id, "python-zipfile")
    return {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-item-v1",
        "plan_sha256": plan_sha256,
        "task_id": task["task_id"],
        "family_id": task["family_id"],
        "kind": "precompressed",
        "item_id": task["item_id"],
        "path": f"items/{task['output_filename']}",
        "bytes": item_path.stat().st_size,
        "sha256": sha256_file(item_path),
        "license": task["license"],
        "source": task["source"],
        "precompression_profile_id": profile_id,
        "tool": {"tool_id": tool_id} | tools_public[tool_id],
        "compression": sanitize_process(
            compression, template=profiles[profile_id]["compress"]
        ),
        "decompression": sanitize_process(
            decompression, template=profiles[profile_id]["decompress"]
        ),
        "exact_roundtrip": True,
        "execution_status": "precompressed_and_exactly_restored",
        "axiom_outcome": "untested",
    }


def validate_resumed_precompressed(
    *,
    receipt: dict[str, Any],
    task: dict[str, Any],
    item_path: Path,
    plan_sha256: str,
    tools_public: dict[str, dict[str, Any]],
    profiles: dict[str, Any],
) -> None:
    profile_id = task["precompression_profile_id"]
    tool_id = TOOL_FOR_PROFILE.get(profile_id, "python-zipfile")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("name") != "incompressible-precompressed-development-item-v1"
        or receipt.get("plan_sha256") != plan_sha256
        or receipt.get("task_id") != task["task_id"]
        or receipt.get("family_id") != task["family_id"]
        or receipt.get("kind") != "precompressed"
        or receipt.get("item_id") != task["item_id"]
        or receipt.get("path") != f"items/{task['output_filename']}"
        or receipt.get("bytes") != item_path.stat().st_size
        or receipt.get("sha256") != sha256_file(item_path)
        or receipt.get("license") != task["license"]
        or receipt.get("source") != task["source"]
        or receipt.get("precompression_profile_id") != profile_id
        or receipt.get("tool") != ({"tool_id": tool_id} | tools_public[tool_id])
        or receipt.get("exact_roundtrip") is not True
        or receipt.get("execution_status") != "precompressed_and_exactly_restored"
        or receipt.get("axiom_outcome") != "untested"
    ):
        raise ValueError(f"resumed precompressed receipt differs: {task['task_id']}")
    for phase in ("compression", "decompression"):
        process = receipt.get(phase)
        if (
            not isinstance(process, dict)
            or set(process) != PROCESS_KEYS
            or process.get("command") != profiles[profile_id][
                "compress" if phase == "compression" else "decompress"
            ]
            or type(process.get("returncode")) is not int
            or process["returncode"] != 0
            or not is_stream_commitment(process.get("stdout"))
            or not is_stream_commitment(process.get("stderr"))
        ):
            raise ValueError(f"resumed precompression process differs: {task['task_id']}")


def materialize_precompressed(
    *,
    work: Path,
    source_corpus: Path,
    task: dict[str, Any],
    plan_sha256: str,
    tools: dict[str, dict[str, Any]],
    tools_public: dict[str, dict[str, Any]],
    profiles: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    source = source_corpus / task["source"]["bundle_path"]
    if (
        not source.is_file()
        or source.is_symlink()
        or source.stat().st_size != task["source"]["bundle_size_bytes"]
        or sha256_file(source) != task["source"]["bundle_sha256"]
    ):
        raise ValueError(f"licensed precompression source differs: {task['task_id']}")
    item_path = work / "items" / task["output_filename"]
    receipt_path = work / "receipts" / f"{task['task_id']}.json"
    if item_path.exists() or receipt_path.exists():
        if not item_path.is_file() or item_path.is_symlink() or not receipt_path.is_file() or receipt_path.is_symlink():
            raise ValueError(f"resumed precompressed task is incomplete: {task['task_id']}")
        receipt = read_canonical_json(receipt_path)
        validate_resumed_precompressed(
            receipt=receipt,
            task=task,
            item_path=item_path,
            plan_sha256=plan_sha256,
            tools_public=tools_public,
            profiles=profiles,
        )
        return receipt

    item_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = item_path.with_name(f".{item_path.name}.partial")
    restored = item_path.with_name(f".{item_path.name}.restored.partial")
    payload.unlink(missing_ok=True)
    restored.unlink(missing_ok=True)
    profile_id = task["precompression_profile_id"]
    profile = profiles[profile_id]
    compress_command = substitute_command(
        profile["compress"],
        profile_id=profile_id,
        tools=tools,
        source=source,
        payload=payload,
        restored=restored,
    )
    decompress_command = substitute_command(
        profile["decompress"],
        profile_id=profile_id,
        tools=tools,
        source=source,
        payload=payload,
        restored=restored,
    )
    try:
        compression = run_process(
            compress_command,
            stdout_path=(
                payload if profile.get("compress_stdout") == "$PAYLOAD" else None
            ),
            timeout_seconds=timeout_seconds,
        )
        if compression["returncode"] != 0 or not payload.is_file() or payload.is_symlink():
            raise ValueError(f"precompression failed: {task['task_id']}")
        decompression = run_process(
            decompress_command,
            stdout_path=(
                restored if profile.get("decompress_stdout") == "$RESTORED" else None
            ),
            timeout_seconds=timeout_seconds,
        )
        if (
            decompression["returncode"] != 0
            or not restored.is_file()
            or restored.is_symlink()
            or not same_file_identity(source, restored)
        ):
            raise ValueError(f"precompression round trip failed: {task['task_id']}")
        payload.replace(item_path)
        receipt = precompressed_receipt(
            task=task,
            item_path=item_path,
            plan_sha256=plan_sha256,
            tools_public=tools_public,
            compression=compression,
            decompression=decompression,
            profiles=profiles,
        )
        write_json_atomic(receipt_path, receipt)
        return receipt
    except BaseException:
        payload.unlink(missing_ok=True)
        restored.unlink(missing_ok=True)
        if not receipt_path.exists():
            item_path.unlink(missing_ok=True)
        raise
    finally:
        restored.unlink(missing_ok=True)


def receipt_manifest(work: Path, receipts: list[dict[str, Any]]) -> str:
    rows = []
    for receipt in receipts:
        path = work / "receipts" / f"{receipt['task_id']}.json"
        rows.append(
            f"receipts/{path.name}\0{path.stat().st_size}\0{sha256_file(path)}\n"
        )
    return hashlib.sha256("".join(rows).encode("utf-8")).hexdigest()


def build_manifest(
    *,
    plan: dict[str, Any],
    plan_sha256: str,
    receipts: list[dict[str, Any]],
    tools_public: dict[str, dict[str, Any]],
    receipts_sha256: str,
) -> dict[str, Any]:
    items = [
        {
            "id": row["item_id"],
            "family_id": row["family_id"],
            "kind": row["kind"],
            "path": row["path"],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
            "license": row["license"],
            "source": row.get("source"),
            "precompression_profile_id": row.get("precompression_profile_id"),
        }
        for row in receipts
    ]
    return {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-corpus-v1",
        "completed": True,
        "plan_sha256": plan_sha256,
        "repository_commit": plan["bindings"]["repository_commit"],
        "item_count": len(items),
        "generated_item_count": sum(row["kind"] == "generated" for row in items),
        "precompressed_item_count": sum(
            row["kind"] == "precompressed" for row in items
        ),
        "items": items,
        "toolchain": tools_public,
        "receipt_manifest_sha256": receipts_sha256,
        "public_validation_status": "unopened and unselected",
        "private_holdout_status": "inaccessible and unselected",
        "axiom_wins": 0,
        "claim_ceiling": plan["claim_ceiling"],
    }


def validate_toolchain(toolchain: object) -> None:
    if not isinstance(toolchain, dict) or set(toolchain) != {
        "gzip",
        "bzip2",
        "zstd",
        "brotli",
        "xz",
        "python-zipfile",
        "corpus-builder",
    }:
        raise ValueError("development corpus toolchain roster differs")
    for tool_id in TOOL_FOR_PROFILE.values():
        row = toolchain[tool_id]
        if (
            not isinstance(row, dict)
            or set(row) != {"version", "binary_size_bytes", "binary_sha256"}
            or not isinstance(row["version"], str)
            or not row["version"]
            or type(row["binary_size_bytes"]) is not int
            or row["binary_size_bytes"] <= 0
            or not is_sha256(row["binary_sha256"])
        ):
            raise ValueError(f"development corpus tool identity differs: {tool_id}")
    zip_tool = toolchain["python-zipfile"]
    if (
        not isinstance(zip_tool, dict)
        or set(zip_tool)
        != {
            "python",
            "zlib_runtime",
            "executable_size_bytes",
            "executable_sha256",
            "runner_sha256",
        }
        or not isinstance(zip_tool["python"], str)
        or not zip_tool["python"]
        or not isinstance(zip_tool["zlib_runtime"], str)
        or not zip_tool["zlib_runtime"]
        or type(zip_tool["executable_size_bytes"]) is not int
        or zip_tool["executable_size_bytes"] <= 0
        or not is_sha256(zip_tool["executable_sha256"])
        or not is_sha256(zip_tool["runner_sha256"])
    ):
        raise ValueError("development corpus ZIP tool identity differs")
    builder_tool = toolchain["corpus-builder"]
    if (
        not isinstance(builder_tool, dict)
        or set(builder_tool)
        != {"implementation", "script_sha256", "stream_chunk_bytes"}
        or builder_tool.get("implementation") != "CPython"
        or builder_tool.get("stream_chunk_bytes") != CHUNK_SIZE
        or not is_sha256(builder_tool.get("script_sha256"))
    ):
        raise ValueError("development corpus builder identity differs")


def validate_corpus(output: Path, plan_path: Path) -> dict[str, Any]:
    plan = read_canonical_json(plan_path)
    plan_sha256 = sha256_file(plan_path)
    if output.is_symlink() or not output.is_dir():
        raise ValueError("development corpus must be an ordinary directory")
    expected_top = {"attempt.json", "items", "receipts", "manifest.json", "receipt.json"}
    if {path.name for path in output.iterdir()} != expected_top:
        raise ValueError("development corpus top-level roster differs")
    if any(path.is_symlink() for path in output.iterdir()):
        raise ValueError("development corpus contains a top-level symlink")
    attempt = read_canonical_json(output / "attempt.json")
    manifest = read_canonical_json(output / "manifest.json")
    receipt = read_canonical_json(output / "receipt.json")
    if (
        set(attempt)
        != {
            "schema_version",
            "name",
            "plan_sha256",
            "repository_commit",
            "toolchain",
            "timeout_seconds_per_precompression_operation",
            "axiom_wins",
            "claim_ceiling",
        }
        or attempt.get("schema_version") != 1
        or attempt.get("name")
        != "incompressible-precompressed-development-corpus-attempt-v1"
        or attempt.get("plan_sha256") != plan_sha256
        or attempt.get("repository_commit") != plan["bindings"]["repository_commit"]
        or type(attempt.get("timeout_seconds_per_precompression_operation"))
        not in {int, float}
        or not math.isfinite(
            attempt.get("timeout_seconds_per_precompression_operation", 0)
        )
        or attempt["timeout_seconds_per_precompression_operation"] <= 0
        or attempt.get("axiom_wins") != 0
        or attempt.get("claim_ceiling") != plan["claim_ceiling"]
        or manifest.get("plan_sha256") != plan_sha256
        or manifest.get("item_count") != 49
        or manifest.get("generated_item_count") != 31
        or manifest.get("precompressed_item_count") != 18
        or manifest.get("axiom_wins") != 0
    ):
        raise ValueError("development corpus identity differs")
    toolchain = attempt.get("toolchain")
    validate_toolchain(toolchain)
    items_root = output / "items"
    receipts_root = output / "receipts"
    if (
        items_root.is_symlink()
        or not items_root.is_dir()
        or receipts_root.is_symlink()
        or not receipts_root.is_dir()
    ):
        raise ValueError("development corpus item/receipt roots are invalid")
    item_entries = set(items_root.iterdir())
    receipt_entries = set(receipts_root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in item_entries | receipt_entries):
        raise ValueError("development corpus contains a non-ordinary item/receipt")
    expected_items = {
        items_root / task["output_filename"] for task in plan["tasks"]
    }
    expected_receipts = {
        receipts_root / f"{task['task_id']}.json" for task in plan["tasks"]
    }
    if item_entries != expected_items or receipt_entries != expected_receipts:
        raise ValueError("development corpus item/receipt roster is incomplete")
    task_map = {row["task_id"]: row for row in plan["tasks"]}
    receipts = []
    for task in plan["tasks"]:
        item_path = output / "items" / task["output_filename"]
        receipt_path = output / "receipts" / f"{task['task_id']}.json"
        row = read_canonical_json(receipt_path)
        if task["kind"] == "generated":
            if row != generated_receipt(task, item_path, plan_sha256):
                raise ValueError(
                    f"development generated receipt differs: {task['task_id']}"
                )
        elif task["kind"] == "precompressed":
            validate_resumed_precompressed(
                receipt=row,
                task=task,
                item_path=item_path,
                plan_sha256=plan_sha256,
                tools_public=attempt["toolchain"],
                profiles=plan["precompression_profiles"],
            )
        else:
            raise ValueError(f"development corpus task kind differs: {task['task_id']}")
        receipts.append(row)
    if set(task_map) != {row["task_id"] for row in receipts}:
        raise ValueError("development corpus task identities differ")
    receipts_sha256 = receipt_manifest(output, receipts)
    expected_manifest = build_manifest(
        plan=plan,
        plan_sha256=plan_sha256,
        receipts=receipts,
        tools_public=attempt["toolchain"],
        receipts_sha256=receipts_sha256,
    )
    if manifest != expected_manifest:
        raise ValueError("development corpus manifest does not reconstruct")
    expected_receipt = {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-corpus-receipt-v1",
        "plan_sha256": plan_sha256,
        "manifest_sha256": sha256_file(output / "manifest.json"),
        "receipt_manifest_sha256": receipts_sha256,
        "item_count": 49,
        "generated_item_count": 31,
        "precompressed_item_count": 18,
        "axiom_wins": 0,
        "claim_ceiling": plan["claim_ceiling"],
    }
    if receipt != expected_receipt:
        raise ValueError("development corpus receipt does not reconstruct")
    return {
        "verified": True,
        "item_count": 49,
        "generated_item_count": 31,
        "precompressed_item_count": 18,
        "manifest_sha256": expected_receipt["manifest_sha256"],
        "receipt_manifest_sha256": receipts_sha256,
        "axiom_wins": 0,
        "claim_ceiling": plan["claim_ceiling"],
    }


def build(
    *,
    plan_path: Path,
    source_corpus: Path,
    tools_root: Path,
    output: Path,
    timeout_seconds: float,
) -> Path:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("precompression timeout must be positive and finite")
    PLAN_VERIFY.verify(
        config_path=PLANNER.DEFAULT_CONFIG,
        acquisition_path=PLANNER.DEFAULT_ACQUISITION,
        plan_path=plan_path,
    )
    plan = read_canonical_json(plan_path)
    plan_sha256 = sha256_file(plan_path)
    if output.exists():
        validate_corpus(output, plan_path)
        return output / "manifest.json"
    work = output.with_name(f".{output.name}.work")
    work.mkdir(parents=True, exist_ok=True)
    tools, tools_public = safe_tool_records(tools_root)
    attempt = {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-corpus-attempt-v1",
        "plan_sha256": plan_sha256,
        "repository_commit": plan["bindings"]["repository_commit"],
        "toolchain": tools_public,
        "timeout_seconds_per_precompression_operation": timeout_seconds,
        "axiom_wins": 0,
        "claim_ceiling": plan["claim_ceiling"],
    }
    attempt_path = work / "attempt.json"
    if attempt_path.exists():
        if read_canonical_json(attempt_path) != attempt:
            raise ValueError("resumed development corpus attempt differs")
    else:
        write_json_atomic(attempt_path, attempt)
    receipts = []
    for index, task in enumerate(plan["tasks"], start=1):
        print(f"[{index}/49] {task['task_id']}", flush=True)
        if task["kind"] == "generated":
            receipt = materialize_generated(
                work=work, task=task, plan_sha256=plan_sha256
            )
        elif task["kind"] == "precompressed":
            receipt = materialize_precompressed(
                work=work,
                source_corpus=source_corpus,
                task=task,
                plan_sha256=plan_sha256,
                tools=tools,
                tools_public=tools_public,
                profiles=plan["precompression_profiles"],
                timeout_seconds=timeout_seconds,
            )
        else:
            raise ValueError(f"unsupported development task kind: {task['kind']}")
        receipts.append(receipt)
    receipts_sha256 = receipt_manifest(work, receipts)
    manifest = build_manifest(
        plan=plan,
        plan_sha256=plan_sha256,
        receipts=receipts,
        tools_public=tools_public,
        receipts_sha256=receipts_sha256,
    )
    write_json_atomic(work / "manifest.json", manifest)
    receipt = {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-corpus-receipt-v1",
        "plan_sha256": plan_sha256,
        "manifest_sha256": sha256_file(work / "manifest.json"),
        "receipt_manifest_sha256": receipts_sha256,
        "item_count": 49,
        "generated_item_count": 31,
        "precompressed_item_count": 18,
        "axiom_wins": 0,
        "claim_ceiling": plan["claim_ceiling"],
    }
    write_json_atomic(work / "receipt.json", receipt)
    validate_corpus(work, plan_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    work.replace(output)
    validate_corpus(output, plan_path)
    return output / "manifest.json"


def main() -> int:
    worker = argparse.ArgumentParser(add_help=False)
    worker.add_argument("--worker-zip", nargs=2, metavar=("SOURCE", "DESTINATION"))
    worker.add_argument("--worker-unzip", nargs=2, metavar=("SOURCE", "DESTINATION"))
    worker_args, _unknown = worker.parse_known_args()
    if worker_args.worker_zip:
        zip_compress(*(Path(value) for value in worker_args.worker_zip))
        return 0
    if worker_args.worker_unzip:
        zip_decompress(*(Path(value) for value in worker_args.worker_unzip))
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--source-corpus", type=Path, default=DEFAULT_SOURCE_CORPUS)
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=43_200.0)
    args = parser.parse_args()
    try:
        result = build(
            plan_path=args.plan,
            source_corpus=args.source_corpus,
            tools_root=args.tools,
            output=args.output,
            timeout_seconds=args.timeout_seconds,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        raise SystemExit(f"incompressible/precompressed corpus build failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
