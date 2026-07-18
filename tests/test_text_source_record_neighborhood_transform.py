import hashlib
import importlib.util
from pathlib import Path
import random
import struct
from typing import Optional
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "text-source-record-neighborhood-transform.py"
SPEC = importlib.util.spec_from_file_location("record_neighborhood_transform", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import {SCRIPT}")
transform = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transform)

U64 = struct.Struct("<Q")


def source_bundle(
    records: Optional[list[tuple[bytes, bytes]]] = None,
) -> bytes:
    if records is None:
        repeated = b"license header\n" + b"shared implementation line\n" * 12
        records = [
            (b"Lib/alpha.py", repeated + b"alpha = 1\n"),
            (b"Lib/beta.py", b"unrelated typescript tokens\n" * 13),
            (b"Lib/gamma.py", repeated + b"gamma = 3\n"),
        ]
    output = bytearray(transform.SOURCE_MAGIC)
    output.extend(U64.pack(len(records)))
    manifest = hashlib.sha256()
    for path, content in records:
        output.extend(U64.pack(len(path)))
        output.extend(path)
        output.extend(U64.pack(len(content)))
        output.extend(content)
        manifest.update(path)
        manifest.update(content)
    output.extend(manifest.digest())
    return bytes(output)


def wikimedia_bundle() -> bytes:
    records = [
        (10, 100, b"Axiom", b"A deterministic compressor.\n" * 8),
        (15, 103, b"Talk:Axiom", b"A reversible record transform.\n" * 8),
        (20, 140, b"Axiom design", b"A deterministic compressor.\n" * 8),
    ]
    output = bytearray(transform.WIKIMEDIA_MAGIC)
    output.extend(U64.pack(len(records)))
    manifest = hashlib.sha256()
    for page_id, revision_id, title, text in records:
        output.extend(struct.pack("<QQQ", page_id, revision_id, len(title)))
        output.extend(title)
        output.extend(U64.pack(len(text)))
        output.extend(text)
        manifest.update(title)
        manifest.update(text)
    output.extend(manifest.digest())
    return bytes(output)


def sections(encoded: bytes) -> tuple[int, int, bytes, bytes, bytes, bytes]:
    _magic, kind, _size, count, _digest = transform.HEADER.unpack_from(encoded)
    offset = transform.HEADER.size
    manifest, offset = transform.take(encoded, offset, 32, "manifest")
    metadata_size, offset = transform.get_varint(encoded, offset)
    order_size, offset = transform.get_varint(encoded, offset)
    payload_size, offset = transform.get_varint(encoded, offset)
    metadata, offset = transform.take(encoded, offset, metadata_size, "metadata")
    order, offset = transform.take(encoded, offset, order_size, "permutation")
    payload, offset = transform.take(encoded, offset, payload_size, "payload")
    if offset != len(encoded):  # pragma: no cover
        raise AssertionError("fixture transform has trailing data")
    return kind, count, manifest, metadata, order, payload


class RecordNeighborhoodTransformTests(unittest.TestCase):
    def test_source_and_wikimedia_round_trip_exactly_and_deterministically(self) -> None:
        for source in (source_bundle(), wikimedia_bundle()):
            with self.subTest(magic=source[:6]):
                encoded = transform.encode(source)
                self.assertEqual(encoded, transform.encode(source))
                self.assertEqual(
                    transform.decode(encoded, max_output_size=len(source)), source
                )

    def test_sample_offsets_are_bounded_deterministic_and_include_endpoints(self) -> None:
        for size in (0, 1, 48, 49, 97, 4096, 1_000_000):
            with self.subTest(size=size):
                offsets = transform.sample_offsets(size)
                self.assertEqual(offsets, transform.sample_offsets(size))
                self.assertLessEqual(len(offsets), transform.MAX_SAMPLE_WINDOWS)
                self.assertEqual(offsets, sorted(set(offsets)))
                self.assertEqual(offsets[0], 0)
                maximum = max(0, size - transform.WINDOW_BYTES)
                self.assertEqual(offsets[-1], maximum)
                self.assertTrue(all(0 <= value <= maximum for value in offsets))

    def test_order_puts_identical_neighborhoods_next_to_each_other(self) -> None:
        shared = b"same sampled neighborhood\n" * 20
        records = [
            (b".py", shared),
            (b".py", b"different neighborhood\n" * 20),
            (b".py", shared),
        ]
        order = transform.record_order(records)
        self.assertEqual(order, transform.record_order(records))
        self.assertEqual(sorted(order), [0, 1, 2])
        self.assertEqual(abs(order.index(0) - order.index(2)), 1)
        self.assertNotEqual(order, [0, 1, 2])

    def test_output_bound_trailing_data_and_seeded_corruption_are_rejected(self) -> None:
        source = source_bundle()
        encoded = transform.encode(source)
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            transform.decode(encoded, max_output_size=len(source) - 1)
        with self.assertRaisesRegex(ValueError, "trailing bytes"):
            transform.decode(encoded + b"x", max_output_size=len(source))
        for invalid in (-1, True, 1.5, "100"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "maximum output size is invalid"):
                    transform.decode(encoded, max_output_size=invalid)  # type: ignore[arg-type]

        randomizer = random.Random(20260718)
        positions = list(range(len(encoded)))
        randomizer.shuffle(positions)
        for position in positions[:128]:
            mutated = bytearray(encoded)
            mutated[position] ^= 1 << randomizer.randrange(8)
            with self.assertRaises(ValueError):
                transform.decode(bytes(mutated), max_output_size=len(source))

    def test_valid_but_alternate_permutation_is_rejected_as_noncanonical(self) -> None:
        records = [
            (b"a.py", b"A" * 192),
            (b"b.py", b"B" * 192),
            (b"c.py", b"C" * 192),
        ]
        source = source_bundle(records)
        encoded = transform.encode(source)
        kind, count, manifest, metadata, order_bytes, _payload = sections(encoded)
        canonical_order = transform.decode_order(order_bytes, count)
        alternate_order = list(reversed(canonical_order))
        self.assertNotEqual(alternate_order, canonical_order)
        alternate_payload = b"".join(records[index][1] for index in alternate_order)
        forged = transform.assemble(
            kind=kind,
            original=source,
            count=count,
            manifest=manifest,
            metadata=metadata,
            order=alternate_order,
            payload=alternate_payload,
        )
        with self.assertRaisesRegex(ValueError, "permutation is noncanonical"):
            transform.decode(forged, max_output_size=len(source))

    def test_invalid_input_framing_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            transform.encode(b"ordinary bytes")


if __name__ == "__main__":
    unittest.main()
