from __future__ import annotations

import shutil
from typing import Dict, Iterable, List

from .models import CodecSpec


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
    codec_id: str, family: str, implementation: str, executable: str, level: int
) -> None:
    path = shutil.which(executable)
    _register(
        CodecSpec(
            codec_id,
            family,
            implementation,
            level,
            available=path is not None,
            unavailable_reason="" if path else f"{executable} executable not found",
        )
    )


for level in (1, 3, 9, 19):
    _register_external(f"zstd-{level}", "Zstandard", "external-zstd", "zstd", level)
for level in (1, 9):
    _register_external(f"lz4-{level}", "LZ4", "external-lz4", "lz4", level)
for level in (1, 6, 11):
    _register_external(f"brotli-{level}", "Brotli", "external-brotli", "brotli", level)


def all_codecs() -> List[CodecSpec]:
    return list(_CODECS.values())


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
