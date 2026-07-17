import struct
import unittest

from compresslab.native import (
    tabular_reassemble as native_tabular_reassemble,
    tabular_transform as native_tabular_transform,
    zstd_compress,
)
from compresslab.tabular_transform import (
    BACKEND_COLUMN,
    HEADER,
    compress,
    compress_auto,
    compress_auto_with_metadata,
    decompress,
    frame_backend,
    frame_delimiter,
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


if __name__ == "__main__":
    unittest.main()
