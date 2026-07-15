import struct
import unittest
from unittest.mock import patch

from compresslab.native import (
    native_available,
    structured_text_decode as native_decode,
    structured_text_encode as native_encode,
    structured_text_zstd_stream_decode,
    zstd_compress,
    zstd_decompress,
)
from compresslab.structured_text import (
    DICTIONARY_SAMPLE_BYTES,
    HEADER,
    MAGIC,
    _ranked_dictionary,
    decode,
    encode_best,
    encode_with_dictionary,
)


class StructuredTextTransformTests(unittest.TestCase):
    def test_dictionary_transform_is_byte_exact_and_escapes_marker(self):
        source = (
            b"repeated_identifier another_identifier repeated_identifier\n"
            b"binary-marker:\xff repeated_identifier\n"
        )
        transformed = encode_with_dictionary(
            source, [b"repeated_identifier", b"another_identifier"]
        )
        self.assertEqual(decode(transformed, len(source)), source)
        self.assertLess(len(transformed), len(source))

    def test_best_candidate_roundtrips_through_zstd(self):
        source = b"".join(
            (
                b"static int repeated_identifier_name = shared_function_name("
                + str(index).encode("ascii")
                + b");\n"
            )
            for index in range(10000)
        )
        candidate = encode_best(source, lambda data: zstd_compress(data, level=3))
        self.assertIsNotNone(candidate)
        payload, detail = candidate
        transformed = zstd_decompress(payload, detail["transformed_size"])
        self.assertEqual(decode(transformed, len(source)), source)
        self.assertGreater(detail["dictionary_tokens"], 0)

    def test_native_transform_matches_python_reference(self):
        if not native_available():
            self.skipTest("native library has not been built")
        source = b"".join(
            b"identifier_alpha identifier_beta identifier_alpha "
            + str(index).encode("ascii")
            + b"\n"
            for index in range(1000)
        ) + b"\xfftail"
        dictionary = _ranked_dictionary(source)[:16]
        expected = encode_with_dictionary(source, dictionary)
        transformed = native_encode(source, len(dictionary))
        self.assertEqual(transformed, expected)
        self.assertEqual(native_decode(transformed, len(source)), source)

    def test_native_candidate_does_not_repeat_python_dictionary_ranking(self):
        if not native_available():
            self.skipTest("native library has not been built")
        source = b"repeated_identifier shared_identifier " * 1000
        with patch(
            "compresslab.structured_text._ranked_dictionary",
            side_effect=AssertionError("unexpected Python ranking pass"),
        ):
            candidate = encode_best(
                source, lambda data: zstd_compress(data, level=3)
            )
        self.assertIsNotNone(candidate)

    def test_sampled_native_dictionary_matches_python_reference(self):
        if not native_available():
            self.skipTest("native library has not been built")
        source = b"".join(
            b"sampled_identifier shared_identifier region_"
            + str(index % 97).encode("ascii")
            + b" value\n"
            for index in range(30000)
        )
        self.assertGreater(len(source), DICTIONARY_SAMPLE_BYTES)
        dictionary = _ranked_dictionary(
            source, DICTIONARY_SAMPLE_BYTES
        )[:128]
        expected = encode_with_dictionary(source, dictionary)
        transformed = native_encode(
            source, len(dictionary), DICTIONARY_SAMPLE_BYTES
        )
        self.assertEqual(transformed, expected)
        self.assertEqual(native_decode(transformed, len(source)), source)

    def test_streaming_zstd_decode_handles_tiny_chunks_and_corruption(self):
        if not native_available():
            self.skipTest("native library has not been built")
        source = (
            b"streaming_identifier shared_identifier value\n" * 10000
        ) + b"\xfftail"
        transformed = native_encode(source, 32)
        payload = zstd_compress(transformed, level=3)
        restored = structured_text_zstd_stream_decode(
            payload, len(transformed), len(source), chunk_size=7
        )
        self.assertEqual(restored, source)

        with self.assertRaises((RuntimeError, ValueError)):
            structured_text_zstd_stream_decode(
                payload[:-1], len(transformed), len(source), chunk_size=7
            )
        with self.assertRaises(ValueError):
            structured_text_zstd_stream_decode(
                payload, len(transformed) + 1, len(source), chunk_size=7
            )
        with self.assertRaises(ValueError):
            structured_text_zstd_stream_decode(
                payload + b"x", len(transformed), len(source), chunk_size=7
            )

    def test_decoder_rejects_truncated_escape_and_duplicate_dictionary(self):
        with self.assertRaises(ValueError):
            decode(HEADER.pack(MAGIC, 0) + b"\xff", 1)

        duplicate = (
            HEADER.pack(MAGIC, 2)
            + struct.pack("B", 3)
            + b"foo"
            + struct.pack("B", 3)
            + b"foo"
        )
        with self.assertRaises(ValueError):
            decode(duplicate, 0)


if __name__ == "__main__":
    unittest.main()
