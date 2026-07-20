#!/usr/bin/env python3
"""Verify the corpus-disabled GDB1 codec, contracts, and optional cmix artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "config/source-python-gdb1-codec-format-v1.json": "4145b3096683f10557651c618e34d82987d7c604aae343e99eec636b5faa4123",
    "config/source-python-gdb1-derived-corpus-contract-v1.json": "90f4eccd8dfd0a0baa9ba9e35426323c27639ee32408039ecac16b1326f8fa59",
    "config/source-python-gdb1-baseline-distributions-v1.json": "ddaa98e1120bb81c28e9e650e1661c47f2b3a116d50813f24da57e94c5b6a23c",
}
CMIX_ARTIFACTS = {
    "cmix": (9890616, "59a16200f2b00ecd72c7c91217e5a5f7df467dc5952a8fdcaafbcf1457b0a644"),
    "english.dic": (411996, "4c8568cca9343b9a6212477880f56f8efd162f8784224a25edd043097d36215a"),
    "COPYING": (35147, "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"),
    "cmix-c443679c0773b8ae5b05423827804063d82ae7a8.tar.gz": (
        827233,
        "bbe21d7a16f4265765b4e18299f75fb8849c95574c92078ed628203b75f7edfb",
    ),
    "zig-aarch64-macos-0.16.0.tar.xz": (
        52238004,
        "b23d70deaa879b5c2d486ed3316f7eaa53e84acf6fc9cc747de152450d401489",
    ),
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != (
        json.dumps(value, indent=2, sort_keys=True) + "\n"
    ).encode():
        raise ValueError(f"noncanonical JSON: {path}")
    return raw, value


def verify(artifact_root: Path | None = None) -> dict[str, Any]:
    values = {}
    for relative, expected in FILES.items():
        raw, value = canonical(ROOT / relative)
        if sha256(raw) != expected:
            raise ValueError(f"frozen checkpoint anchor differs: {relative}")
        values[relative] = value
    codec = ROOT / "scripts/source-python-gdb1-synthetic-codec.py"
    codec_raw = codec.read_bytes()
    format_contract = values["config/source-python-gdb1-codec-format-v1.json"]
    if (
        codec.is_symlink()
        or not codec.is_file()
        or len(codec_raw) != format_contract["decoder"]["bytes"]
        or sha256(codec_raw) != format_contract["decoder"]["sha256"]
        or format_contract["measurement_authorized"] is not False
        or format_contract["synthetic_only"] is not True
    ):
        raise ValueError("synthetic decoder identity or barrier differs")
    corpus = values["config/source-python-gdb1-derived-corpus-contract-v1.json"]
    if (
        corpus["measurement_authorized"] is not False
        or corpus["state"] != "builder_contract_frozen_outputs_unfilled_corpus_unopened"
        or any(value is not None for value in corpus["sealed_outputs"].values())
    ):
        raise ValueError("derived-corpus sealed outputs or barrier differ")
    baselines = values["config/source-python-gdb1-baseline-distributions-v1.json"]
    rows = {row["id"]: row for row in baselines["baselines"]}
    if (
        baselines["measurement_authorized"] is not False
        or baselines["accounting"]["status"]
        != "incomplete_three_linux_distribution_locks_pending"
        or set(rows)
        != {
            "kanzi-max",
            "xz-lzma2-9e",
            "zstd-22-trained-dictionary",
            "cmix-v21-text",
        }
        or any(rows[name]["linux_distribution"] is not None for name in (
            "kanzi-max",
            "xz-lzma2-9e",
            "zstd-22-trained-dictionary",
        ))
        or rows["zstd-22-trained-dictionary"]["dictionary"]["sha256"] is not None
    ):
        raise ValueError("baseline pending-state barrier differs")
    cmix = rows["cmix-v21-text"]
    if cmix["complete_decoder_distribution_bytes"] != sum(
        component["bytes"] for component in cmix["components"]
    ):
        raise ValueError("cmix complete-distribution arithmetic differs")
    artifacts_verified = artifact_root is not None
    if artifact_root is not None:
        if artifact_root.is_symlink() or not artifact_root.is_dir():
            raise ValueError("cmix artifact root must be an ordinary directory")
        if {path.name for path in artifact_root.iterdir()} != set(CMIX_ARTIFACTS):
            raise ValueError("cmix artifact roster differs")
        for name, (size, digest) in CMIX_ARTIFACTS.items():
            path = artifact_root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("cmix artifact must be an ordinary file")
            raw = path.read_bytes()
            if len(raw) != size or sha256(raw) != digest:
                raise ValueError("cmix artifact identity differs")
    return {
        "artifacts_verified": artifacts_verified,
        "cmix_complete_decoder_distribution_bytes": cmix[
            "complete_decoder_distribution_bytes"
        ],
        "measurement_authorized": False,
        "pending_linux_baselines": [
            "kanzi-max",
            "xz-lzma2-9e",
            "zstd-22-trained-dictionary",
        ],
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmix-artifact-root", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.cmix_artifact_root)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"GDB1 checkpoint verification failed: {error}") from error
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
