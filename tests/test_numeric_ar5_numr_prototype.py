from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import struct
import unittest

import compresslab.numeric_ar5_numr as numeric


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config" / "numeric-ar5-numr-toolchain-lock-v1.json"
ACQUIRE = ROOT / "scripts" / "acquire-numeric-ar5-numr-toolchain.py"


def load_acquisition_verifier():
    spec = importlib.util.spec_from_file_location("numeric_toolchain", ACQUIRE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load numeric toolchain verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ACQUISITION = load_acquisition_verifier()


def encode_values(values, code: str, endianness: str) -> bytes:
    prefix = "<" if endianness == "little" else ">"
    return b"".join(struct.pack(prefix + code, value) for value in values)


class NumericToolchainLockTests(unittest.TestCase):
    def test_lock_is_exact_and_fail_closed(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        ACQUISITION.verify_lock(lock)
        self.assertFalse(lock["measurement_authorized"])
        self.assertFalse(lock["corpus_access_authorized"])
        self.assertIsNone(lock["results"])
        self.assertEqual(len(lock["sources"]), 8)
        self.assertEqual(lock["candidate_runtime"]["bundled_libzstd_version"], "1.5.7")

    def test_lock_rejects_authorization_or_source_drift(self) -> None:
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        lock["measurement_authorized"] = True
        with self.assertRaisesRegex(ValueError, "fail-closed"):
            ACQUISITION.verify_lock(lock)
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        lock["sources"][0]["revision"] = "short"
        with self.assertRaisesRegex(ValueError, "incomplete"):
            ACQUISITION.verify_lock(lock)
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        lock["sources"][0]["revision"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "identity drifted"):
            ACQUISITION.verify_lock(lock)


class NumericPrototypeTests(unittest.TestCase):
    def roundtrip(
        self,
        source: bytes,
        *,
        dtype: str,
        endianness: str,
        shape,
        layout: str,
    ) -> bytes:
        first = numeric.compress(
            source,
            dtype=dtype,
            endianness=endianness,
            shape=shape,
            layout=layout,
        )
        second = numeric.compress(
            source,
            dtype=dtype,
            endianness=endianness,
            shape=shape,
            layout=layout,
        )
        self.assertEqual(first, second)
        self.assertEqual(numeric.decompress(first, max_output_size=len(source)), source)
        restored, metadata = numeric.decompress_with_metadata(
            first, max_output_size=len(source)
        )
        self.assertEqual(restored, source)
        self.assertEqual(metadata["dtype"], dtype)
        self.assertEqual(metadata["endianness"], endianness)
        self.assertEqual(metadata["shape"], tuple(shape))
        self.assertEqual(metadata["layout"], layout)
        details = numeric.inspect(first)
        self.assertEqual(details["source_bytes"], len(source))
        self.assertEqual(
            details["frame_bytes"],
            details["metadata_and_table_bytes"] + details["payload_bytes"],
        )
        store_ceiling = (
            numeric.PREFIX.size
            + len(shape) * 8
            + numeric.TAIL.size
            + details["blocks"] * numeric.BLOCK.size
            + len(source)
            + numeric.FOOTER_BYTES
        )
        self.assertLessEqual(len(first), store_ceiling)
        return first

    def test_all_declared_dtypes_and_endian_orders_roundtrip(self) -> None:
        fixtures = {
            "float32": ("f", [0.0, -0.0, 1.25, -2.5, float("inf"), float("-inf")]),
            "float64": ("d", [0.0, -0.0, 1.25, -2.5, float("inf"), float("-inf")]),
            "int16": ("h", [-32768, -1, 0, 1, 32767]),
            "int32": ("i", [-(1 << 31), -1, 0, 1, (1 << 31) - 1]),
            "int64": ("q", [-(1 << 63), -1, 0, 1, (1 << 63) - 1]),
            "uint16": ("H", [0, 1, 255, 256, (1 << 16) - 1]),
            "uint32": ("I", [0, 1, 65535, 65536, (1 << 32) - 1]),
            "uint64": ("Q", [0, 1, 1 << 32, (1 << 64) - 1]),
        }
        for dtype, (code, values) in fixtures.items():
            for endianness in ("little", "big"):
                with self.subTest(dtype=dtype, endianness=endianness):
                    source = encode_values(values, code, endianness)
                    self.roundtrip(
                        source,
                        dtype=dtype,
                        endianness=endianness,
                        shape=(len(values),),
                        layout="one_dimensional_ordered_series",
                    )

    def test_float_special_words_preserve_every_bit(self) -> None:
        for dtype, width, words in (
            (
                "float32",
                4,
                [0, 1 << 31, 1, 0x007FFFFF, 0x7F800000, 0xFF800000, 0x7FC12345, 0x7F812345],
            ),
            (
                "float64",
                8,
                [
                    0,
                    1 << 63,
                    1,
                    0x000FFFFFFFFFFFFF,
                    0x7FF0000000000000,
                    0xFFF0000000000000,
                    0x7FF8123456789ABC,
                    0x7FF0123456789ABC,
                ],
            ),
        ):
            for endianness in ("little", "big"):
                source = b"".join(word.to_bytes(width, endianness) for word in words)
                with self.subTest(dtype=dtype, endianness=endianness):
                    self.roundtrip(
                        source,
                        dtype=dtype,
                        endianness=endianness,
                        shape=(len(words),),
                        layout="one_dimensional_ordered_series",
                    )

    def test_integer_rational_ieee_reconstruction_is_bit_exact(self) -> None:
        generator = random.Random(0x1EEE)
        for dtype in (numeric.DTYPES["float32"], numeric.DTYPES["float64"]):
            exponent_mask = (1 << dtype.exponent_bits) - 1
            for _ in range(2000):
                bits = generator.getrandbits(dtype.float_bits)
                exponent = (bits >> dtype.mantissa_bits) & exponent_mask
                if exponent == exponent_mask:
                    continue
                ratio = numeric._float_bits_to_ratio(bits, dtype)
                self.assertIsNotNone(ratio)
                numerator, denominator = ratio
                if numerator == 0 and bits >> (dtype.float_bits - 1):
                    continue  # negative zero is deliberately an exact raw-word exception
                self.assertEqual(
                    numeric._ratio_to_float_bits(numerator, denominator, dtype), bits
                )

    def test_each_selector_mode_is_exercised(self) -> None:
        random_source = random.Random(7).randbytes(8 * numeric.VECTOR_VALUES)
        xor_source = encode_values([1.25] * 5, "d", "little")
        plane_source = encode_values(range(numeric.VECTOR_VALUES), "q", "little")
        ar5_values = [round(math.sin(index / 10), 3) for index in range(1024)]
        ar5_source = encode_values(ar5_values, "d", "little")
        cases = (
            (random_source, "uint64", "store"),
            (xor_source, "float64", "xor-front-bit"),
            (plane_source, "int64", "byte-plane-zstd"),
            (ar5_source, "float64", "ar5-decimal-origin"),
        )
        for source, dtype, mode in cases:
            with self.subTest(mode=mode):
                frame = self.roundtrip(
                    source,
                    dtype=dtype,
                    endianness="little",
                    shape=(len(source) // numeric.DTYPES[dtype].width,),
                    layout="one_dimensional_ordered_series",
                )
                self.assertEqual(numeric.inspect(frame)["mode_counts"][mode], 1)

    def test_ar5_selected_frame_decodes_exact_raw_word_exceptions(self) -> None:
        source = bytearray(
            encode_values(
                [round(math.sin(index / 10), 3) for index in range(1024)],
                "d",
                "little",
            )
        )
        exception_words = {
            7: 0x7FF0000000000000,
            101: 0x7FF8123456789ABC,
            509: 0x7FF0123456789ABC,
            777: 0x8000000000000000,
            900: 1,
        }
        for index, word in exception_words.items():
            source[index * 8 : (index + 1) * 8] = word.to_bytes(8, "little")
        frame = self.roundtrip(
            bytes(source),
            dtype="float64",
            endianness="little",
            shape=(1024,),
            layout="one_dimensional_ordered_series",
        )
        self.assertEqual(
            numeric.inspect(frame)["mode_counts"]["ar5-decimal-origin"], 1
        )
        self.assertEqual(
            hashlib.sha256(frame).hexdigest(),
            "ecfa86e2c3fe38c2e4a33fae5af2dc832a2b14a787902d574d8d40aa9e47511b",
        )

    def test_matrix_layout_and_tail_block_are_exact(self) -> None:
        values = [index * 17 - 9000 for index in range(33 * 67)]
        source = encode_values(values, "i", "big")
        frame = self.roundtrip(
            source,
            dtype="int32",
            endianness="big",
            shape=(33, 67),
            layout="column_major_dense_matrix",
        )
        self.assertEqual(numeric.inspect(frame)["blocks"], 3)

    def test_tiny_deterministic_raw_word_fuzz(self) -> None:
        generator = random.Random(0xA55A)
        for dtype, width in (("float32", 4), ("float64", 8), ("uint64", 8)):
            for endianness in ("little", "big"):
                for case in range(12):
                    count = 1 + generator.randrange(80)
                    source = generator.randbytes(count * width)
                    with self.subTest(dtype=dtype, endianness=endianness, case=case):
                        self.roundtrip(
                            source,
                            dtype=dtype,
                            endianness=endianness,
                            shape=(count,),
                            layout="one_dimensional_ordered_series",
                        )

    def test_every_single_byte_corruption_and_truncation_are_rejected(self) -> None:
        source = encode_values(
            [round(math.sin(index / 7), 3) for index in range(96)], "d", "little"
        )
        frame = numeric.compress(
            source,
            dtype="float64",
            endianness="little",
            shape=(96,),
            layout="one_dimensional_ordered_series",
        )
        for index in range(len(frame)):
            corrupt = bytearray(frame)
            corrupt[index] ^= 1
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    numeric.decompress(bytes(corrupt))
        for length in range(len(frame)):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    numeric.decompress(frame[:length])

    def test_shape_output_and_input_bounds_fail_closed(self) -> None:
        source = encode_values([1, 2, 3, 4], "i", "little")
        with self.assertRaisesRegex(ValueError, "disagree"):
            numeric.compress(
                source,
                dtype="int32",
                endianness="little",
                shape=(5,),
                layout="one_dimensional_ordered_series",
            )
        frame = numeric.compress(
            source,
            dtype="int32",
            endianness="little",
            shape=(4,),
            layout="one_dimensional_ordered_series",
        )
        with self.assertRaisesRegex(ValueError, "caller bound"):
            numeric.decompress(frame, max_output_size=len(source) - 1)
        oversized = b"\0" * (numeric.MAX_INPUT_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "64 MiB"):
            numeric.compress(
                oversized,
                dtype="uint16",
                endianness="little",
                shape=(len(oversized) // 2,),
                layout="one_dimensional_ordered_series",
            )

    def test_frozen_frame_hash_is_stable(self) -> None:
        source = encode_values(
            [round(math.sin(index / 10), 3) for index in range(64)], "d", "little"
        )
        frame = numeric.compress(
            source,
            dtype="float64",
            endianness="little",
            shape=(64,),
            layout="one_dimensional_ordered_series",
        )
        self.assertEqual(
            hashlib.sha256(frame).hexdigest(),
            "a8c2041f74b70b3bb638c04cf063c6c6d33bbd76b854aeae8008b5213390f0a8",
        )


if __name__ == "__main__":
    unittest.main()
