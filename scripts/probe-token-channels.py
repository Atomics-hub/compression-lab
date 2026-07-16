#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import struct
import sys
import time
from typing import Callable, Iterable, Tuple

from compresslab.native import (
    structured_text_decode_channels as native_decode_channels,
    structured_text_encode,
    structured_text_split_channels as native_split_channels,
    zstd_compress,
    zstd_decompress,
)
from compresslab.structured_text import (
    DICTIONARY_SAMPLE_BYTES,
    ESCAPED_MARKER,
    HEADER as STX_HEADER,
    MAGIC as STX_MAGIC,
    MARKER,
    _dictionary_limit,
)


CHANNEL_HEADER = struct.Struct(">QII")


def dictionary_end(transformed: bytes) -> Tuple[int, int]:
    if len(transformed) < STX_HEADER.size:
        raise ValueError("STX1 header is truncated")
    magic, count = STX_HEADER.unpack(transformed[: STX_HEADER.size])
    if magic != STX_MAGIC or count > 254:
        raise ValueError("STX1 header is invalid")
    offset = STX_HEADER.size
    for _ in range(count):
        if offset >= len(transformed):
            raise ValueError("STX1 dictionary is truncated")
        size = transformed[offset]
        offset += 1
        if size < 3 or size > 64 or size > len(transformed) - offset:
            raise ValueError("STX1 dictionary token is invalid")
        offset += size
    return offset, count


def split_channels(transformed: bytes) -> Tuple[bytes, bytes]:
    body_start, count = dictionary_end(transformed)
    skeleton = bytearray(transformed[:body_start])
    side = bytearray()
    offset = body_start
    while offset < len(transformed):
        value = transformed[offset]
        offset += 1
        skeleton.append(value)
        if value != MARKER:
            continue
        if offset >= len(transformed):
            raise ValueError("STX1 marker is truncated")
        code = transformed[offset]
        offset += 1
        if code != ESCAPED_MARKER and code >= count:
            raise ValueError("STX1 token code is invalid")
        side.append(code)
    return bytes(skeleton), bytes(side)


def join_channels(skeleton: bytes, side: bytes) -> bytes:
    body_start, count = dictionary_end(skeleton)
    transformed = bytearray(skeleton[:body_start])
    side_offset = 0
    for value in skeleton[body_start:]:
        transformed.append(value)
        if value != MARKER:
            continue
        if side_offset >= len(side):
            raise ValueError("token side channel is truncated")
        code = side[side_offset]
        side_offset += 1
        if code != ESCAPED_MARKER and code >= count:
            raise ValueError("token side channel contains an invalid code")
        transformed.append(code)
    if side_offset != len(side):
        raise ValueError("token side channel has trailing data")
    return bytes(transformed)


def delta_encode(data: bytes) -> bytes:
    output = bytearray(len(data))
    previous = 0
    for offset, value in enumerate(data):
        output[offset] = (value - previous) & 0xFF
        previous = value
    return bytes(output)


def delta_decode(data: bytes) -> bytes:
    output = bytearray(len(data))
    previous = 0
    for offset, value in enumerate(data):
        previous = (previous + value) & 0xFF
        output[offset] = previous
    return bytes(output)


def mtf_encode(data: bytes) -> bytes:
    alphabet = list(range(255))
    output = bytearray(len(data))
    for offset, value in enumerate(data):
        rank = alphabet.index(value)
        output[offset] = rank
        if rank:
            alphabet.insert(0, alphabet.pop(rank))
    return bytes(output)


def mtf_decode(data: bytes) -> bytes:
    alphabet = list(range(255))
    output = bytearray(len(data))
    for offset, rank in enumerate(data):
        if rank >= len(alphabet):
            raise ValueError("move-to-front rank is invalid")
        value = alphabet[rank]
        output[offset] = value
        if rank:
            alphabet.insert(0, alphabet.pop(rank))
    return bytes(output)


MODES: dict[str, Tuple[Callable[[bytes], bytes], Callable[[bytes], bytes]]] = {
    "raw": (lambda data: data, lambda data: data),
    "delta": (delta_encode, delta_decode),
    "mtf": (mtf_encode, mtf_decode),
}


def encode_candidate(transformed: bytes, mode: str) -> bytes:
    skeleton, side = native_split_channels(transformed)
    side_encode, _ = MODES[mode]
    encoded_side = side_encode(side)
    skeleton_payload = zstd_compress(skeleton, level=3)
    side_payload = zstd_compress(encoded_side, level=3)
    return (
        CHANNEL_HEADER.pack(
            len(transformed), len(skeleton), len(skeleton_payload)
        )
        + skeleton_payload
        + side_payload
    )


def decode_candidate(payload: bytes, expected_size: int, mode: str) -> bytes:
    if len(payload) < CHANNEL_HEADER.size:
        raise ValueError("channel payload header is truncated")
    transformed_size, skeleton_size, skeleton_payload_size = (
        CHANNEL_HEADER.unpack(payload[: CHANNEL_HEADER.size])
    )
    if skeleton_size > transformed_size:
        raise ValueError("channel skeleton is larger than transformed stream")
    payload_offset = CHANNEL_HEADER.size
    payload_end = payload_offset + skeleton_payload_size
    if payload_end >= len(payload):
        raise ValueError("channel payload boundary is invalid")
    skeleton = zstd_decompress(
        payload[payload_offset:payload_end], skeleton_size
    )
    side_size = transformed_size - skeleton_size
    encoded_side = zstd_decompress(payload[payload_end:], side_size)
    _, side_decode = MODES[mode]
    side = side_decode(encoded_side)
    if len(skeleton) + len(side) != transformed_size:
        raise ValueError("restored transformed size mismatch")
    return native_decode_channels(skeleton, side, expected_size)


