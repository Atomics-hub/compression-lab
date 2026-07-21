#!/usr/bin/env python3
"""Verify the E1 tool declaration, sealed tool root, and offline plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "frontier-headroom-e1-toolchain-v1.json"
E1_CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"
EXPECTED_SOURCE_IDS = {
    "kanzi-max": (
        355126,
        "0f34944b0ea77843b34ae461d5207bacd3a9839436182d8df244c6c190a1e30d",
    ),
    "zstd-19-long": (
        2434947,
        "eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3",
    ),
    "xz-lzma2-9e": (
        1548064,
        "fff1ffcf2b0da84d308a14de513a1aa23d4e9aa3464d17e64b9714bfdd0bbfb6",
    ),
    "zpaq-5-m510": (
        1000646,
        "e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418",
    ),
}
EXPECTED_EXECUTABLE_IDS = {
    "kanzi-max": (
        779328,
        "1518708ef729b2520ac706997721eb90c024266d72e97cc3a1db25a3a1afcbdd",
    ),
    "zstd-19-long": (
        188864,
        "9b5676aae3cb048cf68e2b40c543d9523db3b4cb911b31861bd5f4fcb050c4b6",
    ),
    "xz-lzma2-9e": (
        114336,
        "16b9994cca884ed2a66ba63736f1450049cbc6fd1d93076c51e5f0e7f7a71381",
    ),
    "zpaq-5-m510": (
        350232,
        "fecbedd1fe9ee9bfe8308ad61d223635dc65fc853f18b79dcabd854e5e341ac0",
    ),
}
EXPECTED_RUNTIME_IDS = {
    "lib/libzstd.1.dylib": (
        635328,
        "602d50cbe6fad0f0da6d1b73284ae3f75316015aea482ebd55614b6df2406b43",
    ),
    "lib/liblzma.5.dylib": (
        167472,
        "606a5184911c876c7446f932685183d8b348f5c9a95f764b01607be0e40b64ea",
    ),
    "lib/liblz4.1.dylib": (
        160944,
        "eb5734d2edaf7e9aa64d03d0add9a9ac3656830d7acb14ff69a43b1d96ead0f5",
    ),
}
EXPECTED_SOURCE_METADATA: dict[str, dict[str, Any]] = {
    "kanzi-max": {
        "version": "2.5.3",
        "official_project": "https://github.com/flanglet/kanzi-cpp",
        "url": "https://codeload.github.com/flanglet/kanzi-cpp/tar.gz/6eea1658897019ab3107df2806d5e534ef0798df",
        "cache_path": "cache/kanzi-6eea1658897019ab3107df2806d5e534ef0798df.tar.gz",
        "commit": "6eea1658897019ab3107df2806d5e534ef0798df",
        "license_spdx": "Apache-2.0",
        "license_member": "LICENSE",
        "build_status": "exact E1 binary reproduced by this locked build on the locked toolchain",
        "build_commands": [
            [
                "$CMAKE",
                "-S",
                "$SOURCE",
                "-B",
                "$BUILD",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DKANZI_ENABLE_NATIVE_OPTIMIZATIONS=ON",
                "-DCMAKE_CXX_COMPILER=$CXX",
            ],
            [
                "$CMAKE",
                "--build",
                "$BUILD",
                "--config",
                "Release",
                "--target",
                "kanzi_static",
                "--parallel",
                "10",
            ],
        ],
        "built_relative_path": "build/kanzi_static",
    },
    "zstd-19-long": {
        "version": "1.5.7",
        "official_project": "https://github.com/facebook/zstd",
        "url": "https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz",
        "cache_path": "cache/zstd-1.5.7.tar.gz",
        "commit": None,
        "license_spdx": "BSD-3-Clause OR GPL-2.0-only",
        "license_member": "LICENSE",
        "build_status": "upstream reference build only; it is not the frozen E1 distribution binary and is inadmissible unless its final SHA-256 equals the E1 executable lock",
        "build_commands": [
            [
                "$MAKE",
                "-C",
                "$SOURCE/programs",
                "zstd-release",
                "-j1",
                "CC=$CC",
                "CFLAGS=-O3",
            ]
        ],
        "built_relative_path": "programs/zstd",
    },
    "xz-lzma2-9e": {
        "version": "5.8.3",
        "official_project": "https://tukaani.org/xz/",
        "url": "https://github.com/tukaani-project/xz/releases/download/v5.8.3/xz-5.8.3.tar.xz",
        "cache_path": "cache/xz-5.8.3.tar.xz",
        "commit": None,
        "license_spdx": "0BSD AND GPL-2.0-or-later AND GPL-3.0-or-later AND LGPL-2.1-or-later",
        "license_member": "COPYING",
        "build_status": "upstream reference build only; it is not the frozen E1 distribution binary and is inadmissible unless its final SHA-256 equals the E1 executable lock",
        "build_commands": [
            [
                "$SOURCE/configure",
                "--prefix=$BUILD/install",
                "--disable-shared",
                "--enable-static",
                "--disable-doc",
                "--disable-nls",
                "CC=$CC",
                "CFLAGS=-O3",
            ],
            ["$MAKE", "-j1", "src/xz/xz"],
        ],
        "built_relative_path": "src/xz/xz",
    },
    "zpaq-5-m510": {
        "version": "7.15",
        "official_project": "https://mattmahoney.net/dc/zpaq.html",
        "url": "https://mattmahoney.net/dc/zpaq715.zip",
        "cache_path": "cache/zpaq715.zip",
        "commit": None,
        "license_spdx": "LicenseRef-Public-Domain AND MIT",
        "license_member": "readme.txt",
        "build_status": "exact E1 binary reproduced by this locked build on the locked toolchain",
        "build_commands": [
            [
                "$CXX",
                "-Dunix",
                "-DNOJIT",
                "-O3",
                "-Wno-builtin-macro-redefined",
                '-D__DATE__="Jul 18 2026"',
                "-o",
                "zpaq.o",
                "-c",
                "zpaq.cpp",
                "-pthread",
            ],
            [
                "$CXX",
                "-Dunix",
                "-DNOJIT",
                "-O3",
                "-Wno-builtin-macro-redefined",
                '-D__DATE__="Jul 18 2026"',
                "-o",
                "libzpaq.o",
                "-c",
                "libzpaq.cpp",
            ],
            ["$CXX", "-o", "zpaq", "zpaq.o", "libzpaq.o", "-pthread"],
        ],
        "built_relative_path": "zpaq",
    },
}
EXPECTED_TOOLCHAIN_IDS = {
    "cmake": (
        "/opt/homebrew/Cellar/cmake/4.4.0/bin/cmake",
        14081864,
        "8f136fce6bb8e9dbea38320f8a615b1f4896fe80cc7da5c1ff3da69e834f5d4c",
        "cmake version 4.4.0",
    ),
    "make": (
        "/usr/bin/make",
        118928,
        "12bed4523661307059b879b9b54e77a73176e9d27d27a0e40363271d8f0668ba",
        "GNU Make 3.81",
    ),
    "cxx": (
        "/usr/bin/c++",
        118928,
        "12bed4523661307059b879b9b54e77a73176e9d27d27a0e40363271d8f0668ba",
        "Apple clang version 21.0.0 (clang-2100.1.1.101)",
    ),
    "cc": (
        "/usr/bin/cc",
        118928,
        "12bed4523661307059b879b9b54e77a73176e9d27d27a0e40363271d8f0668ba",
        "Apple clang version 21.0.0 (clang-2100.1.1.101)",
    ),
}
EXPECTED_EXECUTABLE_POLICIES = {
    "kanzi-max": ("bin/kanzi", ["$EXECUTABLE", "--help"], [0], "Kanzi 2.5.3", []),
    "zstd-19-long": (
        "bin/zstd",
        ["$EXECUTABLE", "--version"],
        [0],
        "v1.5.7",
        ["lib/libzstd.1.dylib", "lib/liblzma.5.dylib", "lib/liblz4.1.dylib"],
    ),
    "xz-lzma2-9e": (
        "bin/xz",
        ["$EXECUTABLE", "--version"],
        [0],
        "xz (XZ Utils) 5.8.3",
        ["lib/liblzma.5.dylib"],
    ),
    "zpaq-5-m510": ("bin/zpaq", ["$EXECUTABLE"], [1], "zpaq v7.15", []),
}
EXPECTED_PROCESS_POLICY = {
    "jobs": 1,
    "timeout_seconds": 86400,
    "new_session_per_process": True,
    "kill_process_group_on_timeout": True,
    "terminate_grace_seconds": 5,
    "final_signal": "SIGKILL",
    "peak_rss_source": "POSIX wait4 direct-child ru_maxrss",
    "darwin_rss_unit_bytes": 1,
    "linux_rss_unit_bytes": 1024,
    "stdout_stderr_limit_bytes_each": 1048576,
    "stdin": "DEVNULL",
}
TOP_KEYS = {
    "schema_version",
    "name",
    "declared_at",
    "e1_bindings",
    "security_boundary",
    "platform_lock",
    "build_toolchain",
    "sources",
    "executables",
    "runtime_assets",
    "receipt",
    "execution_plan",
}
SOURCE_KEYS = {
    "codec_id",
    "version",
    "official_project",
    "url",
    "cache_path",
    "bytes",
    "sha256",
    "commit",
    "license_spdx",
    "license_member",
    "build_status",
    "build_commands",
    "built_relative_path",
}
EXECUTABLE_KEYS = {
    "codec_id",
    "path",
    "bytes",
    "sha256",
    "version_command",
    "version_exit_codes",
    "version_substring",
    "runtime_assets",
}
RECEIPT_KEYS = {
    "schema_version",
    "name",
    "completed",
    "config_sha256",
    "e1_config_sha256",
    "host",
    "build_toolchain",
    "sources",
    "executables",
    "runtime_assets",
    "cache_roster",
    "tool_roster",
    "corpus_accessed",
    "measurements_exist",
    "claim_ceiling",
}
PLAN_KEYS = {
    "schema_version",
    "name",
    "completed",
    "config_sha256",
    "e1_config_sha256",
    "tool_receipt_sha256",
    "repository_commit",
    "whole_item_tasks",
    "sample_tasks",
    "conditional_segment_templates",
    "process_policy",
    "corpus_accessed",
    "measurements_exist",
    "validation_status",
    "private_holdout_status",
    "claim_ceiling",
}


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} has unexpected fields")
    return value


def safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is not a path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{label} is not a normalized relative path")
    return value


def e1_sample_ranges(size: int) -> list[tuple[int, int]]:
    if type(size) is not int or size <= 0:
        raise ValueError("E1 sample size differs")
    budget = size * 500 // 10_000
    base, remainder = divmod(budget, 5)
    lengths = [base + (index < remainder) for index in range(5)]
    ranges = [
        ((size - length) * index // 4, length) for index, length in enumerate(lengths)
    ]
    if any(
        length <= 0 or offset < 0 or offset + length > size for offset, length in ranges
    ):
        raise ValueError("E1 sample range differs")
    if any(
        first[0] + first[1] > second[0] for first, second in zip(ranges, ranges[1:])
    ):
        raise ValueError("E1 sample ranges overlap")
    if sum(length for _offset, length in ranges) != budget:
        raise ValueError("E1 sample budget differs")
    return ranges


def ordinary_file(path: Path, *, executable: bool = False) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary file: {path}")
    if executable and not os.access(path, os.X_OK):
        raise ValueError(f"expected executable file: {path}")


def verify_file(
    path: Path, expected_bytes: int, expected_sha256: str, *, executable: bool = False
) -> dict[str, Any]:
    ordinary_file(path, executable=executable)
    if path.stat().st_size != expected_bytes or sha256_file(path) != expected_sha256:
        raise ValueError(f"file identity differs: {path}")
    return {"path": path.name, "bytes": expected_bytes, "sha256": expected_sha256}


def validate_declaration(config: dict[str, Any]) -> dict[str, Any]:
    require_keys(config, TOP_KEYS, "E1 toolchain config")
    if (
        config["schema_version"] != 1
        or config["name"] != "frontier-headroom-e1-toolchain-v1"
    ):
        raise ValueError("E1 toolchain identity differs")
    boundary = config["security_boundary"]
    if (
        boundary.get("official_sources_only") is not True
        or boundary.get("allowed_hosts")
        != [
            "github.com",
            "codeload.github.com",
            "release-assets.githubusercontent.com",
            "mattmahoney.net",
        ]
        or "No corpus path" not in boundary.get("corpus_barrier", "")
        or "performs zero corpus access" not in boundary.get("failure_policy", "")
    ):
        raise ValueError("E1 security boundary differs")
    platform_lock = config["platform_lock"]
    if (
        platform_lock.get("system") != "Darwin"
        or platform_lock.get("machine") != "arm64"
        or platform_lock.get("minimum_memory_bytes") != 7516192768
        or platform_lock.get("required_python_features")
        != ["os.wait4", "os.killpg", "os.setsid"]
        or platform_lock.get("measurement_process_policy") != EXPECTED_PROCESS_POLICY
    ):
        raise ValueError("E1 platform or process policy differs")
    toolchain = config["build_toolchain"]
    if [row.get("id") for row in toolchain] != list(EXPECTED_TOOLCHAIN_IDS):
        raise ValueError("E1 build toolchain roster differs")
    for row in toolchain:
        if set(row) != {"id", "path", "bytes", "sha256", "version_line"}:
            raise ValueError("E1 build toolchain fields differ")
        expected = EXPECTED_TOOLCHAIN_IDS[row["id"]]
        if (
            row["path"],
            row["bytes"],
            row["sha256"],
            row["version_line"],
        ) != expected:
            raise ValueError("E1 build toolchain identity differs")
    bindings = config["e1_bindings"]
    for key in ("config", "protocol", "plan_verifier"):
        path = ROOT / bindings[f"{key}_path"]
        ordinary_file(path)
        if sha256_file(path) != bindings[f"{key}_sha256"]:
            raise ValueError(f"bound E1 {key} drifted")
    e1 = json.loads(E1_CONFIG.read_bytes())
    e1_codecs = {row["id"]: row["binary_sha256"] for row in e1["codecs"]}
    sources = config["sources"]
    if not isinstance(sources, list) or [
        row.get("codec_id") for row in sources
    ] != list(EXPECTED_SOURCE_IDS):
        raise ValueError("E1 source roster differs")
    allowed_hosts = set(config["security_boundary"]["allowed_hosts"])
    for row in sources:
        require_keys(row, SOURCE_KEYS, "E1 source")
        if (row["bytes"], row["sha256"]) != EXPECTED_SOURCE_IDS[row["codec_id"]]:
            raise ValueError("E1 source identity differs")
        metadata = EXPECTED_SOURCE_METADATA[row["codec_id"]]
        if {key: row[key] for key in metadata} != metadata:
            raise ValueError("E1 source metadata or build commands differ")
        if (
            not row["url"].startswith("https://")
            or row["url"].split("/", 3)[2] not in allowed_hosts
        ):
            raise ValueError("E1 source URL is not official and allowed")
        safe_relative(row["cache_path"], "E1 source cache path")
        if (
            not row["license_spdx"]
            or not row["license_member"]
            or not row["build_commands"]
        ):
            raise ValueError("E1 source license or build lock is absent")
    executables = config["executables"]
    if not isinstance(executables, list) or [
        row.get("codec_id") for row in executables
    ] != list(EXPECTED_EXECUTABLE_IDS):
        raise ValueError("E1 executable roster differs")
    for row in executables:
        require_keys(row, EXECUTABLE_KEYS, "E1 executable")
        codec_id = row["codec_id"]
        if (row["bytes"], row["sha256"]) != EXPECTED_EXECUTABLE_IDS[codec_id]:
            raise ValueError("E1 executable identity differs")
        if row["sha256"] != e1_codecs[codec_id]:
            raise ValueError("E1 executable no longer matches frozen census")
        if (
            row["path"],
            row["version_command"],
            row["version_exit_codes"],
            row["version_substring"],
            row["runtime_assets"],
        ) != EXPECTED_EXECUTABLE_POLICIES[codec_id]:
            raise ValueError("E1 executable policy differs")
        safe_relative(row["path"], "E1 executable path")
        for asset in row["runtime_assets"]:
            if asset not in EXPECTED_RUNTIME_IDS:
                raise ValueError("E1 executable runtime dependency differs")
    assets = config["runtime_assets"]
    if {
        row.get("path"): (row.get("bytes"), row.get("sha256")) for row in assets
    } != EXPECTED_RUNTIME_IDS:
        raise ValueError("E1 runtime asset identities differ")
    if (
        len(config["receipt"]["required_keys"]) != len(RECEIPT_KEYS)
        or set(config["receipt"]["required_keys"]) != RECEIPT_KEYS
    ):
        raise ValueError("E1 receipt key schema differs")
    expected_roster = sorted(
        [row["cache_path"] for row in sources]
        + [row["path"] for row in executables]
        + list(EXPECTED_RUNTIME_IDS)
        + ["receipt.json"]
    )
    if config["receipt"]["directory_roster"] != expected_roster:
        raise ValueError("E1 tool directory roster differs")
    declared_plan = config["execution_plan"]
    if declared_plan != {
        "whole_item_task_count": 68,
        "sample_task_count": 68,
        "conditional_segment_template_count": 68,
        "task_status": "locked_not_executed",
        "corpus_accessed": False,
        "measurements_exist": False,
        "claim_ceiling": "Tool acquisition and an offline execution matrix only; no compression result, Axiom win, validation result, holdout result, or state-of-the-art evidence.",
    }:
        raise ValueError("E1 execution-plan declaration differs")
    return e1


def directory_roster(root: Path) -> list[str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("E1 tool root is not an ordinary directory")
    rows = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"E1 tool root contains a symlink: {path}")
        if path.is_file():
            rows.append(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ValueError(f"E1 tool root contains a special entry: {path}")
    return sorted(rows)


def verify_tool_root(
    config: dict[str, Any], root: Path, *, verify_receipt: bool = True
) -> dict[str, Any]:
    expected = list(config["receipt"]["directory_roster"])
    if not verify_receipt:
        expected.remove("receipt.json")
    if directory_roster(root) != expected:
        raise ValueError("E1 tool root has a missing or extra entry")
    for row in config["sources"]:
        verify_file(root / row["cache_path"], row["bytes"], row["sha256"])
    environment = {
        **os.environ,
        "LC_ALL": "C",
        "TZ": "UTC",
        "DYLD_LIBRARY_PATH": str(root / "lib"),
    }
    for row in config["executables"]:
        executable = root / row["path"]
        verify_file(executable, row["bytes"], row["sha256"], executable=True)
        command = [
            str(executable) if arg == "$EXECUTABLE" else arg
            for arg in row["version_command"]
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            env=environment,
            check=False,
        )
        output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
        if (
            completed.returncode not in row["version_exit_codes"]
            or row["version_substring"] not in output
        ):
            raise ValueError(f"E1 executable version differs: {row['codec_id']}")
    for row in config["runtime_assets"]:
        verify_file(root / row["path"], row["bytes"], row["sha256"])
    if verify_receipt:
        raw = (root / "receipt.json").read_bytes()
        receipt = json.loads(raw)
        if raw != json_bytes(receipt):
            raise ValueError("E1 receipt is not canonical")
        require_keys(receipt, RECEIPT_KEYS, "E1 receipt")
        if receipt["corpus_accessed"] or receipt["measurements_exist"]:
            raise ValueError("E1 tool receipt claims forbidden work")
        if receipt["config_sha256"] != sha256_file(DEFAULT_CONFIG) or receipt[
            "e1_config_sha256"
        ] != sha256_file(E1_CONFIG):
            raise ValueError("E1 receipt binding differs")
    return {"verified": True, "corpus_accessed": False, "measurements_exist": False}


def validate_plan(
    plan: dict[str, Any], config: dict[str, Any], receipt_path: Path
) -> None:
    require_keys(plan, PLAN_KEYS, "E1 execution plan")
    e1 = json.loads(E1_CONFIG.read_bytes())
    if plan["config_sha256"] != sha256_file(DEFAULT_CONFIG) or plan[
        "e1_config_sha256"
    ] != sha256_file(E1_CONFIG):
        raise ValueError("E1 execution-plan binding differs")
    if plan["tool_receipt_sha256"] != sha256_file(receipt_path):
        raise ValueError("E1 execution-plan tool receipt differs")
    executable_paths = {
        row["codec_id"]: f"$TOOL_ROOT/{row['path']}" for row in config["executables"]
    }
    replacements = {
        "$KANZI": executable_paths["kanzi-max"],
        "$ZSTD": executable_paths["zstd-19-long"],
        "$XZ": executable_paths["xz-lzma2-9e"],
        "$ZPAQ": executable_paths["zpaq-5-m510"],
        "$INPUT": "$WORK/input.bin",
        "$ARTIFACT": "$WORK/artifact.bin",
        "$RESTORED": "$WORK/restored.bin",
        "$RESTORED_DIRECTORY": "$WORK/restored/input.bin",
    }

    def command(template: list[str]) -> list[str]:
        result = []
        for argument in template:
            for source in sorted(replacements, key=len, reverse=True):
                target = replacements[source]
                argument = argument.replace(source, target)
            if any(source in argument for source in replacements):
                raise ValueError(f"unresolved E1 command placeholder: {argument}")
            result.append(argument)
        return result

    expected_whole = []
    expected_segments = []
    for codec in e1["codecs"]:
        replacements["$ARTIFACT"] = (
            "$WORK/artifact.zpaq" if codec["id"] == "zpaq-5-m510" else "$WORK/artifact.bin"
        )
        for item in e1["items"]:
            expected_whole.append(
                {
                    "task_id": f"whole/{codec['id']}/{item['id']}",
                    "phase": "whole_item",
                    "codec_id": codec["id"],
                    "item_id": item["id"],
                    "category": item["category"],
                    "source_manifest": item["source"],
                    "source_bytes": item["bytes"],
                    "source_sha256": item["sha256"],
                    "compress": command(codec["compress"]),
                    "decompress": command(codec["decompress"]),
                    "status": "locked_not_executed",
                    "corpus_accessed": False,
                }
            )
            expected_segments.append(
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
    expected_samples = []
    for codec in e1["codecs"]:
        replacements["$ARTIFACT"] = (
            "$WORK/artifact.zpaq" if codec["id"] == "zpaq-5-m510" else "$WORK/artifact.bin"
        )
        for item in e1["items"]:
            ranges = e1_sample_ranges(item["bytes"])
            expected_samples.append(
                {
                    "task_id": f"sample/{codec['id']}/{item['id']}",
                    "phase": "stratified_sample_ceiling",
                    "codec_id": codec["id"],
                    "item_id": item["id"],
                    "category": item["category"],
                    "source_manifest": item["source"],
                    "source_bytes": item["bytes"],
                    "source_sha256": item["sha256"],
                    "ranges": [
                        {"offset": offset, "length": length}
                        for offset, length in ranges
                    ],
                    "axe1s_layout": e1["sample_ceiling"]["binary_layout"],
                    "compress": command(codec["compress"]),
                    "decompress": command(codec["decompress"]),
                    "status": "locked_not_executed",
                    "corpus_accessed": False,
                }
            )
    if plan["whole_item_tasks"] != expected_whole:
        raise ValueError("E1 whole-item execution matrix differs")
    if plan["sample_tasks"] != expected_samples:
        raise ValueError("E1 sample execution matrix differs")
    if plan["conditional_segment_templates"] != expected_segments:
        raise ValueError("E1 segment template matrix differs")
    if plan["corpus_accessed"] or plan["measurements_exist"]:
        raise ValueError("E1 plan claims forbidden work")
    if plan["process_policy"] != config["platform_lock"]["measurement_process_policy"]:
        raise ValueError("E1 plan process policy differs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--tool-root", type=Path)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_bytes())
        validate_declaration(config)
        result = {
            "verified": True,
            "declaration_only": args.tool_root is None,
            "corpus_accessed": False,
            "measurements_exist": False,
        }
        if args.tool_root is not None:
            result |= verify_tool_root(config, args.tool_root)
            if args.plan is not None:
                plan = json.loads(args.plan.read_bytes())
                validate_plan(plan, config, args.tool_root / "receipt.json")
                result["execution_plan_verified"] = True
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E1 toolchain verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
