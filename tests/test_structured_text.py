import struct
import unittest

from compresslab.native import (
    native_available,
    structured_text_decode as native_decode,
    structured_text_encode as native_encode,
    zstd_compress,
    zstd_decompress,
)
from compresslab.structured_text import (
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
