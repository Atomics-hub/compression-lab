import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "text-source-wk-c1-transform.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


MODULE = load_module("text_source_wk_c1_transform", SCRIPT)


class TextSourceWkC1TransformTests(unittest.TestCase):
    def roundtrip(self, payload: bytes, variant: str) -> bytes:
        first = MODULE.encode(payload, variant)
        second = MODULE.encode(payload, variant)
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).digest(), hashlib.sha256(second).digest())
        self.assertEqual(MODULE.decode(first, len(payload)), payload)
        return first

    def sections(self, frame: bytes):
        unpacked = MODULE.HEADER.unpack(frame[: MODULE.HEADER.size])
        metadata_size = unpacked[5]
        metadata_end = MODULE.HEADER.size + metadata_size
        columnarize = unpacked[2] == MODULE.VARIANTS["wk-c1-full-schema-columns"]
        return MODULE._read_sections(
            frame[MODULE.HEADER.size : metadata_end],
            frame[metadata_end:],
            columnarize=columnarize,
            limits=MODULE.Limits(),
        )

    def test_recursive_templates_links_and_exact_parameter_order_roundtrip(self) -> None:
        payload = (
            b"before {{Infobox| name =Alice|link=[[A|B=C]]|"
            b"nested={{small|x=y|z={{deep|1}}}}|tail}} after\n"
        )
        for variant in MODULE.VARIANTS:
            frame = self.roundtrip(payload, variant)
            info = MODULE.inspect_frame(frame)
            self.assertEqual(info["template_count"], 3)
            self.assertEqual(info["field_count"], 7)
            self.assertEqual(
                info["complete_transform_bytes"],
                info["header_bytes"]
                + info["metadata_bytes"]
                + info["value_stream_bytes"],
            )

    def test_full_groups_values_by_sorted_data_derived_schema(self) -> None:
        payload = b"{{T|a=one|b=x}}--{{T|b=y|a=two}}"
        full = self.roundtrip(payload, "wk-c1-full-schema-columns")
        _root, schemas, columns, _state = self.sections(full)
        self.assertEqual(
            schemas,
            [
                (b"T", b"N" + MODULE.encode_varint(1) + b"a"),
                (b"T", b"N" + MODULE.encode_varint(1) + b"b"),
            ],
        )
        self.assertEqual(
            [[MODULE._reconstruct(value, maximum_size=100) for value in column] for column in columns],
            [[b"one", b"two"], [b"x", b"y"]],
        )

        structure = self.roundtrip(payload, "wk-c1-structure-only")
        _root, schemas, columns, _state = self.sections(structure)
        self.assertEqual(schemas, [])
        self.assertEqual(
            [MODULE._reconstruct(value, maximum_size=100) for value in columns[0]],
            [b"one", b"x", b"y", b"two"],
        )

    def test_positional_schema_and_nested_value_references_are_canonical(self) -> None:
        payload = b"{{T|first|named={{U|inside}}|third}}"
        frame = self.roundtrip(payload, "wk-c1-full-schema-columns")
        _root, schemas, columns, _state = self.sections(frame)
        self.assertIn((b"T", b"P" + MODULE.encode_varint(0)), schemas)
        self.assertIn((b"T", b"P" + MODULE.encode_varint(2)), schemas)
        self.assertIn((b"T", b"N" + MODULE.encode_varint(5) + b"named"), schemas)
        self.assertIn((b"U", b"P" + MODULE.encode_varint(0)), schemas)
        self.assertEqual(sum(len(column) for column in columns), 4)

    def test_comments_nowiki_triple_braces_and_malformed_regions_are_raw_exact(self) -> None:
        payload = (
            b"<!-- {{hidden|x}} -->"
            b"<nowiki>{{also|hidden}}</nowiki>"
            b"{{{parameter|{{nested|raw}}}}}}"
            b"{{unclosed|x{{later|y=z}}"
        )
        for variant in MODULE.VARIANTS:
            frame = self.roundtrip(payload, variant)
            self.assertEqual(MODULE.inspect_frame(frame)["template_count"], 0)

    def test_scanner_limits_fall_back_to_raw_without_losing_bytes(self) -> None:
        payload = b"A{{outer|x={{inner|y=z}}}}B"
        document, state = MODULE.parse(
            payload,
            MODULE.Limits(maximum_nesting_depth=1),
        )
        self.assertEqual(state.templates, 1)
        self.assertEqual(state.fields, 1)
        schemas, columns = MODULE._assign_references(document, columnarize=True)
        self.assertEqual(len(schemas), 1)
        self.assertEqual(len(columns), 1)

    def test_decoder_rejects_truncation_append_wrong_digest_and_size_limit(self) -> None:
        payload = b"prefix {{T|a=one|two}} suffix"
        frame = self.roundtrip(payload, "wk-c1-full-schema-columns")
        for size in range(MODULE.HEADER.size):
            with self.assertRaises(MODULE.FormatError):
                MODULE.decode(frame[:size], len(payload))
        with self.assertRaisesRegex(MODULE.FormatError, "section accounting"):
            MODULE.decode(frame + b"x", len(payload))
        with self.assertRaisesRegex(MODULE.FormatError, "declared source size"):
            MODULE.decode(frame, len(payload) - 1)
        mutated = bytearray(frame)
        digest_offset = struct.calcsize("<4sBBQ")
        mutated[digest_offset] ^= 1
        with self.assertRaisesRegex(MODULE.FormatError, "identity differs"):
            MODULE.decode(bytes(mutated), len(payload))

    def test_decoder_rejects_noncanonical_varint_and_count_forgery(self) -> None:
        payload = b"plain raw bytes"
        frame = self.roundtrip(payload, "wk-c1-structure-only")
        header = list(MODULE.HEADER.unpack(frame[: MODULE.HEADER.size]))
        metadata_size = header[5]
        metadata = frame[MODULE.HEADER.size : MODULE.HEADER.size + metadata_size]
        values = frame[MODULE.HEADER.size + metadata_size :]
        forged_metadata = b"\x80\x00" + metadata[1:]
        header[5] = len(forged_metadata)
        forged = MODULE.HEADER.pack(*header) + forged_metadata + values
        with self.assertRaisesRegex(MODULE.FormatError, "noncanonical"):
            MODULE.decode(forged, len(payload))

        header = list(MODULE.HEADER.unpack(frame[: MODULE.HEADER.size]))
        header[7] = 1
        forged = MODULE.HEADER.pack(*header) + frame[MODULE.HEADER.size :]
        with self.assertRaisesRegex(MODULE.FormatError, "structure counts"):
            MODULE.decode(forged, len(payload))


if __name__ == "__main__":
    unittest.main()
