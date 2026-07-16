from __future__ import annotations

from collections import Counter
import re
import struct
from typing import Callable, Dict, List, Optional, Tuple

from .native import (
    native_available,
    structured_text_decode as native_decode,
    structured_text_decode_channels as native_decode_channels,
    structured_text_encode as native_encode,
    structured_text_split_channels as native_split_channels,
)


MAGIC = b"STX1"
HEADER = struct.Struct(">4sH")
CHANNEL_HEADER = struct.Struct(">QII")
TOKEN = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,63}")
MARKER = 0xFF
ESCAPED_MARKER = 0xFE
MAX_DICTIONARY_TOKENS = 254
MAX_TOKEN_SIZE = 64
MAX_HEADER_SIZE = HEADER.size + MAX_DICTIONARY_TOKENS * (1 + MAX_TOKEN_SIZE)
SMALL_TEXT_DICTIONARY_TOKENS = 16
JSON_DICTIONARY_TOKENS = 128
DICTIONARY_SAMPLE_BYTES = 1024 * 1024

Encoder = Callable[[bytes], bytes]
TRANSFORMED_SIZE = struct.Struct(">Q")


def _token_continue(value: int) -> bool:
    return value == 95 or 48 <= value <= 57 or 65 <= value <= 90 or 97 <= value <= 122


