import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import compresslab
from compresslab.cli import main as cli_main
from compresslab.codecs import codec_by_id
from compresslab.worker import _adaptive_compress


GOLDEN_FRAMES = (
    (
        1,
        b"fixture-v1\n" * 20,
        "Q0xBQgEBAAAAAAAAANxCXsEA7ZWsKxv/8ykuDWJdUzJC55EDUP9P4zRBhoS7HR+LCAAAAAAABP9Ly6woKS1K1S0z5EobbkwAJNXhe9wAAAA=",
    ),
    (
        2,
        b"fixture-v2\n" * 20,
        "Q0xBQgIDAAAAAAAAANzCsUM1JkCC9rJrZ8+MAbW3V5iXqd/8eqqPwe7W+N+xlii1L/0g3JUAAFhmaXh0dXJlLXYyCgEATlPFCw==",
    ),
    (
        3,
        b"fixture-v3\n" * 20,
        "Q0xBQgMGAAAAAAAAANzvg+K7MDqD+3Qz+cKUFyr2DxNC26fwXxeQTKbZ6CVMbgAAAAEBAAAA3AAAABtDqJgXKLUv/SDclQAAWGZpeHR1cmUtdjMKAQBOU8UL",
    ),
)


class PublicApiTests(unittest.TestCase):
    def require_v3(self):
        if not codec_by_id("adaptive-v3").available:
            self.skipTest("adaptive-v3 codec dependencies are unavailable")

    def test_current_frame_roundtrip_and_metadata(self):
        self.require_v3()
        source = (b"public-api repeated_identifier\n" * 10_000) + bytes(range(256))
        encoded = compresslab.compress(source)
        info = compresslab.inspect_frame(encoded)
        self.assertEqual(info.version, 3)
        self.assertEqual(info.original_size, len(source))
        self.assertEqual(info.encoded_size, len(encoded))
        self.assertEqual(info.segment_count, 1)
        self.assertEqual(compresslab.decompress(encoded), source)

    def test_golden_frames_retain_versioned_decode_compatibility(self):
        for version, source, encoded_base64 in GOLDEN_FRAMES:
            with self.subTest(version=version):
                encoded = base64.b64decode(encoded_base64, validate=True)
                self.assertEqual(compresslab.inspect_frame(encoded).version, version)
                self.assertEqual(compresslab.decompress(encoded), source)

    def test_decoder_enforces_output_allocation_limit(self):
        self.require_v3()
        source = b"bounded-output" * 10_000
        encoded = compresslab.compress(source)
        with self.assertRaisesRegex(ValueError, "safety limit"):
            compresslab.decompress(encoded, max_output_size=len(source) - 1)
        self.assertEqual(
            compresslab.decompress(encoded, max_output_size=len(source)), source
        )

    def test_decoder_retains_legacy_v1_compatibility(self):
        source = b"legacy-compatible\n" * 1_000
        encoded, _ = _adaptive_compress(source, allow_transform=True)
        self.assertEqual(compresslab.inspect_frame(encoded).version, 1)
        self.assertEqual(compresslab.decompress(encoded), source)

    def test_file_helpers_are_atomic_and_refuse_implicit_overwrite(self):
        self.require_v3()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "example.bin"
            source.write_bytes(b"file-helper\n" * 20_000)
            encoded = compresslab.compress_file(source)
            self.assertEqual(encoded, root / "example.bin.clab")
            source.unlink()
            restored = compresslab.decompress_file(encoded)
            self.assertEqual(restored, source)
            self.assertEqual(restored.read_bytes(), b"file-helper\n" * 20_000)
            with self.assertRaises(FileExistsError):
                compresslab.decompress_file(encoded)

    def test_cli_compress_decompress_and_info(self):
        self.require_v3()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cli.txt"
            encoded = root / "cli.clab"
            restored = root / "restored.txt"
            source.write_bytes(b"cli-roundtrip\n" * 15_000)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli_main(["compress", str(source), "-o", str(encoded)]), 0
                )
                self.assertEqual(
                    cli_main(
                        ["decompress", str(encoded), "-o", str(restored)]
                    ),
                    0,
                )
            self.assertEqual(restored.read_bytes(), source.read_bytes())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(cli_main(["info", str(encoded)]), 0)
            metadata = json.loads(stdout.getvalue())
            self.assertEqual(metadata["version"], 3)
            self.assertEqual(metadata["original_size"], source.stat().st_size)

    def test_frame_inspection_rejects_truncation_and_trailing_data(self):
        self.require_v3()
        encoded = compresslab.compress(b"inspect-frame" * 1_000)
        with self.assertRaises(ValueError):
            compresslab.inspect_frame(encoded[:20])
        with self.assertRaisesRegex(ValueError, "trailing data"):
            compresslab.inspect_frame(encoded + b"x")


if __name__ == "__main__":
    unittest.main()
