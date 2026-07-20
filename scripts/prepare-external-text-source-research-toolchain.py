#!/usr/bin/env python3
"""Build one larger-host text/source research-ceiling toolchain profile."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_ROOT = REPOSITORY / ".research-tools" / "text-source-v1" / "external"
PROFILE_SPECS = {
    "paq8px-12L-absolute": {
        "codec_id": "paq8px-forcetext",
        "host_class": "larger-isolated-memory-host",
    },
    "cmix-v21-strong-text": {
        "codec_id": "cmix",
        "host_class": "larger-isolated-memory-host-portable-o3-build",
    },
    "nncp-3.3-transformer": {
        "codec_id": "nncp",
        "host_class": "authorized-linux-cuda-host-plus-second-host-decode",
    },
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LOCAL = load_script(
    "local_research_toolchain_for_external_builder",
    REPOSITORY / "scripts" / "prepare-local-text-source-research-toolchain.py",
)
VALIDATOR = LOCAL.VALIDATOR
PLANNER = LOCAL.PLANNER


def ensure_git_checkout(
    destination: Path,
    *,
    repository: str,
    commit: str,
    allow_download: bool,
) -> Path:
    git = LOCAL.resolve_program("git")
    if not destination.exists():
        if not allow_download:
            raise ValueError("pinned source checkout is absent and downloads are disabled")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
        )
        try:
            subprocess.run([str(git), "init", str(temporary)], check=True, timeout=60)
            subprocess.run(
                [
                    str(git),
                    "-C",
                    str(temporary),
                    "remote",
                    "add",
                    "origin",
                    repository,
                ],
                check=True,
                timeout=60,
            )
            subprocess.run(
                [
                    str(git),
                    "-C",
                    str(temporary),
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    commit,
                ],
                check=True,
                timeout=600,
            )
            subprocess.run(
                [str(git), "-C", str(temporary), "checkout", "--detach", "FETCH_HEAD"],
                check=True,
                timeout=60,
            )
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    head = LOCAL.command_output(
        [str(git), "-C", str(destination), "rev-parse", "HEAD"]
    )
    status = LOCAL.command_output(
        [str(git), "-C", str(destination), "status", "--porcelain"]
    )
    if head != commit or status:
        raise ValueError("cached source checkout identity or cleanliness differs")
    return destination


def safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    total_bytes = 0
    with tarfile.open(archive, "r:gz") as source:
        for info in source:
            member = PurePosixPath(info.name)
            if (
                member.is_absolute()
                or not member.parts
                or any(part in {"", ".", ".."} for part in member.parts)
                or member.parts[0] != "nncp-2024-06-05"
                or not (info.isdir() or info.isreg())
            ):
                raise ValueError(f"unsafe or unexpected TAR member: {info.name}")
            target = destination.joinpath(*member.parts)
            if info.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total_bytes += info.size
            if total_bytes > 32 * 1024 * 1024:
                raise ValueError("NNCP source archive expands beyond the frozen safety cap")
            target.parent.mkdir(parents=True, exist_ok=True)
            input_file = source.extractfile(info)
            if input_file is None:
                raise ValueError(f"could not read TAR member: {info.name}")
            with input_file, target.open("xb") as output:
                shutil.copyfileobj(input_file, output, length=1024 * 1024)


def build_paq8px(
    candidate: dict[str, Any], root: Path, *, cxx: Path, cc: Path, allow_download: bool
) -> tuple[Path, list[Path]]:
    checkout = ensure_git_checkout(
        root / "cache" / "paq8px-v216",
        repository="https://github.com/hxim/paq8px.git",
        commit=candidate["tag_commit"],
        allow_download=allow_download,
    )
    with tempfile.TemporaryDirectory(prefix="compression-lab-paq8px-12l-build-") as raw:
        source = Path(raw) / "source"
        shutil.copytree(checkout, source, ignore=shutil.ignore_patterns(".git"))
        LOCAL.run_build_commands(
            candidate["build_policy"]["commands"], source=source, cxx=cxx, cc=cc
        )
        executable = LOCAL.install_binary(
            source / "build" / "paq8px", root / "bin" / "paq8px-12L-absolute"
        )
    return executable, []


def build_cmix(
    candidate: dict[str, Any], root: Path, *, cxx: Path, cc: Path, allow_download: bool
) -> tuple[Path, list[Path]]:
    checkout = ensure_git_checkout(
        root / "cache" / "cmix-v21",
        repository="https://github.com/byronknoll/cmix.git",
        commit=candidate["tag_commit"],
        allow_download=allow_download,
    )
    expected_asset = candidate["required_decoder_assets"][0]
    dictionary = checkout / expected_asset["path"]
    if (
        dictionary.is_symlink()
        or not dictionary.is_file()
        or dictionary.stat().st_size != expected_asset["bytes"]
        or LOCAL.sha256_file(dictionary) != expected_asset["sha256"]
    ):
        raise ValueError("cmix dictionary identity differs from the frozen plan")
    with tempfile.TemporaryDirectory(prefix="compression-lab-cmix-build-") as raw:
        source = Path(raw) / "source"
        shutil.copytree(checkout, source, ignore=shutil.ignore_patterns(".git"))
        LOCAL.run_build_commands(
            candidate["build_policy"]["commands"], source=source, cxx=cxx, cc=cc
        )
        executable = LOCAL.install_binary(
            source / "cmix", root / "bin" / "cmix-v21-strong-text"
        )
    installed_dictionary = LOCAL.install_binary(
        dictionary, root / expected_asset["path"]
    )
    return executable, [installed_dictionary]


def build_nncp(
    candidate: dict[str, Any], root: Path, *, cxx: Path, cc: Path, allow_download: bool
) -> tuple[Path, list[Path]]:
    archive = LOCAL.download_verified(
        root / "cache" / "nncp-2024-06-05.tar.gz",
        url=candidate["source_archive_url"],
        expected_bytes=candidate["source_archive_bytes"],
        expected_sha256=candidate["source_archive_sha256"],
        allow_download=allow_download,
    )
    with tempfile.TemporaryDirectory(prefix="compression-lab-nncp-build-") as raw:
        extracted = Path(raw) / "extracted"
        safe_extract_tar(archive, extracted)
        source = extracted / "nncp-2024-06-05"
        runtime = candidate["bundled_runtime_identity"]
        runtime_sources = []
        for identity in (runtime["cpu_library"], runtime["cuda_library"]):
            path = extracted / identity["path"]
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != identity["bytes"]
                or LOCAL.sha256_file(path) != identity["sha256"]
            ):
                raise ValueError(f"NNCP runtime identity differs: {identity['path']}")
            runtime_sources.append((identity, path))
        LOCAL.run_build_commands(
            candidate["build_policy"]["commands"], source=source, cxx=cxx, cc=cc
        )
        executable = LOCAL.install_binary(
            source / "nncp", root / "bin" / "nncp-3.3-transformer"
        )
        runtime_paths = [
            LOCAL.install_binary(path, root / identity["path"])
            for identity, path in runtime_sources
        ]
    return executable, runtime_paths


def memory_bytes() -> int:
    if Path("/proc/meminfo").is_file():
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                fields = line.split()
                if len(fields) == 3 and fields[1].isdigit() and fields[2] == "kB":
                    return int(fields[1]) * 1024
    value = LOCAL.sysctl_value("hw.memsize")
    if value.isdigit():
        return int(value)
    raise ValueError("could not determine installed host memory")


def cpu_identity() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def host_record(
    host_class: str, *, host_id: str, gpu: str | None, cuda: str | None
) -> dict[str, Any]:
    if not host_id or len(host_id) > 256:
        raise ValueError("external host ID must be a nonempty pseudonymous label")
    if host_class == "authorized-linux-cuda-host-plus-second-host-decode" and (
        not sys_platform_linux() or not gpu or not cuda
    ):
        raise ValueError("NNCP host requires Linux plus explicit GPU and CUDA identity")
    identity = {
        "host_class": host_class,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu_identity(),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": memory_bytes(),
        "gpu": gpu,
        "cuda": cuda,
    }
    if type(identity["logical_cpus"]) is not int or identity["logical_cpus"] <= 0:
        raise ValueError("could not determine logical CPU count")
    return {"host_id": host_id, **identity}


def sys_platform_linux() -> bool:
    return platform.system() == "Linux"


def prepare(
    *,
    plan_path: Path,
    root: Path,
    profile_id: str,
    host_id: str,
    cxx_name: str,
    cc_name: str,
    gpu: str | None,
    cuda: str | None,
    allow_download: bool,
    record_unavailable: bool = False,
) -> Path:
    if profile_id not in PROFILE_SPECS:
        raise ValueError(f"unsupported external profile: {profile_id}")
    plan = LOCAL.read_canonical_json(plan_path)
    spec = PROFILE_SPECS[profile_id]
    if not any(
        task["profile_id"] == profile_id and task["host_class"] == spec["host_class"]
        for task in plan["tasks"]
    ):
        raise ValueError("external profile is absent from the frozen plan")
    candidates = {row["codec_id"]: row for row in plan["candidate_identities"]}
    candidate = candidates[spec["codec_id"]]
    cxx = LOCAL.resolve_program(cxx_name)
    cc = LOCAL.resolve_program(cc_name)
    compiler = LOCAL.compiler_identity(cxx, cc)
    builders = {
        "paq8px-12L-absolute": build_paq8px,
        "cmix-v21-strong-text": build_cmix,
        "nncp-3.3-transformer": build_nncp,
    }
    executable = None
    runtime_assets: list[Path] = []
    unavailable_reason = None
    try:
        executable, runtime_assets = builders[profile_id](
            candidate,
            root,
            cxx=cxx,
            cc=cc,
            allow_download=allow_download,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        unavailable_reason = f"external build unavailable: {error}"
        if not record_unavailable:
            raise ValueError(unavailable_reason) from error
    common = {
        "profile_id": profile_id,
        "codec_id": spec["codec_id"],
        "status": "available" if executable is not None else "unavailable",
        "axiom_outcome": "untested",
        "source_identity": VALIDATOR.expected_source_identity(candidate),
    }
    if executable is None:
        profile = common | {"reason": unavailable_reason or "build unavailable"}
    else:
        profile = common | {
            "executable": LOCAL.file_record(executable, root),
            "runtime_assets": [LOCAL.file_record(path, root) for path in runtime_assets],
            "build_commands": VALIDATOR.expected_build_commands(candidate),
            "compiler": compiler,
        }
    receipt = {
        "schema_version": 1,
        "name": "text-source-research-ceiling-toolchain-v1",
        "plan_sha256": LOCAL.sha256_file(plan_path),
        "host": host_record(
            spec["host_class"], host_id=host_id, gpu=gpu, cuda=cuda
        ),
        "profiles": [profile],
        "claim_ceiling": (
            "Toolchain availability is not a compression result or an Axiom win."
        ),
    }
    receipt_path = root / "receipt.json"
    LOCAL.write_immutable(receipt_path, receipt)
    VALIDATOR.validate(plan_path, receipt_path, root)
    return receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILE_SPECS), required=True)
    parser.add_argument("--host-id", required=True)
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--gpu")
    parser.add_argument("--cuda")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--record-unavailable", action="store_true")
    args = parser.parse_args()
    try:
        receipt = prepare(
            plan_path=args.plan,
            root=args.root or (DEFAULT_ROOT / args.profile),
            profile_id=args.profile,
            host_id=args.host_id,
            cxx_name=args.cxx,
            cc_name=args.cc,
            gpu=args.gpu,
            cuda=args.cuda,
            allow_download=args.allow_download,
            record_unavailable=args.record_unavailable,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"external research toolchain preparation failed: {error}") from error
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