def is_likely_structured_text(data: bytes) -> bool:
    if len(data) < 256:
        sample = data
    else:
        block = min(8192, len(data) // 3)
        middle = max(0, len(data) // 2 - block // 2)
        sample = data[:block] + data[middle:middle + block] + data[-block:]
    if not sample:
        return False
    printable = sum(
        value in {9, 10, 13} or 32 <= value <= 126 for value in sample
    )
    return printable / len(sample) >= 0.85 and len(TOKEN.findall(sample)) >= 8


def _representative_ranges(data: bytes, sample_budget: int) -> List[Tuple[int, int]]:
    if sample_budget <= 0 or len(data) <= sample_budget:
        return [(0, len(data))]
    block = max(1, sample_budget // 3)
    tail = max(1, sample_budget - 2 * block)
    middle = len(data) // 2 - block // 2
    ranges = [
        [0, min(block, len(data))],
        [middle, min(middle + block, len(data))],
        [max(0, len(data) - tail), len(data)],
    ]
    for bounds in ranges:
        start, end = bounds
        while (
            0 < start < len(data)
            and _token_continue(data[start - 1])
            and _token_continue(data[start])
        ):
            start += 1
        while (
            start < end < len(data)
            and _token_continue(data[end - 1])
            and _token_continue(data[end])
        ):
            end -= 1
        bounds[:] = [start, end]
    return [(start, end) for start, end in ranges]


def _ranked_dictionary(
    data: bytes, sample_budget: int = DICTIONARY_SAMPLE_BYTES
) -> List[bytes]:
    counts: Counter[bytes] = Counter()
    for start, end in _representative_ranges(data, sample_budget):
        counts.update(TOKEN.findall(data[start:end]))
    ranked = []
    for token, count in counts.items():
        estimated_gain = count * (len(token) - 2) - len(token) - 1
        if count >= 2 and estimated_gain > 0:
            ranked.append((estimated_gain, count, token))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [token for _, _, token in ranked[:MAX_DICTIONARY_TOKENS]]


def _dictionary_limit(data: bytes) -> int:
    if len(data) < 64 * 1024:
        return SMALL_TEXT_DICTIONARY_TOKENS
    prefix = data[:4096].lstrip()
    if prefix[:1] in {b"[", b"{"}:
        return JSON_DICTIONARY_TOKENS
    return MAX_DICTIONARY_TOKENS


def _is_json_document(data: bytes) -> bool:
    return data[:4096].lstrip()[:1] in {b"[", b"{"}


def encode_channelized(
    transformed: bytes,
    zstd_encode: Encoder,
) -> bytes:
    if not native_available():
        raise RuntimeError("channelized structured text requires the native library")
    skeleton, side = native_split_channels(transformed)
    if not side or len(skeleton) + len(side) != len(transformed):
        raise ValueError("structured-text channels are inconsistent")
    skeleton_payload = zstd_encode(skeleton)
    side_payload = zstd_encode(side)
    return (
        CHANNEL_HEADER.pack(
            len(transformed), len(skeleton), len(skeleton_payload)
        )
        + skeleton_payload
        + side_payload
    )


def decode_channelized(
    data: bytes,
    expected_size: int,
    zstd_decode: Callable[[bytes, int], bytes],
) -> bytes:
    if not native_available():
        raise RuntimeError("channelized structured text requires the native library")
    if len(data) < CHANNEL_HEADER.size:
        raise ValueError("structured-text channel header is truncated")
    transformed_size, skeleton_size, skeleton_payload_size = (
        CHANNEL_HEADER.unpack(data[: CHANNEL_HEADER.size])
    )
    maximum_size = expected_size * 2 + MAX_HEADER_SIZE
    if transformed_size > maximum_size or skeleton_size > transformed_size:
        raise ValueError("structured-text channel size is invalid")
    side_size = transformed_size - skeleton_size
    if side_size == 0 or skeleton_payload_size == 0:
        raise ValueError("structured-text channel is empty")
    payload_offset = CHANNEL_HEADER.size
    payload_end = payload_offset + skeleton_payload_size
    if payload_end >= len(data):
        raise ValueError("structured-text channel boundary is invalid")
    skeleton = zstd_decode(data[payload_offset:payload_end], skeleton_size)
    side = zstd_decode(data[payload_end:], side_size)
    return native_decode_channels(skeleton, side, expected_size)


def encode_with_dictionary(data: bytes, dictionary: List[bytes]) -> bytes:
    if len(dictionary) > MAX_DICTIONARY_TOKENS:
        raise ValueError("structured-text dictionary is too large")
    if len(set(dictionary)) != len(dictionary):
        raise ValueError("structured-text dictionary contains duplicates")
    for token in dictionary:
        if not TOKEN.fullmatch(token):
            raise ValueError("structured-text dictionary contains an invalid token")

    codes = {token: code for code, token in enumerate(dictionary)}
    output = bytearray(HEADER.pack(MAGIC, len(dictionary)))
    for token in dictionary:
        output.append(len(token))
        output.extend(token)

    offset = 0
    for match in TOKEN.finditer(data):
        output.extend(
            data[offset:match.start()].replace(b"\xff", b"\xff\xfe")
        )
        token = match.group(0)
        code = codes.get(token)
        if code is None:
            output.extend(token)
        else:
            output.extend((MARKER, code))
        offset = match.end()
    output.extend(data[offset:].replace(b"\xff", b"\xff\xfe"))
    return bytes(output)


def encode_best(
    data: bytes,
    zstd_encode: Encoder,
) -> Optional[Tuple[bytes, Dict[str, object]]]:
    if not is_likely_structured_text(data):
        return None
    limit = _dictionary_limit(data)
    if native_available():
        transformed = native_encode(data, limit, DICTIONARY_SAMPLE_BYTES)
        _, dictionary_size = HEADER.unpack(transformed[:HEADER.size])
    else:
        dictionary = _ranked_dictionary(data, DICTIONARY_SAMPLE_BYTES)[:limit]
        if not dictionary:
            return None
        dictionary_size = len(dictionary)
        transformed = encode_with_dictionary(data, dictionary)
    if dictionary_size == 0:
        return None
    interleaved_payload = zstd_encode(transformed)
    representation = "interleaved"
    payload = interleaved_payload
    candidate_count = 1
    skeleton_size = 0
    side_size = 0
    if _is_json_document(data) and native_available():
        candidate_count += 1
        channel_payload = encode_channelized(transformed, zstd_encode)
        if len(channel_payload) < TRANSFORMED_SIZE.size + len(interleaved_payload):
            payload = channel_payload
            representation = "channelized"
            _, skeleton_size, _ = CHANNEL_HEADER.unpack(
                channel_payload[: CHANNEL_HEADER.size]
            )
            side_size = len(transformed) - skeleton_size
    return payload, {
        "dictionary_tokens": dictionary_size,
        "transformed_size": len(transformed),
        "candidate_count": candidate_count,
        "representation": representation,
        "skeleton_size": skeleton_size,
        "side_size": side_size,
    }


def decode(data: bytes, expected_size: int) -> bytes:
    if native_available():
        return native_decode(data, expected_size)
    if len(data) < HEADER.size:
        raise ValueError("structured-text transform is truncated")
    magic, count = HEADER.unpack(data[:HEADER.size])
    if magic != MAGIC:
        raise ValueError("structured-text transform magic mismatch")
    if count > MAX_DICTIONARY_TOKENS:
        raise ValueError("structured-text dictionary is too large")

    offset = HEADER.size
    dictionary: List[bytes] = []
    for _ in range(count):
        if offset >= len(data):
            raise ValueError("structured-text dictionary is truncated")
        size = data[offset]
        offset += 1
        if size == 0 or size > MAX_TOKEN_SIZE or size > len(data) - offset:
            raise ValueError("structured-text dictionary token is invalid")
        token = data[offset:offset + size]
        offset += size
        if not TOKEN.fullmatch(token) or token in dictionary:
            raise ValueError("structured-text dictionary token is invalid")
        dictionary.append(token)

    output = bytearray()
    marker = bytes((MARKER,))
    while offset < len(data):
        marker_offset = data.find(marker, offset)
        if marker_offset < 0:
            suffix = data[offset:]
            if len(suffix) > expected_size - len(output):
                raise ValueError("structured-text output exceeds expected size")
            output.extend(suffix)
            break
        literal = data[offset:marker_offset]
        if len(literal) > expected_size - len(output):
            raise ValueError("structured-text output exceeds expected size")
        output.extend(literal)
        offset = marker_offset + 1
        if offset >= len(data):
            raise ValueError("structured-text escape is truncated")
        code = data[offset]
        offset += 1
        if code == ESCAPED_MARKER:
            token = b"\xff"
        elif code < len(dictionary):
            token = dictionary[code]
        else:
            raise ValueError("structured-text token code is invalid")
        if len(token) > expected_size - len(output):
            raise ValueError("structured-text output exceeds expected size")
        output.extend(token)

    if len(output) != expected_size:
        raise ValueError("structured-text output size mismatch")
    return bytes(output)
