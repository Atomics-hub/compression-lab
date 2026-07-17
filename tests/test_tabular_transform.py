import hashlib
import struct
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import compresslab.native as native_module

from compresslab.native import (
    tabular_reassemble as native_tabular_reassemble,
    tabular_transform as native_tabular_transform,
    zstd_compress,
)
from compresslab.tabular_transform import (
    BACKEND_COLUMN,
    HEADER,
    STREAM_HEADER,
    STREAM_SEGMENT_HEADER,
    compress,
    compress_auto,
    compress_auto_with_metadata,
    compress_dense_auto_with_metadata,
    compress_stream,
    decompress,
    decompress_stream,
    frame_backend,
    frame_delimiter,
    inspect_stream,
    inverse_transform,
    reference_inverse_transform,
    reference_transform,
    transform,
)


class TabularTransformTests(unittest.TestCase):
    def test_auto_delimiter_is_deterministic_and_roundtrips(self):
        semicolon = b"time;value;state\n" + b"1;2;ok\n" * 100
        frame = compress_auto(semicolon, level=3)
        self.assertEqual(frame_delimiter(frame), ord(";"))
        self.assertEqual(decompress(frame), semicolon)
        no_delimiter = compress_auto(b"plain text", level=3)
        self.assertEqual(frame_delimiter(no_delimiter), ord(","))
        self.assertEqual(decompress(no_delimiter), b"plain text")

    def test_bounded_selector_uses_one_full_backend(self):
        source = b"kind,value,state\n" + b"alpha,100,ready\n" * 10000
        frame, metadata = compress_auto_with_metadata(source, level=3)
        self.assertEqual(decompress(frame), source)
        self.assertEqual(metadata["selector_sample_bytes"], len(source))
        self.assertIn(
            metadata["selector_reason"],
            {"sample-column-clear-win", "sample-direct-or-ambiguous"},
        )
        self.assertGreater(metadata["selector_ns"], 0)

    def test_dense_selector_is_deterministic_and_records_parameters(self):
        source = b"a,b,c\n" + b"1,2,3\n" * 20000
        first, metadata = compress_dense_auto_with_metadata(source)
        second, repeated = compress_dense_auto_with_metadata(source)
        self.assertEqual(first, second)
        self.assertEqual(metadata["compression_level"], repeated["compression_level"])
        self.assertEqual(
            metadata["compression_threads"], repeated["compression_threads"]
        )
        self.assertIn(metadata["compression_level"], {9, 16})
        self.assertIn(metadata["compression_threads"], {1, 2})
        self.assertEqual(decompress(first), source)

    def test_dense_selector_enforces_equally_framed_direct_fallback(self):
        source = b"a,b,c\n" * 125
        with (
            patch(
                "compresslab.tabular_transform._sample_backend",
                return_value=(BACKEND_COLUMN, b"d" * 200, b"c" * 100),
            ),
            patch(
                "compresslab.tabular_transform.transform",
                side_effect=lambda data, _delimiter: data + b"expanded" * 100,
            ),
            patch(
                "compresslab.tabular_transform.zstd_compress",
                side_effect=lambda data, level: (
                    b"C" * 1500 if b"expanded" in data else b"D" * 500
                ),
            ),
        ):
            frame, metadata = compress_dense_auto_with_metadata(
                source,
                enforce_direct_fallback=True,
            )
        self.assertEqual(frame_backend(frame), "direct-zstd")
        self.assertTrue(metadata["direct_fallback_compared"])
        self.assertTrue(metadata["direct_fallback_selected"])
        self.assertEqual(metadata["selector_reason"], "full-direct-fallback")

    def test_concurrent_segments_load_python_zstandard_once(self):
        original_import = __import__

        def delayed_import(name, *args, **kwargs):
            if name == "zstandard":
                time.sleep(0.02)
            return original_import(name, *args, **kwargs)

        with (
            patch.object(native_module, "_PYTHON_ZSTD", None),
            patch.object(native_module, "_PYTHON_ZSTD_LOAD_ATTEMPTED", False),
            patch("builtins.__import__", side_effect=delayed_import),
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            modules = list(
                executor.map(
                    lambda _index: native_module._load_python_zstd(),
                    range(8),
                )
            )
        self.assertTrue(all(module is not None for module in modules))
        self.assertEqual(len({id(module) for module in modules}), 1)

    def test_dense_stream_selector_stores_incompressible_segment(self):
        source = hashlib.shake_256(b"tbl1-store-fixture").digest(100_000)
        frame, metadata = compress_dense_auto_with_metadata(
            source,
            enforce_direct_fallback=True,
        )
        self.assertEqual(frame_backend(frame), "store")
        self.assertEqual(len(frame), HEADER.size + len(source))
        self.assertEqual(metadata["compression_level"], 0)
        self.assertEqual(decompress(frame), source)

    def test_native_transform_is_byte_identical_to_reference(self):
        fixtures = [
            (b"", ord(",")),
            (b"a,b\n1,2\n", ord(",")),
            (b"a;b;c\n1;2\n;;\n", ord(";")),
            (b'"a,b",c\n"line",2\n', ord(",")),
            (b"\x00,\xff\nraw,binary", ord(",")),
        ]
        for source, delimiter in fixtures:
            with self.subTest(source=source):
                reference = reference_transform(source, delimiter)
                native = native_tabular_transform(source, delimiter)
                self.assertEqual(native, reference)
                self.assertEqual(
                    native_tabular_reassemble(native, delimiter, len(source)),
                    source,
                )
                self.assertEqual(
                    reference_inverse_transform(reference, delimiter, len(source)),
                    source,
                )

    def test_native_transform_retries_when_compact_capacity_is_too_small(self):
        source = b"," * (2 * 1024 * 1024)
        transformed = native_tabular_transform(source, ord(","))
        self.assertGreater(len(transformed), len(source) + len(source) // 32)
        self.assertEqual(
            native_tabular_reassemble(transformed, ord(","), len(source)),
            source,
        )

    def test_transform_roundtrips_exact_table_bytes(self):
        fixtures = [
            b"",
            b"a,b\n1,2\n",
            b"a,b\r\n1,,3",
            b'"a,b",c\n"line",2\n',
            b"a;b;c\n1;2\n;;\n",
            b"\x00,\xff\nraw,binary",
        ]
        for source in fixtures:
            with self.subTest(source=source):
                encoded = transform(source, ord(","))
                self.assertEqual(
                    inverse_transform(encoded, ord(","), len(source)),
                    source,
                )

    def test_complete_frame_is_deterministic_and_exact(self):
        source = b"time;value;state\n" + b"".join(
            f"2026-01-01T00:{index % 60:02d};{index}.500;{index % 3}\n".encode()
            for index in range(5000)
        )
        first = compress(source, ord(";"), level=9)
        second = compress(source, ord(";"), level=9)
        self.assertEqual(first, second)
        self.assertEqual(decompress(first), source)
        self.assertEqual(frame_backend(first), "column-transpose+zstd")

    def test_complete_frame_falls_back_without_material_expansion(self):
        source = bytes(range(256)) * 100
        frame = compress(source, ord(","), level=9)
        self.assertEqual(decompress(frame), source)
        self.assertEqual(frame_backend(frame), "direct-zstd")
        self.assertLessEqual(len(frame), HEADER.size + len(zstd_compress(source, 9)))

    def test_corruption_truncation_and_bounds_are_rejected(self):
        source = b"a,b\n1,2\n" * 100
        frame = compress(source, ord(","))
        for cut in (0, 1, HEADER.size - 1, len(frame) - 1):
            with self.subTest(cut=cut):
                with self.assertRaises((RuntimeError, ValueError)):
                    decompress(frame[:cut])
        with self.assertRaisesRegex(ValueError, "configured limit"):
            decompress(frame, max_output_size=len(source) - 1)

        corrupted = bytearray(frame)
        corrupted[-1] ^= 1
        with self.assertRaises((RuntimeError, ValueError)):
            decompress(bytes(corrupted))

    def test_inverse_rejects_invalid_metadata_and_unused_columns(self):
        with self.assertRaises(ValueError):
            inverse_transform(b"\x01\x01\x01\x00\x00", ord(","), 0)
        with self.assertRaises(ValueError):
            inverse_transform(b"\xe8\x07\x00\x00", ord(","), 1024)
        valid = bytearray(transform(b"a,b\n", ord(",")))
        valid.append(0)
        with self.assertRaisesRegex(ValueError, "trailing"):
            inverse_transform(bytes(valid), ord(","), 4)

    def test_header_tampering_is_rejected(self):
        source = b"a,b\n"
        frame = bytearray(compress(source, ord(",")))
        struct.pack_into(">Q", frame, 7, len(source) + 1)
        with self.assertRaises((RuntimeError, ValueError)):
            decompress(bytes(frame), max_output_size=1024)

        frame = bytearray(compress(source * 100, ord(",")))
        frame[6] = BACKEND_COLUMN + 99
        with self.assertRaisesRegex(ValueError, "backend"):
            decompress(bytes(frame))

    def test_segmented_stream_is_deterministic_bounded_and_exact(self):
        source_bytes = (
            b"name,value,state\r\n"
            + b"alpha,100,ready\r\n" * 80
            + b"oversized," + b"x" * 300 + b",tail\n"
            + b"unterminated,last,row"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            first = root / "first.tbs1"
            second = root / "second.tbs1"
            restored = root / "restored.csv"
            source.write_bytes(source_bytes)

            metadata = compress_stream(
                source,
                first,
                segment_size=128,
                record_slack=32,
            )
            compress_stream(
                source,
                second,
                segment_size=128,
                record_slack=32,
            )
            info = inspect_stream(first)
            decode_metadata = decompress_stream(first, restored)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(restored.read_bytes(), source_bytes)
            self.assertGreater(info["segment_count"], 2)
            self.assertEqual(info["segment_size"], 128)
            self.assertEqual(info["record_slack"], 32)
            self.assertEqual(metadata["segment_count"], info["segment_count"])
            self.assertEqual(
                decode_metadata["transformed_segments"]
                + decode_metadata["direct_segments"]
                + decode_metadata["stored_segments"],
                info["segment_count"],
            )
            self.assertEqual(
                metadata["direct_fallback_compared_segments"],
                metadata["transformed_segments"],
            )
            self.assertLessEqual(metadata["selector_sample_bytes"], 160)

    def test_segmented_stream_handles_empty_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "empty.csv"
            encoded = root / "empty.tbs1"
            restored = root / "restored.csv"
            source.write_bytes(b"")
            metadata = compress_stream(source, encoded, segment_size=64)
            info = inspect_stream(encoded)
            decompress_stream(encoded, restored)
            self.assertEqual(metadata["segment_count"], 0)
            self.assertEqual(info["segment_count"], 0)
            self.assertEqual(restored.read_bytes(), b"")

    def test_segmented_stream_rejects_corruption_without_clobbering_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            encoded = root / "source.tbs1"
            corrupted = root / "corrupted.tbs1"
            destination = root / "existing.csv"
            source.write_bytes(b"a,b,c\n1,2,3\n" * 100)
            compress_stream(source, encoded, segment_size=256, record_slack=32)
            damaged = bytearray(encoded.read_bytes())
            damaged[-1] ^= 1
            corrupted.write_bytes(damaged)
            destination.write_bytes(b"keep me")

            with self.assertRaises((RuntimeError, ValueError)):
                decompress_stream(corrupted, destination)
            self.assertEqual(destination.read_bytes(), b"keep me")

            with self.assertRaisesRegex(ValueError, "configured limit"):
                decompress_stream(
                    encoded,
                    destination,
                    max_output_size=source.stat().st_size - 1,
                )
            self.assertEqual(destination.read_bytes(), b"keep me")

            truncated = root / "truncated.tbs1"
            truncated.write_bytes(encoded.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                decompress_stream(truncated, destination)

    def test_segmented_stream_rejects_header_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            encoded = root / "source.tbs1"
            source.write_bytes(b"a,b\n1,2\n")
            compress_stream(source, encoded, segment_size=64)
            frame = bytearray(encoded.read_bytes())
            struct.pack_into(">Q", frame, 8, 0)
            encoded.write_bytes(frame)
            with self.assertRaisesRegex(ValueError, "segment size"):
                inspect_stream(encoded)

            self.assertGreater(STREAM_HEADER.size, HEADER.size)

            compress_stream(source, encoded, segment_size=4, record_slack=0)
            frame = bytearray(encoded.read_bytes())
            struct.pack_into(
                ">Q",
                frame,
                STREAM_HEADER.size + 8,
                1024 * 1024,
            )
            encoded.write_bytes(frame)
            with self.assertRaisesRegex(ValueError, "frame size"):
                decompress_stream(encoded, root / "oversized.csv")

            compress_stream(source, encoded, segment_size=4, record_slack=0)
            frame = bytearray(encoded.read_bytes())
            struct.pack_into(">Q", frame, STREAM_HEADER.size, 1)
            encoded.write_bytes(frame)
            with self.assertRaisesRegex(ValueError, "undersized interior"):
                decompress_stream(encoded, root / "undersized.csv")

            self.assertEqual(STREAM_SEGMENT_HEADER.size, 16)


if __name__ == "__main__":
    unittest.main()
