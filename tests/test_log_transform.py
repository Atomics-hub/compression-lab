from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path

from compresslab.log_transform import (
    decode,
    decode_recent,
    encode,
    encode_recent,
)
from compresslab.log_codec import (
    HEADER as LOG_HEADER,
    compress as compress_log_candidate,
    decompress as decompress_log_candidate,
)
from compresslab.native import (
    log_transform_decode as native_decode_recent,
    log_transform_encode as native_encode_recent,
    native_available,
)


class LogTransformTests(unittest.TestCase):
    def test_roundtrip_preserves_line_endings_and_binary_bytes(self) -> None:
        fixtures = (
            b"",
            b"\n",
            b"alpha\nbeta",
            b"alpha\r\nalpha\r\n",
            b"\x00\xff\n\x00\xfe\nlast",
        )
        for source in fixtures:
            with self.subTest(source=source):
                transformed, _ = encode(source)
                self.assertEqual(
                    decode(transformed, expected_size=len(source)),
                    source,
                )

    def test_same_length_records_use_references(self) -> None:
        source = b"".join(
            (
                f'{{"level":"INFO","request":{index:08d},"worker":{index % 8}}}\n'
            ).encode()
            for index in range(1000)
        )
        transformed, telemetry = encode(source)
        self.assertEqual(decode(transformed, expected_size=len(source)), source)
        self.assertGreater(telemetry["referenced_records"], 900)
        self.assertLess(len(transformed), len(source))

    def test_corruption_and_bounds_are_rejected(self) -> None:
        source = b"same-length-0001\nsame-length-0002\n"
        transformed, _ = encode(source)
        for candidate in (
            transformed[:-1],
            transformed + b"\0",
            b"NOPE" + transformed[4:],
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    decode(candidate, expected_size=len(source))
        with self.assertRaises(ValueError):
            decode(transformed, expected_size=len(source) - 1)

    def test_window_size_is_part_of_the_decode_contract(self) -> None:
        source = b"".join(
            f"record-{index % 4:02d}-value-{index:08d}\n".encode()
            for index in range(100)
        )
        transformed, _ = encode(source, window_size=4)
        self.assertEqual(
            decode(transformed, expected_size=len(source), window_size=4),
            source,
        )
        with self.assertRaises(ValueError):
            encode(source, window_size=0)
        with self.assertRaises(ValueError):
            decode(transformed, expected_size=len(source), window_size=17)

    def test_recent_reference_roundtrip_and_corruption(self) -> None:
        source = b"".join(
            f'{{"event":"tick","sequence":{index:08d},"worker":{index % 4}}}\n'.encode()
            for index in range(1000)
        )
        transformed, telemetry = encode_recent(source)
        self.assertEqual(
            decode_recent(transformed, expected_size=len(source)),
            source,
        )
        self.assertGreater(telemetry["referenced_records"], 900)
        self.assertTrue(transformed.startswith(b"LWX2"))
        with self.assertRaises(ValueError):
            decode_recent(transformed[:-1], expected_size=len(source))
        with self.assertRaises(ValueError):
            decode_recent(transformed + b"\0", expected_size=len(source))

    def test_native_recent_transform_matches_python_reference(self) -> None:
        if not native_available():
            self.skipTest("native library is unavailable")
        fixtures = (
            b"",
            b"alpha\nbeta",
            b"".join(
                f'{{"event":"tick","sequence":{index:08d},"worker":{index % 4}}}\n'.encode()
                for index in range(1000)
            ),
            b"x" * (32 * 1024 + 1) + b"\n",
        )
        for source in fixtures:
            with self.subTest(size=len(source)):
                reference, _ = encode_recent(source)
                native = native_encode_recent(source)
                self.assertEqual(native, reference)
                self.assertEqual(
                    native_decode_recent(native, len(source)),
                    source,
                )

    def test_discovery_fallback_is_bounded_and_roundtrips(self) -> None:
        if not native_available():
            self.skipTest("native library is unavailable")
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "probe-log-length-xor.py"
        )
        spec = importlib.util.spec_from_file_location("log_probe", script)
        if spec is None or spec.loader is None:
            self.fail("failed to load log discovery probe")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, source in module.fallback_probe_cases(256 * 1024).items():
            with self.subTest(name=name):
                encoded, detail = compress_log_candidate(source)
                self.assertLessEqual(
                    detail["selected_bytes"],
                    detail["direct_frame_bytes"],
                )
                self.assertEqual(
                    decompress_log_candidate(encoded),
                    source,
                )

    def test_log_candidate_rejects_corruption_and_output_overflow(self) -> None:
        if not native_available():
            self.skipTest("native library is unavailable")
        source = b"".join(
            f'{{"event":"tick","sequence":{index:08d}}}\n'.encode()
            for index in range(1000)
        )
        encoded, _ = compress_log_candidate(source)
        with self.assertRaises(ValueError):
            decompress_log_candidate(encoded[:-1])
        with self.assertRaises(ValueError):
            decompress_log_candidate(encoded + b"\0")
        with self.assertRaises(ValueError):
            decompress_log_candidate(
                encoded,
                max_output_size=len(source) - 1,
            )
        corrupted_hash = bytearray(encoded)
        corrupted_hash[LOG_HEADER.size - 1] ^= 1
        with self.assertRaises(ValueError):
            decompress_log_candidate(bytes(corrupted_hash))


if __name__ == "__main__":
    unittest.main()
