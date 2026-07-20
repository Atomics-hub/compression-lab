#!/usr/bin/env python3
"""Freeze the complete text/source research-ceiling execution matrix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
FORMAL_CANDIDATES = ["zpaq-5", "paq8px-forcetext", "cmix", "nncp"]
EXECUTION_PROFILES = [
    "zpaq-5-m510",
    "paq8px-11L-local-screen",
    "paq8px-12L-absolute",
    "cmix-v21-strong-text",
    "nncp-3.3-transformer",
]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASELINE_PUBLICATION = load_script(
    "baseline_publication_for_research_ceiling_plan",
    REPOSITORY / "scripts" / "publish-text-source-baseline-census.py",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def substitute(command: list[str], **values: str) -> list[str]:
    result = []
    for argument in command:
        for name, value in values.items():
            argument = argument.replace(f"${name}", value)
        result.append(argument)
    return result


def build_profiles(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = {
        row["codec_id"]: row
        for row in config["baseline_tiers"]["research_ceiling"]
    }
    if list(candidates) != FORMAL_CANDIDATES:
        raise ValueError("research-ceiling candidate roster differs from protocol")
    zpaq = candidates["zpaq-5"]
    paq = candidates["paq8px-forcetext"]
    cmix = candidates["cmix"]
    nncp = candidates["nncp"]
    return {
        "zpaq-5-m510": {
            "codec_id": "zpaq-5",
            "formal_ceiling_eligible": True,
            "host_class": "local-macos-18-gib-rss-cap",
            "compress": [
                "zpaq",
                *zpaq["deterministic_command_policy"]["compression_arguments"],
            ],
            "decompress": [
                "zpaq",
                *zpaq["deterministic_command_policy"]["decompression_arguments"],
            ],
            "staged_input_name": zpaq["deterministic_command_policy"][
                "staged_input_name"
            ],
            "staged_input_mtime_utc": zpaq["deterministic_command_policy"][
                "staged_input_mtime_utc"
            ],
            "counted_side_asset_bytes": 0,
            "claim_label": "Formal ZPAQ method-5 ceiling row if every gate passes.",
        },
        "paq8px-11L-local-screen": {
            "codec_id": "paq8px-forcetext",
            "formal_ceiling_eligible": False,
            "host_class": "local-macos-18-gib-rss-cap",
            "compress": paq["local_resource_screen_commands"]["compress"],
            "decompress": paq["local_resource_screen_commands"]["decompress"],
            "counted_side_asset_bytes": 0,
            "claim_label": paq["local_resource_screen_commands"]["claim_label"],
        },
        "paq8px-12L-absolute": {
            "codec_id": "paq8px-forcetext",
            "formal_ceiling_eligible": True,
            "host_class": "larger-isolated-memory-host",
            "compress": paq["absolute_ceiling_commands"]["compress"],
            "decompress": paq["absolute_ceiling_commands"]["decompress"],
            "counted_side_asset_bytes": 0,
            "claim_label": "Formal paq8px absolute ceiling row if every gate passes.",
        },
        "cmix-v21-strong-text": {
            "codec_id": "cmix",
            "formal_ceiling_eligible": True,
            "host_class": "larger-isolated-memory-host-portable-o3-build",
            "compress": cmix["strong_text_commands"]["compress"],
            "decompress": cmix["strong_text_commands"]["decompress"],
            "counted_side_asset_bytes": cmix["required_decoder_assets"][0][
                "bytes"
            ],
            "counted_side_asset_sha256": cmix["required_decoder_assets"][0][
                "sha256"
            ],
            "claim_label": (
                "Formal cmix ceiling row counts english.dic once in the primary "
                "self-contained artifact total."
            ),
        },
        "nncp-3.3-transformer": {
            "codec_id": "nncp",
            "formal_ceiling_eligible": True,
            "host_class": "authorized-linux-cuda-host-plus-second-host-decode",
            "track_commands": nncp["absolute_ceiling_commands"],
            "counted_side_asset_bytes": 0,
            "claim_label": (
                "Formal NNCP ceiling row only after deterministic same-host artifacts "
                "and an exact second-host decode."
            ),
        },
    }


def build_plan(
    config: dict[str, Any],
    baseline: dict[str, Any],
    *,
    config_sha256: str,
    baseline_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    BASELINE_PUBLICATION.validate(baseline)
    profiles = build_profiles(config)
    tasks = []
    for profile_id in EXECUTION_PROFILES:
        profile = profiles[profile_id]
        for item in baseline["items"]:
            replacements = {
                "INPUT": "$WORK/input.bin",
                "PAYLOAD": "$WORK/payload.bin",
                "ARTIFACT": "$WORK/artifact.bin",
                "RESTORED": "$WORK/restored.bin",
                "ENGLISH_DICTIONARY": "$TOOLCHAIN/dictionary/english.dic",
            }
            if profile_id == "nncp-3.3-transformer":
                command_scope = (
                    "source"
                    if item["track"] == "source_code_bundles"
                    else "wikimedia"
                )
                raw_commands = profile["track_commands"][command_scope]
            else:
                command_scope = "all"
                raw_commands = profile
            counted_side_asset_bytes = profile["counted_side_asset_bytes"]
            tasks.append(
                {
                    "task_id": f"{profile_id}/{item['id']}",
                    "profile_id": profile_id,
                    "codec_id": profile["codec_id"],
                    "formal_ceiling_eligible": profile["formal_ceiling_eligible"],
                    "host_class": profile["host_class"],
                    "item_id": item["id"],
                    "track": item["track"],
                    "source_bytes": item["source_bytes"],
                    "source_sha256": item["source_sha256"],
                    "command_scope": command_scope,
                    "compression_command": substitute(
                        raw_commands["compress"], **replacements
                    ),
                    "decompression_command": substitute(
                        raw_commands["decompress"], **replacements
                    ),
                    "counted_side_asset_bytes": counted_side_asset_bytes,
                    "counted_side_asset_sha256": profile.get(
                        "counted_side_asset_sha256"
                    ),
                    "staged_input_name": profile.get("staged_input_name"),
                    "staged_input_mtime_utc": profile.get(
                        "staged_input_mtime_utc"
                    ),
                    "second_host_decode_required": profile_id
                    == "nncp-3.3-transformer",
                    "complete_artifact_accounting": (
                        "payload bytes plus counted_side_asset_bytes; no other decoder "
                        "asset, model, dictionary, or preprocessing state is admitted"
                    ),
                    "claim_label": profile["claim_label"],
                    "execution_status": "pending_toolchain_host_and_measurement",
                    "axiom_outcome": "untested",
                }
            )
    if len(tasks) != 35 or len({task["task_id"] for task in tasks}) != 35:
        raise ValueError("research-ceiling execution matrix is incomplete")
    practical_leaders = {
        track: row["leader"]["codec_id"]
        for track, row in baseline["summary"]["tracks"].items()
    }
    return {
        "schema_version": 1,
        "name": "text-source-research-ceiling-execution-plan-v1",
        "completed": True,
        "bindings": {
            "repository_commit": repository_commit,
            "config_sha256": config_sha256,
            "baseline_results_sha256": baseline_sha256,
            "corpus_manifest_sha256": baseline["bindings"]["manifest_sha256"],
        },
        "formal_candidate_roster": FORMAL_CANDIDATES,
        "candidate_identities": config["baseline_tiers"]["research_ceiling"],
        "execution_profile_roster": EXECUTION_PROFILES,
        "practical_leaders_at_plan_time": practical_leaders,
        "measurement_policy": {
            "warmups": 1,
            "measured_repetitions": 2,
            "exact_roundtrip_required": True,
            "byte_identical_measured_artifacts_required": True,
            "one_codec_thread_except_declared_gpu_intrinsic_parallelism": True,
            "local_peak_rss_cap_gib": config["research_budget"][
                "maximum_local_peak_rss_gib"
            ],
            "maximum_wall_hours_per_family_per_codec": config["research_budget"][
                "maximum_wall_hours_per_family_per_codec"
            ],
            "unavailable_timeout_or_unsafe_resource_is_not_an_axiom_win": True,
        },
        "tasks": tasks,
        "formal_completion_rule": (
            "All 28 formal tasks must complete exact deterministic measurements on "
            "their declared host classes. The seven paq8px-11L local-screen tasks are "
            "context only and never substitute for paq8px-12L."
        ),
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "claim_ceiling": (
            "Predeclared development execution plan only. Pending, unavailable, unsafe, "
            "timed-out, failed, or resource-reduced rows are not Axiom wins and cannot "
            "support a strongest-ratio, world-best, or state-of-the-art claim."
        ),
    }


def write_immutable(path: Path, payload: dict[str, Any]) -> Path:
    encoded = json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError("refusing to replace differing research-ceiling plan")
        return path
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
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        config_raw = args.config.read_bytes()
        config = json.loads(config_raw)
        baseline_raw = args.baseline.read_bytes()
        baseline = json.loads(baseline_raw)
        BASELINE_PUBLICATION.validate_trial_receipts(args.baseline, baseline)
        repository_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        plan = build_plan(
            config,
            baseline,
            config_sha256=sha256_bytes(config_raw),
            baseline_sha256=sha256_bytes(baseline_raw),
            repository_commit=repository_commit,
        )
        output = write_immutable(args.output, plan)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"research-ceiling plan refused: {error}") from error
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
