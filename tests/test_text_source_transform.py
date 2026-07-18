import hashlib
import random
import struct
import unittest

from compresslab import text_source_transform as transform


U64 = struct.Struct("<Q")


def source_bundle() -> bytes:
    records = [
        (b"Include/example.h", b"#pragma once\nint example(void);\n"),
        (b"Lib/alpha.py", b"def alpha(value):\n    return value + 1\n"),
        (b"Lib/beta.py", b"def beta(value):\n    return value - 1\n"),
        (b"Python/example.c", b"int example(void) { return 1; }\n"),
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
        (10, 100, b"Axiom", b"'''Axiom''' is a compressor.\n"),
        (15, 103, b"Axiom design", b"{{Infobox}}\nA reversible design.\n"),
        (
            20,
            140,
            "Caf\N{LATIN SMALL LETTER E WITH ACUTE}".encode(),
            "Text in UTF-8.\n".encode(),
        ),
    ]
    output = bytearray(transform.WIKIMEDIA_MAGIC)
    output.extend(U64.pack(len(records)))
    manifest = hashlib.sha256()
    for page_id, revision_id, title, text in records:
        output.extend(U64.pack(page_id))
        output.extend(U64.pack(revision_id))
        output.extend(U64.pack(len(title)))
        output.extend(title)
        output.extend(U64.pack(len(text)))
        output.extend(text)
        manifest.update(title)
        manifest.update(text)
    output.extend(manifest.digest())
    return bytes(output)


