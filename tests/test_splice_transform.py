from __future__ import annotations

import unittest

from compresslab.splice_transform import decode, encode


class SpliceTransformTests(unittest.TestCase):
    def test_roundtrip_preserves_line_endings_and_binary_bytes(self) -> None:
        fixtures = (
            b"",
            b"\n",
            b"alpha\nbeta",
            b"alpha\r\nalpha-longer\r\n",
            b"\x00\xff-short\n\x00\xff-much-longer\nlast",
        )
        for source in fixtures:
            with self.subTest(source=source):
                transformed, _ = encode(source)
                self.assertEqual(
                    decode(transformed, expected_size=len(source)),
                    source,
                )

    def test_variable_length_records_use_splices(self) -> None:
        source = b"".join(
            (
                f'{{"content":"event-{index % 7}-{"x" * (index % 19)}",'
                f'"sequence":{index},"status":"ok"}}\n'
            ).encode()
            for index in range(1000)
        )
        transformed, telemetry = encode(source)
        self.assertEqual(decode(transformed, expected_size=len(source)), source)
        self.assertGreater(telemetry["spliced_records"], 900)
        self.assertLess(len(transformed), len(source))

    def test_corruption_bounds_and_trailing_data_are_rejected(self) -> None:
        source = b"prefix-one-suffix\nprefix-longer-two-suffix\n"
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


if __name__ == "__main__":
    unittest.main()
