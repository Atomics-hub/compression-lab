#!/usr/bin/env python3
"""Verify that release metadata and an optional tag name agree exactly."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
from typing import Dict, Optional, Sequence


REPOSITORY = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:[-.]?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)?\Z"
)


def toml_value(path: Path, section: str, key: str) -> str:
    current = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if current != section:
            continue
        match = re.fullmatch(rf'{re.escape(key)}\s*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    raise ValueError(f"missing [{section}] {key} in {path}")


def python_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "__version__"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise ValueError(f"missing literal __version__ in {path}")


def verify_release_version(root: Path, tag: Optional[str] = None) -> Dict[str, str]:
    versions = {
        "pyproject": toml_value(root / "pyproject.toml", "project", "version"),
        "python": python_version(root / "src/compresslab/__init__.py"),
        "native": toml_value(root / "native/Cargo.toml", "package", "version"),
        "native_dense": toml_value(
            root / "native-dense/Cargo.toml", "package", "version"
        ),
    }
    unique = set(versions.values())
    if len(unique) != 1:
        raise ValueError(f"release versions disagree: {versions}")
    version = next(iter(unique))
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"release version is not supported: {version!r}")
    if tag is not None:
        expected_tag = f"v{version}"
        if tag != expected_tag:
            raise ValueError(
                f"release tag does not match package version: {tag!r} != "
                f"{expected_tag!r}"
            )
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        if f"## [{version}]" not in changelog:
            raise ValueError(f"CHANGELOG has no release section for {version}")
    return {**versions, "version": version, "tag": tag or ""}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--tag")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    result = verify_release_version(arguments.root.resolve(), arguments.tag)
    tag = result["tag"] or "<not a tag build>"
    print(f"release version verified: {result['version']} ({tag})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
