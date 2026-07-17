import hashlib
import io
import unittest

from compresslab.dense_matrix_transform import (
    HEADER,
    adaptive_compress,
    adaptive_decompress,
    adaptive_inverse_transform,
    adaptive_transform,
    _parallel_transform_python,
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
    parallel_inverse_transform,
    parallel_transform,
    selector_backend,
    selector_compress,
    selector_decompress,
    selector_stream_compress,
    selector_stream_decompress,
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

    def test_parallel_context_lanes_match_reference_and_roundtrip(self):
        source = b"0,1,16,4\n1,0,2,4\n0,1,15,3\n" * 20
        transformed = parallel_transform(source)
        self.assertEqual(transformed, _parallel_transform_python(source))
        self.assertEqual(
            parallel_inverse_transform(transformed, True, len(source)), source
        )

    def test_dense_selector_is_deterministic_exact_and_self_describing(self):
        state = 1
        binary_rows = []
        varied_rows = []
        for _ in range(1000):
            binary_values = []
            varied_values = []
            for _ in range(64):
                state = (1103515245 * state + 12345) & 0x7FFFFFFF
                binary_values.append(
                    b"1.0000" if state & 1 else b"0.0000"
                )
                varied_values.append(str((state >> 8) & 255).encode())
            binary_rows.append(b" ".join(binary_values))
            varied_rows.append(b",".join(varied_values))
        binary = b"\n".join(binary_rows) + b"\n"
        varied = b"\n".join(varied_rows) + b"\n"
        for source, backend in (
            (binary, "dmp1-planes"),
            (varied, "dma2-parallel"),
        ):
            with self.subTest(backend=backend):
                first = selector_compress(source)
                self.assertEqual(first, selector_compress(source))
                self.assertEqual(selector_backend(first), backend)
                self.assertEqual(selector_decompress(first), source)
                with self.assertRaises(ValueError):
                    selector_decompress(first[:-1])

    def test_dense_selector_uses_equally_framed_direct_fallback(self):
        source = bytes(range(256)) * 100
        frame = selector_compress(source)
        self.assertEqual(selector_backend(frame), "direct-zstd1")
        self.assertEqual(selector_decompress(frame), source)

    def test_dense_stream_is_bounded_deterministic_and_exact(self):
        source = (
            b"0,1,16,4\n1,0,2,4\n0,1,15,3\n" * 100
            + bytes(range(256)) * 20
        )
        first = io.BytesIO()
        metadata = selector_stream_compress(
            io.BytesIO(source), first, segment_size=1024
        )
        second = io.BytesIO()
        selector_stream_compress(io.BytesIO(source), second, segment_size=1024)
        self.assertEqual(first.getvalue(), second.getvalue())
        self.assertGreater(metadata["segments"], 1)
        restored = io.BytesIO()
        decode = selector_stream_decompress(
            io.BytesIO(first.getvalue()),
            restored,
            max_output_size=len(source),
        )
        self.assertEqual(restored.getvalue(), source)
        self.assertEqual(decode["source_bytes"], len(source))

    def test_dense_stream_rejects_corruption_and_output_overflow(self):
        source = b"0 1 0 1\n" * 1000
        encoded = io.BytesIO()
        selector_stream_compress(io.BytesIO(source), encoded, segment_size=512)
        corrupt = bytearray(encoded.getvalue())
        corrupt[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            selector_stream_decompress(io.BytesIO(corrupt), io.BytesIO())
        with self.assertRaisesRegex(ValueError, "output exceeds"):
            selector_stream_decompress(
                io.BytesIO(encoded.getvalue()),
                io.BytesIO(),
                max_output_size=len(source) - 1,
            )


if __name__ == "__main__":
    unittest.main()