def expect_failure(call: Callable[[], object]) -> None:
    try:
        call()
    except (RuntimeError, ValueError):
        return
    raise AssertionError("malformed candidate was accepted")


def self_test() -> None:
    source = (
        b"shared_identifier other_identifier shared_identifier\n" * 100
        + b"raw-marker:\xff tail\n"
    )
    transformed = structured_text_encode(source, 16, DICTIONARY_SAMPLE_BYTES)
    skeleton, side = split_channels(transformed)
    assert join_channels(skeleton, side) == transformed
    assert native_split_channels(transformed) == (skeleton, side)
    for mode in MODES:
        payload = encode_candidate(transformed, mode)
        assert decode_candidate(payload, len(source), mode) == source
        expect_failure(lambda: decode_candidate(payload[:8], len(source), mode))
        expect_failure(
            lambda: decode_candidate(payload[:-1], len(source), mode)
        )
    expect_failure(lambda: join_channels(skeleton, side[:-1]))
    expect_failure(lambda: join_channels(skeleton, side + b"\x00"))
    bad_side = bytes([255]) + side[1:]
    expect_failure(lambda: join_channels(skeleton, bad_side))


def public_files(root: Path) -> Iterable[Path]:
    yield from sorted((root / "validation" / "source-code").glob("*"))
    yield from sorted((root / "validation" / "structured-text").glob("*"))


def benchmark_file(
    path: Path,
) -> list[tuple[str, int, int, int, int, float, float, float]]:
    source = path.read_bytes()
    limit = _dictionary_limit(source)
    transform_start = time.perf_counter()
    transformed = structured_text_encode(
        source, limit, DICTIONARY_SAMPLE_BYTES
    )
    transform_seconds = time.perf_counter() - transform_start
    baseline_start = time.perf_counter()
    baseline_payload = zstd_compress(transformed, level=3)
    baseline_seconds = time.perf_counter() - baseline_start
    direct_size = len(zstd_compress(source, level=3))
    baseline_size = 8 + len(baseline_payload)

    rows = []
    for mode in MODES:
        encode_start = time.perf_counter()
        payload = encode_candidate(transformed, mode)
        encode_seconds = time.perf_counter() - encode_start
        decode_start = time.perf_counter()
        restored = decode_candidate(payload, len(source), mode)
        decode_seconds = time.perf_counter() - decode_start
        if hashlib.sha256(restored).digest() != hashlib.sha256(source).digest():
            raise AssertionError(f"round trip mismatch: {path}")
        rows.append(
            (
                mode,
                len(payload),
                encode_seconds,
                decode_seconds,
            )
        )

    results = []
    for mode, candidate_size, encode_seconds, decode_seconds in rows:
        total_encode_seconds = transform_seconds + encode_seconds
        total_baseline_seconds = transform_seconds + baseline_seconds
        print(
            "\t".join(
                (
                    path.name,
                    mode,
                    str(len(source)),
                    str(direct_size),
                    str(baseline_size),
                    str(candidate_size),
                    str(candidate_size - baseline_size),
                    f"{len(source) / 1_000_000 / total_baseline_seconds:.3f}",
                    f"{len(source) / 1_000_000 / total_encode_seconds:.3f}",
                    f"{len(source) / 1_000_000 / decode_seconds:.3f}",
                )
            )
        )
        results.append(
            (
                mode,
                len(source),
                direct_size,
                baseline_size,
                candidate_size,
                total_baseline_seconds,
                total_encode_seconds,
                decode_seconds,
            )
        )
    return results


def print_aggregates(
    rows: list[tuple[str, int, int, int, int, float, float, float]],
) -> None:
    for mode in MODES:
        selected = [row for row in rows if row[0] == mode]
        input_bytes = sum(row[1] for row in selected)
        direct_size = sum(row[2] for row in selected)
        baseline_size = sum(row[3] for row in selected)
        candidate_size = sum(row[4] for row in selected)
        baseline_seconds = sum(row[5] for row in selected)
        encode_seconds = sum(row[6] for row in selected)
        decode_seconds = sum(row[7] for row in selected)
        print(
            "\t".join(
                (
                    "<aggregate>",
                    mode,
                    str(input_bytes),
                    str(direct_size),
                    str(baseline_size),
                    str(candidate_size),
                    str(candidate_size - baseline_size),
                    f"{input_bytes / 1_000_000 / baseline_seconds:.3f}",
                    f"{input_bytes / 1_000_000 / encode_seconds:.3f}",
                    f"{input_bytes / 1_000_000 / decode_seconds:.3f}",
                )
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("corpora/public-starter-v1"),
    )
    arguments = parser.parse_args()
    self_test()
    print(
        "file\tmode\tinput_bytes\tdirect_zstd3\tstx1_bytes\tcandidate_bytes"
        "\tdelta_vs_stx1\tstx1_encode_mb_s\tcandidate_encode_mb_s"
        "\tcandidate_decode_mb_s"
    )
    rows = []
    for path in public_files(arguments.corpus):
        rows.extend(benchmark_file(path))
    print_aggregates(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
