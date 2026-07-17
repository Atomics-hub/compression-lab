from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from typing import Dict, Iterable, List

from .models import CodecSpec
from .native import zstd_available


_CODECS: Dict[str, CodecSpec] = {}


def _register(codec: CodecSpec) -> None:
    _CODECS[codec.id] = codec


_register(CodecSpec("store", "Store", "store"))
_register(CodecSpec("adaptive-v0", "Compression Lab", "adaptive-v0"))
_register(CodecSpec("adaptive-v1", "Compression Lab", "adaptive-v1"))
for level in (1, 6, 9):
    _register(CodecSpec(f"gzip-{level}", "DEFLATE", "gzip", level))
for level in (1, 9):
    _register(CodecSpec(f"bz2-{level}", "BWT", "bz2", level))
for level in (0, 6, 9):
    _register(CodecSpec(f"lzma-{level}", "LZMA2", "lzma", level))


def _register_external(
    codec_id: str,
    family: str,
    implementation: str,
    executables: Iterable[str],
    level: int,
) -> None:
    names = list(executables)
    path = next((found for name in names if (found := shutil.which(name))), None)
    _register(
        CodecSpec(
            codec_id,
            family,
            implementation,
            level,
            available=path is not None,
            unavailable_reason="" if path else f"{' or '.join(names)} executable not found",
            executable=path or "",
        )
    )


for level in (1, 3, 9, 19):
    _register_external(f"zstd-{level}", "Zstandard", "external-zstd", ("zstd",), level)
    if zstd_available() and not _CODECS[f"zstd-{level}"].available:
        _CODECS[f"zstd-{level}"] = replace(
            _CODECS[f"zstd-{level}"],
            available=True,
            unavailable_reason="",
        )
for level in (1, 9):
    _register_external(f"lz4-{level}", "LZ4", "external-lz4", ("lz4",), level)
for level in (1, 6, 11):
    _register_external(
        f"brotli-{level}", "Brotli", "external-brotli", ("brotli",), level
    )
for level in (1, 5, 9):
    _register_external(
        f"7zip-{level}",
        "7-Zip",
        "external-7zip",
        ("7zz", "7z"),
        level,
    )

_v2_dependencies = (_CODECS["zstd-3"],)
_v2_missing = [codec.id for codec in _v2_dependencies if not codec.available]
_register(
    CodecSpec(
        "adaptive-v2",
        "Compression Lab",
        "adaptive-v2",
        available=not _v2_missing,
        unavailable_reason=(
            "missing native dependency: " + ", ".join(_v2_missing)
            if _v2_missing
            else ""
        ),
        version="frame-v2",
    )
)

_v3_dependencies = (_CODECS["zstd-3"],)
_v3_missing = [codec.id for codec in _v3_dependencies if not codec.available]
_register(
    CodecSpec(
        "adaptive-v3",
        "Compression Lab",
        "adaptive-v3",
        available=not _v3_missing,
        unavailable_reason=(
            "missing native dependency: " + ", ".join(_v3_missing)
            if _v3_missing
            else ""
        ),
        version="frame-v3-alpha2",
    )
)

for level in (3, 9, 19):
    dependency = _CODECS[f"zstd-{level}"]
    _register(
        CodecSpec(
            f"tbl1-{level}",
            "Compression Lab tabular",
            "tbl1",
            level,
            available=dependency.available,
            unavailable_reason=(
                "missing native dependency: " + dependency.id
                if not dependency.available
                else ""
            ),
            version="frame-tbl1-v1",
        )
    )


def all_codecs() -> List[CodecSpec]:
    return list(_CODECS.values())


def probe_codec_versions(codecs: Iterable[CodecSpec]) -> List[CodecSpec]:
    """Capture external versions once in the parent, never in timed workers."""
    cache: Dict[str, str] = {}
    probed: List[CodecSpec] = []
    for codec in codecs:
        if not codec.implementation.startswith("external-") or not codec.executable:
            probed.append(codec)
            continue
        if codec.executable not in cache:
            arguments = ("i",) if codec.implementation == "external-7zip" else ("--version",)
            try:
                completed = subprocess.run(
                    [codec.executable, *arguments],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                lines = (completed.stdout + "\n" + completed.stderr).strip().splitlines()
                cache[codec.executable] = next(
                    (line.strip() for line in lines if line.strip()), "version unavailable"
                )
            except (OSError, subprocess.SubprocessError):
                cache[codec.executable] = "version probe failed"
        probed.append(replace(codec, version=cache[codec.executable]))
    return probed


def resolve_codecs(codec_ids: Iterable[str]) -> List[CodecSpec]:
    resolved: List[CodecSpec] = []
    unknown: List[str] = []
    for codec_id in codec_ids:
        codec_id = codec_id.strip()
        if not codec_id:
            continue
        codec = _CODECS.get(codec_id)
        if codec is None:
            unknown.append(codec_id)
        elif not codec.available:
            raise ValueError(f"Codec {codec.id} is unavailable: {codec.unavailable_reason}")
        else:
            resolved.append(codec)
    if unknown:
        raise ValueError(
            f"Unknown codec(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(_CODECS))}"
        )
    if not resolved:
        raise ValueError("At least one codec must be selected")
    return resolved


def codec_by_id(codec_id: str) -> CodecSpec:
    try:
        return _CODECS[codec_id]
    except KeyError as exc:
        raise ValueError(f"Unknown codec: {codec_id}") from exc
