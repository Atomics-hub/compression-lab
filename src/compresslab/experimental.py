"""Experimental category-specific codecs.

These APIs are intentionally outside the stable top-level compatibility
contract. Their formats are versioned, but promotion depends on the repository
validation gates and may change before a stable release.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from ._constants import DEFAULT_MAX_OUTPUT_SIZE
from .json_log_codec import (
    DEFAULT_SEGMENT_SIZE,
    JsonLogFrameInfo,
    compress as _compress_json_logs,
    compress_file as _compress_json_log_file,
    decompress as _decompress_json_logs,
    decompress_file as _decompress_json_log_file,
    inspect as _inspect_json_log_frame,
)


PathLike = Union[str, os.PathLike[str]]
JSON_LOG_EXTENSION = ".jls2"


def _coerce_bytes(
    data: Union[bytes, bytearray, memoryview],
    name: str,
) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes-like")
    return bytes(data)


def compress_json_logs(
    data: Union[bytes, bytearray, memoryview],
    *,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> bytes:
    """Compress newline-delimited flat JSON logs into experimental JLS2."""

    encoded, _ = _compress_json_logs(
        _coerce_bytes(data, "data"),
        segment_size=segment_size,
    )
    return encoded


def decompress_json_logs(
    encoded: Union[bytes, bytearray, memoryview],
    *,
    max_output_size: Optional[int] = DEFAULT_MAX_OUTPUT_SIZE,
) -> bytes:
    """Decode experimental JLS2 after enforcing an output limit."""

    return _decompress_json_logs(
        _coerce_bytes(encoded, "encoded"),
        max_output_size=max_output_size,
    )


def inspect_json_log_frame(
    encoded: Union[bytes, bytearray, memoryview],
) -> JsonLogFrameInfo:
    """Inspect JLS2 metadata and encoded integrity without decoding values."""

    return _inspect_json_log_frame(_coerce_bytes(encoded, "encoded"))


def default_json_log_compressed_path(source: PathLike) -> Path:
    path = Path(source)
    return path.with_name(path.name + JSON_LOG_EXTENSION)


def default_json_log_decompressed_path(source: PathLike) -> Path:
    path = Path(source)
    if path.name.endswith(JSON_LOG_EXTENSION):
        name = path.name[: -len(JSON_LOG_EXTENSION)]
        if name:
            return path.with_name(name)
    return path.with_name(path.name + ".out")


def _validate_distinct_paths(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must be different files")


def compress_json_log_file(
    source: PathLike,
    destination: Optional[PathLike] = None,
    *,
    overwrite: bool = False,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> Path:
    """Stream one JSON-log file into an experimental JLS2 container."""

    source_path = Path(source)
    destination_path = (
        Path(destination)
        if destination is not None
        else default_json_log_compressed_path(source_path)
    )
    _validate_distinct_paths(source_path, destination_path)
    _compress_json_log_file(
        source_path,
        destination_path,
        segment_size=segment_size,
        overwrite=overwrite,
    )
    return destination_path


def decompress_json_log_file(
    source: PathLike,
    destination: Optional[PathLike] = None,
    *,
    overwrite: bool = False,
    max_output_size: Optional[int] = DEFAULT_MAX_OUTPUT_SIZE,
) -> Path:
    """Stream-decode one experimental JLS2 container."""

    source_path = Path(source)
    destination_path = (
        Path(destination)
        if destination is not None
        else default_json_log_decompressed_path(source_path)
    )
    _validate_distinct_paths(source_path, destination_path)
    _decompress_json_log_file(
        source_path,
        destination_path,
        overwrite=overwrite,
        max_output_size=max_output_size,
    )
    return destination_path


__all__ = [
    "DEFAULT_SEGMENT_SIZE",
    "JSON_LOG_EXTENSION",
    "JsonLogFrameInfo",
    "compress_json_log_file",
    "compress_json_logs",
    "decompress_json_log_file",
    "decompress_json_logs",
    "default_json_log_compressed_path",
    "default_json_log_decompressed_path",
    "inspect_json_log_frame",
]
