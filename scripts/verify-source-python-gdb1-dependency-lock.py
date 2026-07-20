#!/usr/bin/env python3
"""Verify the frozen GDB1 PyPI dependency lock and optionally its wheel cache."""

from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any
from urllib.parse import urlparse
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPOSITORY / "config" / "source-python-gdb1-dependency-lock-v1.json"
DEFAULT_CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
HEX = frozenset("0123456789abcdef")
EXPECTED_LOCK_SHA256 = (
    "d31eda5ed923263a7a76f5a3d85cbf35a9e26b78bd3f8cdd7f627863e9f65108"
)
TARGETS = [
    {
        "abi": "cp312",
        "architecture": "arm64",
        "id": "cpython-3.12.12-macos-arm64",
        "implementation": "CPython",
        "platform": "macosx_11_0_arm64",
        "python_version": "3.12.12",
        "role": "local development and exactness",
    },
    {
        "abi": "cp312",
        "architecture": "x86_64",
        "id": "cpython-3.12.12-linux-x86_64",
        "implementation": "CPython",
        "platform": "manylinux_2_28_x86_64",
        "python_version": "3.12.12",
        "role": "hosted development measurement",
    },
]


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path.name} must be an ordinary file")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"{path.name} is not canonical JSON")
    return raw, value


def safe_https_host(url: object, host: str) -> bool:
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


def artifact_rows(lock: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (package, artifact)
        for package in lock["packages"]
        for artifact in package["artifacts"]
    ]


