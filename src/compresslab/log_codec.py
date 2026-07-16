from __future__ import annotations

import hashlib
import struct
from typing import Dict, Optional, Tuple, Union

from .native import (
    log_transform_decode,
    log_transform_encode,
    zstd_compress,
    zstd_decompress,
)


MAGIC = b"CLG1"
VERSION = 1
MODE_DIRECT = 0
MODE_TRANSFORMED = 1
HEADER = struct.Struct(">4sBBHQQ32s")
MAX_TRANSFORM_EXPANSION = 3
MAX_TRANSFORM_OVERHEAD = 16

TelemetryValue = Union[str, int, float, bool]


def _pack(
    mode: int,
    original: bytes,
    transformed_size: int,
    payload: bytes,
) -> bytes:
    return HEADER.pack(
        MAGIC,
        VERSION,
        mode,
        0,
        len(original),
        transformed_size,
        hashlib.sha256(original).digest(),
    ) + payload


def compress(
    data: bytes,
    *,
    level: int = 9,
) -> Tuple[bytes, Dict[str, TelemetryValue]]:
    direct_payload = zstd_compress(data, level=level)
    direct_frame = _pack(MODE_DIRECT, data, 0, direct_payload)

    transformed = log_transform_encode(data)
    transformed_payload = zstd_compress(transformed, level=level)
    transformed_frame = _pack(
        MODE_TRANSFORMED,
        data,
        len(transformed),
        transformed_payload,
    )

    if len(transformed_frame) < len(direct_frame):
        selected = transformed_frame
        selected_mode = "transformed"
    else:
        selected = direct_frame
        selected_mode = "direct"
    return selected, {
        "selected_mode": selected_mode,
        "selected_bytes": len(selected),
        "direct_frame_bytes": len(direct_frame),
        "transformed_frame_bytes": len(transformed_frame),
        "direct_payload_bytes": len(direct_payload),
        "transformed_payload_bytes": len(transformed_payload),
        "transformed_bytes": len(transformed),
        "frame_overhead_bytes": HEADER.size,
        "no_expansion_vs_direct_frame": len(selected) <= len(direct_frame),
        "zstd_level": level,
    }


def decompress(
    frame: bytes,
    *,
    max_output_size: Optional[int] = None,
) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("JSON-log frame is truncated")
    (
        magic,
        version,
        mode,
        reserved,
        original_size,
        transformed_size,
        expected_sha256,
    ) = HEADER.unpack_from(frame)
    if magic != MAGIC:
        raise ValueError("JSON-log frame magic mismatch")
    if version != VERSION:
        raise ValueError(f"unsupported JSON-log frame version: {version}")
    if reserved != 0:
        raise ValueError("JSON-log frame reserved bits are nonzero")
    if max_output_size is not None and original_size > max_output_size:
        raise ValueError(
            f"JSON-log output exceeds safety limit: "
            f"{original_size} > {max_output_size}"
        )
    payload = frame[HEADER.size :]
    try:
        if mode == MODE_DIRECT:
            if transformed_size != 0:
                raise ValueError(
                    "direct JSON-log frame declares a transformed size"
                )
            restored = zstd_decompress(payload, original_size)
        elif mode == MODE_TRANSFORMED:
            maximum_transformed = (
                original_size * MAX_TRANSFORM_EXPANSION
                + MAX_TRANSFORM_OVERHEAD
            )
            if transformed_size > maximum_transformed:
                raise ValueError("JSON-log transformed size exceeds its bound")
            transformed = zstd_decompress(payload, transformed_size)
            restored = log_transform_decode(transformed, original_size)
        else:
            raise ValueError(f"unsupported JSON-log frame mode: {mode}")
    except RuntimeError as error:
        raise ValueError(f"invalid JSON-log payload: {error}") from error
    if hashlib.sha256(restored).digest() != expected_sha256:
        raise ValueError("JSON-log frame SHA-256 mismatch")
    return restored
