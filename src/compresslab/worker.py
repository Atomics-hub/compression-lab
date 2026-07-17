from __future__ import annotations

import argparse
import bz2
import gzip
import json
import lzma
import os
import shutil
import struct
import subprocess
import sys
import time
import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    import resource
except ImportError:  # pragma: no cover - exercised by Windows CI
    resource = None  # type: ignore[assignment]

from .adaptive_v3 import (
    BACKEND_SEGMENTED as BACKEND_SEGMENTED_V3,
    VERSION as ADAPTIVE_VERSION_V3,
    compress as _v3_compress,
    decompress as _v3_decompress,
)
from .codecs import codec_by_id
from .json_log_codec import (
    DEFAULT_SEGMENT_SIZE as JLS2_SEGMENT_SIZE,
    compress_file as _jls2_compress_file,
    decompress_file as _jls2_decompress_file,
)
from .native import (
    delta_transpose as _native_delta_transpose,
    inverse_delta_transpose as _native_inverse_delta_transpose,
    native_available,
    structured_text_zstd_stream_decode,
    structured_text_zstd_stream_decode_into,
    tabular_native_available,
    zstd_available,
    zstd_compress,
    zstd_decompress,
    zstd_engine,
    zstd_ffi_available,
)
from .tabular_transform import (
    compress_dense_auto_with_metadata as _tbl1_dense_compress,
    compress_auto_with_metadata as _tbl1_compress,
    decompress as _tbl1_decompress,
    frame_backend as _tbl1_frame_backend,
    frame_delimiter as _tbl1_frame_delimiter,
    compress_stream as _tbl1_stream_compress,
    decompress_stream as _tbl1_stream_decompress,
)


ADAPTIVE_MAGIC = b"CLAB"
ADAPTIVE_VERSION_V1 = 1
ADAPTIVE_VERSION_V2 = 2
ADAPTIVE_HEADER = struct.Struct(">4sBBQ32s")
BACKEND_STORE = 0
BACKEND_GZIP_1 = 1
BACKEND_DELTA_TRANSPOSE_GZIP_1 = 2
BACKEND_ZSTD_3 = 3
BACKEND_LZ4_1 = 4
BACKEND_DELTA_TRANSPOSE_ZSTD_3 = 5


def _rss_bytes(usage: Any) -> int:
    if resource is None:
        return 0
    value = int(usage.ru_maxrss)
    # macOS reports bytes; Linux and most BSDs report KiB.
    if sys.platform == "darwin":
        return value
    return value * 1024


def _cpu_time_ns() -> int:
    """CPU consumed by this worker plus completed external codec children."""
    if resource is None:
        return time.process_time_ns()
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    seconds = own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime
    return int(seconds * 1_000_000_000)


def _peak_rss_bytes() -> int:
    if resource is None:
        return 0
    return max(
        _rss_bytes(resource.getrusage(resource.RUSAGE_SELF)),
        _rss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN)),
    )


