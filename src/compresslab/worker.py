from __future__ import annotations

import argparse
import bz2
import gzip
import json
import lzma
import os
import resource
import shutil
import struct
import subprocess
import sys
import time
import hashlib
from pathlib import Path
from typing import Callable

from .codecs import codec_by_id


ADAPTIVE_MAGIC = b"CLAB"
ADAPTIVE_VERSION = 1
ADAPTIVE_HEADER = struct.Struct(">4sBBQ32s")
BACKEND_STORE = 0
BACKEND_GZIP_1 = 1
BACKEND_DELTA_TRANSPOSE_GZIP_1 = 2


def _rss_bytes(usage: resource.struct_rusage) -> int:
    value = int(usage.ru_maxrss)
    # macOS reports bytes; Linux and most BSDs report KiB.
    if sys.platform == "darwin":
        return value
    return value * 1024


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


def _representative_sample(data: bytes, block_size: int = 64 * 1024) -> bytes:
    if len(data) <= block_size * 3:
        return data
    middle = max(0, len(data) // 2 - block_size // 2)
    return data[:block_size] + data[middle:middle + block_size] + data[-block_size:]


def _delta_transpose(data: bytes) -> bytes:
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


def _inverse_delta_transpose(data: bytes, original_size: int) -> bytes:
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


def _adaptive_compress(data: bytes, allow_transform: bool = False) -> tuple[bytes, dict]:
    selector_start = time.perf_counter_ns()
    sample = _representative_sample(data)
    sample_compressed = gzip.compress(sample, compresslevel=1, mtime=0)
    sample_ratio = len(sample_compressed) / len(sample) if sample else 1.0
    selected = BACKEND_GZIP_1 if sample_ratio < 0.985 else BACKEND_STORE
    transformed_sample_ratio = 1.0
    if allow_transform and selected == BACKEND_GZIP_1 and len(sample) >= 16:
        transformed_sample = _delta_transpose(sample)
        transformed_compressed = gzip.compress(
            transformed_sample, compresslevel=1, mtime=0
        )
        transformed_sample_ratio = (
            len(transformed_compressed) / len(sample) if sample else 1.0
        )
        if len(transformed_compressed) < len(sample_compressed) * 0.97:
            selected = BACKEND_DELTA_TRANSPOSE_GZIP_1
    selector_ns = time.perf_counter_ns() - selector_start

    if selected == BACKEND_GZIP_1:
        payload = gzip.compress(data, compresslevel=1, mtime=0)
    elif selected == BACKEND_DELTA_TRANSPOSE_GZIP_1:
        payload = gzip.compress(
            _delta_transpose(data), compresslevel=1, mtime=0
        )
    else:
        payload = data
    if selected != BACKEND_STORE:
        if len(payload) >= len(data):
            selected = BACKEND_STORE
            payload = data

    header = ADAPTIVE_HEADER.pack(
        ADAPTIVE_MAGIC,
        ADAPTIVE_VERSION,
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
        "frame_overhead_bytes": ADAPTIVE_HEADER.size,
    }


def _adaptive_decompress(encoded: bytes) -> tuple[bytes, dict]:
    if len(encoded) < ADAPTIVE_HEADER.size:
        raise ValueError("adaptive frame is truncated")
    magic, version, backend, original_size, expected_hash = ADAPTIVE_HEADER.unpack(
        encoded[:ADAPTIVE_HEADER.size]
    )
    if magic != ADAPTIVE_MAGIC:
        raise ValueError("adaptive frame magic mismatch")
    if version != ADAPTIVE_VERSION:
        raise ValueError(f"unsupported adaptive frame version: {version}")
    payload = encoded[ADAPTIVE_HEADER.size:]
    if backend == BACKEND_STORE:
        data = payload
        selected_backend = "store"
    elif backend == BACKEND_GZIP_1:
        data = gzip.decompress(payload)
        selected_backend = "gzip-1"
    elif backend == BACKEND_DELTA_TRANSPOSE_GZIP_1:
        transformed = gzip.decompress(payload)
        data = _inverse_delta_transpose(transformed, original_size)
        selected_backend = "delta-transpose+gzip-1"
    else:
        raise ValueError(f"unsupported adaptive backend: {backend}")
    if len(data) != original_size:
        raise ValueError("adaptive frame original-size mismatch")
    if hashlib.sha256(data).digest() != expected_hash:
        raise ValueError("adaptive frame SHA-256 mismatch")
    return data, {"selected_backend": selected_backend, "selector_ns": 0}


def _external_command(codec, operation: str, source: Path, destination: Path) -> list[str]:
    if codec.implementation == "external-zstd":
        if operation == "compress":
            return ["zstd", "-q", "-f", f"-{codec.level}", str(source), "-o", str(destination)]
        return ["zstd", "-q", "-d", "-f", str(source), "-o", str(destination)]
    if codec.implementation == "external-lz4":
        if operation == "compress":
            return ["lz4", "-q", "-f", f"-{codec.level}", str(source), str(destination)]
        return ["lz4", "-q", "-d", "-f", str(source), str(destination)]
    if codec.implementation == "external-brotli":
        if operation == "compress":
            return [
                "brotli", "-f", "-q", str(codec.level), "-o", str(destination), str(source)
            ]
        return ["brotli", "-f", "-d", "-o", str(destination), str(source)]
    raise ValueError(f"Unsupported external implementation: {codec.implementation}")


def _run_external(codec, operation: str, source: Path, destination: Path) -> dict:
    completed = subprocess.run(
        _external_command(codec, operation, source, destination),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"external codec exited {completed.returncode}: {detail}")
    return {"selected_backend": codec.id, "selector_ns": 0}


def run(codec_id: str, operation: str, source: Path, destination: Path) -> dict:
    codec = codec_by_id(codec_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()

    detail = {}
    if codec.implementation == "store":
        _copy(source, destination)
    elif codec.implementation in {"adaptive-v0", "adaptive-v1"}:
        if operation == "compress":
            output, detail = _adaptive_compress(
                source.read_bytes(),
                allow_transform=codec.implementation == "adaptive-v1",
            )
        else:
            output, detail = _adaptive_decompress(source.read_bytes())
        destination.write_bytes(output)
    elif codec.implementation.startswith("external-"):
        detail = _run_external(codec, operation, source, destination)
    elif operation == "compress":
        destination.write_bytes(_compressor(codec.implementation, codec.level)(source.read_bytes()))
    elif operation == "decompress":
        destination.write_bytes(_decompressor(codec.implementation)(source.read_bytes()))
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    return {
        "codec_id": codec.id,
        "operation": operation,
        "wall_ns": time.perf_counter_ns() - wall_start,
        "cpu_ns": time.process_time_ns() - cpu_start,
        "peak_rss_bytes": max(
            _rss_bytes(resource.getrusage(resource.RUSAGE_SELF)),
            _rss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN)),
        ),
        "input_bytes": source.stat().st_size,
        "output_bytes": destination.stat().st_size,
        "pid": os.getpid(),
        **detail,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codec", required=True)
    parser.add_argument("--operation", choices=("compress", "decompress"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        telemetry = run(args.codec, args.operation, args.source, args.destination)
        args.telemetry.parent.mkdir(parents=True, exist_ok=True)
        args.telemetry.write_text(json.dumps(telemetry, sort_keys=True), encoding="utf-8")
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
