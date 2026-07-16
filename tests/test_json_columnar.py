from __future__ import annotations

import unittest

from compresslab.json_columnar import compress, decompress, transform


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


if __name__ == "__main__":
    unittest.main()
