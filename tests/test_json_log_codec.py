from __future__ import annotations

import hashlib
import random
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from compresslab.experimental import (
    compress_json_log_file,
    compress_json_logs,
    decompress_json_log_file,
    decompress_json_logs,
    inspect_json_log_frame,
)
from compresslab.json_log_codec import (
    FRAME_HEADER,
    compress,
    compress_file,
    compress_frame,
    decompress,
    decompress_file,
    decompress_frame,
    inspect,
)


class JsonLogCodecTests(unittest.TestCase):
    def test_exact_fallback_roundtrips_and_never_expands(self) -> None:
        rng = random.Random(20260716)
        fixtures = {
            "empty": b"",
            "random": rng.randbytes(256 * 1024),
            "text": b"not-json\n" * 20_000,
            "json": b"".join(
                f'{{"id":{index},"event":"tick","value":"v-{index % 7}"}}\n'.encode()
                for index in range(10_000)
            ),
        }
        for name, source in fixtures.items():
            with self.subTest(name=name):
                encoded, detail = compress_frame(source)
                self.assertLessEqual(
                    detail["selected_bytes"],
                    detail["direct_frame_bytes"],
                )
                self.assertEqual(decompress_frame(encoded), source)

    def test_segmented_roundtrip_preserves_boundaries_and_long_records(self) -> None:
        source = (
            b'{"a":1}\r\n'
            + b'{"long":"' + b"x" * 4096 + b'"}\n'
            + b'{"tail":true}'
        )
        encoded, detail = compress(source, segment_size=64)
        self.assertGreater(detail["segment_count"], 1)
        self.assertTrue(detail["no_expansion_vs_direct_frame"])
        self.assertEqual(decompress(encoded), source)
        self.assertEqual(compress(source, segment_size=64)[0], encoded)

    def test_corruption_truncation_and_bounds_are_rejected(self) -> None:
        source = b'{"id":1,"event":"tick"}\n' * 1000
        frame, _ = compress_frame(source)
        stream, _ = compress(source, segment_size=1024)
        for candidate, decoder in (
            (frame[:-1], decompress_frame),
            (frame + b"\0", decompress_frame),
            (stream[:-1], decompress),
            (stream + b"\0", decompress),
        ):
            with self.subTest(size=len(candidate)):
                with self.assertRaises(ValueError):
                    decoder(candidate)
        invalid_mode = bytearray(frame)
        invalid_mode[5] = 255
        with self.assertRaises(ValueError):
            decompress_frame(bytes(invalid_mode))
        corrupted_hash = bytearray(frame)
        corrupted_hash[FRAME_HEADER.size - 1] ^= 1
        with self.assertRaises(ValueError):
            decompress_frame(bytes(corrupted_hash))
        with self.assertRaises(ValueError):
            decompress(stream, max_output_size=len(source) - 1)

    def test_file_api_matches_bytes_api_and_streams_segments(self) -> None:
        source = (
            b'{"a":1}\n'
            + b'{"long":"' + b"x" * 4096 + b'"}\n'
            + b'{"tail":true}'
        )
        expected, _ = compress(source, segment_size=64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.jsonl"
            encoded_path = root / "source.jls"
            restored_path = root / "restored.jsonl"
            source_path.write_bytes(source)
            compression = compress_file(
                source_path,
                encoded_path,
                segment_size=64,
            )
            self.assertEqual(encoded_path.read_bytes(), expected)
            self.assertGreater(compression["segment_count"], 1)
            decompression = decompress_file(
                encoded_path,
                restored_path,
            )
            self.assertEqual(restored_path.read_bytes(), source)
            self.assertEqual(decompression["restored_bytes"], len(source))

    def test_single_segment_file_decode_avoids_executor_overhead(self) -> None:
        source = b'{"id":1,"event":"tick"}\n' * 100
        encoded, detail = compress(source, segment_size=len(source) + 1)
        self.assertEqual(detail["segment_count"], 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encoded_path = root / "source.jls2"
            restored_path = root / "restored.jsonl"
            encoded_path.write_bytes(encoded)
            with mock.patch(
                "compresslab.json_log_codec.ThreadPoolExecutor",
                side_effect=AssertionError("single-segment decode used executor"),
            ):
                decompress_file(encoded_path, restored_path)
            self.assertEqual(restored_path.read_bytes(), source)

    def test_inspection_reports_validated_segment_metadata(self) -> None:
        source = (
            b'{"id":1,"event":"tick"}\n'
            b'{"id":2,"event":"tick"}\n'
            b'{"id":3,"event":"tock"}\n'
        )
        encoded, detail = compress(source, segment_size=32)
        info = inspect(encoded)
        self.assertEqual(info.format, "JLS2")
        self.assertEqual(info.version, 1)
        self.assertEqual(info.original_size, len(source))
        self.assertEqual(info.encoded_size, len(encoded))
        self.assertEqual(info.segment_count, detail["segment_count"])
        self.assertEqual(
            info.direct_segments + info.columnar_segments,
            info.segment_count,
        )
        self.assertLessEqual(info.maximum_segment_size, len(source))
        self.assertEqual(info.sha256, hashlib.sha256(source).hexdigest())

        corrupted = bytearray(encoded)
        corrupted[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "encoded SHA-256"):
            inspect(bytes(corrupted))

    def test_experimental_api_roundtrips_and_refuses_overwrite(self) -> None:
        source = b"".join(
            f'{{"id":{index},"event":"tick","bucket":{index % 5}}}\n'.encode()
            for index in range(500)
        )
        encoded = compress_json_logs(source, segment_size=1024)
        info = inspect_json_log_frame(encoded)
        self.assertEqual(info.original_size, len(source))
        self.assertEqual(decompress_json_logs(encoded), source)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "events.jsonl"
            source_path.write_bytes(source)
            encoded_path = compress_json_log_file(
                source_path,
                segment_size=1024,
            )
            self.assertEqual(encoded_path, root / "events.jsonl.jls2")
            with self.assertRaises(FileExistsError):
                compress_json_log_file(
                    source_path,
                    encoded_path,
                    segment_size=1024,
                )
            self.assertEqual(
                compress_json_log_file(
                    source_path,
                    encoded_path,
                    overwrite=True,
                    segment_size=1024,
                ),
                encoded_path,
            )

            source_path.unlink()
            restored_path = decompress_json_log_file(encoded_path)
            self.assertEqual(restored_path, source_path)
            self.assertEqual(restored_path.read_bytes(), source)
            with self.assertRaises(FileExistsError):
                decompress_json_log_file(encoded_path, restored_path)

    def test_experimental_api_rejects_invalid_input_types_and_paths(self) -> None:
        with self.assertRaises(TypeError):
            compress_json_logs("not bytes")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            decompress_json_logs("not bytes")  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "same.jsonl"
            source.write_bytes(b'{"ok":true}\n')
            with self.assertRaisesRegex(ValueError, "must be different"):
                compress_json_log_file(source, source)


if __name__ == "__main__":
    unittest.main()
