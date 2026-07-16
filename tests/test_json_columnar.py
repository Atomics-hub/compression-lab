from __future__ import annotations

import unittest

from compresslab.json_columnar import (
    compress,
    decompress,
    pack_transform,
    transform,
    transform_reference,
    unpack_transform,
)
from compresslab.native import (
    json_columnar_reassemble as native_reassemble,
    json_columnar_transform as native_transform,
    native_available,
)


class JsonColumnarTests(unittest.TestCase):
    def test_roundtrip_preserves_exact_jsonl_bytes(self) -> None:
        fixtures = (
            b"",
            b'{"a":1,"b":"two"}\n',
            b' { "b" : [1,2,{"x":"y"}], "a": true }\r\n'
            b'{"a":null,"b":"escaped \\\\\" quote"}',
            b'not-json\xff\n{"a":1}\n',
            b'{"missing":"a"}\n{"different":2,"missing":"b"}\n',
        )
        for source in fixtures:
            with self.subTest(source=source):
                encoded, _ = compress(source)
                self.assertEqual(decompress(encoded), source)

    def test_channels_follow_raw_top_level_keys(self) -> None:
        source = b"".join(
            f'{{"id":{index},"event":"tick","value":"v-{index % 7}"}}\n'.encode()
            for index in range(1000)
        )
        skeleton, channels, telemetry = transform(source)
        self.assertEqual(telemetry["channel_count"], 3)
        self.assertEqual(telemetry["extracted_records"], 1000)
        self.assertEqual(telemetry["extracted_values"], 3000)
        self.assertTrue(skeleton)
        self.assertTrue(all(channels))
        encoded, _ = compress(source)
        self.assertLess(len(encoded), len(source))
        self.assertEqual(decompress(encoded), source)

    def test_corruption_truncation_and_bounds_are_rejected(self) -> None:
        source = b'{"id":1,"event":"tick"}\n' * 100
        encoded, _ = compress(source)
        for candidate in (
            encoded[:-1],
            encoded + b"\0",
            b"NOPE" + encoded[4:],
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    decompress(candidate)
        with self.assertRaises(ValueError):
            decompress(encoded, max_output_size=len(source) - 1)

    def test_native_transform_is_byte_identical_to_reference(self) -> None:
        if not native_available():
            self.skipTest("native library is unavailable")
        too_many_keys = (
            b"{"
            + b",".join(
                f'"key-{index}":{index}'.encode()
                for index in range(257)
            )
            + b"}\n"
        )
        fixtures = (
            b"",
            b'{"a":1,"b":"two"}\n',
            b' { "b" : [1,2,{"x":"y"}], "a": true }\r\n',
            b'{"a":"escaped \\\\\" quote","b":-1.25e+3}',
            b'{"a":NaN}\n',
            b'not-json\xff\n{"a":1}\n',
            too_many_keys,
        )
        for source in fixtures:
            with self.subTest(size=len(source)):
                skeleton, channels, telemetry = transform_reference(source)
                reference = pack_transform(
                    skeleton,
                    channels,
                    telemetry,
                )
                native = native_transform(source)
                self.assertEqual(native, reference)
                self.assertEqual(unpack_transform(native), (
                    skeleton,
                    channels,
                    telemetry,
                ))
                self.assertEqual(native_reassemble(native, len(source)), source)
                self.assertEqual(transform(source), (
                    skeleton,
                    channels,
                    telemetry,
                ))


if __name__ == "__main__":
    unittest.main()