def _copy(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def _compressor(implementation: str, level: int) -> Callable[[bytes], bytes]:
    if implementation == "gzip":
        return lambda data: gzip.compress(data, compresslevel=level, mtime=0)
    if implementation == "bz2":
        return lambda data: bz2.compress(data, compresslevel=level)
    if implementation == "lzma":
        return lambda data: lzma.compress(data, format=lzma.FORMAT_XZ, preset=level)
    raise ValueError(f"Unsupported implementation: {implementation}")


def _decompressor(implementation: str) -> Callable[[bytes], bytes]:
    if implementation == "gzip":
        return gzip.decompress
    if implementation == "bz2":
        return bz2.decompress
    if implementation == "lzma":
        return lzma.decompress
    raise ValueError(f"Unsupported implementation: {implementation}")


def _representative_sample(data: bytes, total_size: int = 16 * 1024) -> bytes:
    if len(data) <= total_size:
        return data
    block_size = max(1, total_size // 3)
    middle = max(0, len(data) // 2 - block_size // 2)
    tail_size = total_size - 2 * block_size
    return data[:block_size] + data[middle : middle + block_size] + data[-tail_size:]


def _python_delta_transpose(data: bytes) -> bytes:
    word_count = len(data) // 4
    core_size = word_count * 4
    if word_count == 0:
        return data
    planes = [bytearray(word_count) for _ in range(4)]
    previous = 0
    for index in range(word_count):
        value = struct.unpack_from("<I", data, index * 4)[0]
        delta = (value - previous) & 0xFFFFFFFF
        previous = value
        planes[0][index] = delta & 0xFF
        planes[1][index] = (delta >> 8) & 0xFF
        planes[2][index] = (delta >> 16) & 0xFF
        planes[3][index] = (delta >> 24) & 0xFF
    return b"".join(planes) + data[core_size:]


def _python_inverse_delta_transpose(data: bytes, original_size: int) -> bytes:
    if len(data) != original_size:
        raise ValueError("transformed payload size mismatch")
    word_count = original_size // 4
    core_size = word_count * 4
    if word_count == 0:
        return data
    output = bytearray(original_size)
    previous = 0
    for index in range(word_count):
        delta = (
            data[index]
            | (data[word_count + index] << 8)
            | (data[2 * word_count + index] << 16)
            | (data[3 * word_count + index] << 24)
        )
        value = (previous + delta) & 0xFFFFFFFF
        struct.pack_into("<I", output, index * 4, value)
        previous = value
    output[core_size:] = data[core_size:]
    return bytes(output)


def _delta_transpose(data: bytes) -> bytes:
    if native_available():
        return _native_delta_transpose(data)
    return _python_delta_transpose(data)


def _inverse_delta_transpose(data: bytes, original_size: int) -> bytes:
    if len(data) != original_size:
        raise ValueError("transformed payload size mismatch")
    if native_available():
        return _native_inverse_delta_transpose(data)
    return _python_inverse_delta_transpose(data, original_size)


def _codec_filter(codec_id: str, operation: str, data: bytes) -> bytes:
    codec = codec_by_id(codec_id)
    if not codec.available or not codec.executable:
        raise RuntimeError(f"native codec is unavailable: {codec_id}")
    if codec.implementation == "external-zstd":
        arguments = (
            ["-q", f"-{codec.level}", "-c"]
            if operation == "compress"
            else ["-q", "-d", "-c"]
        )
    elif codec.implementation == "external-lz4":
        arguments = (
            ["-q", f"-{codec.level}", "-c"]
            if operation == "compress"
            else ["-q", "-d", "-c"]
        )
    else:
        raise ValueError(f"codec does not support filter mode: {codec_id}")
    completed = subprocess.run(
        [codec.executable, *arguments],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"{codec_id} {operation} exited {completed.returncode}: {detail}"
        )
    return completed.stdout


def _v2_zstd_compress(data: bytes) -> bytes:
    if zstd_available():
        return zstd_compress(data, level=3)
    return _codec_filter("zstd-3", "compress", data)


def _v2_zstd_decompress(data: bytes, expected_size: int) -> bytes:
    if zstd_available():
        return zstd_decompress(data, expected_size)
    return _codec_filter("zstd-3", "decompress", data)


def _v2_codec_engine(backend: int) -> str:
    if backend in {BACKEND_ZSTD_3, BACKEND_DELTA_TRANSPOSE_ZSTD_3}:
        return zstd_engine()
    if backend == BACKEND_LZ4_1:
        return "lz4-cli"
    return "store"


def _adaptive_compress(
    data: bytes, allow_transform: bool = False
) -> tuple[bytes, dict]:
    selector_start = time.perf_counter_ns()
    sample = _representative_sample(data, 16 * 1024)
    sample_compressed = gzip.compress(sample, compresslevel=1, mtime=0)
    sample_ratio = len(sample_compressed) / len(sample) if sample else 1.0
    selected = BACKEND_GZIP_1 if sample_ratio < 0.985 else BACKEND_STORE
    transformed_sample_ratio = 1.0
    selector_stages = 1
    sampled_bytes = len(sample)
    if allow_transform and len(sample) >= 16:
        transformed_sample = _delta_transpose(sample)
        transformed_compressed = gzip.compress(
            transformed_sample, compresslevel=1, mtime=0
        )
        transformed_sample_ratio = (
            len(transformed_compressed) / len(sample) if sample else 1.0
        )
        transform_gain = len(transformed_compressed) / max(1, len(sample_compressed))
        if transform_gain < 0.94:
            selected = BACKEND_DELTA_TRANSPOSE_GZIP_1
        elif transform_gain <= 1.03 and len(data) > len(sample):
            selector_stages = 2
            sample = _representative_sample(data, 32 * 1024)
            sampled_bytes += len(sample)
            sample_compressed = gzip.compress(sample, compresslevel=1, mtime=0)
            sample_ratio = len(sample_compressed) / len(sample) if sample else 1.0
            transformed_sample = _delta_transpose(sample)
            transformed_compressed = gzip.compress(
                transformed_sample, compresslevel=1, mtime=0
            )
            transformed_sample_ratio = len(transformed_compressed) / len(sample)
            if len(transformed_compressed) < len(sample_compressed) * 0.97:
                selected = BACKEND_DELTA_TRANSPOSE_GZIP_1
            else:
                selected = BACKEND_GZIP_1 if sample_ratio < 0.985 else BACKEND_STORE
    selector_ns = time.perf_counter_ns() - selector_start

    if selected == BACKEND_GZIP_1:
        payload = gzip.compress(data, compresslevel=1, mtime=0)
    elif selected == BACKEND_DELTA_TRANSPOSE_GZIP_1:
        payload = gzip.compress(_delta_transpose(data), compresslevel=1, mtime=0)
    else:
        payload = data
    if selected != BACKEND_STORE:
        if len(payload) >= len(data):
            selected = BACKEND_STORE
            payload = data

    header = ADAPTIVE_HEADER.pack(
        ADAPTIVE_MAGIC,
        ADAPTIVE_VERSION_V1,
        selected,
        len(data),
        hashlib.sha256(data).digest(),
    )
    return header + payload, {
        "selected_backend": {
            BACKEND_STORE: "store",
            BACKEND_GZIP_1: "gzip-1",
            BACKEND_DELTA_TRANSPOSE_GZIP_1: "delta-transpose+gzip-1",
        }[selected],
        "selector_ns": selector_ns,
        "sample_ratio": sample_ratio,
        "transformed_sample_ratio": transformed_sample_ratio,
        "selector_stages": selector_stages,
        "selector_sample_bytes": sampled_bytes,
        "transform_engine": "rust" if native_available() else "python-fallback",
        "frame_overhead_bytes": ADAPTIVE_HEADER.size,
    }


def _v2_balanced_backend(sample_ratio: float) -> tuple[int, str]:
    if sample_ratio >= 0.97:
        return BACKEND_STORE, "sample-near-incompressible"
    return BACKEND_ZSTD_3, "compressible-balanced"


def _adaptive_v2_compress(data: bytes) -> tuple[bytes, dict]:
    selector_start = time.perf_counter_ns()
    sample = _representative_sample(data, 16 * 1024)
    sample_compressed = gzip.compress(sample, compresslevel=1, mtime=0)
    sample_ratio = len(sample_compressed) / len(sample) if sample else 1.0
    selected, selector_reason = _v2_balanced_backend(sample_ratio)
    transformed_sample_ratio = 1.0
    selector_stages = 1
    sampled_bytes = len(sample)

    if len(sample) >= 16:
        transformed_sample = _delta_transpose(sample)
        transformed_compressed = gzip.compress(
            transformed_sample, compresslevel=1, mtime=0
        )
        transformed_sample_ratio = len(transformed_compressed) / len(sample)
        transform_gain = len(transformed_compressed) / max(1, len(sample_compressed))
        if transform_gain < 0.94:
            selected = BACKEND_DELTA_TRANSPOSE_ZSTD_3
            selector_reason = "numeric-transform-clear-win"
        elif transform_gain <= 1.03 and len(data) > len(sample):
            selector_stages = 2
            sample = _representative_sample(data, 32 * 1024)
            sampled_bytes += len(sample)
            sample_compressed = gzip.compress(sample, compresslevel=1, mtime=0)
            sample_ratio = len(sample_compressed) / len(sample) if sample else 1.0
            transformed_sample = _delta_transpose(sample)
            transformed_compressed = gzip.compress(
                transformed_sample, compresslevel=1, mtime=0
            )
            transformed_sample_ratio = len(transformed_compressed) / len(sample)
            if len(transformed_compressed) < len(sample_compressed) * 0.97:
                selected = BACKEND_DELTA_TRANSPOSE_ZSTD_3
                selector_reason = "numeric-transform-confirmed"
            else:
                selected, selector_reason = _v2_balanced_backend(sample_ratio)
    selector_ns = time.perf_counter_ns() - selector_start

    if selected == BACKEND_ZSTD_3:
        payload = _v2_zstd_compress(data)
    elif selected == BACKEND_LZ4_1:
        payload = _codec_filter("lz4-1", "compress", data)
    elif selected == BACKEND_DELTA_TRANSPOSE_ZSTD_3:
        payload = _v2_zstd_compress(_delta_transpose(data))
    else:
        payload = data
    if selected != BACKEND_STORE and len(payload) >= len(data):
        selected = BACKEND_STORE
        payload = data
        selector_reason = "full-output-expansion-fallback"

    header = ADAPTIVE_HEADER.pack(
        ADAPTIVE_MAGIC,
        ADAPTIVE_VERSION_V2,
        selected,
        len(data),
        hashlib.sha256(data).digest(),
    )
    return header + payload, {
        "selected_backend": {
            BACKEND_STORE: "store",
            BACKEND_ZSTD_3: "zstd-3",
            BACKEND_LZ4_1: "lz4-1",
            BACKEND_DELTA_TRANSPOSE_ZSTD_3: "delta-transpose+zstd-3",
        }[selected],
        "selector_ns": selector_ns,
        "sample_ratio": sample_ratio,
        "transformed_sample_ratio": transformed_sample_ratio,
        "selector_stages": selector_stages,
        "selector_sample_bytes": sampled_bytes,
        "selector_reason": selector_reason,
        "transform_engine": "rust" if native_available() else "python-fallback",
        "codec_engine": _v2_codec_engine(selected),
        "frame_overhead_bytes": ADAPTIVE_HEADER.size,
    }


def _adaptive_v3_compress(data: bytes) -> tuple[bytes, dict]:
    return _v3_compress(
        data,
        zstd_encode=_v2_zstd_compress,
        delta_transpose=_delta_transpose,
        transform_engine="rust" if native_available() else "python-fallback",
        codec_engine=zstd_engine(),
    )


def _adaptive_v3_decompress(
    encoded: bytes, max_output_size: Optional[int] = None
) -> tuple[bytes, dict]:
    return _v3_decompress(
        encoded,
        zstd_decode=_v2_zstd_decompress,
        inverse_delta_transpose=_inverse_delta_transpose,
        structured_text_zstd_decode=(
            structured_text_zstd_stream_decode
            if native_available() and zstd_ffi_available()
            else None
        ),
        structured_text_zstd_decode_into=(
            structured_text_zstd_stream_decode_into
            if native_available() and zstd_ffi_available()
            else None
        ),
        transform_engine="rust" if native_available() else "python-fallback",
        codec_engine=zstd_engine(),
        max_output_size=max_output_size,
    )


def _adaptive_decompress(
    encoded: bytes, max_output_size: Optional[int] = None
) -> tuple[bytes, dict]:
    if len(encoded) < ADAPTIVE_HEADER.size:
        raise ValueError("adaptive frame is truncated")
    magic, version, backend, original_size, expected_hash = ADAPTIVE_HEADER.unpack(
        encoded[: ADAPTIVE_HEADER.size]
    )
    if magic != ADAPTIVE_MAGIC:
        raise ValueError("adaptive frame magic mismatch")
    if max_output_size is not None and original_size > max_output_size:
        raise ValueError(
            f"adaptive output exceeds safety limit: {original_size} > {max_output_size}"
        )
    if version == ADAPTIVE_VERSION_V3:
        if backend != BACKEND_SEGMENTED_V3:
            raise ValueError(f"unsupported adaptive-v3 backend: {backend}")
        return _adaptive_v3_decompress(encoded, max_output_size=max_output_size)
    if version not in {ADAPTIVE_VERSION_V1, ADAPTIVE_VERSION_V2}:
        raise ValueError(f"unsupported adaptive frame version: {version}")
    payload = encoded[ADAPTIVE_HEADER.size :]
    if backend == BACKEND_STORE:
        data = payload
        selected_backend = "store"
    elif version == ADAPTIVE_VERSION_V1 and backend == BACKEND_GZIP_1:
        data = gzip.decompress(payload)
        selected_backend = "gzip-1"
    elif version == ADAPTIVE_VERSION_V1 and backend == BACKEND_DELTA_TRANSPOSE_GZIP_1:
        transformed = gzip.decompress(payload)
        data = _inverse_delta_transpose(transformed, original_size)
        selected_backend = "delta-transpose+gzip-1"
    elif version == ADAPTIVE_VERSION_V2 and backend == BACKEND_ZSTD_3:
        data = _v2_zstd_decompress(payload, original_size)
        selected_backend = "zstd-3"
    elif version == ADAPTIVE_VERSION_V2 and backend == BACKEND_LZ4_1:
        data = _codec_filter("lz4-1", "decompress", payload)
        selected_backend = "lz4-1"
    elif version == ADAPTIVE_VERSION_V2 and backend == BACKEND_DELTA_TRANSPOSE_ZSTD_3:
        transformed = _v2_zstd_decompress(payload, original_size)
        data = _inverse_delta_transpose(transformed, original_size)
        selected_backend = "delta-transpose+zstd-3"
    else:
        raise ValueError(f"unsupported adaptive backend: {backend}")
    if len(data) != original_size:
        raise ValueError("adaptive frame original-size mismatch")
    if hashlib.sha256(data).digest() != expected_hash:
        raise ValueError("adaptive frame SHA-256 mismatch")
    return data, {
        "selected_backend": selected_backend,
        "selector_ns": 0,
        "transform_engine": "rust" if native_available() else "python-fallback",
        "codec_engine": (
            _v2_codec_engine(backend)
            if version == ADAPTIVE_VERSION_V2
            else "python-stdlib"
        ),
    }


def _external_command(
    codec, operation: str, source: Path, destination: Path
) -> list[str]:
    executable = codec.executable or {
        "external-zstd": "zstd",
        "external-lz4": "lz4",
        "external-brotli": "brotli",
        "external-7zip": "7zz",
    }.get(codec.implementation, codec.implementation)
    if codec.implementation == "external-zstd":
        if operation == "compress":
            return [
                executable,
                "-q",
                "-f",
                f"-{codec.level}",
                str(source),
                "-o",
                str(destination),
            ]
        return [executable, "-q", "-d", "-f", str(source), "-o", str(destination)]
    if codec.implementation == "external-lz4":
        if operation == "compress":
            return [
                executable,
                "-q",
                "-f",
                f"-{codec.level}",
                str(source),
                str(destination),
            ]
        return [executable, "-q", "-d", "-f", str(source), str(destination)]
    if codec.implementation == "external-brotli":
        if operation == "compress":
            return [
                executable,
                "-f",
                "-q",
                str(codec.level),
                "-o",
                str(destination),
                str(source),
            ]
        return [executable, "-f", "-d", "-o", str(destination), str(source)]
    if codec.implementation == "external-7zip":
        if operation == "compress":
            return [
                executable,
                "a",
                "-t7z",
                "-bd",
                "-bb0",
                "-y",
                f"-mx={codec.level}",
                str(destination),
                str(source),
            ]
        return [executable, "e", "-bd", "-bb0", "-y", "-so", str(source)]
    raise ValueError(f"Unsupported external implementation: {codec.implementation}")


def _run_external(codec, operation: str, source: Path, destination: Path) -> dict:
    command = _external_command(codec, operation, source, destination)
    if codec.implementation == "external-7zip" and operation == "decompress":
        with destination.open("wb") as output:
            binary_result = subprocess.run(
                command, stdout=output, stderr=subprocess.PIPE, check=False
            )
        stdout = ""
        stderr = binary_result.stderr.decode("utf-8", errors="replace")
        returncode = binary_result.returncode
    else:
        text_result = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
        stdout = text_result.stdout
        stderr = text_result.stderr
        returncode = text_result.returncode
    if returncode != 0:
        detail = stderr.strip() or stdout.strip()
        raise RuntimeError(f"external codec exited {returncode}: {detail}")
    return {
        "selected_backend": codec.id,
        "selector_ns": 0,
        "codec_engine": f"{codec.implementation}-cli",
    }


def _run_zstd_ffi(codec, operation: str, source: Path, destination: Path) -> dict:
    data = source.read_bytes()
    if operation == "compress":
        output = zstd_compress(data, level=codec.level)
    elif operation == "decompress":
        output = zstd_decompress(data)
    else:
        raise ValueError(f"Unsupported operation: {operation}")
    destination.write_bytes(output)
    return {
        "selected_backend": codec.id,
        "selector_ns": 0,
        "codec_engine": zstd_engine(),
    }


def run(codec_id: str, operation: str, source: Path, destination: Path) -> dict:
    codec = codec_by_id(codec_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wall_start = time.perf_counter_ns()
    cpu_start = _cpu_time_ns()

    detail: Dict[str, Any] = {}
    if codec.implementation == "store":
        _copy(source, destination)
    elif codec.implementation == "jls2":
        if operation == "compress":
            compression_telemetry = _jls2_compress_file(
                source,
                destination,
                segment_size=JLS2_SEGMENT_SIZE,
                overwrite=True,
            )
            segment_count = int(compression_telemetry["segment_count"])
            direct_segments = int(compression_telemetry["direct_segments"])
            detail = {
                "selected_backend": "jls2",
                "selector_ns": 0,
                "transform_engine": (
                    "rust" if native_available() else "python-fallback"
                ),
                "codec_engine": zstd_engine(),
                "stream_segment_size": JLS2_SEGMENT_SIZE,
                "stream_concurrency": 2,
                "segment_count": segment_count,
                "candidate_segment_count": segment_count,
                "transformed_segments": int(compression_telemetry["columnar_segments"]),
                "direct_segments": direct_segments,
                "direct_fallback_compared_segments": segment_count,
                "direct_fallback_selected_segments": direct_segments,
            }
        elif operation == "decompress":
            decompression_telemetry = _jls2_decompress_file(
                source,
                destination,
                overwrite=True,
            )
            detail = {
                "selected_backend": "jls2-decode",
                "selector_ns": 0,
                "transform_engine": (
                    "rust" if native_available() else "python-fallback"
                ),
                "codec_engine": zstd_engine(),
                "stream_segment_size": JLS2_SEGMENT_SIZE,
                "stream_concurrency": 2,
                "segment_count": int(decompression_telemetry["segment_count"]),
            }
        else:
            raise ValueError(f"Unsupported operation: {operation}")
    elif codec.implementation in {
        "adaptive-v0",
        "adaptive-v1",
        "adaptive-v2",
        "adaptive-v3",
    }:
        if operation == "compress":
            if codec.implementation == "adaptive-v3":
                output, detail = _adaptive_v3_compress(source.read_bytes())
            elif codec.implementation == "adaptive-v2":
                output, detail = _adaptive_v2_compress(source.read_bytes())
            else:
                output, detail = _adaptive_compress(
                    source.read_bytes(),
                    allow_transform=codec.implementation == "adaptive-v1",
                )
        else:
            output, detail = _adaptive_decompress(source.read_bytes())
        destination.write_bytes(output)
    elif codec.implementation == "tbl1-stream-dense":
        if operation == "compress":
            detail = _tbl1_stream_compress(source, destination)
        elif operation == "decompress":
            detail = _tbl1_stream_decompress(source, destination)
        else:
            raise ValueError(f"Unsupported operation: {operation}")
        detail.update(
            {
                "transform_engine": (
                    "rust" if tabular_native_available() else "python-fallback"
                ),
                "codec_engine": zstd_engine(),
            }
        )
    elif codec.implementation in {"tbl1", "tbl1-dense"}:
        if operation == "compress":
            if codec.implementation == "tbl1-dense":
                output, selector_detail = _tbl1_dense_compress(source.read_bytes())
            else:
                output, selector_detail = _tbl1_compress(
                    source.read_bytes(), level=codec.level
                )
            detail = {
                "selected_backend": _tbl1_frame_backend(output),
                "transform_engine": (
                    "rust" if tabular_native_available() else "python-fallback"
                ),
                "codec_engine": zstd_engine(),
                "delimiter": _tbl1_frame_delimiter(output),
                **selector_detail,
            }
        elif operation == "decompress":
            output = _tbl1_decompress(source.read_bytes())
            detail = {
                "selected_backend": "tbl1-decode",
                "selector_ns": 0,
                "transform_engine": (
                    "rust" if tabular_native_available() else "python-fallback"
                ),
                "codec_engine": zstd_engine(),
            }
        else:
            raise ValueError(f"Unsupported operation: {operation}")
        destination.write_bytes(output)
    elif codec.implementation == "external-zstd" and zstd_available():
        detail = _run_zstd_ffi(codec, operation, source, destination)
    elif codec.implementation.startswith("external-"):
        detail = _run_external(codec, operation, source, destination)
    elif operation == "compress":
        destination.write_bytes(
            _compressor(codec.implementation, codec.level)(source.read_bytes())
        )
    elif operation == "decompress":
        destination.write_bytes(
            _decompressor(codec.implementation)(source.read_bytes())
        )
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    return {
        "codec_id": codec.id,
        "operation": operation,
        "wall_ns": time.perf_counter_ns() - wall_start,
        "cpu_ns": _cpu_time_ns() - cpu_start,
        "peak_rss_bytes": _peak_rss_bytes(),
        "input_bytes": source.stat().st_size,
        "output_bytes": destination.stat().st_size,
        "pid": os.getpid(),
        **detail,
    }


def _run_batch(
    codec_id: str,
    operation: str,
    source: Path,
    destination: Path,
    minimum_duration_ns: int,
    max_iterations: int,
) -> dict:
    if minimum_duration_ns < 0:
        raise ValueError("minimum batch duration cannot be negative")
    if max_iterations < 1:
        raise ValueError("maximum batch iterations must be at least 1")

    results = []
    total_worker_wall_ns = 0
    while True:
        telemetry = run(codec_id, operation, source, destination)
        results.append(telemetry)
        total_worker_wall_ns += int(telemetry["wall_ns"])
        if (
            total_worker_wall_ns >= minimum_duration_ns
            or len(results) >= max_iterations
        ):
            break

    backends = {str(row.get("selected_backend", "")) for row in results}
    if len(backends) > 1:
        raise RuntimeError(f"batched selector was nondeterministic: {sorted(backends)}")

    aggregate = dict(results[-1])
    iterations = len(results)
    for field in ("wall_ns", "cpu_ns", "selector_ns"):
        aggregate[field] = int(
            sum(int(row.get(field, 0)) for row in results) / iterations
        )
    aggregate["peak_rss_bytes"] = max(
        int(row.get("peak_rss_bytes", 0)) for row in results
    )
    aggregate["batch_iterations"] = iterations
    aggregate["batch_target_ns"] = minimum_duration_ns
    aggregate["batch_total_worker_wall_ns"] = total_worker_wall_ns
    aggregate["batch_target_met"] = total_worker_wall_ns >= minimum_duration_ns
    return aggregate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server",
        action="store_true",
        help="serve newline-delimited JSON requests on stdin/stdout",
    )
    parser.add_argument("--codec")
    parser.add_argument("--operation", choices=("compress", "decompress"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--telemetry", type=Path)
    return parser


def _serve() -> int:
    """Run requests without paying Python import/startup cost for every trial."""
    sys.stdout.write(json.dumps({"ready": True}, sort_keys=True) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("request_id", ""))
            if request.get("command") == "shutdown":
                response = {"request_id": request_id, "shutdown": True}
                sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
                sys.stdout.flush()
                return 0
            telemetry = _run_batch(
                str(request["codec"]),
                str(request["operation"]),
                Path(request["source"]),
                Path(request["destination"]),
                int(request.get("minimum_duration_ns", 0)),
                int(request.get("max_iterations", 1)),
            )
            response = {"request_id": request_id, "telemetry": telemetry}
        except Exception as exc:
            response = {
                "request_id": request_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.server:
        return _serve()
    missing = [
        name
        for name in ("codec", "operation", "source", "destination", "telemetry")
        if getattr(args, name) is None
    ]
    if missing:
        raise SystemExit(f"missing required arguments: {', '.join(missing)}")
    try:
        telemetry = run(args.codec, args.operation, args.source, args.destination)
        args.telemetry.parent.mkdir(parents=True, exist_ok=True)
        args.telemetry.write_text(
            json.dumps(telemetry, sort_keys=True), encoding="utf-8"
        )
        return 0
    except Exception as exc:
        args.telemetry.parent.mkdir(parents=True, exist_ok=True)
        args.telemetry.write_text(
            json.dumps({"error": f"{type(exc).__name__}: {exc}"}, sort_keys=True),
            encoding="utf-8",
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
