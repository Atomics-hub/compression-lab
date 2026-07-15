import unittest
import struct
import random
import hashlib

from compresslab.codecs import codec_by_id
from compresslab.worker import (
    ADAPTIVE_HEADER,
    ADAPTIVE_MAGIC,
    ADAPTIVE_VERSION_V2,
    BACKEND_GZIP_1,
    BACKEND_LZ4_1,
    _adaptive_compress,
    _adaptive_decompress,
    _adaptive_v2_compress,
    _codec_filter,
    _delta_transpose,
    _inverse_delta_transpose,
    _python_delta_transpose,
    _python_inverse_delta_transpose,
)
from compresslab.native import (
    native_available,
    zstd_available,
    zstd_compress,
    zstd_decompress,
)


class AdaptiveFrameTests(unittest.TestCase):
    def require_v2(self):
        if not codec_by_id("adaptive-v2").available:
            self.skipTest("adaptive-v2 native dependencies are unavailable")

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

    def test_libzstd_roundtrip(self):
        if not zstd_available():
            self.skipTest("libzstd is unavailable")
        source = (b"direct-zstd-ffi\n" * 10000) + bytes(range(256))
        encoded = zstd_compress(source, level=3)
        self.assertEqual(zstd_decompress(encoded, len(source)), source)

    def test_v1_selects_numeric_transform_when_it_wins(self):
        source = b"".join(struct.pack("<I", index) for index in range(100000))
        encoded, detail = _adaptive_compress(source, allow_transform=True)
        restored, decoded = _adaptive_decompress(encoded)
        self.assertEqual(restored, source)
        self.assertEqual(detail["selected_backend"], "delta-transpose+gzip-1")
        self.assertEqual(decoded["selected_backend"], detail["selected_backend"])
        self.assertLessEqual(detail["selector_sample_bytes"], 48 * 1024)

    def test_v2_routes_native_backends_and_preserves_v1_compatibility(self):
        self.require_v2()
        cases = [
            (b"small-structured-row\n" * 8000, "zstd-3"),
            (b"large-structured-row\n" * 40000, "zstd-3"),
            (
                b"".join(struct.pack("<I", index) for index in range(100000)),
                "delta-transpose+zstd-3",
            ),
        ]
        for source, expected_backend in cases:
            encoded, detail = _adaptive_v2_compress(source)
            restored, decoded = _adaptive_decompress(encoded)
            self.assertEqual(encoded[4], 2)
            self.assertEqual(restored, source)
            self.assertEqual(detail["selected_backend"], expected_backend)
            self.assertEqual(decoded["selected_backend"], expected_backend)
            self.assertLessEqual(detail["selector_sample_bytes"], 48 * 1024)
            if "zstd" in expected_backend:
                self.assertEqual(detail["codec_engine"], "libzstd-ffi")

        v1_encoded, _ = _adaptive_compress(cases[0][0], allow_transform=True)
        self.assertEqual(v1_encoded[4], 1)
        self.assertEqual(_adaptive_decompress(v1_encoded)[0], cases[0][0])

        lz4_source = cases[1][0]
        lz4_frame = ADAPTIVE_HEADER.pack(
            ADAPTIVE_MAGIC,
            ADAPTIVE_VERSION_V2,
            BACKEND_LZ4_1,
            len(lz4_source),
            hashlib.sha256(lz4_source).digest(),
        ) + _codec_filter("lz4-1", "compress", lz4_source)
        self.assertEqual(_adaptive_decompress(lz4_frame)[0], lz4_source)

    def test_v2_stores_incompressible_data_and_rejects_version_backend_mismatch(self):
        self.require_v2()
        rng = random.Random(17)
        source = bytes(rng.randrange(256) for _ in range(200000))
        encoded, detail = _adaptive_v2_compress(source)
        self.assertEqual(detail["selected_backend"], "store")
        self.assertEqual(_adaptive_decompress(encoded)[0], source)

        invalid = bytearray(encoded)
        invalid[5] = BACKEND_GZIP_1
        self.assertEqual(len(invalid[:ADAPTIVE_HEADER.size]), ADAPTIVE_HEADER.size)
        with self.assertRaises(ValueError):
            _adaptive_decompress(bytes(invalid))


if __name__ == "__main__":
    unittest.main()
