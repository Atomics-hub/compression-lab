from __future__ import annotations

import hashlib
import struct
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from collections import defaultdict
from typing import BinaryIO, Iterator

from .dense_native import (
    dense_adaptive_native_available,
    dense_adaptive_reassemble,
    dense_adaptive_transform as native_dense_adaptive_transform,
    dense_plane_native_available,
    dense_plane_reassemble,
    dense_plane_transform as native_dense_plane_transform,
    dense_parallel_native_available,
    dense_parallel_reassemble,
    dense_parallel_transform as native_dense_parallel_transform,
    dense_sample_alphabet,
)
from .native import (
    zstd_compress,
    zstd_decompress,
    zstd_frame_content_size,
)


MAGIC = b"DMT1"
MATRIX_MAGIC = b"DMI1"
PLANE_MAGIC = b"DMP1"
CONTEXT_MAGIC = b"DMC1"
ADAPTIVE_MAGIC = b"DMA1"
PARALLEL_MAGIC = b"DMA2"
SELECTOR_MAGIC = b"DMS2"
SELECTOR_STREAM_MAGIC = b"DSS1"
VERSION = 1
SEPARATOR_BYTES = frozenset(b" \t,;|\r\n")
HEADER = struct.Struct(">4sBBQQ32s")
STREAM_HEADER = struct.Struct(">4sBQ")
STREAM_LENGTH = struct.Struct(">Q")
STREAM_TRAILER = struct.Struct(">Q32s")
MAX_DICTIONARY_ENTRIES = 1 << 20
MAX_TRANSFORMED_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_STREAM_SEGMENT_SIZE = 16 * 1024 * 1024
MAX_STREAM_SEGMENT_SIZE = 256 * 1024 * 1024
SELECTOR_STARTS_WITH_TOKEN = 1
SELECTOR_PLANES = 2
SELECTOR_DIRECT = 4


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("cannot encode a negative varint")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _decode_varint(data: bytes | memoryview, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("truncated DMT1 varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise ValueError("DMT1 varint is too large")


def _split_runs(data: bytes) -> tuple[bool, list[bytes], list[bytes]]:
    if not data:
        return True, [], []
    starts_with_token = data[0] not in SEPARATOR_BYTES
    tokens: list[bytes] = []
    separators: list[bytes] = []
    start = 0
    is_separator = not starts_with_token
    for offset in range(1, len(data)):
        next_is_separator = data[offset] in SEPARATOR_BYTES
        if next_is_separator == is_separator:
            continue
        run = data[start:offset]
        (separators if is_separator else tokens).append(run)
        start = offset
        is_separator = next_is_separator
    run = data[start:]
    (separators if is_separator else tokens).append(run)
    return starts_with_token, tokens, separators


def _write_dictionary(output: bytearray, entries: list[bytes]) -> None:
    output.extend(_encode_varint(len(entries)))
    for entry in entries:
        output.extend(_encode_varint(len(entry)))
        output.extend(entry)


def _read_dictionary(
    data: bytes | memoryview, offset: int
) -> tuple[list[bytes], int]:
    count, offset = _decode_varint(data, offset)
    if count > MAX_DICTIONARY_ENTRIES:
        raise ValueError("DMT1 dictionary exceeds entry bound")
    entries: list[bytes] = []
    for _ in range(count):
        size, offset = _decode_varint(data, offset)
        end = offset + size
        if end > len(data):
            raise ValueError("truncated DMT1 dictionary entry")
        entries.append(bytes(data[offset:end]))
        offset = end
    if len(set(entries)) != len(entries):
        raise ValueError("DMT1 dictionary contains duplicate entries")
    return entries, offset


def _bit_width(count: int) -> int:
    return 0 if count <= 1 else (count - 1).bit_length()


def _pack_indices(indices: list[int], dictionary_size: int) -> bytes:
    width = _bit_width(dictionary_size)
    if width == 0:
        if any(indices):
            raise ValueError("DMT1 singleton dictionary index is not zero")
        return b""
    output = bytearray((len(indices) * width + 7) // 8)
    bit_offset = 0
    for index in indices:
        if not 0 <= index < dictionary_size:
            raise ValueError("DMT1 index exceeds dictionary")
        for shift in range(width):
            if index & (1 << shift):
                output[bit_offset >> 3] |= 1 << (bit_offset & 7)
            bit_offset += 1
    return bytes(output)


def _unpack_indices(
    data: bytes | memoryview, count: int, dictionary_size: int
) -> list[int]:
    width = _bit_width(dictionary_size)
    expected_size = (count * width + 7) // 8
    if len(data) != expected_size:
        raise ValueError("DMT1 packed index size mismatch")
    if width == 0:
        if count and dictionary_size != 1:
            raise ValueError("DMT1 indices have no dictionary")
        return [0] * count
    indices: list[int] = []
    bit_offset = 0
    for _ in range(count):
        index = 0
        for shift in range(width):
            if data[bit_offset >> 3] & (1 << (bit_offset & 7)):
                index |= 1 << shift
            bit_offset += 1
        if index >= dictionary_size:
            raise ValueError("DMT1 packed index exceeds dictionary")
        indices.append(index)
    if bit_offset & 7:
        padding_mask = ~((1 << (bit_offset & 7)) - 1) & 0xFF
        if data[-1] & padding_mask:
            raise ValueError("DMT1 packed indices have nonzero padding")
    return indices


def transform(data: bytes) -> bytes:
    starts_with_token, tokens, separators = _split_runs(data)
    token_dictionary = sorted(set(tokens))
    separator_dictionary = sorted(set(separators))
    token_lookup = {entry: index for index, entry in enumerate(token_dictionary)}
    separator_lookup = {
        entry: index for index, entry in enumerate(separator_dictionary)
    }
    token_indices = [token_lookup[token] for token in tokens]
    separator_indices = [separator_lookup[item] for item in separators]
    packed_tokens = _pack_indices(token_indices, len(token_dictionary))
    packed_separators = _pack_indices(
        separator_indices, len(separator_dictionary)
    )

    output = bytearray()
    _write_dictionary(output, token_dictionary)
    _write_dictionary(output, separator_dictionary)
    output.extend(_encode_varint(len(tokens)))
    output.extend(_encode_varint(len(separators)))
    output.extend(_encode_varint(len(packed_tokens)))
    output.extend(packed_tokens)
    output.extend(_encode_varint(len(packed_separators)))
    output.extend(packed_separators)
    return bytes(output)


def inverse_transform(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if not 0 <= expected_size <= MAX_TRANSFORMED_BYTES:
        raise ValueError("DMT1 output size exceeds bound")
    view = memoryview(transformed)
    token_dictionary, offset = _read_dictionary(view, 0)
    separator_dictionary, offset = _read_dictionary(view, offset)
    token_count, offset = _decode_varint(view, offset)
    separator_count, offset = _decode_varint(view, offset)
    if token_count + separator_count > expected_size + 1:
        raise ValueError("DMT1 run count exceeds output bound")
    if abs(token_count - separator_count) > 1:
        raise ValueError("DMT1 run counts cannot alternate")
    if starts_with_token and separator_count > token_count:
        raise ValueError("DMT1 run counts disagree with start type")
    if not starts_with_token and token_count > separator_count:
        raise ValueError("DMT1 run counts disagree with start type")

    packed_token_size, offset = _decode_varint(view, offset)
    packed_token_end = offset + packed_token_size
    if packed_token_end > len(view):
        raise ValueError("truncated DMT1 token indices")
    token_indices = _unpack_indices(
        view[offset:packed_token_end], token_count, len(token_dictionary)
    )
    offset = packed_token_end
    packed_separator_size, offset = _decode_varint(view, offset)
    packed_separator_end = offset + packed_separator_size
    if packed_separator_end != len(view):
        raise ValueError("truncated or trailing DMT1 separator indices")
    separator_indices = _unpack_indices(
        view[offset:packed_separator_end],
        separator_count,
        len(separator_dictionary),
    )

    output = bytearray()
    token_offset = 0
    separator_offset = 0
    is_token = starts_with_token
    for _ in range(token_count + separator_count):
        if is_token:
            output.extend(token_dictionary[token_indices[token_offset]])
            token_offset += 1
        else:
            output.extend(separator_dictionary[separator_indices[separator_offset]])
            separator_offset += 1
        if len(output) > expected_size:
            raise ValueError("DMT1 output exceeds declared size")
        is_token = not is_token
    if len(output) != expected_size:
        raise ValueError("DMT1 output size does not match declaration")
    return bytes(output)


def compress(data: bytes, level: int = 9) -> bytes:
    starts_with_token, _tokens, _separators = _split_runs(data)
    transformed = transform(data)
    payload = zstd_compress(transformed, level=level)
    return HEADER.pack(
        MAGIC,
        VERSION,
        int(starts_with_token),
        len(data),
        len(transformed),
        hashlib.sha256(data).digest(),
    ) + payload


def decompress(frame: bytes) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMT1 frame")
    magic, version, starts, original_size, transformed_size, digest = (
        HEADER.unpack_from(frame)
    )
    if magic != MAGIC or version != VERSION or starts not in (0, 1):
        raise ValueError("invalid DMT1 header")
    if transformed_size > MAX_TRANSFORMED_BYTES:
        raise ValueError("DMT1 transformed size exceeds bound")
    payload = frame[HEADER.size :]
    if zstd_frame_content_size(payload) != transformed_size:
        raise ValueError("DMT1 transformed size does not match payload")
    try:
        transformed = zstd_decompress(payload, transformed_size)
    except RuntimeError as error:
        raise ValueError(f"invalid DMT1 payload: {error}") from error
    output = inverse_transform(transformed, bool(starts), original_size)
    if hashlib.sha256(output).digest() != digest:
        raise ValueError("DMT1 checksum mismatch")
    return output


def _is_numeric_lexeme(token: bytes) -> bool:
    if not token:
        return False
    offset = int(token[0] in (ord("+"), ord("-")))
    if offset == len(token):
        return False
    dot_seen = False
    digit_seen = False
    for byte in token[offset:]:
        if ord("0") <= byte <= ord("9"):
            digit_seen = True
        elif byte == ord(".") and not dot_seen:
            dot_seen = True
        else:
            return False
    return digit_seen


def _matrix_shape(data: bytes) -> tuple[int, int]:
    row_counts: list[int] = []
    row_tokens = 0
    in_token = False
    for byte in data:
        if byte == ord("\n"):
            row_counts.append(row_tokens)
            row_tokens = 0
            in_token = False
        elif byte in SEPARATOR_BYTES:
            in_token = False
        elif not in_token:
            row_tokens += 1
            in_token = True
    if data and data[-1] != ord("\n"):
        row_counts.append(row_tokens)
    if not row_counts or row_counts[0] == 0:
        raise ValueError("DMI1 input has no nonempty matrix rows")
    column_count = row_counts[0]
    if any(count != column_count for count in row_counts):
        raise ValueError("DMI1 input is not rectangular")
    return len(row_counts), column_count


def matrix_transform(data: bytes) -> bytes:
    starts_with_token, tokens, separators = _split_runs(data)
    if any(not _is_numeric_lexeme(token) for token in tokens):
        raise ValueError("DMI1 input contains a nonnumeric field")
    row_count, column_count = _matrix_shape(data)
    if len(tokens) != row_count * column_count:
        raise ValueError("DMI1 token count does not match matrix shape")

    token_dictionary = sorted(set(tokens))
    separator_dictionary = sorted(set(separators))
    token_lookup = {entry: index for index, entry in enumerate(token_dictionary)}
    separator_lookup = {
        entry: index for index, entry in enumerate(separator_dictionary)
    }
    row_major = [token_lookup[token] for token in tokens]
    column_major = [
        row_major[row * column_count + column]
        for column in range(column_count)
        for row in range(row_count)
    ]
    separator_indices = [separator_lookup[item] for item in separators]
    packed_tokens = _pack_indices(column_major, len(token_dictionary))
    packed_separators = _pack_indices(
        separator_indices, len(separator_dictionary)
    )

    output = bytearray()
    _write_dictionary(output, token_dictionary)
    _write_dictionary(output, separator_dictionary)
    output.extend(_encode_varint(row_count))
    output.extend(_encode_varint(column_count))
    output.extend(_encode_varint(len(separators)))
    output.extend(_encode_varint(len(packed_tokens)))
    output.extend(packed_tokens)
    output.extend(_encode_varint(len(packed_separators)))
    output.extend(packed_separators)
    return bytes(output)


def matrix_inverse_transform(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if not 0 <= expected_size <= MAX_TRANSFORMED_BYTES:
        raise ValueError("DMI1 output size exceeds bound")
    view = memoryview(transformed)
    token_dictionary, offset = _read_dictionary(view, 0)
    separator_dictionary, offset = _read_dictionary(view, offset)
    row_count, offset = _decode_varint(view, offset)
    column_count, offset = _decode_varint(view, offset)
    separator_count, offset = _decode_varint(view, offset)
    if row_count == 0 or column_count == 0:
        raise ValueError("DMI1 matrix shape cannot be empty")
    token_count = row_count * column_count
    if token_count > expected_size + 1 or separator_count > expected_size + 1:
        raise ValueError("DMI1 run count exceeds output bound")
    if abs(token_count - separator_count) > 1:
        raise ValueError("DMI1 run counts cannot alternate")

    packed_token_size, offset = _decode_varint(view, offset)
    packed_token_end = offset + packed_token_size
    if packed_token_end > len(view):
        raise ValueError("truncated DMI1 token indices")
    column_major = _unpack_indices(
        view[offset:packed_token_end], token_count, len(token_dictionary)
    )
    offset = packed_token_end
    packed_separator_size, offset = _decode_varint(view, offset)
    packed_separator_end = offset + packed_separator_size
    if packed_separator_end != len(view):
        raise ValueError("truncated or trailing DMI1 separator indices")
    separator_indices = _unpack_indices(
        view[offset:packed_separator_end],
        separator_count,
        len(separator_dictionary),
    )
    row_major = [0] * token_count
    for column in range(column_count):
        for row in range(row_count):
            row_major[row * column_count + column] = column_major[
                column * row_count + row
            ]

    output = bytearray()
    token_offset = 0
    separator_offset = 0
    is_token = starts_with_token
    for _ in range(token_count + separator_count):
        if is_token:
            output.extend(token_dictionary[row_major[token_offset]])
            token_offset += 1
        else:
            output.extend(separator_dictionary[separator_indices[separator_offset]])
            separator_offset += 1
        if len(output) > expected_size:
            raise ValueError("DMI1 output exceeds declared size")
        is_token = not is_token
    if len(output) != expected_size:
        raise ValueError("DMI1 output size does not match declaration")
    return bytes(output)


def matrix_compress(data: bytes, level: int = 9) -> bytes:
    starts_with_token, _tokens, _separators = _split_runs(data)
    transformed = matrix_transform(data)
    payload = zstd_compress(transformed, level=level)
    return HEADER.pack(
        MATRIX_MAGIC,
        VERSION,
        int(starts_with_token),
        len(data),
        len(transformed),
        hashlib.sha256(data).digest(),
    ) + payload


def matrix_decompress(frame: bytes) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMI1 frame")
    magic, version, starts, original_size, transformed_size, digest = (
        HEADER.unpack_from(frame)
    )
    if magic != MATRIX_MAGIC or version != VERSION or starts not in (0, 1):
        raise ValueError("invalid DMI1 header")
    if transformed_size > MAX_TRANSFORMED_BYTES:
        raise ValueError("DMI1 transformed size exceeds bound")
    payload = frame[HEADER.size :]
    if zstd_frame_content_size(payload) != transformed_size:
        raise ValueError("DMI1 transformed size does not match payload")
    try:
        transformed = zstd_decompress(payload, transformed_size)
    except RuntimeError as error:
        raise ValueError(f"invalid DMI1 payload: {error}") from error
    output = matrix_inverse_transform(transformed, bool(starts), original_size)
    if hashlib.sha256(output).digest() != digest:
        raise ValueError("DMI1 checksum mismatch")
    return output


def _plane_transform_python(data: bytes) -> bytes:
    starts_with_token, tokens, separators = _split_runs(data)
    if any(not _is_numeric_lexeme(token) for token in tokens):
        raise ValueError("DMP1 input contains a nonnumeric field")
    _matrix_shape(data)
    token_dictionary = sorted(
        set(tokens),
        key=lambda token: (Decimal(token.decode("ascii")), token),
    )
    separator_dictionary = sorted(set(separators))
    token_lookup = {entry: index for index, entry in enumerate(token_dictionary)}
    separator_lookup = {
        entry: index for index, entry in enumerate(separator_dictionary)
    }
    token_indices = [token_lookup[token] for token in tokens]
    width = _bit_width(len(token_dictionary))
    plane_bytes = bytearray()
    for bit in range(width):
        plane_bytes.extend(
            _pack_indices(
                [(index >> bit) & 1 for index in token_indices],
                2,
            )
        )
    separator_indices = [separator_lookup[item] for item in separators]
    packed_separators = _pack_indices(
        separator_indices, len(separator_dictionary)
    )
    output = bytearray()
    _write_dictionary(output, token_dictionary)
    _write_dictionary(output, separator_dictionary)
    output.extend(_encode_varint(len(tokens)))
    output.extend(_encode_varint(len(separators)))
    output.extend(_encode_varint(len(plane_bytes)))
    output.extend(plane_bytes)
    output.extend(_encode_varint(len(packed_separators)))
    output.extend(packed_separators)
    return bytes(output)


def _plane_inverse_transform_python(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if not 0 <= expected_size <= MAX_TRANSFORMED_BYTES:
        raise ValueError("DMP1 output size exceeds bound")
    view = memoryview(transformed)
    token_dictionary, offset = _read_dictionary(view, 0)
    separator_dictionary, offset = _read_dictionary(view, offset)
    token_count, offset = _decode_varint(view, offset)
    separator_count, offset = _decode_varint(view, offset)
    if token_count + separator_count > expected_size + 1:
        raise ValueError("DMP1 run count exceeds output bound")
    if abs(token_count - separator_count) > 1:
        raise ValueError("DMP1 run counts cannot alternate")
    width = _bit_width(len(token_dictionary))
    bytes_per_plane = (token_count + 7) // 8
    plane_size, offset = _decode_varint(view, offset)
    if plane_size != bytes_per_plane * width:
        raise ValueError("DMP1 plane size mismatch")
    plane_end = offset + plane_size
    if plane_end > len(view):
        raise ValueError("truncated DMP1 planes")
    token_indices = [0] * token_count
    for bit in range(width):
        start = offset + bit * bytes_per_plane
        plane = _unpack_indices(
            view[start : start + bytes_per_plane], token_count, 2
        )
        for index, value in enumerate(plane):
            token_indices[index] |= value << bit
    if any(index >= len(token_dictionary) for index in token_indices):
        raise ValueError("DMP1 token index exceeds dictionary")
    offset = plane_end
    separator_size, offset = _decode_varint(view, offset)
    separator_end = offset + separator_size
    if separator_end != len(view):
        raise ValueError("truncated or trailing DMP1 separator indices")
    separator_indices = _unpack_indices(
        view[offset:separator_end], separator_count, len(separator_dictionary)
    )

    output = bytearray()
    token_offset = 0
    separator_offset = 0
    is_token = starts_with_token
    for _ in range(token_count + separator_count):
        if is_token:
            output.extend(token_dictionary[token_indices[token_offset]])
            token_offset += 1
        else:
            output.extend(separator_dictionary[separator_indices[separator_offset]])
            separator_offset += 1
        if len(output) > expected_size:
            raise ValueError("DMP1 output exceeds declared size")
        is_token = not is_token
    if len(output) != expected_size:
        raise ValueError("DMP1 output size does not match declaration")
    return bytes(output)


def plane_transform(data: bytes) -> bytes:
    if dense_plane_native_available():
        transformed, starts_with_token = native_dense_plane_transform(data)
        expected_start = not data or data[0] not in SEPARATOR_BYTES
        if starts_with_token != expected_start:
            raise ValueError("native DMP1 start type does not match input")
        return transformed
    return _plane_transform_python(data)


def plane_inverse_transform(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if dense_plane_native_available():
        return dense_plane_reassemble(
            transformed, starts_with_token, expected_size
        )
    return _plane_inverse_transform_python(
        transformed, starts_with_token, expected_size
    )


def plane_compress(data: bytes, level: int = 9) -> bytes:
    starts_with_token, _tokens, _separators = _split_runs(data)
    transformed = plane_transform(data)
    payload = zstd_compress(transformed, level=level)
    return HEADER.pack(
        PLANE_MAGIC,
        VERSION,
        int(starts_with_token),
        len(data),
        len(transformed),
        hashlib.sha256(data).digest(),
    ) + payload


def plane_decompress(frame: bytes) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMP1 frame")
    magic, version, starts, original_size, transformed_size, digest = (
        HEADER.unpack_from(frame)
    )
    if magic != PLANE_MAGIC or version != VERSION or starts not in (0, 1):
        raise ValueError("invalid DMP1 header")
    if transformed_size > MAX_TRANSFORMED_BYTES:
        raise ValueError("DMP1 transformed size exceeds bound")
    payload = frame[HEADER.size :]
    if zstd_frame_content_size(payload) != transformed_size:
        raise ValueError("DMP1 transformed size does not match payload")
    try:
        transformed = zstd_decompress(payload, transformed_size)
    except RuntimeError as error:
        raise ValueError(f"invalid DMP1 payload: {error}") from error
    output = plane_inverse_transform(transformed, bool(starts), original_size)
    if hashlib.sha256(output).digest() != digest:
        raise ValueError("DMP1 checksum mismatch")
    return output


class _BitWriter:
    def __init__(self) -> None:
        self.output = bytearray()
        self.current = 0
        self.used = 0

    def write(self, bit: int) -> None:
        self.current = (self.current << 1) | bit
        self.used += 1
        if self.used == 8:
            self.output.append(self.current)
            self.current = 0
            self.used = 0

    def finish(self) -> bytes:
        if self.used:
            self.output.append(self.current << (8 - self.used))
        return bytes(self.output)


class _BitReader:
    def __init__(self, data: bytes | memoryview) -> None:
        self.data = data
        self.offset = 0

    def read(self) -> int:
        byte_offset = self.offset >> 3
        self.offset += 1
        if byte_offset >= len(self.data):
            return 0
        return (self.data[byte_offset] >> (7 - ((self.offset - 1) & 7))) & 1


def _cumulative(counts: list[int], symbol: int) -> tuple[int, int, int]:
    low = sum(counts[:symbol])
    return low, low + counts[symbol], sum(counts)


def _arithmetic_encode(
    symbols: list[int], contexts: list[tuple[int, int]], models: dict
) -> bytes:
    full = 1 << 32
    half = full >> 1
    quarter = half >> 1
    three_quarters = quarter * 3
    low = 0
    high = full - 1
    pending = 0
    writer = _BitWriter()

    def emit(bit: int) -> None:
        nonlocal pending
        writer.write(bit)
        while pending:
            writer.write(bit ^ 1)
            pending -= 1

    if len(symbols) != len(contexts):
        raise ValueError("DMC1 symbol and context counts differ")
    for symbol, context in zip(symbols, contexts):
        counts = models[context]
        cumulative_low, cumulative_high, total = _cumulative(counts, symbol)
        interval = high - low + 1
        high = low + interval * cumulative_high // total - 1
        low = low + interval * cumulative_low // total
        while True:
            if high < half:
                emit(0)
            elif low >= half:
                emit(1)
                low -= half
                high -= half
            elif low >= quarter and high < three_quarters:
                pending += 1
                low -= quarter
                high -= quarter
            else:
                break
            low <<= 1
            high = (high << 1) | 1
    pending += 1
    emit(0 if low < quarter else 1)
    return writer.finish()


def _arithmetic_decode(
    encoded: bytes | memoryview,
    contexts: list[tuple[int, int]],
    models: dict,
) -> list[int]:
    full = 1 << 32
    half = full >> 1
    quarter = half >> 1
    three_quarters = quarter * 3
    low = 0
    high = full - 1
    reader = _BitReader(encoded)
    code = 0
    for _ in range(32):
        code = (code << 1) | reader.read()
    output: list[int] = []
    for context in contexts:
        counts = models.get(context)
        if counts is None:
            raise ValueError("DMC1 context model is missing")
        total = sum(counts)
        interval = high - low + 1
        scaled = ((code - low + 1) * total - 1) // interval
        cumulative = 0
        symbol = -1
        for index, count in enumerate(counts):
            if cumulative + count > scaled:
                symbol = index
                break
            cumulative += count
        if symbol < 0 or counts[symbol] == 0:
            raise ValueError("DMC1 arithmetic symbol is invalid")
        high = low + interval * (cumulative + counts[symbol]) // total - 1
        low = low + interval * cumulative // total
        while True:
            if high < half:
                pass
            elif low >= half:
                low -= half
                high -= half
                code -= half
            elif low >= quarter and high < three_quarters:
                low -= quarter
                high -= quarter
                code -= quarter
            else:
                break
            low <<= 1
            high = (high << 1) | 1
            code = (code << 1) | reader.read()
        output.append(symbol)
    return output


def context_transform(data: bytes) -> bytes:
    starts_with_token, tokens, separators = _split_runs(data)
    if any(not _is_numeric_lexeme(token) for token in tokens):
        raise ValueError("DMC1 input contains a nonnumeric field")
    row_count, column_count = _matrix_shape(data)
    token_dictionary = sorted(
        set(tokens), key=lambda token: (Decimal(token.decode("ascii")), token)
    )
    separator_dictionary = sorted(set(separators))
    token_lookup = {entry: index for index, entry in enumerate(token_dictionary)}
    separator_lookup = {
        entry: index for index, entry in enumerate(separator_dictionary)
    }
    symbols = [token_lookup[token] for token in tokens]
    alphabet_size = len(token_dictionary)
    sentinel = alphabet_size
    contexts: list[tuple[int, int]] = []
    models: dict[tuple[int, int], list[int]] = defaultdict(
        lambda: [0] * alphabet_size
    )
    for row in range(row_count):
        previous = sentinel
        for column in range(column_count):
            symbol = symbols[row * column_count + column]
            context = (column, previous)
            contexts.append(context)
            models[context][symbol] += 1
            previous = symbol
    arithmetic = _arithmetic_encode(symbols, contexts, models)
    separator_indices = [separator_lookup[item] for item in separators]
    packed_separators = _pack_indices(
        separator_indices, len(separator_dictionary)
    )

    output = bytearray()
    _write_dictionary(output, token_dictionary)
    _write_dictionary(output, separator_dictionary)
    output.extend(_encode_varint(row_count))
    output.extend(_encode_varint(column_count))
    output.extend(_encode_varint(len(separators)))
    output.extend(_encode_varint(len(models)))
    for (column, previous), counts in sorted(models.items()):
        output.extend(_encode_varint(column))
        output.extend(_encode_varint(previous))
        nonzero = [(symbol, count) for symbol, count in enumerate(counts) if count]
        output.extend(_encode_varint(len(nonzero)))
        for symbol, count in nonzero:
            output.extend(_encode_varint(symbol))
            output.extend(_encode_varint(count))
    output.extend(_encode_varint(len(arithmetic)))
    output.extend(arithmetic)
    output.extend(_encode_varint(len(packed_separators)))
    output.extend(packed_separators)
    return bytes(output)


def context_inverse_transform(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if not 0 <= expected_size <= MAX_TRANSFORMED_BYTES:
        raise ValueError("DMC1 output size exceeds bound")
    view = memoryview(transformed)
    token_dictionary, offset = _read_dictionary(view, 0)
    separator_dictionary, offset = _read_dictionary(view, offset)
    row_count, offset = _decode_varint(view, offset)
    column_count, offset = _decode_varint(view, offset)
    separator_count, offset = _decode_varint(view, offset)
    token_count = row_count * column_count
    if row_count == 0 or column_count == 0 or token_count > expected_size + 1:
        raise ValueError("DMC1 matrix shape exceeds output bound")
    alphabet_size = len(token_dictionary)
    model_count, offset = _decode_varint(view, offset)
    if model_count > token_count:
        raise ValueError("DMC1 model count exceeds token count")
    models: dict[tuple[int, int], list[int]] = {}
    for _ in range(model_count):
        column, offset = _decode_varint(view, offset)
        previous, offset = _decode_varint(view, offset)
        if column >= column_count or previous > alphabet_size:
            raise ValueError("DMC1 model key is invalid")
        entry_count, offset = _decode_varint(view, offset)
        counts = [0] * alphabet_size
        for _ in range(entry_count):
            symbol, offset = _decode_varint(view, offset)
            count, offset = _decode_varint(view, offset)
            if symbol >= alphabet_size or count == 0 or counts[symbol]:
                raise ValueError("DMC1 model entry is invalid")
            counts[symbol] = count
        key = (column, previous)
        if key in models or not any(counts):
            raise ValueError("DMC1 model is duplicate or empty")
        models[key] = counts
    arithmetic_size, offset = _decode_varint(view, offset)
    arithmetic_end = offset + arithmetic_size
    if arithmetic_end > len(view):
        raise ValueError("truncated DMC1 arithmetic stream")
    arithmetic = view[offset:arithmetic_end]
    offset = arithmetic_end
    separator_size, offset = _decode_varint(view, offset)
    separator_end = offset + separator_size
    if separator_end != len(view):
        raise ValueError("truncated or trailing DMC1 separator indices")
    separator_indices = _unpack_indices(
        view[offset:separator_end], separator_count, len(separator_dictionary)
    )

    symbols: list[int] = []
    contexts: list[tuple[int, int]] = []
    sentinel = alphabet_size
    decoder_symbols: list[int] = []
    # Decode one row at a time because each context depends on the prior symbol.
    reader = _BitReader(arithmetic)
    # Reuse the arithmetic decoder by progressively supplying known contexts.
    # The stream state must be continuous, so construct contexts through a
    # dedicated inline decoder below.
    full = 1 << 32
    half = full >> 1
    quarter = half >> 1
    three_quarters = quarter * 3
    low = 0
    high = full - 1
    code = 0
    for _ in range(32):
        code = (code << 1) | reader.read()
    for _row in range(row_count):
        previous = sentinel
        for column in range(column_count):
            context = (column, previous)
            contexts.append(context)
            model_counts = models.get(context)
            if model_counts is None:
                raise ValueError("DMC1 context model is missing")
            total = sum(model_counts)
            interval = high - low + 1
            scaled = ((code - low + 1) * total - 1) // interval
            cumulative = 0
            symbol = -1
            for index, count in enumerate(model_counts):
                if cumulative + count > scaled:
                    symbol = index
                    break
                cumulative += count
            if symbol < 0 or model_counts[symbol] == 0:
                raise ValueError("DMC1 arithmetic symbol is invalid")
            high = (
                low
                + interval * (cumulative + model_counts[symbol]) // total
                - 1
            )
            low = low + interval * cumulative // total
            while True:
                if high < half:
                    pass
                elif low >= half:
                    low -= half
                    high -= half
                    code -= half
                elif low >= quarter and high < three_quarters:
                    low -= quarter
                    high -= quarter
                    code -= quarter
                else:
                    break
                low <<= 1
                high = (high << 1) | 1
                code = (code << 1) | reader.read()
            decoder_symbols.append(symbol)
            previous = symbol
    symbols = decoder_symbols

    output = bytearray()
    token_offset = 0
    separator_offset = 0
    is_token = starts_with_token
    for _ in range(token_count + separator_count):
        if is_token:
            output.extend(token_dictionary[symbols[token_offset]])
            token_offset += 1
        else:
            output.extend(separator_dictionary[separator_indices[separator_offset]])
            separator_offset += 1
        if len(output) > expected_size:
            raise ValueError("DMC1 output exceeds declared size")
        is_token = not is_token
    if len(output) != expected_size:
        raise ValueError("DMC1 output size does not match declaration")
    return bytes(output)


def context_compress(data: bytes, level: int = 9) -> bytes:
    starts_with_token, _tokens, _separators = _split_runs(data)
    transformed = context_transform(data)
    payload = zstd_compress(transformed, level=level)
    return HEADER.pack(
        CONTEXT_MAGIC,
        VERSION,
        int(starts_with_token),
        len(data),
        len(transformed),
        hashlib.sha256(data).digest(),
    ) + payload


def context_decompress(frame: bytes) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMC1 frame")
    magic, version, starts, original_size, transformed_size, digest = (
        HEADER.unpack_from(frame)
    )
    if magic != CONTEXT_MAGIC or version != VERSION or starts not in (0, 1):
        raise ValueError("invalid DMC1 header")
    payload = frame[HEADER.size :]
    if zstd_frame_content_size(payload) != transformed_size:
        raise ValueError("DMC1 transformed size does not match payload")
    try:
        transformed = zstd_decompress(payload, transformed_size)
    except RuntimeError as error:
        raise ValueError(f"invalid DMC1 payload: {error}") from error
    output = context_inverse_transform(transformed, bool(starts), original_size)
    if hashlib.sha256(output).digest() != digest:
        raise ValueError("DMC1 checksum mismatch")
    return output


def _update_adaptive(counts: list[int]) -> None:
    if sum(counts) >= 16384:
        for index, count in enumerate(counts):
            counts[index] = (count + 1) // 2


def _adaptive_encode(symbols: list[int], columns: int, alphabet: int) -> bytes:
    full = 1 << 32
    half = full >> 1
    quarter = half >> 1
    three_quarters = quarter * 3
    low = 0
    high = full - 1
    pending = 0
    writer = _BitWriter()
    models: dict[tuple[int, int], list[int]] = {}

    def emit(bit: int) -> None:
        nonlocal pending
        writer.write(bit)
        while pending:
            writer.write(bit ^ 1)
            pending -= 1

    previous = alphabet
    for index, symbol in enumerate(symbols):
        column = index % columns
        if column == 0:
            previous = alphabet
        context = (column, previous)
        counts = models.setdefault(context, [1] * alphabet)
        cumulative_low, cumulative_high, total = _cumulative(counts, symbol)
        interval = high - low + 1
        high = low + interval * cumulative_high // total - 1
        low = low + interval * cumulative_low // total
        while True:
            if high < half:
                emit(0)
            elif low >= half:
                emit(1)
                low -= half
                high -= half
            elif low >= quarter and high < three_quarters:
                pending += 1
                low -= quarter
                high -= quarter
            else:
                break
            low <<= 1
            high = (high << 1) | 1
        counts[symbol] += 1
        _update_adaptive(counts)
        previous = symbol
    pending += 1
    emit(0 if low < quarter else 1)
    return writer.finish()


def _adaptive_decode(
    encoded: bytes | memoryview, count: int, columns: int, alphabet: int
) -> list[int]:
    full = 1 << 32
    half = full >> 1
    quarter = half >> 1
    three_quarters = quarter * 3
    low = 0
    high = full - 1
    reader = _BitReader(encoded)
    code = 0
    for _ in range(32):
        code = (code << 1) | reader.read()
    models: dict[tuple[int, int], list[int]] = {}
    output: list[int] = []
    previous = alphabet
    for index in range(count):
        column = index % columns
        if column == 0:
            previous = alphabet
        context = (column, previous)
        counts = models.setdefault(context, [1] * alphabet)
        total = sum(counts)
        interval = high - low + 1
        scaled = ((code - low + 1) * total - 1) // interval
        cumulative = 0
        symbol = -1
        for candidate, frequency in enumerate(counts):
            if cumulative + frequency > scaled:
                symbol = candidate
                break
            cumulative += frequency
        if symbol < 0:
            raise ValueError("DMA1 arithmetic symbol is invalid")
        high = low + interval * (cumulative + counts[symbol]) // total - 1
        low = low + interval * cumulative // total
        while True:
            if high < half:
                pass
            elif low >= half:
                low -= half
                high -= half
                code -= half
            elif low >= quarter and high < three_quarters:
                low -= quarter
                high -= quarter
                code -= quarter
            else:
                break
            low <<= 1
            high = (high << 1) | 1
            code = (code << 1) | reader.read()
        output.append(symbol)
        counts[symbol] += 1
        _update_adaptive(counts)
        previous = symbol
    return output


def _adaptive_transform_python(data: bytes) -> bytes:
    starts_with_token, tokens, separators = _split_runs(data)
    if any(not _is_numeric_lexeme(token) for token in tokens):
        raise ValueError("DMA1 input contains a nonnumeric field")
    row_count, column_count = _matrix_shape(data)
    token_dictionary = sorted(
        set(tokens), key=lambda token: (Decimal(token.decode("ascii")), token)
    )
    separator_dictionary = sorted(set(separators))
    token_lookup = {entry: index for index, entry in enumerate(token_dictionary)}
    separator_lookup = {
        entry: index for index, entry in enumerate(separator_dictionary)
    }
    symbols = [token_lookup[token] for token in tokens]
    arithmetic = _adaptive_encode(symbols, column_count, len(token_dictionary))
    separator_indices = [separator_lookup[item] for item in separators]
    packed_separators = _pack_indices(
        separator_indices, len(separator_dictionary)
    )
    output = bytearray()
    _write_dictionary(output, token_dictionary)
    _write_dictionary(output, separator_dictionary)
    output.extend(_encode_varint(row_count))
    output.extend(_encode_varint(column_count))
    output.extend(_encode_varint(len(separators)))
    output.extend(_encode_varint(len(arithmetic)))
    output.extend(arithmetic)
    output.extend(_encode_varint(len(packed_separators)))
    output.extend(packed_separators)
    return bytes(output)


def _adaptive_inverse_transform_python(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    view = memoryview(transformed)
    token_dictionary, offset = _read_dictionary(view, 0)
    separator_dictionary, offset = _read_dictionary(view, offset)
    row_count, offset = _decode_varint(view, offset)
    column_count, offset = _decode_varint(view, offset)
    separator_count, offset = _decode_varint(view, offset)
    token_count = row_count * column_count
    if row_count == 0 or column_count == 0 or token_count > expected_size + 1:
        raise ValueError("DMA1 matrix shape exceeds output bound")
    arithmetic_size, offset = _decode_varint(view, offset)
    arithmetic_end = offset + arithmetic_size
    if arithmetic_end > len(view):
        raise ValueError("truncated DMA1 arithmetic stream")
    symbols = _adaptive_decode(
        view[offset:arithmetic_end],
        token_count,
        column_count,
        len(token_dictionary),
    )
    offset = arithmetic_end
    separator_size, offset = _decode_varint(view, offset)
    separator_end = offset + separator_size
    if separator_end != len(view):
        raise ValueError("truncated or trailing DMA1 separator indices")
    separator_indices = _unpack_indices(
        view[offset:separator_end], separator_count, len(separator_dictionary)
    )
    output = bytearray()
    token_offset = 0
    separator_offset = 0
    is_token = starts_with_token
    for _ in range(token_count + separator_count):
        if is_token:
            output.extend(token_dictionary[symbols[token_offset]])
            token_offset += 1
        else:
            output.extend(separator_dictionary[separator_indices[separator_offset]])
            separator_offset += 1
        if len(output) > expected_size:
            raise ValueError("DMA1 output exceeds declared size")
        is_token = not is_token
    if len(output) != expected_size:
        raise ValueError("DMA1 output size does not match declaration")
    return bytes(output)


def adaptive_transform(data: bytes) -> bytes:
    if dense_adaptive_native_available():
        transformed, starts_with_token = native_dense_adaptive_transform(data)
        expected_start = not data or data[0] not in SEPARATOR_BYTES
        if starts_with_token != expected_start:
            raise ValueError("native DMA1 start type does not match input")
        return transformed
    return _adaptive_transform_python(data)


def adaptive_inverse_transform(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if dense_adaptive_native_available():
        return dense_adaptive_reassemble(
            transformed, starts_with_token, expected_size
        )
    return _adaptive_inverse_transform_python(
        transformed, starts_with_token, expected_size
    )


def _parallel_transform_python(data: bytes) -> bytes:
    _starts_with_token, tokens, separators = _split_runs(data)
    if any(not _is_numeric_lexeme(token) for token in tokens):
        raise ValueError("DMA2 input contains a nonnumeric field")
    row_count, column_count = _matrix_shape(data)
    token_dictionary = sorted(
        set(tokens), key=lambda token: (Decimal(token.decode("ascii")), token)
    )
    separator_dictionary = sorted(set(separators))
    token_lookup = {entry: index for index, entry in enumerate(token_dictionary)}
    separator_lookup = {
        entry: index for index, entry in enumerate(separator_dictionary)
    }
    symbols = [token_lookup[token] for token in tokens]
    requested_lanes = 7 if len(token_dictionary) <= 8 else 6
    lane_count = min(row_count, requested_lanes)
    boundaries = [
        row_count * lane // lane_count * column_count
        for lane in range(lane_count + 1)
    ]
    streams = [
        _adaptive_encode(
            symbols[boundaries[lane] : boundaries[lane + 1]],
            column_count,
            len(token_dictionary),
        )
        for lane in range(lane_count)
    ]
    separator_indices = [separator_lookup[item] for item in separators]
    packed_separators = _pack_indices(
        separator_indices, len(separator_dictionary)
    )
    output = bytearray()
    _write_dictionary(output, token_dictionary)
    _write_dictionary(output, separator_dictionary)
    output.extend(_encode_varint(row_count))
    output.extend(_encode_varint(column_count))
    output.extend(_encode_varint(len(separators)))
    output.extend(_encode_varint(lane_count))
    for stream in streams:
        output.extend(_encode_varint(len(stream)))
        output.extend(stream)
    output.extend(_encode_varint(len(packed_separators)))
    output.extend(packed_separators)
    return bytes(output)


def _parallel_inverse_transform_python(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    view = memoryview(transformed)
    token_dictionary, offset = _read_dictionary(view, 0)
    separator_dictionary, offset = _read_dictionary(view, offset)
    row_count, offset = _decode_varint(view, offset)
    column_count, offset = _decode_varint(view, offset)
    separator_count, offset = _decode_varint(view, offset)
    token_count = row_count * column_count
    if row_count == 0 or column_count == 0 or token_count > expected_size + 1:
        raise ValueError("DMA2 matrix shape exceeds output bound")
    lane_count, offset = _decode_varint(view, offset)
    if not 1 <= lane_count <= 7 or lane_count > row_count:
        raise ValueError("DMA2 lane count is invalid")
    symbols: list[int] = []
    for lane in range(lane_count):
        stream_size, offset = _decode_varint(view, offset)
        stream_end = offset + stream_size
        if stream_end > len(view):
            raise ValueError("truncated DMA2 arithmetic lane")
        start_row = row_count * lane // lane_count
        end_row = row_count * (lane + 1) // lane_count
        symbols.extend(
            _adaptive_decode(
                view[offset:stream_end],
                (end_row - start_row) * column_count,
                column_count,
                len(token_dictionary),
            )
        )
        offset = stream_end
    separator_size, offset = _decode_varint(view, offset)
    separator_end = offset + separator_size
    if separator_end != len(view):
        raise ValueError("truncated or trailing DMA2 separator indices")
    separator_indices = _unpack_indices(
        view[offset:separator_end], separator_count, len(separator_dictionary)
    )
    output = bytearray()
    token_offset = 0
    separator_offset = 0
    is_token = starts_with_token
    for _ in range(token_count + separator_count):
        if is_token:
            output.extend(token_dictionary[symbols[token_offset]])
            token_offset += 1
        else:
            output.extend(separator_dictionary[separator_indices[separator_offset]])
            separator_offset += 1
        if len(output) > expected_size:
            raise ValueError("DMA2 output exceeds declared size")
        is_token = not is_token
    if len(output) != expected_size:
        raise ValueError("DMA2 output size does not match declaration")
    return bytes(output)


def parallel_transform(data: bytes) -> bytes:
    if dense_parallel_native_available():
        transformed, starts_with_token = native_dense_parallel_transform(data)
        expected_start = not data or data[0] not in SEPARATOR_BYTES
        if starts_with_token != expected_start:
            raise ValueError("native DMA2 start type does not match input")
        return transformed
    return _parallel_transform_python(data)


def parallel_inverse_transform(
    transformed: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    if dense_parallel_native_available():
        return dense_parallel_reassemble(
            transformed, starts_with_token, expected_size
        )
    return _parallel_inverse_transform_python(
        transformed, starts_with_token, expected_size
    )


def _sample_alphabet_python(data: bytes, sample_size: int = 64 * 1024) -> int:
    _starts, tokens, _separators = _split_runs(data[:sample_size])
    if any(not _is_numeric_lexeme(token) for token in tokens):
        raise ValueError("DMS2 sample contains a nonnumeric field")
    return min(5, len(set(tokens)))


def _selector_frame(
    data: bytes,
    payload_source: bytes,
    *,
    flags: int,
    level: int,
) -> bytes:
    payload = zstd_compress(payload_source, level=level)
    return HEADER.pack(
        SELECTOR_MAGIC,
        VERSION,
        flags,
        len(data),
        len(payload_source),
        hashlib.sha256(data).digest(),
    ) + payload


def selector_compress(data: bytes, level: int = 19) -> bytes:
    starts_with_token = not data or data[0] not in SEPARATOR_BYTES
    start_flag = SELECTOR_STARTS_WITH_TOKEN if starts_with_token else 0

    # The direct candidate is deliberately level 1: it is the fast, safe path
    # for arbitrary input.  ctypes releases the GIL for both native operations,
    # so materialize it beside the specialist without adding their CPU times.
    with ThreadPoolExecutor(max_workers=1) as executor:
        direct_future = executor.submit(
            _selector_frame,
            data,
            data,
            flags=start_flag | SELECTOR_DIRECT,
            level=1,
        )
        try:
            alphabet = (
                dense_sample_alphabet(data)
                if dense_parallel_native_available()
                else _sample_alphabet_python(data)
            )
            use_planes = alphabet <= 4
            transformed = (
                plane_transform(data) if use_planes else parallel_transform(data)
            )
            specialist = _selector_frame(
                data,
                transformed,
                flags=start_flag | (SELECTOR_PLANES if use_planes else 0),
                level=level,
            )
        except (UnicodeDecodeError, ValueError):
            specialist = None
        direct = direct_future.result()
    if specialist is None or len(direct) < len(specialist):
        return direct
    return specialist


def selector_decompress(frame: bytes) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMS2 frame")
    magic, version, flags, original_size, transformed_size, digest = (
        HEADER.unpack_from(frame)
    )
    if magic != SELECTOR_MAGIC or version != VERSION or flags > 7:
        raise ValueError("invalid DMS2 header")
    payload = frame[HEADER.size :]
    if zstd_frame_content_size(payload) != transformed_size:
        raise ValueError("DMS2 transformed size does not match payload")
    try:
        transformed = zstd_decompress(payload, transformed_size)
    except RuntimeError as error:
        raise ValueError(f"invalid DMS2 payload: {error}") from error
    starts_with_token = bool(flags & 1)
    if flags & SELECTOR_DIRECT:
        if flags & SELECTOR_PLANES or transformed_size != original_size:
            raise ValueError("invalid DMS2 direct frame")
        output = transformed
    elif flags & SELECTOR_PLANES:
        output = plane_inverse_transform(
            transformed, starts_with_token, original_size
        )
    else:
        output = parallel_inverse_transform(
            transformed, starts_with_token, original_size
        )
    if hashlib.sha256(output).digest() != digest:
        raise ValueError("DMS2 checksum mismatch")
    return output


def selector_backend(frame: bytes) -> str:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMS2 frame")
    magic, version, flags, _original, _transformed, _digest = HEADER.unpack_from(
        frame
    )
    if magic != SELECTOR_MAGIC or version != VERSION or flags > 7:
        raise ValueError("invalid DMS2 header")
    if flags & SELECTOR_DIRECT:
        return "direct-zstd1"
    return "dmp1-planes" if flags & SELECTOR_PLANES else "dma2-parallel"


def _stream_segments(source: BinaryIO, segment_size: int) -> Iterator[bytes]:
    pending = bytearray()
    while chunk := source.read(segment_size):
        pending.extend(chunk)
        while len(pending) >= segment_size:
            boundary = pending.rfind(b"\n", 0, segment_size + 1) + 1
            if boundary == 0:
                boundary = segment_size
            yield bytes(pending[:boundary])
            del pending[:boundary]
    if pending:
        yield bytes(pending)


def selector_stream_compress(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    segment_size: int = DEFAULT_STREAM_SEGMENT_SIZE,
    level: int = 19,
) -> dict[str, int]:
    if not 1 <= segment_size <= MAX_STREAM_SEGMENT_SIZE:
        raise ValueError("DSS1 segment size is outside the supported range")
    destination.write(
        STREAM_HEADER.pack(SELECTOR_STREAM_MAGIC, VERSION, segment_size)
    )
    digest = hashlib.sha256()
    source_bytes = 0
    frame_bytes = STREAM_HEADER.size
    segments = 0
    for segment in _stream_segments(source, segment_size):
        frame = selector_compress(segment, level=level)
        destination.write(STREAM_LENGTH.pack(len(frame)))
        destination.write(frame)
        digest.update(segment)
        source_bytes += len(segment)
        frame_bytes += STREAM_LENGTH.size + len(frame)
        segments += 1
    destination.write(STREAM_LENGTH.pack(0))
    destination.write(STREAM_TRAILER.pack(source_bytes, digest.digest()))
    frame_bytes += STREAM_LENGTH.size + STREAM_TRAILER.size
    return {
        "source_bytes": source_bytes,
        "complete_bytes": frame_bytes,
        "segments": segments,
        "segment_size": segment_size,
    }


def _read_exact(source: BinaryIO, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        chunk = source.read(size - len(output))
        if not chunk:
            raise ValueError("truncated DSS1 stream")
        output.extend(chunk)
    return bytes(output)


def selector_stream_decompress(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    max_output_size: int = MAX_TRANSFORMED_BYTES,
) -> dict[str, int]:
    magic, version, segment_size = STREAM_HEADER.unpack(
        _read_exact(source, STREAM_HEADER.size)
    )
    if (
        magic != SELECTOR_STREAM_MAGIC
        or version != VERSION
        or not 1 <= segment_size <= MAX_STREAM_SEGMENT_SIZE
    ):
        raise ValueError("invalid DSS1 header")
    digest = hashlib.sha256()
    output_bytes = 0
    frame_bytes = STREAM_HEADER.size
    segments = 0
    while True:
        (frame_size,) = STREAM_LENGTH.unpack(
            _read_exact(source, STREAM_LENGTH.size)
        )
        frame_bytes += STREAM_LENGTH.size
        if frame_size == 0:
            break
        if frame_size > max_output_size + HEADER.size + 1024 * 1024:
            raise ValueError("DSS1 segment frame exceeds output bound")
        frame = _read_exact(source, frame_size)
        frame_bytes += frame_size
        restored = selector_decompress(frame)
        if len(restored) > segment_size:
            raise ValueError("DSS1 segment exceeds declared bound")
        if output_bytes + len(restored) > max_output_size:
            raise ValueError("DSS1 output exceeds configured bound")
        destination.write(restored)
        digest.update(restored)
        output_bytes += len(restored)
        segments += 1
    declared_size, declared_digest = STREAM_TRAILER.unpack(
        _read_exact(source, STREAM_TRAILER.size)
    )
    frame_bytes += STREAM_TRAILER.size
    if source.read(1):
        raise ValueError("trailing DSS1 bytes")
    if declared_size != output_bytes or declared_digest != digest.digest():
        raise ValueError("DSS1 stream checksum mismatch")
    return {
        "source_bytes": output_bytes,
        "complete_bytes": frame_bytes,
        "segments": segments,
        "segment_size": segment_size,
    }


def adaptive_compress(data: bytes, level: int = 3) -> bytes:
    starts_with_token, _tokens, _separators = _split_runs(data)
    transformed = adaptive_transform(data)
    payload = zstd_compress(transformed, level=level)
    return HEADER.pack(
        ADAPTIVE_MAGIC,
        VERSION,
        int(starts_with_token),
        len(data),
        len(transformed),
        hashlib.sha256(data).digest(),
    ) + payload


def adaptive_decompress(frame: bytes) -> bytes:
    if len(frame) < HEADER.size:
        raise ValueError("truncated DMA1 frame")
    magic, version, starts, original_size, transformed_size, digest = (
        HEADER.unpack_from(frame)
    )
    if magic != ADAPTIVE_MAGIC or version != VERSION or starts not in (0, 1):
        raise ValueError("invalid DMA1 header")
    payload = frame[HEADER.size :]
    if zstd_frame_content_size(payload) != transformed_size:
        raise ValueError("DMA1 transformed size does not match payload")
    transformed = zstd_decompress(payload, transformed_size)
    output = adaptive_inverse_transform(transformed, bool(starts), original_size)
    if hashlib.sha256(output).digest() != digest:
        raise ValueError("DMA1 checksum mismatch")
    return output
