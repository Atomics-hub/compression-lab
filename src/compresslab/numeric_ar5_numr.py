"""Experimental exact AR5/NUM-R numeric-frame prototype.

This module is deliberately outside the public API.  It implements only the
frozen, cheapest high-information ablation and is authorized for synthetic
exactness/corruption/determinism preflight, not corpus measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Tuple, cast

import zstandard


MAGIC = b"NMR1"
VERSION = 1
VECTOR_VALUES = 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_FRAME_BYTES = MAX_INPUT_BYTES + 16 * 1024 * 1024
MAX_BLOCK_PAYLOAD_OVERHEAD = 4096
PREFIX = struct.Struct(">4sBBBBBI")
TAIL = struct.Struct(">QII")
BLOCK = struct.Struct(">BHII")
FOOTER_BYTES = 64

MODE_STORE = 0
MODE_XOR_FRONT = 1
MODE_BYTE_PLANE_ZSTD = 2
MODE_AR5_DECIMAL_ORIGIN = 3
MODE_NAMES = {
    MODE_STORE: "store",
    MODE_XOR_FRONT: "xor-front-bit",
    MODE_BYTE_PLANE_ZSTD: "byte-plane-zstd",
    MODE_AR5_DECIMAL_ORIGIN: "ar5-decimal-origin",
}

ENDIAN_CODES = {"little": 0, "big": 1}
ENDIAN_NAMES = {value: key for key, value in ENDIAN_CODES.items()}
LAYOUT_CODES = {
    "one_dimensional_ordered_series": 0,
    "row_major_dense_matrix": 1,
    "column_major_dense_matrix": 2,
}
LAYOUT_NAMES = {value: key for key, value in LAYOUT_CODES.items()}


@dataclass(frozen=True)
class DType:
    code: int
    width: int
    float_bits: int = 0
    exponent_bits: int = 0
    mantissa_bits: int = 0
    bias: int = 0
    max_decimal_exponent: int = 0

    @property
    def is_float(self) -> bool:
        return self.float_bits != 0


DTYPES: Dict[str, DType] = {
    "float32": DType(0, 4, 32, 8, 23, 127, 10),
    "float64": DType(1, 8, 64, 11, 52, 1023, 18),
    "int16": DType(2, 2),
    "int32": DType(3, 4),
    "int64": DType(4, 8),
    "uint16": DType(5, 2),
    "uint32": DType(6, 4),
    "uint64": DType(7, 8),
}
DTYPE_NAMES = {value.code: key for key, value in DTYPES.items()}
ByteOrder = Literal["little", "big"]


class _BitWriter:
    def __init__(self) -> None:
        self._bytes = bytearray()
        self._value = 0
        self._bits = 0

    def write(self, value: int, width: int) -> None:
        if width < 0 or value < 0 or (width == 0 and value) or value.bit_length() > width:
            raise ValueError("bit value does not fit declared width")
        if width == 0:
            return
        self._value = (self._value << width) | value
        self._bits += width
        while self._bits >= 8:
            shift = self._bits - 8
            self._bytes.append((self._value >> shift) & 0xFF)
            self._value &= (1 << shift) - 1
            self._bits = shift

    def finish(self) -> bytes:
        if self._bits:
            self._bytes.append((self._value << (8 - self._bits)) & 0xFF)
            self._value = 0
            self._bits = 0
        return bytes(self._bytes)


class _BitReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def read(self, width: int) -> int:
        if width < 0 or self._offset + width > len(self._data) * 8:
            raise ValueError("truncated bit stream")
        value = 0
        for _ in range(width):
            byte = self._data[self._offset // 8]
            bit = (byte >> (7 - self._offset % 8)) & 1
            value = (value << 1) | bit
            self._offset += 1
        return value

    def finish(self) -> None:
        remaining = len(self._data) * 8 - self._offset
        if remaining >= 8:
            raise ValueError("unconsumed bit-stream bytes")
        if remaining and self.read(remaining) != 0:
            raise ValueError("nonzero bit-stream padding")


def _round_ratio_even(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("rounding expects a nonnegative rational")
    quotient, remainder = divmod(numerator, denominator)
    doubled = remainder * 2
    if doubled > denominator or (doubled == denominator and quotient & 1):
        quotient += 1
    return quotient


def _ratio_floor_log2(numerator: int, denominator: int) -> int:
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        if numerator < denominator << exponent:
            exponent -= 1
    elif numerator << -exponent < denominator:
        exponent -= 1
    return exponent


def _ratio_to_float_bits(numerator: int, denominator: int, dtype: DType) -> int:
    if not dtype.is_float or denominator <= 0:
        raise ValueError("invalid rational float conversion")
    sign = 1 if numerator < 0 else 0
    numerator = abs(numerator)
    if numerator == 0:
        return sign << (dtype.float_bits - 1)
    exponent = _ratio_floor_log2(numerator, denominator)
    minimum_exponent = 1 - dtype.bias
    maximum_exponent = ((1 << dtype.exponent_bits) - 2) - dtype.bias
    if exponent > maximum_exponent:
        return (sign << (dtype.float_bits - 1)) | (
            ((1 << dtype.exponent_bits) - 1) << dtype.mantissa_bits
        )
    if exponent >= minimum_exponent:
        shift = dtype.mantissa_bits - exponent
        if shift >= 0:
            significand = _round_ratio_even(numerator << shift, denominator)
        else:
            significand = _round_ratio_even(numerator, denominator << -shift)
        if significand == 1 << (dtype.mantissa_bits + 1):
            significand >>= 1
            exponent += 1
            if exponent > maximum_exponent:
                return (sign << (dtype.float_bits - 1)) | (
                    ((1 << dtype.exponent_bits) - 1) << dtype.mantissa_bits
                )
        exponent_field = exponent + dtype.bias
        mantissa = significand - (1 << dtype.mantissa_bits)
    else:
        shift = dtype.mantissa_bits - minimum_exponent
        significand = _round_ratio_even(numerator << shift, denominator)
        if significand == 0:
            return sign << (dtype.float_bits - 1)
        if significand >= 1 << dtype.mantissa_bits:
            exponent_field = 1
            mantissa = 0
        else:
            exponent_field = 0
            mantissa = significand
    return (
        (sign << (dtype.float_bits - 1))
        | (exponent_field << dtype.mantissa_bits)
        | mantissa
    )


def _float_bits_to_ratio(bits: int, dtype: DType) -> Optional[Tuple[int, int]]:
    sign = -1 if bits >> (dtype.float_bits - 1) else 1
    exponent_mask = (1 << dtype.exponent_bits) - 1
    exponent_field = (bits >> dtype.mantissa_bits) & exponent_mask
    mantissa = bits & ((1 << dtype.mantissa_bits) - 1)
    if exponent_field == exponent_mask:
        return None
    if exponent_field == 0:
        significand = mantissa
        exponent = 1 - dtype.bias - dtype.mantissa_bits
    else:
        significand = (1 << dtype.mantissa_bits) | mantissa
        exponent = exponent_field - dtype.bias - dtype.mantissa_bits
    numerator = sign * significand
    if exponent >= 0:
        return numerator << exponent, 1
    return numerator, 1 << -exponent


def _recast_integer(bits: int, decimal_power: int, dtype: DType) -> Optional[int]:
    ratio = _float_bits_to_ratio(bits, dtype)
    if ratio is None:
        return None
    numerator, denominator = ratio
    sign = -1 if numerator < 0 else 1
    encoded = sign * _round_ratio_even(abs(numerator) * (10**decimal_power), denominator)
    if not -(1 << 127) <= encoded < (1 << 127):
        return None
    if _ratio_to_float_bits(encoded, 10**decimal_power, dtype) != bits:
        return None
    return encoded


def _pack_fixed(values: Iterable[int], width: int) -> bytes:
    writer = _BitWriter()
    for value in values:
        writer.write(value, width)
    return writer.finish()


def _unpack_fixed(data: bytes, count: int, width: int) -> List[int]:
    reader = _BitReader(data)
    values = [reader.read(width) for _ in range(count)]
    reader.finish()
    return values


def _xor_encode(raw: bytes, width_bytes: int, endianness: ByteOrder) -> bytes:
    count = len(raw) // width_bytes
    if count == 0:
        return b""
    words = [
        int.from_bytes(raw[offset : offset + width_bytes], endianness)
        for offset in range(0, len(raw), width_bytes)
    ]
    width = width_bytes * 8
    count_width = 5 if width == 32 else 6 if width == 64 else 4
    writer = _BitWriter()
    previous = words[0]
    window: Optional[Tuple[int, int]] = None
    for word in words[1:]:
        xor = previous ^ word
        previous = word
        if xor == 0:
            writer.write(0, 1)
            continue
        writer.write(1, 1)
        leading = width - xor.bit_length()
        trailing = (xor & -xor).bit_length() - 1
        if window is not None and leading >= window[0] and trailing >= window[1]:
            writer.write(0, 1)
            significant_width = width - window[0] - window[1]
            writer.write(xor >> window[1], significant_width)
        else:
            writer.write(1, 1)
            significant_width = width - leading - trailing
            writer.write(leading, count_width)
            writer.write(significant_width - 1, count_width)
            writer.write(xor >> trailing, significant_width)
            window = (leading, trailing)
    return raw[:width_bytes] + writer.finish()


def _xor_decode(
    payload: bytes, count: int, width_bytes: int, endianness: ByteOrder
) -> bytes:
    if count == 0:
        if payload:
            raise ValueError("nonempty XOR payload for empty block")
        return b""
    if len(payload) < width_bytes:
        raise ValueError("truncated XOR first word")
    width = width_bytes * 8
    count_width = 5 if width == 32 else 6 if width == 64 else 4
    previous = int.from_bytes(payload[:width_bytes], endianness)
    output = bytearray(payload[:width_bytes])
    window: Optional[Tuple[int, int]] = None
    reader = _BitReader(payload[width_bytes:])
    for _ in range(count - 1):
        if reader.read(1) == 0:
            word = previous
        else:
            reuse = reader.read(1) == 0
            if reuse:
                if window is None:
                    raise ValueError("XOR stream reuses an absent window")
                leading, trailing = window
                significant_width = width - leading - trailing
            else:
                leading = reader.read(count_width)
                significant_width = reader.read(count_width) + 1
                trailing = width - leading - significant_width
                if trailing < 0:
                    raise ValueError("invalid XOR window")
                window = (leading, trailing)
            significant = reader.read(significant_width)
            word = previous ^ (significant << trailing)
        output.extend(word.to_bytes(width_bytes, endianness))
        previous = word
    reader.finish()
    return bytes(output)


def _byte_plane(raw: bytes, width: int, endianness: ByteOrder) -> bytes:
    count = len(raw) // width
    canonical = bytearray(len(raw))
    for index in range(count):
        word = int.from_bytes(raw[index * width : (index + 1) * width], endianness)
        canonical[index * width : (index + 1) * width] = word.to_bytes(width, "big")
    return b"".join(canonical[plane::width] for plane in range(width))


def _inverse_byte_plane(planes: bytes, width: int, endianness: ByteOrder) -> bytes:
    count = len(planes) // width
    canonical = bytearray(len(planes))
    for plane in range(width):
        values = planes[plane * count : (plane + 1) * count]
        canonical[plane::width] = values
    output = bytearray(len(planes))
    for index in range(count):
        word = int.from_bytes(canonical[index * width : (index + 1) * width], "big")
        output[index * width : (index + 1) * width] = word.to_bytes(width, endianness)
    return bytes(output)


def _zstd_compress(data: bytes) -> bytes:
    compressor = zstandard.ZstdCompressor(
        level=9,
        threads=0,
        write_checksum=True,
        write_content_size=True,
        write_dict_id=False,
    )
    return compressor.compress(data)


def _zstd_decompress(data: bytes, expected_size: int) -> bytes:
    try:
        restored = zstandard.ZstdDecompressor().decompress(
            data, max_output_size=expected_size
        )
    except zstandard.ZstdError as error:
        raise ValueError("invalid Zstandard payload") from error
    if len(restored) != expected_size:
        raise ValueError("Zstandard output size differs")
    return restored


def _ar5_payload_for_pair(
    raw: bytes, dtype: DType, endianness: ByteOrder, exponent: int, factor: int
) -> Tuple[bytes, int]:
    width = dtype.width
    words = [
        int.from_bytes(raw[offset : offset + width], endianness)
        for offset in range(0, len(raw), width)
    ]
    power = exponent - factor
    recast = [_recast_integer(word, power, dtype) for word in words]
    regular = [value for value in recast if value is not None]
    origin = min(regular) if regular else 0
    offsets = [value - origin for value in regular]
    bit_width = max((value.bit_length() for value in offsets), default=0)
    bitmap = bytearray(math.ceil(len(words) / 8))
    exceptions = bytearray()
    for index, (word, value) in enumerate(zip(words, recast)):
        if value is None:
            bitmap[index // 8] |= 1 << (index % 8)
            exceptions.extend(word.to_bytes(width, endianness))
    packed = _pack_fixed(offsets, bit_width)
    header = struct.pack(
        ">BB16sBHHI",
        exponent,
        factor,
        origin.to_bytes(16, "big", signed=True),
        bit_width,
        len(exceptions) // width,
        len(bitmap),
        len(packed),
    )
    return header + bitmap + packed + exceptions, origin


def _ar5_encode(raw: bytes, dtype: DType, endianness: ByteOrder) -> bytes:
    best: Optional[Tuple[int, int, int, int, bytes]] = None
    # Every (exponent, factor) pair with the same difference represents the
    # same decimal scale and complete payload length.  The frozen tie break
    # therefore canonically chooses (power, 0), the lowest eligible exponent.
    for power in range(dtype.max_decimal_exponent + 1):
        payload, origin = _ar5_payload_for_pair(
            raw, dtype, endianness, power, 0
        )
        key = (len(payload), power, 0, origin)
        if best is None or key < best[:4]:
            best = (len(payload), power, 0, origin, payload)
    if best is None:
        raise AssertionError("AR5 search did not enumerate a pair")
    return best[4]


def _ar5_decode(
    payload: bytes, count: int, dtype: DType, endianness: ByteOrder
) -> bytes:
    header_size = struct.calcsize(">BB16sBHHI")
    if len(payload) < header_size:
        raise ValueError("truncated AR5 header")
    exponent, factor, origin_raw, bit_width, exception_count, bitmap_size, packed_size = struct.unpack(
        ">BB16sBHHI", payload[:header_size]
    )
    if exponent > dtype.max_decimal_exponent or factor > exponent or bit_width > 128:
        raise ValueError("invalid AR5 parameters")
    expected_bitmap_size = math.ceil(count / 8)
    if bitmap_size != expected_bitmap_size:
        raise ValueError("AR5 exception bitmap size differs")
    regular_count = count - exception_count
    expected_packed_size = math.ceil(regular_count * bit_width / 8)
    if packed_size != expected_packed_size:
        raise ValueError("AR5 packed size differs")
    bitmap_end = header_size + bitmap_size
    packed_end = bitmap_end + packed_size
    exception_bytes = exception_count * dtype.width
    if packed_end + exception_bytes != len(payload):
        raise ValueError("AR5 payload length differs")
    bitmap = payload[header_size:bitmap_end]
    if count % 8 and bitmap and bitmap[-1] >> (count % 8):
        raise ValueError("AR5 bitmap has nonzero padding")
    observed_exceptions = sum(bin(byte).count("1") for byte in bitmap)
    if observed_exceptions != exception_count:
        raise ValueError("AR5 exception count differs")
    offsets = iter(
        _unpack_fixed(payload[bitmap_end:packed_end], regular_count, bit_width)
    )
    exceptions = memoryview(payload)[packed_end:]
    exception_offset = 0
    origin = int.from_bytes(origin_raw, "big", signed=True)
    power = exponent - factor
    output = bytearray()
    for index in range(count):
        if bitmap[index // 8] & (1 << (index % 8)):
            output.extend(
                exceptions[exception_offset : exception_offset + dtype.width]
            )
            exception_offset += dtype.width
        else:
            recast = origin + next(offsets)
            if not -(1 << 127) <= recast < (1 << 127):
                raise ValueError("AR5 recast integer overflow")
            bits = _ratio_to_float_bits(recast, 10**power, dtype)
            output.extend(bits.to_bytes(dtype.width, endianness))
    return bytes(output)


def _validate_input(
    data: bytes, dtype_name: str, endianness: str, shape: Sequence[int], layout: str
) -> Tuple[DType, Tuple[int, ...]]:
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("prototype input exceeds the 64 MiB bounded chunk")
    if dtype_name not in DTYPES:
        raise ValueError("unsupported numeric dtype")
    if endianness not in ENDIAN_CODES:
        raise ValueError("endianness must be explicit")
    if layout not in LAYOUT_CODES:
        raise ValueError("unsupported numeric layout")
    frozen_shape = tuple(shape)
    if not frozen_shape or len(frozen_shape) > 8 or any(
        not isinstance(dimension, int) or dimension < 0 for dimension in frozen_shape
    ):
        raise ValueError("shape must contain one to eight nonnegative integers")
    if layout == "one_dimensional_ordered_series" and len(frozen_shape) != 1:
        raise ValueError("ordered series must have rank one")
    if layout != "one_dimensional_ordered_series" and len(frozen_shape) != 2:
        raise ValueError("dense matrix must have rank two")
    dtype = DTYPES[dtype_name]
    value_count = math.prod(frozen_shape)
    if value_count * dtype.width != len(data):
        raise ValueError("shape, dtype, and payload byte count disagree")
    return dtype, frozen_shape


def _metadata(
    dtype: DType,
    endianness: str,
    layout: str,
    shape: Tuple[int, ...],
    value_count: int,
    original_size: int,
    block_count: int,
) -> bytes:
    prefix = PREFIX.pack(
        MAGIC,
        VERSION,
        dtype.code,
        ENDIAN_CODES[endianness],
        LAYOUT_CODES[layout],
        len(shape),
        VECTOR_VALUES,
    )
    dimensions = b"".join(struct.pack(">Q", dimension) for dimension in shape)
    return prefix + dimensions + TAIL.pack(value_count, original_size, block_count)


def compress(
    data: bytes,
    *,
    dtype: str,
    endianness: str,
    shape: Sequence[int],
    layout: str,
) -> bytes:
    """Encode one bounded exact numeric item with the frozen prototype selector."""
    dtype_spec, frozen_shape = _validate_input(data, dtype, endianness, shape, layout)
    byte_order = cast(ByteOrder, endianness)
    value_count = len(data) // dtype_spec.width
    block_count = math.ceil(value_count / VECTOR_VALUES) if value_count else 0
    metadata = _metadata(
        dtype_spec,
        endianness,
        layout,
        frozen_shape,
        value_count,
        len(data),
        block_count,
    )
    blocks = bytearray()
    for start in range(0, value_count, VECTOR_VALUES):
        count = min(VECTOR_VALUES, value_count - start)
        raw_start = start * dtype_spec.width
        raw_end = raw_start + count * dtype_spec.width
        raw = data[raw_start:raw_end]
        candidates = [
            (len(raw), MODE_STORE, raw),
            (
                len(xor_payload := _xor_encode(raw, dtype_spec.width, byte_order)),
                MODE_XOR_FRONT,
                xor_payload,
            ),
            (
                len(
                    plane_payload := _zstd_compress(
                        _byte_plane(raw, dtype_spec.width, byte_order)
                    )
                ),
                MODE_BYTE_PLANE_ZSTD,
                plane_payload,
            ),
        ]
        if dtype_spec.is_float:
            ar5_payload = _ar5_encode(raw, dtype_spec, byte_order)
            candidates.append(
                (len(ar5_payload), MODE_AR5_DECIMAL_ORIGIN, ar5_payload)
            )
        payload_size, mode, payload = min(candidates, key=lambda row: (row[0], row[1]))
        blocks.extend(BLOCK.pack(mode, count, len(raw), payload_size))
        blocks.extend(payload)
    body = metadata + blocks
    source_digest = hashlib.sha256(metadata + data).digest()
    frame_digest = hashlib.sha256(body + source_digest).digest()
    frame = body + source_digest + frame_digest
    if len(frame) > len(metadata) + block_count * BLOCK.size + len(data) + FOOTER_BYTES:
        raise AssertionError("selector expanded beyond its equally framed store fallback")
    return frame


def _parse_header(
    frame: bytes,
) -> Tuple[DType, ByteOrder, str, Tuple[int, ...], int, int, int, int]:
    if len(frame) < PREFIX.size + TAIL.size + FOOTER_BYTES:
        raise ValueError("truncated numeric frame")
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError("numeric frame exceeds the prototype bound")
    magic, version, dtype_code, endian_code, layout_code, rank, vector_values = PREFIX.unpack(
        frame[: PREFIX.size]
    )
    if magic != MAGIC or version != VERSION or vector_values != VECTOR_VALUES:
        raise ValueError("unsupported numeric frame header")
    if dtype_code not in DTYPE_NAMES or endian_code not in ENDIAN_NAMES:
        raise ValueError("invalid numeric type or endian code")
    if layout_code not in LAYOUT_NAMES or rank == 0 or rank > 8:
        raise ValueError("invalid numeric layout or rank")
    offset = PREFIX.size
    dimensions_end = offset + rank * 8
    if dimensions_end + TAIL.size + FOOTER_BYTES > len(frame):
        raise ValueError("truncated numeric shape")
    shape = tuple(
        struct.unpack(">Q", frame[index : index + 8])[0]
        for index in range(offset, dimensions_end, 8)
    )
    value_count, original_size, block_count = TAIL.unpack(
        frame[dimensions_end : dimensions_end + TAIL.size]
    )
    dtype = DTYPES[DTYPE_NAMES[dtype_code]]
    layout = LAYOUT_NAMES[layout_code]
    if original_size > MAX_INPUT_BYTES or original_size != value_count * dtype.width:
        raise ValueError("invalid numeric source size")
    if math.prod(shape) != value_count:
        raise ValueError("numeric shape and value count disagree")
    if (layout == "one_dimensional_ordered_series") != (rank == 1):
        raise ValueError("numeric rank and layout disagree")
    if layout != "one_dimensional_ordered_series" and rank != 2:
        raise ValueError("dense numeric rank must be two")
    expected_blocks = math.ceil(value_count / VECTOR_VALUES) if value_count else 0
    if block_count != expected_blocks:
        raise ValueError("numeric block count differs")
    body_end = len(frame) - FOOTER_BYTES
    frame_digest = frame[-32:]
    if hashlib.sha256(frame[:body_end] + frame[body_end : body_end + 32]).digest() != frame_digest:
        raise ValueError("numeric frame checksum differs")
    return (
        dtype,
        cast(ByteOrder, ENDIAN_NAMES[endian_code]),
        layout,
        shape,
        value_count,
        original_size,
        block_count,
        dimensions_end + TAIL.size,
    )


def decompress(frame: bytes, *, max_output_size: int = MAX_INPUT_BYTES) -> bytes:
    """Decode one numeric prototype frame after structural and checksum checks."""
    (
        dtype,
        endianness,
        _layout,
        _shape,
        value_count,
        original_size,
        block_count,
        offset,
    ) = _parse_header(frame)
    if original_size > max_output_size:
        raise ValueError("numeric output exceeds the caller bound")
    body_end = len(frame) - FOOTER_BYTES
    output = bytearray()
    observed_values = 0
    for _ in range(block_count):
        if offset + BLOCK.size > body_end:
            raise ValueError("truncated numeric block header")
        mode, count, raw_size, payload_size = BLOCK.unpack(
            frame[offset : offset + BLOCK.size]
        )
        offset += BLOCK.size
        if count == 0 or count > VECTOR_VALUES or raw_size != count * dtype.width:
            raise ValueError("invalid numeric block dimensions")
        if payload_size > raw_size + MAX_BLOCK_PAYLOAD_OVERHEAD:
            raise ValueError("numeric block payload exceeds its bound")
        payload_end = offset + payload_size
        if payload_end > body_end:
            raise ValueError("truncated numeric block payload")
        payload = frame[offset:payload_end]
        offset = payload_end
        if mode == MODE_STORE:
            restored = payload
        elif mode == MODE_XOR_FRONT:
            restored = _xor_decode(payload, count, dtype.width, endianness)
        elif mode == MODE_BYTE_PLANE_ZSTD:
            planes = _zstd_decompress(payload, raw_size)
            restored = _inverse_byte_plane(planes, dtype.width, endianness)
        elif mode == MODE_AR5_DECIMAL_ORIGIN and dtype.is_float:
            restored = _ar5_decode(payload, count, dtype, endianness)
        else:
            raise ValueError("unsupported numeric block mode")
        if len(restored) != raw_size:
            raise ValueError("numeric block output size differs")
        output.extend(restored)
        observed_values += count
    if offset != body_end or observed_values != value_count or len(output) != original_size:
        raise ValueError("numeric frame accounting differs")
    metadata_end = (
        PREFIX.size + len(_shape) * 8 + TAIL.size
    )
    source_digest = frame[body_end : body_end + 32]
    if hashlib.sha256(frame[:metadata_end] + output).digest() != source_digest:
        raise ValueError("numeric source checksum differs")
    return bytes(output)


def decompress_with_metadata(
    frame: bytes, *, max_output_size: int = MAX_INPUT_BYTES
) -> Tuple[bytes, dict]:
    """Decode payload and return the exact self-described side metadata."""
    restored = decompress(frame, max_output_size=max_output_size)
    dtype, endianness, layout, shape, value_count, _, block_count, _ = _parse_header(
        frame
    )
    return restored, {
        "dtype": DTYPE_NAMES[dtype.code],
        "endianness": endianness,
        "rank": len(shape),
        "shape": shape,
        "layout": layout,
        "value_count": value_count,
        "block_count": block_count,
    }


def inspect(frame: bytes) -> dict:
    """Return counted frame metadata after verifying an exact decode."""
    restored = decompress(frame)
    dtype, endianness, layout, shape, value_count, _, block_count, offset = _parse_header(
        frame
    )
    mode_counts = {name: 0 for name in MODE_NAMES.values()}
    payload_bytes = 0
    metadata_bytes = offset
    body_end = len(frame) - FOOTER_BYTES
    for _ in range(block_count):
        mode, _count, _raw_size, payload_size = BLOCK.unpack(
            frame[offset : offset + BLOCK.size]
        )
        offset += BLOCK.size + payload_size
        mode_counts[MODE_NAMES[mode]] += 1
        payload_bytes += payload_size
    if offset != body_end:
        raise ValueError("numeric frame inspection accounting differs")
    return {
        "dtype": DTYPE_NAMES[dtype.code],
        "endianness": endianness,
        "layout": layout,
        "shape": shape,
        "value_count": value_count,
        "source_bytes": len(restored),
        "frame_bytes": len(frame),
        "metadata_and_table_bytes": len(frame) - payload_bytes,
        "payload_bytes": payload_bytes,
        "blocks": block_count,
        "mode_counts": mode_counts,
        "selector_never_exceeds_equally_framed_store": len(frame)
        <= metadata_bytes
        + block_count * BLOCK.size
        + len(restored)
        + FOOTER_BYTES,
    }
