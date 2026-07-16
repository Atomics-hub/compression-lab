from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import struct
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple, Union

from .json_columnar import (
    compress as compress_columnar,
    decompress as decompress_columnar,
)
from .native import zstd_compress, zstd_decompress


FRAME_MAGIC = b"JLF2"
STREAM_MAGIC = b"JLS2"
VERSION = 1
MODE_DIRECT = 0
MODE_COLUMNAR = 1
FRAME_HEADER = struct.Struct(">4sBBHQQ32s32s")
STREAM_HEADER = struct.Struct(">4sBBHQ32s32sI")
SEGMENT_HEADER = struct.Struct(">QQ")
DEFAULT_SEGMENT_SIZE = 16 * 1024 * 1024
ZSTD_LEVEL = 6

TelemetryValue = Union[str, int, float, bool]


def _pack_frame(mode: int, source: bytes, payload: bytes) -> bytes:
    return FRAME_HEADER.pack(
        FRAME_MAGIC,
        VERSION,
        mode,
        0,
        len(source),
        len(payload),
        hashlib.sha256(source).digest(),
        hashlib.sha256(payload).digest(),
    ) + payload


def compress_frame(
    data: bytes,
) -> Tuple[bytes, Dict[str, TelemetryValue]]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        direct_future = executor.submit(zstd_compress, data, ZSTD_LEVEL)
        columnar_future = executor.submit(
            compress_columnar,
            data,
            level=ZSTD_LEVEL,
        )
        direct_payload = direct_future.result()
        columnar_payload, columnar_telemetry = columnar_future.result()
    direct_frame = _pack_frame(MODE_DIRECT, data, direct_payload)
    columnar_frame = _pack_frame(
        MODE_COLUMNAR,
        data,
        columnar_payload,
    )
    if len(columnar_frame) < len(direct_frame):
        selected = columnar_frame
        selected_mode = "columnar"
    else:
        selected = direct_frame
        selected_mode = "direct"
    return selected, {
        "selected_mode": selected_mode,
        "selected_bytes": len(selected),
        "direct_frame_bytes": len(direct_frame),
        "columnar_frame_bytes": len(columnar_frame),
        "direct_payload_bytes": len(direct_payload),
        "columnar_payload_bytes": len(columnar_payload),
        "no_expansion_vs_direct_frame": len(selected) <= len(direct_frame),
        "zstd_level": ZSTD_LEVEL,
        **{
            f"columnar_{key}": value
            for key, value in columnar_telemetry.items()
        },
    }


def decompress_frame(
    frame: bytes,
    *,
    max_output_size: Optional[int] = None,
) -> bytes:
    if len(frame) < FRAME_HEADER.size:
        raise ValueError("JLF2 frame is truncated")
    (
        magic,
        version,
        mode,
        reserved,
        original_size,
        payload_size,
        expected_sha256,
        expected_payload_sha256,
    ) = FRAME_HEADER.unpack_from(frame)
    if magic != FRAME_MAGIC:
        raise ValueError("JLF2 magic mismatch")
    if version != VERSION:
        raise ValueError(f"unsupported JLF2 version: {version}")
    if reserved != 0:
        raise ValueError("JLF2 reserved bits are nonzero")
    if payload_size != len(frame) - FRAME_HEADER.size:
        raise ValueError("JLF2 payload size mismatch")
    if max_output_size is not None and original_size > max_output_size:
        raise ValueError("JLF2 output exceeds safety limit")
    payload = frame[FRAME_HEADER.size :]
    if hashlib.sha256(payload).digest() != expected_payload_sha256:
        raise ValueError("JLF2 payload SHA-256 mismatch")
    try:
        if mode == MODE_DIRECT:
            restored = zstd_decompress(payload, original_size)
        elif mode == MODE_COLUMNAR:
            restored = decompress_columnar(
                payload,
                max_output_size=original_size,
            )
        else:
            raise ValueError(f"unsupported JLF2 mode: {mode}")
    except RuntimeError as error:
        raise ValueError(f"invalid JLF2 payload: {error}") from error
    if len(restored) != original_size:
        raise ValueError("JLF2 output size mismatch")
    if hashlib.sha256(restored).digest() != expected_sha256:
        raise ValueError("JLF2 original SHA-256 mismatch")
    return restored


def _segments(data: bytes, target_size: int) -> List[bytes]:
    if target_size < 1:
        raise ValueError("segment size must be positive")
    segments = []
    offset = 0
    while offset < len(data):
        target = min(len(data), offset + target_size)
        if target == len(data):
            end = len(data)
        else:
            newline = data.rfind(b"\n", offset, target)
            if newline >= offset:
                end = newline + 1
            else:
                following = data.find(b"\n", target)
                end = len(data) if following < 0 else following + 1
        if end <= offset:
            raise AssertionError("JSON-log segmenter did not advance")
        segments.append(data[offset:end])
        offset = end
    return segments


