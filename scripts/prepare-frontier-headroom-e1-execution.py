#!/usr/bin/env python3
"""Create the E1 offline execution matrix after the tool barrier passes."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "frontier-headroom-e1-toolchain-v1.json"
DEFAULT_TOOL_ROOT = ROOT / ".research-tools" / "frontier-headroom-e1-v1"
DEFAULT_OUTPUT = ROOT / "runs" / "frontier-headroom-e1-execution-plan-v1.json"


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL_VERIFIER = load_script(
    "frontier_headroom_e1_tool_verifier_for_execution",
    ROOT / "scripts" / "verify-frontier-headroom-e1-toolchain.py",
)
E1_VERIFIER = load_script(
    "frontier_headroom_e1_plan_verifier_for_execution",
    ROOT / "scripts" / "verify-frontier-headroom-e1-plan.py",
)


def substitute(command: list[str], replacements: dict[str, str]) -> list[str]:
    result = []
    for argument in command:
        for source in sorted(replacements, key=len, reverse=True):
            target = replacements[source]
            argument = argument.replace(source, target)
        if any(source in argument for source in replacements):
            raise ValueError(f"unresolved command placeholder: {argument}")
        result.append(argument)
    return result


def build_plan(
    config: dict[str, Any],
    e1: dict[str, Any],
    *,
    tool_root: Path,
    config_sha256: str,
    e1_config_sha256: str,
    receipt_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    executables = {
        row["codec_id"]: str((tool_root / row["path"]).resolve())
        for row in config["executables"]
    }
    variables = {
        "$KANZI": executables["kanzi-max"],
        "$ZSTD": executables["zstd-19-long"],
        "$XZ": executables["xz-lzma2-9e"],
        "$ZPAQ": executables["zpaq-5-m510"],
        "$INPUT": "$WORK/input.bin",
        "$ARTIFACT": "$WORK/artifact.bin",
        "$RESTORED": "$WORK/restored.bin",
        "$RESTORED_DIRECTORY": "$WORK/restored",
    }
    whole = []
    samples = []
    segments = []
    for codec in e1["codecs"]:
        for item in e1["items"]:
            whole.append(
                {
                    "task_id": f"whole/{codec['id']}/{item['id']}",
                    "phase": "whole_item",
                    "codec_id": codec["id"],
                    "item_id": item["id"],
                    "category": item["category"],
                    "source_manifest": item["source"],
                    "source_bytes": item["bytes"],
                    "source_sha256": item["sha256"],
                    "compress": substitute(codec["compress"], variables),
                    "decompress": substitute(codec["decompress"], variables),
                    "status": "locked_not_executed",
                    "corpus_accessed": False,
                }
            )
            segments.append(
                {
                    "task_id": f"conditional-segments/{codec['id']}/{item['id']}",
                    "phase": "conditional_segments",
                    "codec_id": codec["id"],
                    "item_id": item["id"],
                    "category": item["category"],
                    "segment_bytes": e1["oracle_routing"]["segment_bytes"],
                    "trigger": e1["oracle_routing"]["segment_trigger"],
                    "status": "conditional_locked_not_executed",
                    "corpus_accessed": False,
                }
            )
    ceiling = next(
        row
        for row in e1["codecs"]
        if row["id"] == e1["sample_ceiling"]["selected_profile"]
    )
    for item in e1["items"]:
        samples.append(
            {
                "task_id": f"sample/{ceiling['id']}/{item['id']}",
                "phase": "stratified_sample_ceiling",
                "codec_id": ceiling["id"],
                "item_id": item["id"],
                "category": item["category"],
                "source_manifest": item["source"],
                "source_bytes": item["bytes"],
                "source_sha256": item["sha256"],
                "ranges": [
                    {"offset": offset, "length": length}
                    for offset, length in E1_VERIFIER.sample_ranges(item["bytes"])
                ],
                "axe1s_layout": e1["sample_ceiling"]["binary_layout"],
                "compress": substitute(ceiling["compress"], variables),
                "decompress": substitute(ceiling["decompress"], variables),
                "status": "locked_not_executed",
                "corpus_accessed": False,
            }
        )
    if (len(whole), len(samples), len(segments)) != (68, 17, 68):
        raise ValueError("E1 execution task counts differ")
    return {
        "schema_version": 1,
        "name": "frontier-headroom-e1-execution-plan-v1",
        "completed": True,
        "config_sha256": config_sha256,
        "e1_config_sha256": e1_config_sha256,
        "tool_receipt_sha256": receipt_sha256,
        "repository_commit": repository_commit,
        "whole_item_tasks": whole,
        "sample_tasks": samples,
        "conditional_segment_templates": segments,
        "process_policy": config["platform_lock"]["measurement_process_policy"],
        "corpus_accessed": False,
        "measurements_exist": False,
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "claim_ceiling": config["execution_plan"]["claim_ceiling"],
    }


def write_immutable(path: Path, payload: dict[str, Any]) -> None:
    encoded = TOOL_VERIFIER.json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError("refusing to replace a differing E1 execution plan")
        return
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


def prepare(config_path: Path, tool_root: Path, output: Path) -> Path:
    config = json.loads(config_path.read_bytes())
    e1 = TOOL_VERIFIER.validate_declaration(config)
    TOOL_VERIFIER.verify_tool_root(config, tool_root)
    repository_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()
    plan = build_plan(
        config,
        e1,
        tool_root=tool_root,
        config_sha256=TOOL_VERIFIER.sha256_file(config_path),
        e1_config_sha256=TOOL_VERIFIER.sha256_file(TOOL_VERIFIER.E1_CONFIG),
        receipt_sha256=TOOL_VERIFIER.sha256_file(tool_root / "receipt.json"),
        repository_commit=repository_commit,
    )
    TOOL_VERIFIER.validate_plan(plan, config, tool_root / "receipt.json")
    write_immutable(output, plan)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--tool-root", type=Path, default=DEFAULT_TOOL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = prepare(args.config, args.tool_root, args.output)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E1 execution planning failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
