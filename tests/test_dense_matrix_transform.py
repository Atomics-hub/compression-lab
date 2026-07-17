import hashlib
import unittest

from compresslab.dense_matrix_transform import (
    HEADER,
    adaptive_compress,
    adaptive_decompress,
    adaptive_inverse_transform,
    adaptive_transform,
    compress,
    context_compress,
    context_decompress,
    context_inverse_transform,
    context_transform,
    decompress,
    inverse_transform,
    matrix_compress,
    matrix_decompress,
    matrix_inverse_transform,
    matrix_transform,
    plane_compress,
    plane_decompress,
    plane_inverse_transform,
    plane_transform,
    transform,
)


class DenseMatrixTransformTests(unittest.TestCase):
    def test_exact_transform_roundtrips_separator_spelling(self):
        fixtures = (
            b"",
            b"0,1,16\n1,0,2\n",
            b"  0  3  4  \r\n 10  0  6",
            b"0.0000 1.0000 0.0000 \n",
            bytes(range(256)),
        )
        for source in fixtures:
            with self.subTest(digest=hashlib.sha256(source).hexdigest()):
                transformed = transform(source)
                starts_with_token = not source or source[0] not in b" \t,;|\r\n"
                self.assertEqual(
                    inverse_transform(transformed, starts_with_token, len(source)),
                    source,
                )

    def test_complete_frame_is_deterministic_and_exact(self):
        source = (b"  0  1  6  6  0\n" * 10_000) + b"0,1,16\n"
        first = compress(source, level=9)
        second = compress(source, level=9)
        self.assertEqual(first, second)
        self.assertEqual(decompress(first), source)

    def test_corruption_and_truncation_are_rejected(self):
        source = b"0 1 0 1\n" * 100
        frame = compress(source)
        with self.assertRaises(ValueError):
            decompress(frame[:-1])
        corrupt = bytearray(frame)
        corrupt[HEADER.size - 1] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            decompress(bytes(corrupt))

    def test_declared_output_bound_is_enforced(self):
        transformed = transform(b"1 0\n")
        with self.assertRaisesRegex(ValueError, "output size"):
            inverse_transform(transformed, True, -1)

    def test_numeric_matrix_planes_roundtrip_exactly(self):
        fixtures = (
            b"0,1,16\n1,0,2\n",
            b"  0  3  4  \r\n 10  0  6  \r\n",
            b"0.0000 1.0000 0.0000 \n1.0000 0.0000 1.0000 \n",
        )
        for source in fixtures:
            with self.subTest(source=source):
                transformed = matrix_transform(source)
                starts_with_token = source[0] not in b" \t,;|\r\n"
                self.assertEqual(
                    matrix_inverse_transform(
                        transformed, starts_with_token, len(source)
                    ),
                    source,
                )
                frame = matrix_compress(source, level=9)
                self.assertEqual(matrix_decompress(frame), source)

    def test_numeric_matrix_rejects_ragged_and_nonnumeric_rows(self):
        with self.assertRaisesRegex(ValueError, "rectangular"):
            matrix_transform(b"1,2\n3\n")
        with self.assertRaisesRegex(ValueError, "nonnumeric"):
            matrix_transform(b"1,header\n2,3\n")

    def test_row_major_numeric_bit_planes_roundtrip_exactly(self):
        source = b"  0  3  4  \n 10  0  6  \n"
        transformed = plane_transform(source)
        self.assertEqual(
            plane_inverse_transform(transformed, False, len(source)),
            source,
        )
        frame = plane_compress(source, level=9)
        self.assertEqual(plane_decompress(frame), source)

    def test_static_context_arithmetic_roundtrips_exactly(self):
        source = b"0,1,16,4\n1,0,2,4\n0,1,15,3\n"
        transformed = context_transform(source)
        self.assertEqual(
            context_inverse_transform(transformed, True, len(source)),
            source,
        )
        frame = context_compress(source, level=9)
        self.assertEqual(context_decompress(frame), source)

    def test_adaptive_context_arithmetic_roundtrips_exactly(self):
        source = b"0,1,16,4\n1,0,2,4\n0,1,15,3\n"
        transformed = adaptive_transform(source)
        self.assertEqual(
            adaptive_inverse_transform(transformed, True, len(source)),
            source,
        )
        frame = adaptive_compress(source)
        self.assertEqual(adaptive_decompress(frame), source)


if __name__ == "__main__":
    unittest.main()
