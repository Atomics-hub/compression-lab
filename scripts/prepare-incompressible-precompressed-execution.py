#!/usr/bin/env python3
"""Freeze the incompressible/precompressed development execution matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "incompressible-precompressed-gates-v1.json"
DEFAULT_ACQUISITION = REPOSITORY / "runs" / "text-source-development-acquisition-v1.json"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "incompressible-precompressed-development-plan-v1.json"
DOMAIN = "compression-lab/incompressible-development/v1"
GENERATED_BLOCK_BYTES = 1024 * 1024
EXPECTED_FAMILIES = [
    "shake256-uniform",
    "deceptive-region-order",
    "magic-spoofed-random",
    "licensed-precompressed-source",
    "licensed-precompressed-wikimedia",
]
EXPECTED_PRECOMPRESSION = [
    "gzip-9",
    "bzip2-9",
    "zstd-19",
    "brotli-11",
    "xz-lzma2-9e",
    "zip-deflate-9",
]
EXTENSIONS = {
    "gzip-9": ".gz",
    "bzip2-9": ".bz2",
    "zstd-19": ".zst",
    "brotli-11": ".br",
    "xz-lzma2-9e": ".xz",
    "zip-deflate-9": ".zip",
}


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


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
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def family_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    families = config.get("development_families")
    if (
        config.get("name") != "incompressible-precompressed-product-gates-v1"
        or type(config.get("schema_version")) is not int
        or config["schema_version"] != 1
        or not isinstance(families, list)
        or [row.get("family_id") for row in families] != EXPECTED_FAMILIES
    ):
        raise ValueError("incompressible/precompressed config identity is invalid")
    profiles = config.get("precompression_profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(EXPECTED_PRECOMPRESSION):
        raise ValueError("precompression profile roster differs from protocol")
    return {row["family_id"]: row for row in families}


def generated_tasks(families: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    shake = families["shake256-uniform"]
    for size in shake["sizes_bytes"]:
        item_id = f"shake256-{size}"
        tasks.append(
            {
                "task_id": item_id,
                "family_id": shake["family_id"],
                "kind": "generated",
                "item_id": item_id,
                "output_filename": f"{item_id}.bin",
                "planned_bytes": size,
                "license": shake["license"],
                "generation": {
                    "algorithm": "counter-mode-shake256-v1",
                    "domain": DOMAIN,
                    "item_id": item_id,
                    "block_bytes": GENERATED_BLOCK_BYTES,
                    "counter_encoding": "uint64 little-endian",
                },
                "execution_status": "pending_generation",
                "axiom_outcome": "untested",
            }
        )
    deceptive = families["deceptive-region-order"]
    if deceptive["sizes_bytes"] != [64 * 1024**2]:
        raise ValueError("deceptive family size differs from protocol")
    for layout in deceptive["layouts"]:
        item_id = f"deceptive-{layout}"
        tasks.append(
            {
                "task_id": item_id,
                "family_id": deceptive["family_id"],
                "kind": "generated",
                "item_id": item_id,
                "output_filename": f"{item_id}.bin",
                "planned_bytes": deceptive["sizes_bytes"][0],
                "license": deceptive["license"],
                "generation": {
                    "algorithm": "deceptive-region-order-v1",
                    "domain": DOMAIN,
                    "layout": layout,
                    "region_bytes": GENERATED_BLOCK_BYTES,
                },
                "execution_status": "pending_generation",
                "axiom_outcome": "untested",
            }
        )
    spoofed = families["magic-spoofed-random"]
    for format_id, prefix_hex in spoofed["magic_prefixes_hex"].items():
        for size in spoofed["sizes_bytes"]:
            item_id = f"magic-spoof-{format_id}-{size}"
            tasks.append(
                {
                    "task_id": item_id,
                    "family_id": spoofed["family_id"],
                    "kind": "generated",
                    "item_id": item_id,
                    "output_filename": f"{item_id}.bin",
                    "planned_bytes": size,
                    "license": spoofed["license"],
                    "generation": {
                        "algorithm": "magic-spoofed-counter-mode-shake256-v1",
                        "domain": DOMAIN,
                        "item_id": item_id,
                        "block_bytes": GENERATED_BLOCK_BYTES,
                        "magic_id": format_id,
                        "magic_prefix_hex": prefix_hex,
                    },
                    "execution_status": "pending_generation",
                    "axiom_outcome": "untested",
                }
            )
    return tasks


def precompression_tasks(
    families: dict[str, dict[str, Any]], source_manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    sources = {row["source_id"]: row for row in source_manifest["items"]}
    tasks = []
    for family_id in (
        "licensed-precompressed-source",
        "licensed-precompressed-wikimedia",
    ):
        family = families[family_id]
        if family["precompression_codecs"] != EXPECTED_PRECOMPRESSION:
            raise ValueError(f"precompression codec order differs: {family_id}")
        for source_id in family["source_ids"]:
            if source_id not in sources:
                raise ValueError(f"planned source is absent from manifest: {source_id}")
            source = sources[source_id]
            for profile_id in EXPECTED_PRECOMPRESSION:
                item_id = f"precompressed-{source_id}-{profile_id}"
                tasks.append(
                    {
                        "task_id": item_id,
                        "family_id": family_id,
                        "kind": "precompressed",
                        "item_id": item_id,
                        "output_filename": item_id + EXTENSIONS[profile_id],
                        "license": family["license"],
                        "source": {
                            "source_id": source_id,
                            "bundle_path": source["bundle_path"],
                            "bundle_size_bytes": source["bundle_size_bytes"],
                            "bundle_sha256": source["bundle_sha256"],
                            "format": source["format"],
                        },
                        "precompression_profile_id": profile_id,
                        "execution_status": "pending_precompression_and_roundtrip",
                        "axiom_outcome": "untested",
                    }
                )
    return tasks


def build_plan(
    config: dict[str, Any],
    acquisition: dict[str, Any],
    *,
    config_sha256: str,
    acquisition_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    families = family_map(config)
    if acquisition.get("aggregate_manifest_sha256") != families[
        "licensed-precompressed-source"
    ]["source_aggregate_manifest_sha256"] or acquisition.get(
        "aggregate_manifest_sha256"
    ) != families[
        "licensed-precompressed-wikimedia"
    ][
        "source_aggregate_manifest_sha256"
    ]:
        raise ValueError("licensed source acquisition binding differs from protocol")
    if (
        acquisition.get("name") != "text-source-development-acquisition-v1"
        or acquisition.get("passed") is not True
        or acquisition.get("public_validation_accessed") is not False
        or acquisition.get("item_count") != 7
        or len(acquisition.get("items", [])) != 7
    ):
        raise ValueError("licensed source acquisition identity is invalid")
    tasks = generated_tasks(families) + precompression_tasks(families, acquisition)
    if len(tasks) != 49 or len({row["task_id"] for row in tasks}) != 49:
        raise ValueError("development execution matrix must contain 49 unique tasks")
    return {
        "schema_version": 1,
        "name": "incompressible-precompressed-development-execution-plan-v1",
        "completed": True,
        "bindings": {
            "repository_commit": repository_commit,
            "config_sha256": config_sha256,
            "licensed_acquisition_sha256": acquisition_sha256,
            "licensed_aggregate_manifest_sha256": acquisition[
                "aggregate_manifest_sha256"
            ],
        },
        "generation_policy": {
            "domain": DOMAIN,
            "block_bytes": GENERATED_BLOCK_BYTES,
            "generated_license": "CC0-1.0",
            "ordinary_files_only": True,
        },
        "precompression_profiles": config["precompression_profiles"],
        "task_count": len(tasks),
        "tasks": tasks,
        "execution_order": (
            "Generate and byte-verify all 31 CC0 items first; then precompress and "
            "exactly restore all 18 licensed derivative items with pinned tools. "
            "Promote only one complete atomic corpus with a canonical manifest."
        ),
        "development_corpus_status": "planned_not_constructed",
        "public_validation_status": "unopened and unselected",
        "private_holdout_status": "inaccessible and unselected",
        "axiom_wins": 0,
        "claim_ceiling": config["claim_ceiling"],
    }


def write_immutable(path: Path, payload: dict[str, Any]) -> Path:
    encoded = json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError("refusing to replace a differing development plan")
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


def repository_state() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return commit, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--acquisition", type=Path, default=DEFAULT_ACQUISITION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        config = read_canonical_json(args.config)
        acquisition = read_canonical_json(args.acquisition)
        commit, status = repository_state()
        if status:
            raise ValueError("development plan requires a completely clean repository")
        plan = build_plan(
            config,
            acquisition,
            config_sha256=sha256_file(args.config),
            acquisition_sha256=sha256_file(args.acquisition),
            repository_commit=commit,
        )
        result = write_immutable(args.output, plan)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"incompressible/precompressed plan refused: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
