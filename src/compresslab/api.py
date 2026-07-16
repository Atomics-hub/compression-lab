"""Stable public API for Compression Lab frames.

The product API deliberately exposes only the current encoder and the
backward-compatible decoder. Benchmark internals and selector telemetry remain
available elsewhere but are not part of this compatibility contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import tempfile
from typing import Any, Optional, Union

from .adaptive_v3 import (
    BACKEND_SEGMENTED,
    FRAME_HEADER,
    MAGIC,
    SEGMENT_COUNT,
    SEGMENT_HEADER,
    VERSION,
    _RECIPE_NAMES,
)
from .worker import _adaptive_decompress, _adaptive_v3_compress


PathLike = Union[str, os.PathLike[str]]
DEFAULT_EXTENSION = ".clab"
DEFAULT_MAX_OUTPUT_SIZE = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class FrameInfo:
    """Metadata that can be inspected without decompressing a frame."""

    version: int
    original_size: int
    encoded_size: int
    sha256: str
    segment_count: int
    recipes: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_bytes(data: Union[bytes, bytearray, memoryview], name: str) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes-like")
    return bytes(data)


def _validate_output_limit(original_size: int, max_output_size: Optional[int]) -> None:
    if max_output_size is None:
        return
    if isinstance(max_output_size, bool) or not isinstance(max_output_size, int):
        raise TypeError("max_output_size must be an integer or None")
    if max_output_size < 0:
        raise ValueError("max_output_size cannot be negative")
    if original_size > max_output_size:
        raise ValueError(
            f"frame declares {original_size} output bytes, exceeding the "
            f"{max_output_size} byte safety limit"
        )


def inspect_frame(encoded: Union[bytes, bytearray, memoryview]) -> FrameInfo:
    """Parse bounded frame metadata without allocating the decoded output."""

    frame = _coerce_bytes(encoded, "encoded")
    if len(frame) < FRAME_HEADER.size:
        raise ValueError("compression-lab frame is truncated")
    magic, version, backend, original_size, expected_hash = FRAME_HEADER.unpack(
        frame[: FRAME_HEADER.size]
    )
    if magic != MAGIC:
        raise ValueError("compression-lab frame magic mismatch")
    if version not in {1, 2, VERSION}:
        raise ValueError(f"unsupported compression-lab frame version: {version}")

    if version != VERSION:
        return FrameInfo(
            version=version,
            original_size=original_size,
            encoded_size=len(frame),
            sha256=expected_hash.hex(),
            segment_count=1 if original_size else 0,
            recipes={f"legacy-backend-{backend}": 1} if original_size else {},
        )
    if backend != BACKEND_SEGMENTED:
        raise ValueError(f"unsupported adaptive-v3 backend: {backend}")
    if len(frame) < FRAME_HEADER.size + SEGMENT_COUNT.size:
        raise ValueError("adaptive-v3 segment count is truncated")

    offset = FRAME_HEADER.size
    segment_count = SEGMENT_COUNT.unpack(frame[offset : offset + SEGMENT_COUNT.size])[0]
    offset += SEGMENT_COUNT.size
    if original_size == 0 and segment_count != 0:
        raise ValueError("empty adaptive-v3 frame contains segments")
    if original_size > 0 and (segment_count == 0 or segment_count > original_size):
        raise ValueError("adaptive-v3 segment count is invalid")

    decoded_total = 0
    recipes: dict[str, int] = {}
    for _ in range(segment_count):
        if len(frame) - offset < SEGMENT_HEADER.size:
            raise ValueError("adaptive-v3 segment header is truncated")
        recipe, segment_size, payload_size, _ = SEGMENT_HEADER.unpack(
            frame[offset : offset + SEGMENT_HEADER.size]
        )
        offset += SEGMENT_HEADER.size
        if recipe not in _RECIPE_NAMES:
            raise ValueError(f"unsupported adaptive-v3 segment recipe: {recipe}")
        if segment_size == 0 or segment_size > original_size - decoded_total:
            raise ValueError("adaptive-v3 segment size is invalid")
        if payload_size > len(frame) - offset:
            raise ValueError("adaptive-v3 segment payload is truncated")
        offset += payload_size
        decoded_total += segment_size
        name = _RECIPE_NAMES[recipe]
        recipes[name] = recipes.get(name, 0) + 1

    if offset != len(frame):
        raise ValueError("adaptive-v3 frame has trailing data")
    if decoded_total != original_size:
        raise ValueError("adaptive-v3 frame original-size mismatch")
    return FrameInfo(
        version=version,
        original_size=original_size,
        encoded_size=len(frame),
        sha256=expected_hash.hex(),
        segment_count=segment_count,
        recipes=recipes,
    )


def compress(data: Union[bytes, bytearray, memoryview]) -> bytes:
    """Compress bytes into the current deterministic frame format (version 3)."""

    source = _coerce_bytes(data, "data")
    encoded, _ = _adaptive_v3_compress(source)
    return encoded


def decompress(
    encoded: Union[bytes, bytearray, memoryview],
    *,
    max_output_size: Optional[int] = DEFAULT_MAX_OUTPUT_SIZE,
) -> bytes:
    """Decode any supported frame after enforcing an allocation safety limit."""

    frame = _coerce_bytes(encoded, "encoded")
    _validate_output_limit(0, max_output_size)
    info = inspect_frame(frame)
    _validate_output_limit(info.original_size, max_output_size)
    restored, _ = _adaptive_decompress(frame, max_output_size=max_output_size)
    return restored


def default_compressed_path(source: PathLike) -> Path:
    path = Path(source)
    return path.with_name(path.name + DEFAULT_EXTENSION)


def default_decompressed_path(source: PathLike) -> Path:
    path = Path(source)
    if path.name.endswith(DEFAULT_EXTENSION):
        name = path.name[: -len(DEFAULT_EXTENSION)]
        if name:
            return path.with_name(name)
    return path.with_name(path.name + ".out")


def _atomic_write(destination: Path, data: bytes, overwrite: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination already exists: {destination}")
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if destination.exists() and not overwrite:
            raise FileExistsError(f"destination already exists: {destination}")
        os.replace(temporary_name, destination)
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def _validate_distinct_paths(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must be different files")


def compress_file(
    source: PathLike,
    destination: Optional[PathLike] = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Compress one file and atomically write a `.clab` frame."""

    source_path = Path(source)
    destination_path = (
        Path(destination) if destination is not None else default_compressed_path(source_path)
    )
    _validate_distinct_paths(source_path, destination_path)
    _atomic_write(destination_path, compress(source_path.read_bytes()), overwrite)
    return destination_path


def decompress_file(
    source: PathLike,
    destination: Optional[PathLike] = None,
    *,
    overwrite: bool = False,
    max_output_size: Optional[int] = DEFAULT_MAX_OUTPUT_SIZE,
) -> Path:
    """Safely decode one frame and atomically write the restored file."""

    source_path = Path(source)
    destination_path = (
        Path(destination)
        if destination is not None
        else default_decompressed_path(source_path)
    )
    _validate_distinct_paths(source_path, destination_path)
    restored = decompress(source_path.read_bytes(), max_output_size=max_output_size)
    _atomic_write(destination_path, restored, overwrite)
    return destination_path
