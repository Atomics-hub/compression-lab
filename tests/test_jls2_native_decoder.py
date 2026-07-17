from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from compresslab.json_log_codec import (
    FRAME_HEADER,
    MODE_COLUMNAR,
    SEGMENT_HEADER,
    STREAM_HEADER,
    compress,
    decompress,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def binary_path() -> Path:
    name = "clab-jls2.exe" if sys.platform == "win32" else "clab-jls2"
    release = REPOSITORY / "native" / "target" / "release" / name
    if release.is_file():
        return release
    return REPOSITORY / "native" / "target" / "debug" / name


def refresh_stream_digest(frame: bytearray) -> None:
    frame[48:80] = hashlib.sha256(frame[STREAM_HEADER.size :]).digest()


def first_nested_offsets(stream: bytes) -> tuple[int, int, int]:
    segment_offset = STREAM_HEADER.size
    _, frame_size = SEGMENT_HEADER.unpack_from(stream, segment_offset)
    frame_offset = segment_offset + SEGMENT_HEADER.size
    if frame_offset + frame_size > len(stream):
        raise AssertionError("fixture has a truncated first frame")
    payload_offset = frame_offset + FRAME_HEADER.size
    return frame_offset, payload_offset, frame_size


class JLS2NativeDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not binary_path().is_file():
            raise unittest.SkipTest("clab-jls2 has not been built")

    def run_decoder(
        self,
        encoded: bytes,
        *,
        force: bool = False,
        max_output_size: int | None = None,
        preexisting: bytes | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], bytes | None, list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.jls2"
            destination = root / "restored.jsonl"
            source.write_bytes(encoded)
            if preexisting is not None:
                destination.write_bytes(preexisting)
            command = [
                str(binary_path()),
                "decompress",
                str(source),
                "-o",
                str(destination),
            ]
            if force:
                command.append("--force")
            if max_output_size is not None:
                command.extend(["--max-output-size", str(max_output_size)])
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            restored = destination.read_bytes() if destination.exists() else None
            partials = sorted(path.name for path in root.glob("*.partial"))
            return completed, restored, partials

    def test_standalone_round_trips_empty_direct_and_columnar_streams(self) -> None:
        sources = [
            b"",
            os.urandom(256 * 1024),
            b"".join(
                (
                    f'{{"id":{index},"service":"api","status":200,'
                    f'"bucket":{index % 8},"message":"stable"}}\n'
                ).encode()
                for index in range(20_000)
            ),
        ]
        for source in sources:
            with self.subTest(size=len(source)):
                encoded, _ = compress(source, segment_size=256 * 1024)
                completed, restored, partials = self.run_decoder(encoded)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(restored, source)
                self.assertEqual(partials, [])

    def test_refuses_overwrite_then_replaces_only_with_force(self) -> None:
        source = b'{"ok":true}\n' * 1000
        encoded, _ = compress(source, segment_size=4096)
        refused, restored, partials = self.run_decoder(encoded, preexisting=b"sentinel")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("destination already exists", refused.stderr)
        self.assertEqual(restored, b"sentinel")
        self.assertEqual(partials, [])

        replaced, restored, partials = self.run_decoder(
            encoded, force=True, preexisting=b"sentinel"
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertEqual(restored, source)
        self.assertEqual(partials, [])

    def test_output_limit_rejects_without_publishing(self) -> None:
        source = b'{"bounded":true}\n' * 1000
        encoded, _ = compress(source, segment_size=4096)
        completed, restored, partials = self.run_decoder(
            encoded, max_output_size=len(source) - 1
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("output exceeds safety limit", completed.stderr)
        self.assertIsNone(restored)
        self.assertEqual(partials, [])

    def test_rejects_nested_original_digest_even_when_outer_digest_is_valid(
        self,
    ) -> None:
        source = b'{"digest":"nested","value":42}\n' * 10_000
        encoded, _ = compress(source, segment_size=len(source))
        hostile = bytearray(encoded)
        frame_offset, _, _ = first_nested_offsets(hostile)
        hostile[frame_offset + 24] ^= 1
        refresh_stream_digest(hostile)
        self.assertEqual(decompress(bytes(hostile)), source)
        completed, restored, partials = self.run_decoder(bytes(hostile))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("JLF2 original SHA-256", completed.stderr)
        self.assertIsNone(restored)
        self.assertEqual(partials, [])

    def test_rejects_column_original_digest_even_when_parent_is_valid(self) -> None:
        source = b"".join(
            (
                f'{{"id":{index},"timestamp":{1_700_000_000_000 + index},'
                f'"user":{index * 7919},"ip":"10.{index % 255}.'
                f'{(index // 255) % 255}.{(index // 65025) % 255}",'
                f'"service":"api","status":{200 + index % 5},'
                f'"duration":{index * 13 % 10_000},'
                f'"message":"request completed"}}\n'
            ).encode()
            for index in range(20_000)
        )
        encoded, _ = compress(source, segment_size=len(source))
        hostile = bytearray(encoded)
        frame_offset, payload_offset, _ = first_nested_offsets(hostile)
        self.assertEqual(hostile[frame_offset + 5], MODE_COLUMNAR)
        hostile[payload_offset + 16] ^= 1
        payload = hostile[payload_offset:]
        hostile[frame_offset + 56 : frame_offset + 88] = hashlib.sha256(
            payload
        ).digest()
        refresh_stream_digest(hostile)
        self.assertEqual(decompress(bytes(hostile)), source)
        completed, restored, partials = self.run_decoder(bytes(hostile))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("JSON-column original SHA-256", completed.stderr)
        self.assertIsNone(restored)
        self.assertEqual(partials, [])

    def test_rejects_trailing_data_with_recomputed_outer_digest(self) -> None:
        source = b'{"trailers":false}\n' * 1000
        encoded, _ = compress(source, segment_size=4096)
        hostile = bytearray(encoded)
        hostile.extend(b"trailer")
        refresh_stream_digest(hostile)
        with self.assertRaisesRegex(ValueError, "trailing data"):
            decompress(bytes(hostile))
        completed, restored, partials = self.run_decoder(bytes(hostile))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("trailing data", completed.stderr)
        self.assertIsNone(restored)
        self.assertEqual(partials, [])

    def test_rejects_input_output_collision(self) -> None:
        source = b'{"same_path":false}\n' * 100
        encoded, _ = compress(source, segment_size=4096)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "same.jls2"
            path.write_bytes(encoded)
            completed = subprocess.run(
                [
                    str(binary_path()),
                    "decompress",
                    str(path),
                    "-o",
                    str(path),
                    "--force",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("same file", completed.stderr)
            self.assertEqual(path.read_bytes(), encoded)


if __name__ == "__main__":
    unittest.main()
