import unittest
import struct

from compresslab.worker import (
    _adaptive_compress,
    _adaptive_decompress,
    _delta_transpose,
    _inverse_delta_transpose,
    _python_delta_transpose,
    _python_inverse_delta_transpose,
)
from compresslab.native import native_available


class AdaptiveFrameTests(unittest.TestCase):
    def test_roundtrip_and_corruption_detection(self):
        source = (b"structured-data-" * 10000) + bytes(range(256))
        encoded, detail = _adaptive_compress(source)
        restored, decoded = _adaptive_decompress(encoded)
        self.assertEqual(restored, source)
        self.assertEqual(detail["selected_backend"], decoded["selected_backend"])

        corrupted = bytearray(encoded)
        corrupted[-1] ^= 0x01
        with self.assertRaises((ValueError, OSError, EOFError)):
            _adaptive_decompress(bytes(corrupted))

    def test_delta_transpose_is_reversible_with_tail(self):
        source = b"".join(struct.pack("<I", index * 3) for index in range(4096)) + b"xyz"
        transformed = _delta_transpose(source)
        self.assertEqual(len(transformed), len(source))
        self.assertEqual(_inverse_delta_transpose(transformed, len(source)), source)

    def test_native_transform_matches_reference(self):
        if not native_available():
            self.skipTest("native library has not been built")
        source = b"".join(struct.pack("<I", index * 17) for index in range(8193)) + b"xy"
        transformed = _delta_transpose(source)
        self.assertEqual(transformed, _python_delta_transpose(source))
        self.assertEqual(
            _python_inverse_delta_transpose(transformed, len(source)),
            _inverse_delta_transpose(transformed, len(source)),
        )

    def test_v1_selects_numeric_transform_when_it_wins(self):
        source = b"".join(struct.pack("<I", index) for index in range(100000))
        encoded, detail = _adaptive_compress(source, allow_transform=True)
        restored, decoded = _adaptive_decompress(encoded)
        self.assertEqual(restored, source)
        self.assertEqual(detail["selected_backend"], "delta-transpose+gzip-1")
        self.assertEqual(decoded["selected_backend"], detail["selected_backend"])
        self.assertLessEqual(detail["selector_sample_bytes"], 48 * 1024)


if __name__ == "__main__":
    unittest.main()