def validate_lock(lock: dict[str, Any], config_raw: bytes) -> None:
    if (
        set(lock)
        != {
            "acquisition",
            "claim_ceiling",
            "created_before_corpus_access",
            "name",
            "packages",
            "protocol_config_sha256",
            "resolution",
            "schema_version",
            "targets",
        }
        or lock.get("schema_version") != 1
        or lock.get("name") != "source-python-gdb1-dependency-lock-v1"
        or lock.get("created_before_corpus_access") is not True
        or lock.get("protocol_config_sha256") != sha256_bytes(config_raw)
        or lock.get("targets") != TARGETS
    ):
        raise ValueError("dependency lock identity, config binding, or targets differ")
    acquisition = lock.get("acquisition", {})
    if (
        acquisition.get("allowed_metadata_host") != "pypi.org"
        or acquisition.get("allowed_artifact_host") != "files.pythonhosted.org"
        or acquisition.get("official_index") != "https://pypi.org/"
    ):
        raise ValueError("dependency lock official PyPI boundary differs")
    resolution = lock.get("resolution", {})
    if (
        resolution.get("package_set_complete") is not True
        or resolution.get("active_requirement")
        != 'pyyaml>=5.2; python_version < "3.13"'
        or set(resolution.get("excluded_by_python_3_12_markers", []))
        != {
            'pyyaml-ft>=8.0.0; python_version == "3.13"',
            'pyyaml>=6.0.3; python_version >= "3.14"',
            'typing-extensions; python_version < "3.10"',
        }
        or "never authorizes measurement"
        not in resolution.get("runtime_distribution_boundary", "")
    ):
        raise ValueError("dependency closure or runtime-accounting boundary differs")
    packages = lock.get("packages")
    if not isinstance(packages, list) or [
        row.get("normalized_name") for row in packages
    ] != [
        "libcst",
        "pyyaml",
    ]:
        raise ValueError("dependency package roster differs")
    expected_package_fields = {
        "libcst": {
            "name": "libcst",
            "version": "1.8.6",
            "requires_python": ">=3.9",
            "requires_dist": [
                'pyyaml>=5.2; python_version < "3.13"',
                'pyyaml-ft>=8.0.0; python_version == "3.13"',
                'pyyaml>=6.0.3; python_version >= "3.14"',
                'typing-extensions; python_version < "3.10"',
            ],
            "license_spdx_expression": "MIT AND PSF-2.0 AND Apache-2.0",
            "pypi_json_url": "https://pypi.org/pypi/libcst/1.8.6/json",
            "source_url": "https://github.com/Instagram/LibCST",
        },
        "pyyaml": {
            "name": "PyYAML",
            "version": "6.0.3",
            "requires_python": ">=3.8",
            "requires_dist": [],
            "license_spdx_expression": "MIT",
            "pypi_json_url": "https://pypi.org/pypi/pyyaml/6.0.3/json",
            "source_url": "https://github.com/yaml/pyyaml",
        },
    }
    target_ids = {row["id"] for row in TARGETS}
    targets_by_id = {row["id"]: row for row in TARGETS}
    filenames: set[str] = set()
    for package in packages:
        expected = expected_package_fields[package["normalized_name"]]
        if any(package.get(key) != value for key, value in expected.items()):
            raise ValueError(
                f"{package.get('normalized_name')} package metadata differs"
            )
        if package.get("license_files") != ["LICENSE"]:
            raise ValueError("dependency license roster differs")
        artifacts = package.get("artifacts")
        if (
            not isinstance(artifacts, list)
            or {row.get("target_id") for row in artifacts} != target_ids
            or len(artifacts) != len(target_ids)
        ):
            raise ValueError("dependency target artifact roster differs")
        if not safe_https_host(package.get("pypi_json_url"), "pypi.org"):
            raise ValueError("dependency metadata URL is outside official PyPI")
        for artifact in artifacts:
            filename = artifact.get("filename")
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or filename in filenames
                or not filename.endswith(".whl")
                or not safe_https_host(artifact.get("url"), "files.pythonhosted.org")
                or not artifact["url"].endswith("/" + filename)
                or type(artifact.get("size_bytes")) is not int
                or artifact["size_bytes"] <= 0
                or not is_sha256(artifact.get("sha256"))
                or not isinstance(artifact.get("upload_time_iso_8601"), str)
                or not artifact["upload_time_iso_8601"].endswith("Z")
            ):
                raise ValueError("dependency artifact identity differs")
            filenames.add(filename)
            internal = artifact.get("internal")
            if not isinstance(internal, dict) or set(internal) != {
                "license",
                "metadata",
                "record",
                "wheel",
            }:
                raise ValueError("dependency internal evidence roster differs")
            for name, member in internal.items():
                if (
                    not isinstance(member, dict)
                    or set(member) != {"bytes", "member", "sha256"}
                    or type(member.get("bytes")) is not int
                    or member["bytes"] <= 0
                    or not is_sha256(member.get("sha256"))
                    or not isinstance(member.get("member"), str)
                    or PurePosixPath(member["member"]).is_absolute()
                    or ".." in PurePosixPath(member["member"]).parts
                    or not member["member"].endswith(
                        {
                            "license": "/licenses/LICENSE",
                            "metadata": "/METADATA",
                            "record": "/RECORD",
                            "wheel": "/WHEEL",
                        }[name]
                    )
                ):
                    raise ValueError("dependency internal member identity differs")
            tags = artifact.get("wheel_tags")
            if not isinstance(tags, list) or not tags or tags != sorted(set(tags)):
                raise ValueError("dependency wheel tag roster differs")
            target = targets_by_id[artifact["target_id"]]
            if (
                not all(
                    tag.startswith(target["abi"] + "-" + target["abi"] + "-")
                    for tag in tags
                )
                or not any(tag.endswith("-" + target["platform"]) for tag in tags)
                or target["abi"] not in filename
                or target["architecture"] not in filename
            ):
                raise ValueError("dependency wheel does not match its target")
    if len(filenames) != 4:
        raise ValueError("dependency wheel roster is not exactly four artifacts")


def _record_hash(value: bytes) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()
    )


