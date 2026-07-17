"""Setuptools hook that embeds the Rust C-ABI library in platform wheels."""

from __future__ import annotations

import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Optional

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py


ROOT = Path(__file__).resolve().parent


def native_library_name() -> str:
    if sys.platform == "darwin":
        return "libcompression_lab_native.dylib"
    if sys.platform == "win32":
        return "compression_lab_native.dll"
    return "libcompression_lab_native.so"


def dense_native_library_name() -> str:
    if sys.platform == "darwin":
        return "libcompression_lab_dense_native.dylib"
    if sys.platform == "win32":
        return "compression_lab_dense_native.dll"
    return "libcompression_lab_dense_native.so"


def macos_architecture() -> str:
    flags = os.environ.get("ARCHFLAGS", "")
    if "x86_64" in flags and "arm64" not in flags:
        return "x86_64"
    if "arm64" in flags and "x86_64" not in flags:
        return "arm64"
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else "x86_64"


def cargo_target() -> Optional[str]:
    if sys.platform != "darwin":
        return None
    return (
        "aarch64-apple-darwin"
        if macos_architecture() == "arm64"
        else "x86_64-apple-darwin"
    )


class PlatformDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        return True


class BuildWithRust(build_py):
    def run(self) -> None:
        cargo = os.environ.get("CARGO", "cargo")
        command = [
            cargo,
            "build",
            "--manifest-path",
            str(ROOT / "native" / "Cargo.toml"),
            "--release",
            "--locked",
        ]
        target = cargo_target()
        if target is not None:
            subprocess.run(["rustup", "target", "add", target], cwd=ROOT, check=True)
            command.extend(["--target", target])
        subprocess.run(command, cwd=ROOT, check=True)
        dense_command = command.copy()
        manifest_index = dense_command.index(str(ROOT / "native" / "Cargo.toml"))
        dense_command[manifest_index] = str(ROOT / "native-dense" / "Cargo.toml")
        subprocess.run(dense_command, cwd=ROOT, check=True)
        super().run()
        for directory, name in (
            ("native", native_library_name()),
            ("native-dense", dense_native_library_name()),
        ):
            source = ROOT / directory / "target"
            if target is not None:
                source /= target
            source = source / "release" / name
            if not source.is_file():
                raise RuntimeError(f"Cargo did not produce {source}")
            destination = Path(self.build_lib) / "compresslab" / "_native" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


class PlatformWheel(bdist_wheel):
    def get_tag(self):
        _, _, platform = super().get_tag()
        if sys.platform == "darwin":
            architecture = macos_architecture()
            minimum = "11_0" if architecture == "arm64" else "10_12"
            platform = f"macosx_{minimum}_{architecture}"
        return "py3", "none", platform


setup(
    cmdclass={"build_py": BuildWithRust, "bdist_wheel": PlatformWheel},
    distclass=PlatformDistribution,
    zip_safe=False,
)
