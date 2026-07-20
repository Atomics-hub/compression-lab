import hashlib
import importlib.util
from pathlib import Path
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


MODULE = load_module("wk_c1_decoder_adversarial", SCRIPT)
v = MODULE.encode_varint


def raw_document(payload: bytes) -> bytes:
    return v(1) + bytes([MODULE.RAW]) + v(len(payload)) + payload


def template_document(parameters: list[tuple[bytes, tuple[int, int]]]) -> bytes:
    output = bytearray(v(1) + bytes([MODULE.TEMPLATE]) + v(1) + b"T" + v(len(parameters)))
    for key, (column, row) in parameters:
        output.extend(bytes([MODULE.NAMED]) + v(len(key)) + key + v(column) + v(row))
    return bytes(output)


def full_frame(
    *,
    source: bytes,
    schemas: list[tuple[bytes, bytes]],
    root: bytes,
    columns: list[list[bytes]],
    templates: int,
    fields: int,
) -> bytes:
    metadata = bytearray(v(len(schemas)))
    for name, key in schemas:
        metadata.extend(v(len(name)) + name + v(len(key)) + key)
    metadata.extend(v(len(root)) + root)
    values = bytearray(v(len(columns)))
    for column in columns:
        values.extend(v(len(column)))
        for document in column:
            values.extend(v(len(document)) + document)
    return MODULE.HEADER.pack(
        MODULE.MAGIC,
        MODULE.VERSION,
        MODULE.VARIANTS["wk-c1-full-schema-columns"],
        len(source),
        hashlib.sha256(source).digest(),
        len(metadata),
        len(values),
        templates,
        fields,
    ) + bytes(metadata) + bytes(values)


def structure_frame(
    *,
    source: bytes,
    root: bytes,
    values: list[bytes],
    templates: int,
    fields: int,
) -> bytes:
    metadata = v(0) + v(len(root)) + root
    value_stream = bytearray(v(len(values)))
    for document in values:
        value_stream.extend(v(len(document)) + document)
    return MODULE.HEADER.pack(
        MODULE.MAGIC,
        MODULE.VERSION,
        MODULE.VARIANTS["wk-c1-structure-only"],
        len(source),
        hashlib.sha256(source).digest(),
        len(metadata),
        len(value_stream),
        templates,
        fields,
    ) + metadata + bytes(value_stream)


class TextSourceWkC1DecoderAdversarialTests(unittest.TestCase):
    def schema(self, key: bytes) -> tuple[bytes, bytes]:
        return b"T", b"N" + v(len(key)) + key

    def test_rejects_out_of_range_reference(self) -> None:
        frame = full_frame(
            source=b"{{T|a=x}}",
            schemas=[self.schema(b"a")],
            root=template_document([(b"a", (0, 1))]),
            columns=[[raw_document(b"x")]],
            templates=1,
            fields=1,
        )
        with self.assertRaisesRegex(MODULE.FormatError, "out of range"):
            MODULE.decode(frame, 100)

    def test_rejects_noncanonical_permutation_and_non_bijection(self) -> None:
        schemas = [self.schema(b"a")]
        columns = [[raw_document(b"x"), raw_document(b"y")]]
        reordered = full_frame(
            source=b"{{T|a=y}}{{T|a=x}}",
            schemas=schemas,
            root=(
                v(2)
                + template_document([(b"a", (0, 1))])[1:]
                + template_document([(b"a", (0, 0))])[1:]
            ),
            columns=columns,
            templates=2,
            fields=2,
        )
        with self.assertRaisesRegex(MODULE.FormatError, "permutation is noncanonical"):
            MODULE.decode(reordered, 100)

        duplicate = full_frame(
            source=b"{{T|a=x}}{{T|a=x}}",
            schemas=schemas,
            root=(
                v(2)
                + template_document([(b"a", (0, 0))])[1:]
                + template_document([(b"a", (0, 0))])[1:]
            ),
            columns=columns,
            templates=2,
            fields=2,
        )
        with self.assertRaisesRegex(MODULE.FormatError, "permutation is noncanonical"):
            MODULE.decode(duplicate, 100)

    def test_rejects_schema_mismatch_and_schema_reorder(self) -> None:
        mismatch = full_frame(
            source=b"{{T|a=x}}",
            schemas=[self.schema(b"b")],
            root=template_document([(b"a", (0, 0))]),
            columns=[[raw_document(b"x")]],
            templates=1,
            fields=1,
        )
        with self.assertRaisesRegex(MODULE.FormatError, "schema reference differs"):
            MODULE.decode(mismatch, 100)

        reordered = full_frame(
            source=b"{{T|a=x|b=y}}",
            schemas=[self.schema(b"b"), self.schema(b"a")],
            root=template_document([(b"a", (1, 0)), (b"b", (0, 0))]),
            columns=[[raw_document(b"y")], [raw_document(b"x")]],
            templates=1,
            fields=2,
        )
        with self.assertRaisesRegex(MODULE.FormatError, "schema table is noncanonical"):
            MODULE.decode(reordered, 100)

    def test_rejects_oversized_document_zero_adjacent_raw_and_unknown_tag(self) -> None:
        root = template_document([(b"a", (0, 0))])
        oversized_values = v(1) + v(1) + v(MODULE.MAXIMUM_INPUT_BYTES + 1)
        metadata = v(1) + v(1) + b"T" + v(3) + b"N\x01a" + v(len(root)) + root
        oversized = MODULE.HEADER.pack(
            MODULE.MAGIC,
            MODULE.VERSION,
            MODULE.VARIANTS["wk-c1-full-schema-columns"],
            1,
            hashlib.sha256(b"x").digest(),
            len(metadata),
            len(oversized_values),
            1,
            1,
        ) + metadata + oversized_values
        with self.assertRaisesRegex(MODULE.FormatError, "value document exceeds"):
            MODULE.decode(oversized, MODULE.MAXIMUM_INPUT_BYTES)

        invalid_documents = [
            v(1) + bytes([MODULE.RAW]) + v(0),
            v(2) + bytes([MODULE.RAW]) + v(1) + b"a" + bytes([MODULE.RAW]) + v(1) + b"b",
            v(1) + b"\x7f",
        ]
        messages = ["raw node exceeds", "raw node exceeds", "unknown WKC1 node tag"]
        for document, message in zip(invalid_documents, messages):
            frame = structure_frame(
                source=b"x",
                root=document,
                values=[],
                templates=0,
                fields=0,
            )
            with self.assertRaisesRegex(MODULE.FormatError, message):
                MODULE.decode(frame, 100)

    def test_rejects_reference_depth_above_frozen_limit(self) -> None:
        depth = MODULE.MAXIMUM_NESTING_DEPTH + 1

        def positional_document(reference: int) -> bytes:
            return (
                v(1)
                + bytes([MODULE.TEMPLATE])
                + v(1)
                + b"T"
                + v(1)
                + bytes([MODULE.POSITIONAL])
                + v(reference)
            )

        root = positional_document(0)
        values = [positional_document(index + 1) for index in range(depth - 1)]
        values.append(raw_document(b"x"))
        source = b"{{T|" * depth + b"x" + b"}}" * depth
        frame = structure_frame(
            source=source,
            root=root,
            values=values,
            templates=depth,
            fields=depth,
        )
        with self.assertRaisesRegex(MODULE.FormatError, "reference depth"):
            MODULE.decode(frame, len(source))


if __name__ == "__main__":
    unittest.main()