def _file_segments(source: BinaryIO, target_size: int) -> Iterator[bytes]:
    if target_size < 1:
        raise ValueError("segment size must be positive")
    buffer = bytearray()
    reached_eof = False
    while True:
        while len(buffer) < target_size and not reached_eof:
            chunk = source.read(target_size - len(buffer))
            if chunk:
                buffer.extend(chunk)
            else:
                reached_eof = True
        if not buffer:
            return
        if reached_eof:
            yield bytes(buffer)
            return
        newline = buffer.rfind(b"\n", 0, target_size)
        if newline >= 0:
            end = newline + 1
            yield bytes(buffer[:end])
            del buffer[:end]
            continue
        while True:
            newline = buffer.find(b"\n", target_size)
            if newline >= 0:
                end = newline + 1
                yield bytes(buffer[:end])
                del buffer[:end]
                break
            chunk = source.read(min(target_size, 1024 * 1024))
            if chunk:
                buffer.extend(chunk)
                continue
            reached_eof = True
            yield bytes(buffer)
            return


def compress(
    data: bytes,
    *,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> Tuple[bytes, Dict[str, TelemetryValue]]:
    source_segments = _segments(data, segment_size)
    encoded_segments = []
    details = []
    for segment in source_segments:
        encoded, detail = compress_frame(segment)
        encoded_segments.append(encoded)
        details.append(detail)
    payload = bytearray()
    for source, encoded in zip(source_segments, encoded_segments):
        payload.extend(SEGMENT_HEADER.pack(len(source), len(encoded)))
        payload.extend(encoded)
    output = (
        STREAM_HEADER.pack(
            STREAM_MAGIC,
            VERSION,
            0,
            0,
            len(data),
            hashlib.sha256(data).digest(),
            hashlib.sha256(payload).digest(),
            len(source_segments),
        )
        + payload
    )
    direct_segments = sum(
        detail["selected_mode"] == "direct" for detail in details
    )
    return output, {
        "segment_count": len(source_segments),
        "direct_segments": direct_segments,
        "columnar_segments": len(source_segments) - direct_segments,
        "selected_bytes": len(output),
        "segment_target_bytes": segment_size,
        "no_expansion_vs_direct_frame": all(
            bool(detail["no_expansion_vs_direct_frame"])
            for detail in details
        ),
    }


def compress_file(
    source_path: Path,
    destination_path: Path,
    *,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
) -> Dict[str, TelemetryValue]:
    temporary_path = destination_path.with_name(
        destination_path.name + ".partial"
    )
    original_size = 0
    segment_count = 0
    direct_segments = 0
    digest = hashlib.sha256()
    encoded_digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source, temporary_path.open("w+b") as output:
            output.write(
                STREAM_HEADER.pack(
                    STREAM_MAGIC,
                    VERSION,
                    0,
                    0,
                    0,
                    b"\0" * 32,
                    b"\0" * 32,
                    0,
                )
            )
            for segment in _file_segments(source, segment_size):
                digest.update(segment)
                original_size += len(segment)
                encoded, detail = compress_frame(segment)
                segment_header = SEGMENT_HEADER.pack(len(segment), len(encoded))
                output.write(segment_header)
                output.write(encoded)
                encoded_digest.update(segment_header)
                encoded_digest.update(encoded)
                segment_count += 1
                if detail["selected_mode"] == "direct":
                    direct_segments += 1
            output.seek(0)
            output.write(
                STREAM_HEADER.pack(
                    STREAM_MAGIC,
                    VERSION,
                    0,
                    0,
                    original_size,
                    digest.digest(),
                    encoded_digest.digest(),
                    segment_count,
                )
            )
            output.flush()
        temporary_path.replace(destination_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return {
        "original_bytes": original_size,
        "encoded_bytes": destination_path.stat().st_size,
        "segment_count": segment_count,
        "direct_segments": direct_segments,
        "columnar_segments": segment_count - direct_segments,
        "segment_target_bytes": segment_size,
    }


def decompress(
    data: bytes,
    *,
    max_output_size: Optional[int] = None,
) -> bytes:
    if len(data) < STREAM_HEADER.size:
        raise ValueError("JLS2 stream is truncated")
    (
        magic,
        version,
        flags,
        reserved,
        original_size,
        expected_sha256,
        expected_encoded_sha256,
        segment_count,
    ) = STREAM_HEADER.unpack_from(data)
    if magic != STREAM_MAGIC:
        raise ValueError("JLS2 magic mismatch")
    if version != VERSION:
        raise ValueError(f"unsupported JLS2 version: {version}")
    if flags != 0 or reserved != 0:
        raise ValueError("JLS2 flags or reserved bits are nonzero")
    if max_output_size is not None and original_size > max_output_size:
        raise ValueError("JLS2 output exceeds safety limit")
    if original_size == 0 and segment_count != 0:
        raise ValueError("empty JLS2 stream declares segments")
    if original_size > 0 and segment_count == 0:
        raise ValueError("nonempty JLS2 stream has no segments")
    if (
        hashlib.sha256(data[STREAM_HEADER.size :]).digest()
        != expected_encoded_sha256
    ):
        raise ValueError("JLS2 encoded SHA-256 mismatch")
    offset = STREAM_HEADER.size
    output = bytearray()
    for _ in range(segment_count):
        header_end = offset + SEGMENT_HEADER.size
        if header_end > len(data):
            raise ValueError("JLS2 segment header is truncated")
        segment_size, frame_size = SEGMENT_HEADER.unpack_from(data, offset)
        offset = header_end
        frame_end = offset + frame_size
        if frame_end > len(data):
            raise ValueError("JLS2 segment frame is truncated")
        if segment_size > original_size - len(output):
            raise ValueError("JLS2 segment exceeds declared output size")
        restored = decompress_frame(
            data[offset:frame_end],
            max_output_size=segment_size,
        )
        if len(restored) != segment_size:
            raise ValueError("JLS2 segment size mismatch")
        output.extend(restored)
        offset = frame_end
    if offset != len(data):
        raise ValueError("JLS2 stream has trailing data")
    if len(output) != original_size:
        raise ValueError("JLS2 output size mismatch")
    restored = bytes(output)
    if hashlib.sha256(restored).digest() != expected_sha256:
        raise ValueError("JLS2 original SHA-256 mismatch")
    return restored


def decompress_file(
    source_path: Path,
    destination_path: Path,
    *,
    max_output_size: Optional[int] = None,
) -> Dict[str, int]:
    temporary_path = destination_path.with_name(
        destination_path.name + ".partial"
    )
    encoded_size = source_path.stat().st_size
    try:
        with source_path.open("rb") as source:
            header = source.read(STREAM_HEADER.size)
            if len(header) != STREAM_HEADER.size:
                raise ValueError("JLS2 stream is truncated")
            (
                magic,
                version,
                flags,
                reserved,
                original_size,
                expected_sha256,
                expected_encoded_sha256,
                segment_count,
            ) = STREAM_HEADER.unpack(header)
            if magic != STREAM_MAGIC:
                raise ValueError("JLS2 magic mismatch")
            if version != VERSION:
                raise ValueError(f"unsupported JLS2 version: {version}")
            if flags != 0 or reserved != 0:
                raise ValueError("JLS2 flags or reserved bits are nonzero")
            if max_output_size is not None and original_size > max_output_size:
                raise ValueError("JLS2 output exceeds safety limit")
            if original_size == 0 and segment_count != 0:
                raise ValueError("empty JLS2 stream declares segments")
            if original_size > 0 and segment_count == 0:
                raise ValueError("nonempty JLS2 stream has no segments")
            restored_size = 0
            digest = hashlib.sha256()
            encoded_digest = hashlib.sha256()
            with temporary_path.open("wb") as output:
                for _ in range(segment_count):
                    segment_header = source.read(SEGMENT_HEADER.size)
                    if len(segment_header) != SEGMENT_HEADER.size:
                        raise ValueError("JLS2 segment header is truncated")
                    encoded_digest.update(segment_header)
                    segment_size, frame_size = SEGMENT_HEADER.unpack(
                        segment_header
                    )
                    if segment_size > original_size - restored_size:
                        raise ValueError(
                            "JLS2 segment exceeds declared output size"
                        )
                    if frame_size > encoded_size - source.tell():
                        raise ValueError("JLS2 segment frame is truncated")
                    frame = source.read(frame_size)
                    if len(frame) != frame_size:
                        raise ValueError("JLS2 segment frame is truncated")
                    encoded_digest.update(frame)
                    restored = decompress_frame(
                        frame,
                        max_output_size=segment_size,
                    )
                    if len(restored) != segment_size:
                        raise ValueError("JLS2 segment size mismatch")
                    output.write(restored)
                    digest.update(restored)
                    restored_size += len(restored)
                if source.read(1):
                    raise ValueError("JLS2 stream has trailing data")
            if restored_size != original_size:
                raise ValueError("JLS2 output size mismatch")
            if encoded_digest.digest() != expected_encoded_sha256:
                raise ValueError("JLS2 encoded SHA-256 mismatch")
            if digest.digest() != expected_sha256:
                raise ValueError("JLS2 original SHA-256 mismatch")
        temporary_path.replace(destination_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return {
        "encoded_bytes": source_path.stat().st_size,
        "restored_bytes": original_size,
        "segment_count": segment_count,
    }
