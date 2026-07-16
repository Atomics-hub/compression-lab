import hashlib
import random
import struct
import unittest

import compresslab
from compresslab.api import DEFAULT_MAX_OUTPUT_SIZE
from compresslab.codecs import codec_by_id
from compresslab.worker import ADAPTIVE_HEADER, ADAPTIVE_MAGIC, BACKEND_STORE


class HostileFrameTests(unittest.TestCase):
    def require_v3(self):
        if not codec_by_id("adaptive-v3").available:
            self.skipTest("adaptive-v3 codec dependencies are unavailable")

    def test_legacy_bomb_is_rejected_before_payload_processing(self):
        declared_size = DEFAULT_MAX_OUTPUT_SIZE + 1
        frame = ADAPTIVE_HEADER.pack(
            ADAPTIVE_MAGIC,
            1,
            BACKEND_STORE,
            declared_size,
            hashlib.sha256(b"").digest(),
        )
        with self.assertRaisesRegex(ValueError, "safety limit"):
            compresslab.decompress(frame)

    def test_every_truncation_of_a_small_frame_is_rejected(self):
        self.require_v3()
        frame = compresslab.compress(b"truncate-me\n" * 2_000)
        for length in range(len(frame)):
            with self.subTest(length=length):
                with self.assertRaises((RuntimeError, ValueError)):
                    compresslab.decompress(frame[:length])

    def test_single_byte_mutations_never_return_silent_corruption(self):
        self.require_v3()
        source = (b"mutation-resistant repeated_identifier\n" * 5_000)
        frame = compresslab.compress(source)
        positions = sorted(
            set(
                [0, 4, 5, 6, 13, 14, 45, len(frame) - 1]
                + [index * len(frame) // 64 for index in range(1, 64)]
            )
        )
        for position in positions:
            corrupted = bytearray(frame)
            corrupted[position] ^= 0x01
            with self.subTest(position=position):
                try:
                    restored = compresslab.decompress(bytes(corrupted))
                except (RuntimeError, ValueError):
                    continue
                self.assertEqual(restored, source)

    def test_structurally_plausible_random_frames_fail_boundedly(self):
        rng = random.Random(20260716)
        for case in range(250):
            original_size = rng.randrange(0, 4096)
            version = rng.choice((1, 2, 3, 255))
            backend = rng.randrange(0, 9)
            suffix = rng.randbytes(rng.randrange(0, 256))
            frame = struct.pack(
                ">4sBBQ32s",
                ADAPTIVE_MAGIC,
                version,
                backend,
                original_size,
                rng.randbytes(32),
            ) + suffix
            with self.subTest(case=case):
                try:
                    restored = compresslab.decompress(
                        frame, max_output_size=4096
                    )
                except (OSError, RuntimeError, ValueError):
                    continue
                self.assertEqual(len(restored), original_size)
                self.assertEqual(hashlib.sha256(restored).digest(), frame[14:46])

    def test_invalid_public_api_arguments_are_rejected(self):
        with self.assertRaises(TypeError):
            compresslab.compress("text")
        with self.assertRaises(TypeError):
            compresslab.decompress(b"", max_output_size=True)
        with self.assertRaises(ValueError):
            compresslab.decompress(b"", max_output_size=-1)


if __name__ == "__main__":
    unittest.main()