def verify_wheel(path: Path, package: dict[str, Any], artifact: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path.name} must be an ordinary wheel file")
    raw = path.read_bytes()
    if len(raw) != artifact["size_bytes"] or sha256_bytes(raw) != artifact["sha256"]:
        raise ValueError(f"{path.name} size or SHA-256 differs")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
            infos = wheel.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError(f"{path.name} contains duplicate ZIP members")
            for info in infos:
                member = PurePosixPath(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or "\\" in info.filename
                    or mode == stat.S_IFLNK
                ):
                    raise ValueError(f"{path.name} contains an unsafe ZIP member")
            members = {
                name: wheel.read(name) for name in names if not name.endswith("/")
            }
    except zipfile.BadZipFile as error:
        raise ValueError(f"{path.name} is not a valid wheel ZIP") from error
    for evidence in artifact["internal"].values():
        value = members.get(evidence["member"])
        if (
            value is None
            or len(value) != evidence["bytes"]
            or sha256_bytes(value) != evidence["sha256"]
        ):
            raise ValueError(f"{path.name} internal evidence differs")
    metadata = BytesParser().parsebytes(
        members[artifact["internal"]["metadata"]["member"]]
    )
    if (
        metadata.get("Name") != package["name"]
        or metadata.get("Version") != package["version"]
        or metadata.get("Requires-Python") != package["requires_python"]
        or (metadata.get_all("Requires-Dist") or []) != package["requires_dist"]
        or (metadata.get_all("License-File") or []) != package["license_files"]
    ):
        raise ValueError(f"{path.name} embedded package metadata differs")
    license_text = metadata.get("License") or ""
    if package["normalized_name"] == "libcst":
        required_license_tokens = (
            "MIT licensed",
            "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2",
            "APACHE LICENSE, VERSION 2.0",
        )
        if not all(token in license_text for token in required_license_tokens):
            raise ValueError(f"{path.name} embedded composite license differs")
    elif package["normalized_name"] == "pyyaml" and license_text != "MIT":
        raise ValueError(f"{path.name} embedded MIT license identity differs")
    wheel_metadata = BytesParser().parsebytes(
        members[artifact["internal"]["wheel"]["member"]]
    )
    if (
        wheel_metadata.get("Root-Is-Purelib") != "false"
        or sorted(wheel_metadata.get_all("Tag") or []) != artifact["wheel_tags"]
    ):
        raise ValueError(f"{path.name} embedded wheel tags differ")
    record_member = artifact["internal"]["record"]["member"]
    record_rows = list(csv.reader(io.StringIO(members[record_member].decode("utf-8"))))
    if any(len(row) != 3 for row in record_rows):
        raise ValueError(f"{path.name} RECORD row differs")
    if len(record_rows) != len(members) or {row[0] for row in record_rows} != set(
        members
    ):
        raise ValueError(f"{path.name} RECORD roster differs")
    for row in record_rows:
        if row[0] not in members:
            raise ValueError(f"{path.name} RECORD row differs")
        if row[0] == record_member:
            if row[1:] != ["", ""]:
                raise ValueError(f"{path.name} RECORD self-entry differs")
            continue
        value = members[row[0]]
        if row[1] != "sha256=" + _record_hash(value) or row[2] != str(len(value)):
            raise ValueError(f"{path.name} RECORD hash or size differs")


def verify_artifact_directory(root: Path, lock: dict[str, Any]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact cache must be an ordinary directory")
    rows = artifact_rows(lock)
    expected = {artifact["filename"] for _package, artifact in rows}
    observed = {path.name for path in root.iterdir()}
    if observed != expected:
        raise ValueError("artifact cache roster differs")
    for package, artifact in rows:
        verify_wheel(root / artifact["filename"], package, artifact)


def verify(
    lock_path: Path = DEFAULT_LOCK,
    config_path: Path = DEFAULT_CONFIG,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    config_raw, _config = read_canonical(config_path)
    lock_raw, lock = read_canonical(lock_path)
    if sha256_bytes(lock_raw) != EXPECTED_LOCK_SHA256:
        raise ValueError("dependency lock differs from the frozen trust anchor")
    validate_lock(lock, config_raw)
    if artifact_dir is not None:
        verify_artifact_directory(artifact_dir, lock)
    return {
        "verified": True,
        "artifact_bytes_verified": artifact_dir is not None,
        "artifact_count": len(artifact_rows(lock)),
        "package_count": len(lock["packages"]),
        "target_count": len(lock["targets"]),
        "lock_sha256": sha256_bytes(lock_raw),
        "protocol_config_sha256": sha256_bytes(config_raw),
        "claim_ceiling": lock["claim_ceiling"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.lock, args.config, args.artifact_dir)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"GDB1 dependency-lock verification failed: {error}"
        ) from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
