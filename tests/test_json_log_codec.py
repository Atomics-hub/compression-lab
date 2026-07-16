from __future__ import annotations

import random
from pathlib import Path
import tempfile
import unittest

from compresslab.json_log_codec import (
    FRAME_HEADER,
    compress,
    compress_file,
    compress_frame,
    decompress,
    decompress_file,
    decompress_frame,
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


if __name__ == "__main__":
    unittest.main()
