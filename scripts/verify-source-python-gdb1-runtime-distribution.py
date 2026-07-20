#!/usr/bin/env python3
"""Verify GDB1 standalone runtime accounting and optional source artifacts."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
from types import ModuleType
from typing import Any
from urllib.parse import urlparse
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    REPOSITORY / "config" / "source-python-gdb1-runtime-distribution-v1.json"
)
DEFAULT_CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
DEFAULT_DEPENDENCY_LOCK = (
    REPOSITORY / "config" / "source-python-gdb1-dependency-lock-v1.json"
)
EXPECTED_CONTRACT_SHA256 = (
    "c1c3e9ff49603433a72463626bbeccc394c95def1873359fc7ec6341a65c024e"
)


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


INVENTORY = load_script(
    "gdb1_runtime_inventory_for_verifier",
    REPOSITORY / "scripts" / "inventory-source-python-gdb1-runtime.py",
)
DEPENDENCIES = load_script(
    "gdb1_dependency_lock_for_runtime_verifier",
    REPOSITORY / "scripts" / "verify-source-python-gdb1-dependency-lock.py",
)


def https_host(url: object, host: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == host
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and not parsed.fragment
    )


def inventory_path(contract_path: Path, target: dict[str, Any]) -> Path:
    return contract_path.parent / target["inventory"]["filename"]


def wheel_native_inventory(
    root: Path,
    dependency: dict[str, Any],
    target_id: str,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for _package, artifact in DEPENDENCIES.artifact_rows(dependency):
        if artifact["target_id"] != target_id:
            continue
        path = root / artifact["filename"]
        with zipfile.ZipFile(path) as wheel:
            for member in wheel.namelist():
                value = wheel.read(member)
                native = INVENTORY.native_dependencies(value)
                if native is None:
                    if member.endswith((".so", ".dylib")):
                        raise ValueError("wheel native-extension identity differs")
                    continue
                records.append(
                    {
                        "bytes": len(value),
                        "dependencies": native[1],
                        "format": native[0],
                        "path": member,
                        "sha256": INVENTORY.sha256_bytes(value),
                        "wheel": artifact["filename"],
                    }
                )
    records.sort(key=lambda row: (row["wheel"].encode(), row["path"].encode()))
    return {
        "manifest_sha256": INVENTORY.digest_records(records),
        "native_bytes": sum(row["bytes"] for row in records),
        "object_count": len(records),
        "records": records,
    }


def validate_source_archive(path: Path, source: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CPython source archive must be an ordinary file")
    raw = path.read_bytes()
    if (
        len(raw) != source["size_bytes"]
        or INVENTORY.sha256_bytes(raw) != source["sha256"]
    ):
        raise ValueError("CPython source archive size or SHA-256 differs")
    observed: set[str] = set()
    license_value: bytes | None = None
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
            for member in archive:
                path_value = PurePosixPath(member.name)
                if (
                    path_value.is_absolute()
                    or ".." in path_value.parts
                    or "\\" in member.name
                    or not path_value.parts
                    or path_value.parts[0] != "Python-3.12.12"
                    or member.name in observed
                ):
                    raise ValueError("CPython source archive member is unsafe")
                observed.add(member.name)
                if not (member.isfile() or member.isdir()):
                    raise ValueError("CPython source archive member type is unsafe")
                if member.name == source["license_member"]:
                    if not member.isfile():
                        raise ValueError("CPython source license is not a file")
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError("CPython source license is not a file")
                    license_value = extracted.read(member.size + 1)
    except tarfile.TarError as error:
        raise ValueError("CPython source archive is invalid") from error
    if (
        license_value is None
        or INVENTORY.sha256_bytes(license_value) != source["license_sha256"]
    ):
        raise ValueError("CPython source license differs")


def validate_contract(
    contract_path: Path,
    contract: dict[str, Any],
    config_raw: bytes,
    dependency_raw: bytes,
    dependency: dict[str, Any],
) -> None:
    if (
        set(contract)
        != {
            "accounting",
            "bindings",
            "builder",
            "claim_ceiling",
            "created_before_corpus_access",
            "measurement_authorized",
            "name",
            "python_source",
            "schema_version",
            "targets",
        }
        or contract.get("schema_version") != 1
        or contract.get("name") != "source-python-gdb1-runtime-distribution-v1"
        or contract.get("created_before_corpus_access") is not True
        or contract.get("measurement_authorized") is not False
        or contract.get("bindings")
        != {
            "dependency_lock_sha256": INVENTORY.sha256_bytes(dependency_raw),
            "gdb1_protocol_config_sha256": INVENTORY.sha256_bytes(config_raw),
        }
    ):
        raise ValueError("runtime contract identity, access state, or binding differs")
    accounting = contract.get("accounting", {})
    if (
        accounting.get("primary_mode") != "standalone"
        or "can never satisfy G0, G1, product, or strongest-ratio gates"
        not in accounting.get("installed_library_secondary_view", "")
        or "Nothing is amortized away" not in accounting.get("primary_rule", "")
        or accounting.get("required_result_components")
        != json.loads(config_raw)["accounting"]["complete_bundle_components"]
        or "separately frozen self-contained distribution identity"
        not in accounting.get("symmetric_baseline_rule", "")
    ):
        raise ValueError("runtime standalone or symmetric accounting rule differs")
    builder = contract.get("builder", {})
    if (
        builder.get("project") != "astral-sh/python-build-standalone"
        or builder.get("release_tag") != "20251028"
        or builder.get("license_spdx") != "MPL-2.0"
        or not https_host(builder.get("release_api_url"), "api.github.com")
        or not https_host(builder.get("source_url"), "github.com")
        or not https_host(builder.get("license_url"), "github.com")
    ):
        raise ValueError("runtime builder identity differs")
    source = contract.get("python_source", {})
    if (
        source.get("version") != "3.12.12"
        or source.get("filename") != "Python-3.12.12.tar.xz"
        or source.get("license_spdx") != "PSF-2.0"
        or not https_host(source.get("source_url"), "www.python.org")
        or type(source.get("size_bytes")) is not int
        or source["size_bytes"] <= 0
        or not DEPENDENCIES.is_sha256(source.get("sha256"))
        or not DEPENDENCIES.is_sha256(source.get("license_sha256"))
    ):
        raise ValueError("CPython source identity differs")
    targets = contract.get("targets")
    if not isinstance(targets, list) or [row.get("target_id") for row in targets] != [
        "cpython-3.12.12-macos-arm64",
        "cpython-3.12.12-linux-x86_64",
    ]:
        raise ValueError("runtime target roster differs")
    wheels_by_target: dict[str, int] = {
        target["id"]: sum(
            artifact["size_bytes"]
            for _package, artifact in DEPENDENCIES.artifact_rows(dependency)
            if artifact["target_id"] == target["id"]
        )
        for target in dependency["targets"]
    }
    inventory_names: set[str] = set()
    archive_names: set[str] = set()
    for target in targets:
        archive = target.get("archive", {})
        inventory_binding = target.get("inventory", {})
        if (
            not isinstance(archive.get("filename"), str)
            or Path(archive["filename"]).name != archive["filename"]
            or archive["filename"] in archive_names
            or not archive["filename"].endswith("install_only_stripped.tar.gz")
            or not https_host(archive.get("release_asset_url"), "github.com")
            or type(archive.get("size_bytes")) is not int
            or archive["size_bytes"] <= 0
            or not DEPENDENCIES.is_sha256(archive.get("sha256"))
            or not isinstance(archive.get("updated_at"), str)
            or not archive["updated_at"].endswith("Z")
        ):
            raise ValueError("runtime release artifact identity differs")
        archive_names.add(archive["filename"])
        if (
            target.get("runtime_archive_bytes") != archive["size_bytes"]
            or target.get("package_wheel_bytes")
            != wheels_by_target[target["target_id"]]
            or target.get("base_distribution_bytes")
            != target["runtime_archive_bytes"] + target["package_wheel_bytes"]
        ):
            raise ValueError("runtime complete distribution arithmetic differs")
        if (
            not isinstance(inventory_binding.get("filename"), str)
            or Path(inventory_binding["filename"]).name
            != inventory_binding["filename"]
            or inventory_binding["filename"] in inventory_names
            or any(
                not DEPENDENCIES.is_sha256(inventory_binding.get(field))
                for field in (
                    "sha256",
                    "inventory_manifest_sha256",
                    "license_manifest_sha256",
                    "native_manifest_sha256",
                    "stdlib_manifest_sha256",
                )
            )
        ):
            raise ValueError("runtime inventory binding differs")
        inventory_names.add(inventory_binding["filename"])
        package_native = target.get("package_native", {})
        records = package_native.get("records")
        target_wheels = {
            artifact["filename"]
            for _package, artifact in DEPENDENCIES.artifact_rows(dependency)
            if artifact["target_id"] == target["target_id"]
        }
        if (
            not isinstance(records, list)
            or package_native.get("object_count") != len(records)
            or package_native.get("native_bytes")
            != sum(row.get("bytes", -1) for row in records if isinstance(row, dict))
            or package_native.get("manifest_sha256")
            != INVENTORY.digest_records(records)
        ):
            raise ValueError("runtime package-native accounting differs")
        for record in records:
            if (
                not isinstance(record, dict)
                or set(record)
                != {
                    "bytes",
                    "dependencies",
                    "format",
                    "path",
                    "sha256",
                    "wheel",
                }
                or record.get("wheel") not in target_wheels
                or type(record.get("bytes")) is not int
                or record["bytes"] <= 0
                or not DEPENDENCIES.is_sha256(record.get("sha256"))
                or record.get("format") not in {"mach-o-64-little", "elf-64-little"}
                or not isinstance(record.get("path"), str)
                or PurePosixPath(record["path"]).is_absolute()
                or ".." in PurePosixPath(record["path"]).parts
                or not record["path"].endswith((".so", ".dylib"))
                or not isinstance(record.get("dependencies"), list)
                or any(
                    not isinstance(dependency_name, str) or not dependency_name
                    for dependency_name in record.get("dependencies", [])
                )
                or record["dependencies"] != sorted(set(record["dependencies"]))
            ):
                raise ValueError("runtime package-native record differs")
        inventory_raw, inventory = INVENTORY.read_canonical(
            inventory_path(contract_path, target)
        )
        if (
            INVENTORY.sha256_bytes(inventory_raw) != inventory_binding["sha256"]
            or inventory.get("target_id") != target["target_id"]
            or inventory.get("archive")
            != {
                "filename": archive["filename"],
                "sha256": archive["sha256"],
                "size_bytes": archive["size_bytes"],
            }
            or inventory.get("inventory", {}).get("manifest_sha256")
            != inventory_binding["inventory_manifest_sha256"]
            or inventory.get("licenses", {}).get("manifest_sha256")
            != inventory_binding["license_manifest_sha256"]
            or inventory.get("native", {}).get("manifest_sha256")
            != inventory_binding["native_manifest_sha256"]
            or inventory.get("stdlib", {}).get("manifest_sha256")
            != inventory_binding["stdlib_manifest_sha256"]
        ):
            raise ValueError("runtime inventory evidence differs")
        inventory_dependencies = inventory.get("external_system_dependencies")
        if (
            not isinstance(inventory_dependencies, list)
            or any(
                not isinstance(dependency_name, str) or not dependency_name
                for dependency_name in inventory_dependencies
            )
            or inventory_dependencies != sorted(set(inventory_dependencies))
        ):
            raise ValueError("runtime inventory dependency closure differs")
        combined_dependencies = sorted(
            set(inventory_dependencies)
            | {
                dependency_name
                for record in records
                for dependency_name in record["dependencies"]
            }
        )
        target_dependencies = target.get("external_system_dependencies")
        if (
            not isinstance(target_dependencies, list)
            or any(
                not isinstance(dependency_name, str) or not dependency_name
                for dependency_name in target_dependencies
            )
            or target_dependencies != sorted(set(target_dependencies))
            or combined_dependencies != target_dependencies
        ):
            raise ValueError("runtime external-system dependency closure differs")


def verify(
    contract_path: Path = DEFAULT_CONTRACT,
    config_path: Path = DEFAULT_CONFIG,
    dependency_lock_path: Path = DEFAULT_DEPENDENCY_LOCK,
    artifact_dir: Path | None = None,
    dependency_artifact_dir: Path | None = None,
) -> dict[str, Any]:
    config_raw, _config = INVENTORY.read_canonical(config_path)
    dependency_raw, dependency = INVENTORY.read_canonical(dependency_lock_path)
    DEPENDENCIES.verify(dependency_lock_path, config_path)
    contract_raw, contract = INVENTORY.read_canonical(contract_path)
    if INVENTORY.sha256_bytes(contract_raw) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("runtime contract differs from the frozen trust anchor")
    validate_contract(
        contract_path,
        contract,
        config_raw,
        dependency_raw,
        dependency,
    )
    runtime_artifacts_verified = artifact_dir is not None
    if artifact_dir is not None:
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise ValueError("runtime artifact cache must be an ordinary directory")
        expected = {contract["python_source"]["filename"]} | {
            target["archive"]["filename"] for target in contract["targets"]
        }
        observed = {path.name for path in artifact_dir.iterdir()}
        if observed != expected:
            raise ValueError("runtime artifact cache roster differs")
        validate_source_archive(
            artifact_dir / contract["python_source"]["filename"],
            contract["python_source"],
        )
        for target in contract["targets"]:
            archive = target["archive"]
            recomputed = INVENTORY.inventory(
                artifact_dir / archive["filename"],
                target_id=target["target_id"],
                expected_size=archive["size_bytes"],
                expected_sha256=archive["sha256"],
            )
            _inventory_raw, checked_in = INVENTORY.read_canonical(
                inventory_path(contract_path, target)
            )
            if recomputed != checked_in:
                raise ValueError("runtime archive differs from checked-in inventory")
    dependency_artifacts_verified = dependency_artifact_dir is not None
    if dependency_artifact_dir is not None:
        DEPENDENCIES.verify(
            dependency_lock_path,
            config_path,
            dependency_artifact_dir,
        )
        for target in contract["targets"]:
            recomputed_native = wheel_native_inventory(
                dependency_artifact_dir,
                dependency,
                target["target_id"],
            )
            if recomputed_native != target["package_native"]:
                raise ValueError("wheel native inventory differs from runtime contract")
    return {
        "verified": True,
        "artifacts_verified": (
            runtime_artifacts_verified and dependency_artifacts_verified
        ),
        "dependency_artifacts_verified": dependency_artifacts_verified,
        "runtime_artifacts_verified": runtime_artifacts_verified,
        "contract_sha256": INVENTORY.sha256_bytes(contract_raw),
        "dependency_lock_sha256": INVENTORY.sha256_bytes(dependency_raw),
        "measurement_authorized": False,
        "mode": contract["accounting"]["primary_mode"],
        "targets": {
            target["target_id"]: {
                "base_distribution_bytes": target["base_distribution_bytes"],
                "inventory_sha256": target["inventory"]["sha256"],
            }
            for target in contract["targets"]
        },
        "claim_ceiling": contract["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--dependency-lock", type=Path, default=DEFAULT_DEPENDENCY_LOCK
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--dependency-artifact-dir", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            args.contract,
            args.config,
            args.dependency_lock,
            args.artifact_dir,
            args.dependency_artifact_dir,
        )
    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"GDB1 runtime verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