class TextSourceTransformTests(unittest.TestCase):
    def test_empty_source_bundle_round_trips_in_both_source_modes(self) -> None:
        source = transform.SOURCE_MAGIC + U64.pack(0) + hashlib.sha256(b"").digest()
        for extension_lanes in (False, True):
            encoded = transform.encode_source(source, extension_lanes=extension_lanes)
            self.assertEqual(transform.decode(encoded), source)

    def test_source_demux_round_trip_is_exact_and_deterministic(self) -> None:
        source = source_bundle()
        encoded = transform.encode_source(source, extension_lanes=False)
        self.assertEqual(
            encoded, transform.encode_source(source, extension_lanes=False)
        )
        self.assertEqual(transform.decode(encoded), source)
        self.assertEqual(encoded[transform.HEADER.size + 32], 1)

    def test_source_extension_lanes_round_trip_and_differ_from_plain_demux(
        self,
    ) -> None:
        source = source_bundle()
        demux = transform.encode_source(source, extension_lanes=False)
        lanes = transform.encode_source(source, extension_lanes=True)
        self.assertNotEqual(demux, lanes)
        self.assertEqual(transform.decode(lanes), source)
        _, kind, _, count, _ = transform.HEADER.unpack_from(lanes)
        self.assertEqual(kind, transform.SOURCE_EXTENSION_LANES)
        self.assertEqual(count, 4)

    def test_source_extension_lanes_reject_unused_noncanonical_lane(self) -> None:
        encoded = bytearray(
            transform.encode_source(source_bundle(), extension_lanes=True)
        )
        lane_count_offset = transform.HEADER.size + 32
        lane_count, offset = transform._get_varint(encoded, lane_count_offset)
        self.assertEqual(lane_count, 3)
        for _ in range(lane_count):
            name_size, offset = transform._get_varint(encoded, offset)
            offset += name_size
        encoded[lane_count_offset] = 4
        encoded[offset:offset] = b"\x04.zzz"
        encoded.append(0)
        with self.assertRaisesRegex(ValueError, "lane roster differs from records"):
            transform.decode(bytes(encoded), max_output_size=len(source_bundle()))

    def test_front_coding_requires_maximal_canonical_prefixes(self) -> None:
        source = source_bundle()
        encoded_source = transform.encode_source(source, extension_lanes=False)
        offset = transform.HEADER.size + 32
        lane_count, offset = transform._get_varint(encoded_source, offset)
        for _ in range(lane_count):
            name_size, offset = transform._get_varint(encoded_source, offset)
            offset += name_size
        metadata_size_offset = offset
        metadata_size, metadata_start = transform._get_varint(encoded_source, offset)
        metadata_end = metadata_start + metadata_size
        metadata = bytearray(encoded_source[metadata_start:metadata_end])
        metadata_offset = 0
        for _ in range(2):
            _prefix, metadata_offset = transform._get_varint(metadata, metadata_offset)
            suffix_size, metadata_offset = transform._get_varint(
                metadata, metadata_offset
            )
            metadata_offset += suffix_size
            _content_size, metadata_offset = transform._get_varint(
                metadata, metadata_offset
            )
            _lane, metadata_offset = transform._get_varint(metadata, metadata_offset)
        prefix_offset = metadata_offset
        prefix, metadata_offset = transform._get_varint(metadata, metadata_offset)
        suffix_size_offset = metadata_offset
        suffix_size, suffix_offset = transform._get_varint(metadata, metadata_offset)
        self.assertEqual(prefix, 4)
        metadata[prefix_offset] = 0
        metadata[suffix_size_offset] = suffix_size + 4
        metadata[suffix_offset:suffix_offset] = b"Lib/"
        self.assertLess(len(metadata), 128)
        noncanonical_source = (
            encoded_source[:metadata_size_offset]
            + bytes([len(metadata)])
            + bytes(metadata)
            + encoded_source[metadata_end:]
        )
        with self.assertRaisesRegex(ValueError, "front-coded path is noncanonical"):
            transform.decode(noncanonical_source, max_output_size=len(source))

        wiki = wikimedia_bundle()
        encoded_wiki = bytearray(transform.encode(wiki))
        offset = transform.HEADER.size + 32
        metadata_size, offset = transform._get_varint(encoded_wiki, offset)
        titles_size_offset = offset
        titles_size, offset = transform._get_varint(encoded_wiki, offset)
        _texts_size, metadata_start = transform._get_varint(encoded_wiki, offset)
        titles_start = metadata_start + metadata_size
        wiki_metadata = bytearray(
            encoded_wiki[metadata_start : metadata_start + metadata_size]
        )
        metadata_offset = 0
        for _ in range(5):
            _value, metadata_offset = transform._get_varint(
                wiki_metadata, metadata_offset
            )
        for _ in range(2):
            _value, metadata_offset = transform._get_varint(
                wiki_metadata, metadata_offset
            )
        prefix_offset = metadata_offset
        prefix, metadata_offset = transform._get_varint(wiki_metadata, metadata_offset)
        suffix_size_offset = metadata_offset
        suffix_size, _metadata_offset = transform._get_varint(
            wiki_metadata, metadata_offset
        )
        self.assertEqual(prefix, len(b"Axiom"))
        wiki_metadata[prefix_offset] = 0
        wiki_metadata[suffix_size_offset] = suffix_size + len(b"Axiom")
        encoded_wiki[metadata_start : metadata_start + metadata_size] = wiki_metadata
        encoded_wiki[titles_size_offset] = titles_size + len(b"Axiom")
        encoded_wiki[titles_start + len(b"Axiom") : titles_start + len(b"Axiom")] = (
            b"Axiom"
        )
        with self.assertRaisesRegex(ValueError, "front-coded title is noncanonical"):
            transform.decode(bytes(encoded_wiki), max_output_size=len(wiki))

    def test_wikimedia_demux_round_trip_is_exact_and_deterministic(self) -> None:
        source = wikimedia_bundle()
        encoded = transform.encode(source)
        self.assertEqual(encoded, transform.encode(source))
        self.assertEqual(transform.decode(encoded), source)
        _, kind, _, count, _ = transform.HEADER.unpack_from(encoded)
        self.assertEqual(kind, transform.WIKIMEDIA_DEMUX)
        self.assertEqual(count, 3)

    def test_decoder_enforces_output_bound_before_allocation(self) -> None:
        source = source_bundle()
        encoded = transform.encode(source)
        self.assertEqual(transform.decode(encoded, max_output_size=len(source)), source)
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            transform.decode(encoded, max_output_size=len(source) - 1)

        forged = bytearray(encoded)
        magic, kind, _size, count, digest = transform.HEADER.unpack_from(forged)
        transform.HEADER.pack_into(
            forged, 0, magic, kind, transform.MAX_U64, count, digest
        )
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            transform.decode(bytes(forged), max_output_size=len(source))

        too_many = bytearray(encoded)
        transform.HEADER.pack_into(
            too_many,
            0,
            magic,
            kind,
            len(source),
            transform.MAX_RECORDS + 1,
            digest,
        )
        with self.assertRaisesRegex(ValueError, "record count exceeds limit"):
            transform.decode(bytes(too_many), max_output_size=len(source))

        for invalid in (-1, True, 1.5, "100"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    ValueError, "maximum output size is invalid"
                ):
                    transform.decode(encoded, max_output_size=invalid)  # type: ignore[arg-type]

    def test_decoder_rejects_noncanonical_varints_and_false_output_sizes(self) -> None:
        encoded = bytearray(
            transform.encode_source(source_bundle(), extension_lanes=False)
        )
        lane_count = transform.HEADER.size + 32
        self.assertEqual(encoded[lane_count], 1)
        encoded[lane_count : lane_count + 1] = b"\x81\x00"
        with self.assertRaisesRegex(ValueError, "overlong"):
            transform.decode(bytes(encoded))

        encoded = bytearray(transform.encode(source_bundle()))
        magic, kind, size, count, digest = transform.HEADER.unpack_from(encoded)
        transform.HEADER.pack_into(encoded, 0, magic, kind, size - 1, count, digest)
        with self.assertRaisesRegex(ValueError, "declared output size"):
            transform.decode(bytes(encoded))

    def test_corruption_is_rejected_by_structure_or_end_to_end_digest(self) -> None:
        encoded = bytearray(transform.encode(source_bundle()))
        encoded[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "digest"):
            transform.decode(bytes(encoded))

    def test_seeded_single_bit_mutations_never_restore_silently(self) -> None:
        randomizer = random.Random(20260718)
        for source in (source_bundle(), wikimedia_bundle()):
            encoded = transform.encode(source)
            positions = list(range(len(encoded)))
            randomizer.shuffle(positions)
            for position in positions[:128]:
                mutated = bytearray(encoded)
                mutated[position] ^= 1 << randomizer.randrange(8)
                with self.assertRaises(ValueError):
                    transform.decode(bytes(mutated), max_output_size=len(source))

    def test_invalid_magic_kind_and_trailing_bytes_are_rejected(self) -> None:
        encoded = bytearray(transform.encode(source_bundle()))
        encoded[0] ^= 1
        with self.assertRaisesRegex(ValueError, "magic"):
            transform.decode(bytes(encoded))
        encoded = bytearray(transform.encode(source_bundle()))
        encoded[5] = 255
        with self.assertRaisesRegex(ValueError, "kind"):
            transform.decode(bytes(encoded))
        with self.assertRaisesRegex(ValueError, "trailing"):
            transform.decode(transform.encode(source_bundle()) + b"x")

    def test_unsorted_source_paths_and_non_utf8_titles_are_rejected(self) -> None:
        source = bytearray(transform.SOURCE_MAGIC)
        source.extend(U64.pack(2))
        for path in (b"b.py", b"a.py"):
            source.extend(U64.pack(len(path)))
            source.extend(path)
            source.extend(U64.pack(1))
            source.extend(b"x")
        source.extend(b"0" * 32)
        with self.assertRaisesRegex(ValueError, "strictly sorted"):
            transform.encode(bytes(source))

        wiki = bytearray(transform.WIKIMEDIA_MAGIC)
        wiki.extend(U64.pack(1))
        wiki.extend(U64.pack(1))
        wiki.extend(U64.pack(2))
        wiki.extend(U64.pack(1))
        wiki.extend(b"\xff")
        wiki.extend(U64.pack(1))
        wiki.extend(b"x")
        wiki.extend(b"0" * 32)
        with self.assertRaisesRegex(ValueError, "not UTF-8"):
            transform.encode(bytes(wiki))

    def test_encoder_enforces_record_path_title_and_lane_bounds(self) -> None:
        for magic, label in (
            (transform.SOURCE_MAGIC, "source bundle"),
            (transform.WIKIMEDIA_MAGIC, "Wikimedia"),
        ):
            oversized_count = magic + U64.pack(transform.MAX_RECORDS + 1) + b"0" * 32
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "record count exceeds limit"):
                    transform.encode(oversized_count)

        oversized_path = bytearray(transform.SOURCE_MAGIC)
        oversized_path.extend(U64.pack(1))
        oversized_path.extend(U64.pack(transform.MAX_PATH_BYTES + 1))
        oversized_path.extend(b"0" * 32)
        with self.assertRaisesRegex(ValueError, "path length is invalid"):
            transform.encode(bytes(oversized_path))

        oversized_title = bytearray(transform.WIKIMEDIA_MAGIC)
        oversized_title.extend(U64.pack(1))
        oversized_title.extend(U64.pack(1))
        oversized_title.extend(U64.pack(1))
        oversized_title.extend(U64.pack(transform.MAX_PATH_BYTES + 1))
        oversized_title.extend(b"0" * 32)
        with self.assertRaisesRegex(ValueError, "title is too large"):
            transform.encode(bytes(oversized_title))

        too_many_lanes = bytearray(transform.SOURCE_MAGIC)
        too_many_lanes.extend(U64.pack(transform.MAX_LANES + 1))
        manifest = hashlib.sha256()
        for index in range(transform.MAX_LANES + 1):
            path = f"f{index:05d}.e{index:05d}".encode()
            too_many_lanes.extend(U64.pack(len(path)))
            too_many_lanes.extend(path)
            too_many_lanes.extend(U64.pack(0))
            manifest.update(path)
        too_many_lanes.extend(manifest.digest())
        with self.assertRaisesRegex(ValueError, "lane count exceeds limit"):
            transform.encode_source(bytes(too_many_lanes), extension_lanes=True)


if __name__ == "__main__":
    unittest.main()
