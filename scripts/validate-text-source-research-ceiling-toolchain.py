#!/usr/bin/env python3
"""Validate one host-scoped research-ceiling toolchain receipt and its files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
PROFILE_CODEC = {
    "zpaq-5-m510": "zpaq-5",
    "paq8px-11L-local-screen": "paq8px-forcetext",
    "paq8px-12L-absolute": "paq8px-forcetext",
    "cmix-v21-strong-text": "cmix",
    "nncp-3.3-transformer": "nncp",
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load_script(
    "research_ceiling_planner_for_toolchain",
    REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PLANNER.json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def safe_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("toolchain path must be a nonempty relative path")
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"toolchain file is missing or non-ordinary: {relative}")
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"toolchain path escapes root: {relative}") from error
    return candidate


def expected_source_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "version": candidate["version"],
        "official_source": candidate["official_source"],
        "license": candidate["license"],
    }
    for key in (
        "source_archive_url",
        "source_archive_bytes",
        "source_archive_sha256",
        "tag_commit",
    ):
        if key in candidate:
            identity[key] = candidate[key]
    return identity


def expected_runtime_assets(
    profile_id: str, candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    if profile_id == "cmix-v21-strong-text":
        return [
            {
                "path": candidate["required_decoder_assets"][0]["path"],
                "bytes": candidate["required_decoder_assets"][0]["bytes"],
                "sha256": candidate["required_decoder_assets"][0]["sha256"],
            }
        ]
    if profile_id == "nncp-3.3-transformer":
        runtime = candidate["bundled_runtime_identity"]
        return [
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in (runtime["cpu_library"], runtime["cuda_library"])
        ]
    return []


def expected_build_commands(candidate: dict[str, Any]) -> list[list[str]]:
    commands = candidate.get("build_policy", {}).get("commands")
    if (
        not isinstance(commands, list)
        or not commands
        or any(
            not isinstance(command, list)
            or not command
            or any(not isinstance(argument, str) or not argument for argument in command)
            for command in commands
        )
    ):
        raise ValueError("candidate build policy is invalid")
    return commands


def validate_binary_record(
    record: object, tools_root: Path, *, executable: bool = False
) -> None:
    if (
        not isinstance(record, dict)
        or set(record) != {"path", "bytes", "sha256"}
        or type(record.get("bytes")) is not int
        or record["bytes"] <= 0
        or not PLANNER.BASELINE_PUBLICATION.is_lower_hex(record.get("sha256"), 64)
    ):
        raise ValueError("toolchain binary record is invalid")
    path = safe_file(tools_root, record["path"])
    if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
        raise ValueError(f"toolchain file identity differs: {record['path']}")
    if executable and not os.access(path, os.X_OK):
        raise ValueError(f"toolchain executable is not runnable: {record['path']}")


def validate(
    plan_path: Path, receipt_path: Path, tools_root: Path
) -> dict[str, Any]:
    if tools_root.is_symlink() or not tools_root.is_dir():
        raise ValueError("toolchain root must be an ordinary directory")
    plan = read_canonical_json(plan_path)
    receipt = read_canonical_json(receipt_path)
    if (
        plan.get("name") != "text-source-research-ceiling-execution-plan-v1"
        or len(plan.get("tasks", [])) != 35
    ):
        raise ValueError("research-ceiling plan identity is invalid")
    expected_receipt_keys = {
        "schema_version",
        "name",
        "plan_sha256",
        "host",
        "profiles",
        "claim_ceiling",
    }
    if (
        set(receipt) != expected_receipt_keys
        or type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or receipt.get("name") != "text-source-research-ceiling-toolchain-v1"
        or receipt.get("plan_sha256") != sha256_file(plan_path)
        or receipt.get("claim_ceiling")
        != "Toolchain availability is not a compression result or an Axiom win."
    ):
        raise ValueError("toolchain receipt identity is invalid")
    host = receipt.get("host")
    if (
        not isinstance(host, dict)
        or set(host)
        != {
            "host_id",
            "host_class",
            "platform",
            "machine",
            "cpu",
            "logical_cpus",
            "memory_bytes",
            "gpu",
            "cuda",
        }
        or not all(
            isinstance(host.get(key), str) and 0 < len(host[key]) <= 4096
            for key in ("host_id", "host_class", "platform", "machine", "cpu")
        )
        or type(host.get("logical_cpus")) is not int
        or host["logical_cpus"] <= 0
        or type(host.get("memory_bytes")) is not int
        or host["memory_bytes"] <= 0
        or (
            host.get("gpu") is not None
            and (
                not isinstance(host["gpu"], str)
                or not host["gpu"]
                or len(host["gpu"]) > 4096
            )
        )
        or (
            host.get("cuda") is not None
            and (
                not isinstance(host["cuda"], str)
                or not host["cuda"]
                or len(host["cuda"]) > 4096
            )
        )
    ):
        raise ValueError("toolchain host identity is invalid")
    local_cap_bytes = int(
        plan["measurement_policy"]["local_peak_rss_cap_gib"] * 1024**3
    )
    if host["host_class"] == "local-macos-18-gib-rss-cap" and (
        host["memory_bytes"] <= local_cap_bytes
        or host["gpu"] is not None
        or host["cuda"] is not None
    ):
        raise ValueError("local host does not have valid memory or accelerator identity")
    if host["host_class"] in {
        "larger-isolated-memory-host",
        "larger-isolated-memory-host-portable-o3-build",
    } and host["memory_bytes"] < 32 * 1024**3:
        raise ValueError("larger-memory host reports less than 32 GiB")
    host_profiles = {
        row["profile_id"]
        for row in plan["tasks"]
        if row["host_class"] == host["host_class"]
    }
    expected_profiles = [
        profile_id
        for profile_id in plan["execution_profile_roster"]
        if profile_id in host_profiles
    ]
    profiles = receipt.get("profiles")
    if (
        not isinstance(profiles, list)
        or [row.get("profile_id") for row in profiles] != expected_profiles
    ):
        raise ValueError("toolchain profile roster differs from host-class plan")
    candidates = {row["codec_id"]: row for row in plan["candidate_identities"]}
    available = 0
    unavailable = 0
    for row in profiles:
        profile_id = row["profile_id"]
        codec_id = PROFILE_CODEC[profile_id]
        source_identity = expected_source_identity(candidates[codec_id])
        common = {
            "profile_id": profile_id,
            "codec_id": codec_id,
            "status": row.get("status"),
            "axiom_outcome": "untested",
            "source_identity": source_identity,
        }
        if any(row.get(key) != value for key, value in common.items()):
            raise ValueError(f"toolchain profile identity differs: {profile_id}")
        if row["status"] == "unavailable":
            if set(row) != set(common) | {"reason"} or not isinstance(
                row.get("reason"), str
            ) or not row["reason"] or len(row["reason"]) > 4096:
                raise ValueError(f"unavailable profile record is invalid: {profile_id}")
            unavailable += 1
            continue
        if row["status"] != "available":
            raise ValueError(f"toolchain profile status is invalid: {profile_id}")
        if (
            set(row)
            != set(common)
            | {"executable", "runtime_assets", "build_commands", "compiler"}
            or row.get("build_commands") != expected_build_commands(
                candidates[codec_id]
            )
            or not isinstance(row.get("compiler"), str)
            or not row["compiler"]
            or len(row["compiler"]) > 16384
        ):
            raise ValueError(f"available profile record is invalid: {profile_id}")
        validate_binary_record(row["executable"], tools_root, executable=True)
        expected_assets = expected_runtime_assets(profile_id, candidates[codec_id])
        if row.get("runtime_assets") != expected_assets:
            raise ValueError(f"toolchain runtime asset roster differs: {profile_id}")
        for asset in row["runtime_assets"]:
            validate_binary_record(asset, tools_root)
        if profile_id == "nncp-3.3-transformer" and (
            not host.get("gpu") or not host.get("cuda")
        ):
            raise ValueError("NNCP availability requires GPU and CUDA identity")
        available += 1
    return {
        "verified": True,
        "host_id": host["host_id"],
        "host_class": host["host_class"],
        "available_profiles": available,
        "unavailable_profiles": unavailable,
        "axiom_wins": 0,
        "plan_sha256": receipt["plan_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--tools-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.plan, args.receipt, args.tools_root)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"research-ceiling toolchain validation failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
