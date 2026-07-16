import unittest
import struct
import random
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from compresslab.codecs import codec_by_id
from compresslab.adaptive_v3 import (
    FRAME_HEADER as V3_FRAME_HEADER,
    SEGMENT_COUNT as V3_SEGMENT_COUNT,
    SEGMENT_HEADER as V3_SEGMENT_HEADER,
)
from compresslab.worker import (
    ADAPTIVE_HEADER,
    ADAPTIVE_MAGIC,
    ADAPTIVE_VERSION_V2,
    ADAPTIVE_VERSION_V3,
    BACKEND_GZIP_1,
    BACKEND_LZ4_1,
    _adaptive_compress,
    _adaptive_decompress,
    _adaptive_v2_compress,
    _adaptive_v3_compress,
    _codec_filter,
    _delta_transpose,
    _inverse_delta_transpose,
    _python_delta_transpose,
    _python_inverse_delta_transpose,
    run as run_codec,
)
from compresslab.native import (
    native_available,
    zstd_available,
    zstd_compress,
    zstd_decompress,
    zstd_engine,
    zstd_frame_content_size,
)


class AdaptiveFrameTests(unittest.TestCase):
    def require_v2(self):
        if not codec_by_id("adaptive-v2").available:
            self.skipTest("adaptive-v2 native dependencies are unavailable")

    def require_v3(self):
        if not codec_by_id("adaptive-v3").available:
            self.skipTest("adaptive-v3 native dependencies are unavailable")

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
        self.assertEqual(zstd_frame_content_size(encoded), len(source))
        self.assertEqual(zstd_decompress(encoded, len(source)), source)
        self.assertEqual(zstd_decompress(encoded), source)

    def test_python_zstandard_fallback_normalizes_corruption_errors(self):
        source = (b"portable-zstandard\n" * 1000) + bytes(range(256))
        with patch("compresslab.native._load_zstd", return_value=None):
            encoded = zstd_compress(source, level=3)
            self.assertEqual(zstd_engine(), "python-zstandard")
            self.assertEqual(zstd_decompress(encoded, len(source)), source)
            with self.assertRaisesRegex(ValueError, "invalid Zstandard payload"):
                zstd_decompress(encoded + b"\0", len(source))
            corrupted = bytearray(encoded)
            corrupted[-1] ^= 0x01
            with self.assertRaisesRegex(ValueError, "invalid Zstandard payload"):
                zstd_decompress(bytes(corrupted), len(source))

    def test_zstd_baseline_uses_in_process_library(self):
        if not zstd_available() or not codec_by_id("zstd-3").available:
            self.skipTest("zstd baseline dependencies are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            encoded = root / "encoded"
            restored = root / "restored"
            source.write_bytes((b"native-baseline\n" * 10000) + bytes(range(256)))
            compressed = run_codec("zstd-3", "compress", source, encoded)
            decompressed = run_codec("zstd-3", "decompress", encoded, restored)
            self.assertEqual(compressed["codec_engine"], zstd_engine())
            self.assertEqual(decompressed["codec_engine"], zstd_engine())
            self.assertEqual(restored.read_bytes(), source.read_bytes())

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
                self.assertEqual(detail["codec_engine"], zstd_engine())

        v1_encoded, _ = _adaptive_compress(cases[0][0], allow_transform=True)
        self.assertEqual(v1_encoded[4], 1)
        self.assertEqual(_adaptive_decompress(v1_encoded)[0], cases[0][0])

        if codec_by_id("lz4-1").available:
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

    def test_v3_segments_heterogeneous_data_and_roundtrips(self):
        self.require_v3()
        rng = random.Random(23)
        random_block = rng.randbytes(1024 * 1024)
        numeric_block = b"".join(
            struct.pack("<I", index) for index in range((1024 * 1024) // 4)
        )
        text_row = b"region,type,value\nalpha,compressible,00000001\n"
        text_block = (text_row * (1024 * 1024 // len(text_row) + 1))[:1024 * 1024]
        source = random_block + numeric_block + text_block

        encoded, detail = _adaptive_v3_compress(source)
        restored, decoded = _adaptive_decompress(encoded)

        self.assertEqual(encoded[4], ADAPTIVE_VERSION_V3)
        self.assertEqual(restored, source)
        self.assertEqual(detail["candidate_segment_count"], 3)
        self.assertEqual(detail["segment_count"], 3)
        self.assertGreaterEqual(detail["transformed_segments"], 1)
        self.assertGreaterEqual(detail["stored_segments"], 1)
        self.assertEqual(decoded["selected_backend"], detail["selected_backend"])
        self.assertEqual(decoded["segment_count"], detail["segment_count"])

        corrupted = bytearray(encoded)
        first_payload = (
            V3_FRAME_HEADER.size + V3_SEGMENT_COUNT.size + V3_SEGMENT_HEADER.size
        )
        corrupted[first_payload] ^= 0x01
        with self.assertRaises(ValueError):
            _adaptive_decompress(bytes(corrupted))

    def test_v3_falls_back_to_whole_stream_for_homogeneous_data(self):
        self.require_v3()
        row = b"homogeneous source row with stable repetition\n"
        source = (row * (3 * 1024 * 1024 // len(row) + 1))[:3 * 1024 * 1024]
        encoded, detail = _adaptive_v3_compress(source)
        restored, decoded = _adaptive_decompress(encoded)

        self.assertEqual(restored, source)
        self.assertTrue(detail["selector_reason"].startswith("whole-"))
        self.assertEqual(detail["candidate_segment_count"], 1)
        self.assertEqual(detail["segment_count"], 1)
        self.assertEqual(decoded["segment_count"], 1)
        self.assertLessEqual(len(encoded), len(source) + 64)

    def test_v3_stores_incompressible_data_with_bounded_frame_overhead(self):
        self.require_v3()
        source = random.Random(29).randbytes(256 * 1024)
        encoded, detail = _adaptive_v3_compress(source)

        self.assertEqual(detail["selected_backend"], "v3[store=1]")
        self.assertEqual(detail["stored_segments"], 1)
        self.assertLessEqual(len(encoded), len(source) + 64)
        self.assertEqual(_adaptive_decompress(encoded)[0], source)

    def test_v3_selects_structured_text_recipe_when_complete_frame_wins(self):
        self.require_v3()
        source = b"".join(
            (
                b"static int repeated_identifier_name = shared_function_name("
                + str(index).encode("ascii")
                + b");\n"
            )
            for index in range(20000)
        )
        encoded, detail = _adaptive_v3_compress(source)
        restored, decoded = _adaptive_decompress(encoded)

        self.assertEqual(restored, source)
        self.assertEqual(detail["selector_reason"], "whole-structured-text-smaller")
        self.assertEqual(detail["structured_text_segments"], 1)
        self.assertEqual(detail["transformed_segments"], 1)
        self.assertGreater(detail["structured_dictionary_tokens"], 0)
        self.assertEqual(decoded["selected_backend"], detail["selected_backend"])
        self.assertEqual(decoded["structured_text_segments"], 1)

        corrupted = bytearray(encoded)
        first_payload = (
            V3_FRAME_HEADER.size + V3_SEGMENT_COUNT.size + V3_SEGMENT_HEADER.size
        )
        corrupted[first_payload] = 0xFF
        with self.assertRaises(ValueError):
            _adaptive_decompress(bytes(corrupted))

    def test_v3_selects_channelized_structured_text_for_json(self):
        self.require_v3()
        rows = (
            (
                '  {\n    "TrackId": %d,\n'
                '    "Name": "Track number %d unique title %08x",\n'
                '    "Composer": "Composer %d",\n'
                '    "Milliseconds": %d,\n    "Bytes": %d,\n'
                '    "UnitPrice": %.2f\n  }'
                % (index, index, index * 2654435761 & 0xFFFFFFFF,
                   index % 997, 180000 + index * 17,
                   1000000 + index * 7919, 0.49 + (index % 10) * 0.1)
            ).encode("ascii")
            for index in range(5000)
        )
        source = b"[\n" + b",\n".join(rows) + b"\n]"
        encoded, detail = _adaptive_v3_compress(source)
        restored, decoded = _adaptive_decompress(encoded)

        self.assertEqual(restored, source)
        self.assertEqual(detail["selector_reason"], "whole-structured-text-smaller")
        self.assertEqual(detail["structured_channel_segments"], 1)
        self.assertEqual(decoded["structured_channel_segments"], 1)

        corrupted = bytearray(encoded)
        first_payload = (
            V3_FRAME_HEADER.size + V3_SEGMENT_COUNT.size + V3_SEGMENT_HEADER.size
        )
        corrupted[first_payload] = 0xFF
        with self.assertRaises(ValueError):
            _adaptive_decompress(bytes(corrupted))


if __name__ == "__main__":
    unittest.main()
