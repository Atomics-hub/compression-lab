#!/usr/bin/env python3
"""Build and receipt the local ZPAQ/paq8px text/source ceiling tools."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import tempfile
from types import ModuleType
from typing import Any
import urllib.request
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = REPOSITORY / "runs" / "text-source-research-ceiling-plan-v1.json"
DEFAULT_ROOT = REPOSITORY / ".research-tools" / "text-source-v1" / "local"
LOCAL_HOST_CLASS = "local-macos-18-gib-rss-cap"
LOCAL_PROFILES = ["zpaq-5-m510", "paq8px-11L-local-screen"]


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load_script(
    "research_ceiling_planner_for_local_builder",
    REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py",
)
VALIDATOR = load_script(
    "research_ceiling_validator_for_local_builder",
    REPOSITORY / "scripts" / "validate-text-source-research-ceiling-toolchain.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != PLANNER.json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def write_immutable(path: Path, payload: dict[str, Any]) -> None:
    encoded = PLANNER.json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError(f"refusing to replace differing toolchain receipt: {path}")
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


def command_output(command: list[str]) -> str:
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=60
    )
    return (completed.stdout + completed.stderr).strip()


def resolve_program(name: str) -> Path:
    value = shutil.which(name)
    if value is None:
        raise ValueError(f"required build program is unavailable: {name}")
    return Path(value).resolve()


def compiler_identity(cxx: Path, cc: Path) -> str:
    return (
        f"CXX={cxx.name} bytes={cxx.stat().st_size} sha256={sha256_file(cxx)}: "
        f"{command_output([str(cxx), '--version'])}; "
        f"CC={cc.name} bytes={cc.stat().st_size} sha256={sha256_file(cc)}: "
        f"{command_output([str(cc), '--version'])}"
    )


def download_verified(
    destination: Path,
    *,
    url: str,
    expected_bytes: int,
    expected_sha256: str,
    allow_download: bool,
) -> Path:
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(f"cached source is not an ordinary file: {destination}")
    elif not allow_download:
        raise ValueError(f"pinned source is not cached and downloads are disabled: {url}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                with urllib.request.urlopen(url, timeout=120) as response:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > expected_bytes:
                            raise ValueError("download exceeded the pinned byte count")
                        output.write(chunk)
            os.replace(temporary_name, destination)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise
    if (
        destination.stat().st_size != expected_bytes
        or sha256_file(destination) != expected_sha256
    ):
        raise ValueError(f"pinned source identity differs: {destination}")
    return destination


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            member = PurePosixPath(info.filename)
            unix_mode = info.external_attr >> 16
            if (
                member.is_absolute()
                or not member.parts
                or any(part in {"", ".", ".."} for part in member.parts)
                or stat.S_ISLNK(unix_mode)
                or info.is_dir()
            ):
                raise ValueError(f"unsafe or unexpected ZIP member: {info.filename}")
            target = destination.joinpath(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as input_file, target.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)


def run_build_commands(
    commands: list[list[str]], *, source: Path, cxx: Path, cc: Path
) -> None:
    replacements = {"$CXX": str(cxx), "$CC": str(cc)}
    environment = dict(os.environ)
    environment.update({"LC_ALL": "C", "TZ": "UTC"})
    for template in commands:
        command = []
        for argument in template:
            for key, value in replacements.items():
                argument = argument.replace(key, value)
            command.append(argument)
        subprocess.run(
            command,
            cwd=source,
            env=environment,
            check=True,
            stdin=subprocess.DEVNULL,
            timeout=3600,
        )


def install_binary(source: Path, destination: Path) -> Path:
    if source.is_symlink() or not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"build produced no ordinary executable: {source}")
    payload = source.read_bytes()
    if destination.exists():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.read_bytes() != payload
            or not os.access(destination, os.X_OK)
        ):
            raise ValueError(f"refusing to replace differing tool binary: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
        os.chmod(temporary_name, 0o755)
        os.replace(temporary_name, destination)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return destination


def build_zpaq(
    candidate: dict[str, Any], root: Path, *, cxx: Path, cc: Path, allow_download: bool
) -> Path:
    archive = download_verified(
        root / "cache" / "zpaq715.zip",
        url=candidate["source_archive_url"],
        expected_bytes=candidate["source_archive_bytes"],
        expected_sha256=candidate["source_archive_sha256"],
        allow_download=allow_download,
    )
    with tempfile.TemporaryDirectory(prefix="compression-lab-zpaq-build-") as raw:
        source = Path(raw) / "source"
        safe_extract_zip(archive, source)
        required = {"Makefile", "zpaq.cpp", "libzpaq.cpp", "libzpaq.h"}
        if not required.issubset(path.name for path in source.iterdir()):
            raise ValueError("ZPAQ source archive roster is incomplete")
        run_build_commands(
            candidate["build_policy"]["commands"], source=source, cxx=cxx, cc=cc
        )
        return install_binary(source / "zpaq", root / "bin" / "zpaq-5-m510")


def ensure_paq_checkout(
    destination: Path, *, commit: str, allow_download: bool
) -> Path:
    git = resolve_program("git")
    if not destination.exists():
        if not allow_download:
            raise ValueError("pinned paq8px checkout is absent and downloads are disabled")
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
                    "https://github.com/hxim/paq8px.git",
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
    head = command_output([str(git), "-C", str(destination), "rev-parse", "HEAD"])
    status = command_output(
        [str(git), "-C", str(destination), "status", "--porcelain"]
    )
    if head != commit or status:
        raise ValueError("cached paq8px checkout identity or cleanliness differs")
    return destination


def build_paq8px(
    candidate: dict[str, Any], root: Path, *, cxx: Path, cc: Path, allow_download: bool
) -> Path:
    checkout = ensure_paq_checkout(
        root / "cache" / "paq8px-v216",
        commit=candidate["tag_commit"],
        allow_download=allow_download,
    )
    with tempfile.TemporaryDirectory(prefix="compression-lab-paq8px-build-") as raw:
        source = Path(raw) / "source"
        shutil.copytree(checkout, source, ignore=shutil.ignore_patterns(".git"))
        run_build_commands(
            candidate["build_policy"]["commands"], source=source, cxx=cxx, cc=cc
        )
        return install_binary(
            source / "build" / "paq8px",
            root / "bin" / "paq8px-11L-local-screen",
        )


def sysctl_value(name: str) -> str:
    try:
        return command_output(["/usr/sbin/sysctl", "-n", name])
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def host_record() -> dict[str, Any]:
    memory = sysctl_value("hw.memsize")
    if not memory.isdigit():
        raise ValueError("could not determine installed host memory")
    cpu = sysctl_value("machdep.cpu.brand_string")
    if cpu == "unavailable":
        cpu = sysctl_value("hw.model")
    identity = {
        "host_class": LOCAL_HOST_CLASS,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "memory_bytes": int(memory),
        "gpu": None,
        "cuda": None,
    }
    if type(identity["logical_cpus"]) is not int or identity["logical_cpus"] <= 0:
        raise ValueError("could not determine logical CPU count")
    host_id = hashlib.sha256(PLANNER.json_bytes(identity)).hexdigest()[:16]
    return {"host_id": f"local-macos-{host_id}", **identity}


def profile_record(
    *,
    profile_id: str,
    codec_id: str,
    candidate: dict[str, Any],
    executable: Path | None,
    root: Path,
    compiler: str,
    unavailable_reason: str | None,
) -> dict[str, Any]:
    common = {
        "profile_id": profile_id,
        "codec_id": codec_id,
        "status": "available" if executable is not None else "unavailable",
        "axiom_outcome": "untested",
        "source_identity": VALIDATOR.expected_source_identity(candidate),
    }
    if executable is None:
        return common | {"reason": unavailable_reason or "build unavailable"}
    return common | {
        "executable": file_record(executable, root),
        "runtime_assets": [],
        "build_commands": VALIDATOR.expected_build_commands(candidate),
        "compiler": compiler,
    }


def prepare(
    *,
    plan_path: Path,
    root: Path,
    allow_download: bool,
    record_unavailable: bool = False,
) -> Path:
    plan = read_canonical_json(plan_path)
    if (
        plan.get("name") != "text-source-research-ceiling-execution-plan-v1"
        or plan.get("execution_profile_roster", [])[:2] != LOCAL_PROFILES
    ):
        raise ValueError("research-ceiling plan is not the expected local profile plan")
    candidates = {row["codec_id"]: row for row in plan["candidate_identities"]}
    cxx = resolve_program("c++")
    cc = resolve_program("cc")
    compiler = compiler_identity(cxx, cc)
    profiles = []
    builders = [
        ("zpaq-5-m510", "zpaq-5", build_zpaq),
        ("paq8px-11L-local-screen", "paq8px-forcetext", build_paq8px),
    ]
    for profile_id, codec_id, builder in builders:
        executable = None
        unavailable_reason = None
        try:
            executable = builder(
                candidates[codec_id],
                root,
                cxx=cxx,
                cc=cc,
                allow_download=allow_download,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            unavailable_reason = f"local build unavailable: {error}"
            if not record_unavailable:
                raise ValueError(unavailable_reason) from error
        profiles.append(
            profile_record(
                profile_id=profile_id,
                codec_id=codec_id,
                candidate=candidates[codec_id],
                executable=executable,
                root=root,
                compiler=compiler,
                unavailable_reason=unavailable_reason,
            )
        )
    receipt = {
        "schema_version": 1,
        "name": "text-source-research-ceiling-toolchain-v1",
        "plan_sha256": sha256_file(plan_path),
        "host": host_record(),
        "profiles": profiles,
        "claim_ceiling": (
            "Toolchain availability is not a compression result or an Axiom win."
        ),
    }
    receipt_path = root / "receipt.json"
    write_immutable(receipt_path, receipt)
    VALIDATOR.validate(plan_path, receipt_path, root)
    return receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--record-unavailable", action="store_true")
    args = parser.parse_args()
    try:
        receipt = prepare(
            plan_path=args.plan,
            root=args.root,
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
        raise SystemExit(f"local research toolchain preparation failed: {error}") from error
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
