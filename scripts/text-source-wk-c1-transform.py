#!/usr/bin/env python3
"""Bounded reversible WK-C1 recursive template columnarization transform."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Any


MAGIC = b"WKC1"
VERSION = 1
VARIANTS = {
    "wk-c1-full-schema-columns": 1,
    "wk-c1-structure-only": 2,
}
VARIANTS_BY_KIND = {value: key for key, value in VARIANTS.items()}
HEADER = struct.Struct("<4sBBQ32sQQII")
MAXIMUM_INPUT_BYTES = 2_147_483_648
MAXIMUM_NESTING_DEPTH = 64
MAXIMUM_TEMPLATES = 1_000_000
MAXIMUM_TOTAL_FIELDS = 8_000_000
MAXIMUM_FIELDS_PER_TEMPLATE = 1_024
MAXIMUM_TEMPLATE_NAME_BYTES = 4_096
MAXIMUM_PARAMETER_KEY_BYTES = 4_096
MAXIMUM_FIELD_BYTES = 134_217_728
RAW = 0
TEMPLATE = 1
POSITIONAL = 0
NAMED = 1


class FormatError(ValueError):
    """Raised when a WKC1 stream or candidate construct is invalid."""


@dataclass
class Limits:
    maximum_input_bytes: int = MAXIMUM_INPUT_BYTES
    maximum_nesting_depth: int = MAXIMUM_NESTING_DEPTH
    maximum_templates: int = MAXIMUM_TEMPLATES
    maximum_total_fields: int = MAXIMUM_TOTAL_FIELDS
    maximum_fields_per_template: int = MAXIMUM_FIELDS_PER_TEMPLATE
    maximum_template_name_bytes: int = MAXIMUM_TEMPLATE_NAME_BYTES
    maximum_parameter_key_bytes: int = MAXIMUM_PARAMETER_KEY_BYTES
    maximum_field_bytes: int = MAXIMUM_FIELD_BYTES


@dataclass
class State:
    templates: int = 0
    fields: int = 0


@dataclass
class Document:
    nodes: list[Any]


@dataclass
class Parameter:
    named: bool
    key: bytes
    ordinal: int
    value: Document
    reference: tuple[int, ...] | None = None


@dataclass
class TemplateNode:
    name: bytes
    parameters: list[Parameter]


def encode_varint(value: int) -> bytes:
    if type(value) is not int or value < 0 or value > 2**64 - 1:
        raise FormatError("integer is outside canonical uint64 range")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        if type(size) is not int or size < 0 or size > len(self.data) - self.offset:
            raise FormatError("truncated WKC1 section")
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def byte(self) -> int:
        return self.read(1)[0]

    def varint(self) -> int:
        start = self.offset
        value = 0
        shift = 0
        for _ in range(10):
            current = self.byte()
            value |= (current & 0x7F) << shift
            if current < 0x80:
                if value > 2**64 - 1 or self.data[start : self.offset] != encode_varint(value):
                    raise FormatError("noncanonical WKC1 varint")
                return value
            shift += 7
        raise FormatError("WKC1 varint is too long")

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise FormatError("trailing bytes in WKC1 section")


def _skip_protected(data: bytes, position: int) -> int | None:
    if data.startswith(b"<!--", position):
        end = data.find(b"-->", position + 4)
        return len(data) if end < 0 else end + 3
    if data.startswith(b"<nowiki>", position):
        end = data.find(b"</nowiki>", position + 8)
        return len(data) if end < 0 else end + 9
    return None


def _balanced_template_end(data: bytes, start: int) -> int | None:
    if not data.startswith(b"{{", start) or data.startswith(b"{{{", start):
        return None
    depth = 1
    position = start + 2
    while position < len(data):
        protected_end = _skip_protected(data, position)
        if protected_end is not None:
            position = protected_end
            continue
        if data.startswith(b"{{{", position):
            return None
        if data.startswith(b"{{", position):
            depth += 1
            position += 2
            continue
        if data.startswith(b"}}", position):
            depth -= 1
            position += 2
            if depth == 0:
                return position
            continue
        position += 1
    return None


def _top_level_positions(data: bytes, separator: int) -> list[int] | None:
    positions = []
    template_depth = 0
    link_depth = 0
    position = 0
    while position < len(data):
        protected_end = _skip_protected(data, position)
        if protected_end is not None:
            position = protected_end
            continue
        if data.startswith(b"{{{", position):
            return None
        if data.startswith(b"{{", position):
            template_depth += 1
            position += 2
            continue
        if data.startswith(b"}}", position):
            if template_depth == 0:
                return None
            template_depth -= 1
            position += 2
            continue
        if data.startswith(b"[[", position):
            link_depth += 1
            position += 2
            continue
        if data.startswith(b"]]", position) and link_depth:
            link_depth -= 1
            position += 2
            continue
        if data[position] == separator and template_depth == 0 and link_depth == 0:
            positions.append(position)
        position += 1
    if template_depth or link_depth:
        return None
    return positions


def _split_top_level(data: bytes, separator: int) -> list[bytes] | None:
    positions = _top_level_positions(data, separator)
    if positions is None:
        return None
    fields = []
    start = 0
    for position in positions:
        fields.append(data[start:position])
        start = position + 1
    fields.append(data[start:])
    return fields


def _has_nested_construct(data: bytes) -> bool:
    position = 0
    while position < len(data):
        protected_end = _skip_protected(data, position)
        if protected_end is not None:
            position = protected_end
            continue
        if data.startswith((b"{{", b"[["), position):
            return True
        position += 1
    return False


def _parse_template(
    candidate: bytes,
    *,
    depth: int,
    limits: Limits,
    state: State,
) -> TemplateNode | None:
    if depth > limits.maximum_nesting_depth or not candidate.endswith(b"}}"):
        return None
    interior = candidate[2:-2]
    fields = _split_top_level(interior, ord("|"))
    if fields is None or not fields or len(fields) - 1 > limits.maximum_fields_per_template:
        return None
    name = fields[0]
    if (
        not name
        or len(name) > limits.maximum_template_name_bytes
        or _has_nested_construct(name)
    ):
        return None
    if state.templates >= limits.maximum_templates:
        return None
    snapshot = (state.templates, state.fields)
    state.templates += 1
    parameters = []
    try:
        for ordinal, field in enumerate(fields[1:]):
            if len(field) > limits.maximum_field_bytes:
                raise FormatError("field exceeds frozen scanner limit")
            if state.fields >= limits.maximum_total_fields:
                raise FormatError("field count exceeds frozen scanner limit")
            state.fields += 1
            equals = _top_level_positions(field, ord("="))
            if equals is None:
                raise FormatError("unsupported parameter structure")
            named = bool(equals)
            if named:
                split = equals[0]
                key = field[:split]
                value = field[split + 1 :]
                if (
                    not key
                    or len(key) > limits.maximum_parameter_key_bytes
                    or _has_nested_construct(key)
                ):
                    raise FormatError("unsupported named parameter key")
            else:
                key = b""
                value = field
            value_document = _parse_document(
                value,
                depth=depth + 1,
                limits=limits,
                state=state,
            )
            parameters.append(
                Parameter(
                    named=named,
                    key=key,
                    ordinal=ordinal,
                    value=value_document,
                )
            )
    except FormatError:
        state.templates, state.fields = snapshot
        return None
    return TemplateNode(name=name, parameters=parameters)


def _parse_document(data: bytes, *, depth: int, limits: Limits, state: State) -> Document:
    nodes: list[Any] = []
    raw_start = 0
    position = 0
    while position < len(data):
        protected_end = _skip_protected(data, position)
        if protected_end is not None:
            position = protected_end
            continue
        if data.startswith(b"{{{", position):
            end = data.find(b"}}}", position + 3)
            position = len(data) if end < 0 else end + 3
            continue
        if not data.startswith(b"{{", position):
            position += 1
            continue
        end = _balanced_template_end(data, position)
        if end is None:
            break
        node = _parse_template(
            data[position:end], depth=depth, limits=limits, state=state
        )
        if node is None:
            position = end
            continue
        if position > raw_start:
            nodes.append(data[raw_start:position])
        nodes.append(node)
        raw_start = end
        position = end
    if raw_start < len(data):
        nodes.append(data[raw_start:])
    return Document(nodes=nodes)


def parse(data: bytes, limits: Limits | None = None) -> tuple[Document, State]:
    limits = limits or Limits()
    if len(data) > limits.maximum_input_bytes:
        raise FormatError("input exceeds frozen scanner limit")
    state = State()
    document = _parse_document(data, depth=1, limits=limits, state=state)
    return document, state


def _schema(parameter: Parameter, template_name: bytes) -> tuple[bytes, bytes]:
    if parameter.named:
        key = b"N" + encode_varint(len(parameter.key)) + parameter.key
    else:
        key = b"P" + encode_varint(parameter.ordinal)
    return template_name, key


def _serialized_schema(schema: tuple[bytes, bytes]) -> bytes:
    template_name, parameter_key = schema
    return (
        encode_varint(len(template_name))
        + template_name
        + encode_varint(len(parameter_key))
        + parameter_key
    )


def _walk_templates(document: Document):
    for node in document.nodes:
        if isinstance(node, TemplateNode):
            yield node
            for parameter in node.parameters:
                yield from _walk_templates(parameter.value)


def _assign_references(
    document: Document, *, columnarize: bool
) -> tuple[list[tuple[bytes, bytes]], list[list[Document]]]:
    schemas = sorted(
        {
            _schema(parameter, template.name)
            for template in _walk_templates(document)
            for parameter in template.parameters
        },
        key=_serialized_schema,
    )
    if not columnarize:
        schemas = []
        columns: list[list[Document]] = [[]]
    else:
        columns = [[] for _ in schemas]
    schema_ids = {schema: index for index, schema in enumerate(schemas)}

    def visit(current: Document) -> None:
        for node in current.nodes:
            if not isinstance(node, TemplateNode):
                continue
            for parameter in node.parameters:
                if columnarize:
                    column = schema_ids[_schema(parameter, node.name)]
                    row = len(columns[column])
                    parameter.reference = (column, row)
                    columns[column].append(parameter.value)
                else:
                    row = len(columns[0])
                    parameter.reference = (row,)
                    columns[0].append(parameter.value)
                visit(parameter.value)

    visit(document)
    return schemas, columns


def _serialize_document(document: Document, *, columnarize: bool) -> bytes:
    output = bytearray(encode_varint(len(document.nodes)))
    for node in document.nodes:
        if isinstance(node, bytes):
            output.append(RAW)
            output.extend(encode_varint(len(node)))
            output.extend(node)
            continue
        if not isinstance(node, TemplateNode):
            raise FormatError("unknown WK-C1 node")
        output.append(TEMPLATE)
        output.extend(encode_varint(len(node.name)))
        output.extend(node.name)
        output.extend(encode_varint(len(node.parameters)))
        for parameter in node.parameters:
            output.append(NAMED if parameter.named else POSITIONAL)
            if parameter.named:
                output.extend(encode_varint(len(parameter.key)))
                output.extend(parameter.key)
            if parameter.reference is None:
                raise FormatError("unassigned WK-C1 value reference")
            for value in parameter.reference:
                output.extend(encode_varint(value))
    return bytes(output)


def _serialize_sections(
    document: Document, *, columnarize: bool
) -> tuple[bytes, bytes, list[tuple[bytes, bytes]]]:
    schemas, columns = _assign_references(document, columnarize=columnarize)
    metadata = bytearray(encode_varint(len(schemas)))
    for template_name, parameter_key in schemas:
        metadata.extend(encode_varint(len(template_name)))
        metadata.extend(template_name)
        metadata.extend(encode_varint(len(parameter_key)))
        metadata.extend(parameter_key)
    root = _serialize_document(document, columnarize=columnarize)
    metadata.extend(encode_varint(len(root)))
    metadata.extend(root)

    values = bytearray()
    if columnarize:
        values.extend(encode_varint(len(columns)))
        selected_columns = columns
    else:
        values.extend(encode_varint(len(columns[0])))
        selected_columns = [columns[0]]
    for column in selected_columns:
        if columnarize:
            values.extend(encode_varint(len(column)))
        for value in column:
            encoded = _serialize_document(value, columnarize=columnarize)
            values.extend(encode_varint(len(encoded)))
            values.extend(encoded)
    return bytes(metadata), bytes(values), schemas


def encode(data: bytes, variant: str) -> bytes:
    if variant not in VARIANTS:
        raise FormatError(f"unsupported WK-C1 variant: {variant}")
    document, state = parse(data)
    columnarize = variant == "wk-c1-full-schema-columns"
    metadata, values, _schemas = _serialize_sections(
        document, columnarize=columnarize
    )
    header = HEADER.pack(
        MAGIC,
        VERSION,
        VARIANTS[variant],
        len(data),
        hashlib.sha256(data).digest(),
        len(metadata),
        len(values),
        state.templates,
        state.fields,
    )
    return header + metadata + values


@dataclass
class DecodeState:
    templates: int = 0
    fields: int = 0


def _read_document(
    data: bytes,
    *,
    columnarize: bool,
    limits: Limits,
    state: DecodeState,
) -> Document:
    reader = Reader(data)
    node_count = reader.varint()
    if node_count > limits.maximum_total_fields + limits.maximum_templates + 1:
        raise FormatError("WKC1 node count exceeds frozen limit")
    nodes: list[Any] = []
    for _ in range(node_count):
        tag = reader.byte()
        if tag == RAW:
            size = reader.varint()
            if (
                size == 0
                or size > limits.maximum_input_bytes
                or (nodes and isinstance(nodes[-1], bytes))
            ):
                raise FormatError("WKC1 raw node exceeds frozen limit")
            nodes.append(reader.read(size))
            continue
        if tag != TEMPLATE:
            raise FormatError("unknown WKC1 node tag")
        state.templates += 1
        if state.templates > limits.maximum_templates:
            raise FormatError("WKC1 template count exceeds frozen limit")
        name_size = reader.varint()
        if name_size == 0 or name_size > limits.maximum_template_name_bytes:
            raise FormatError("WKC1 template name exceeds frozen limit")
        name = reader.read(name_size)
        field_count = reader.varint()
        if field_count > limits.maximum_fields_per_template:
            raise FormatError("WKC1 field count exceeds frozen limit")
        state.fields += field_count
        if state.fields > limits.maximum_total_fields:
            raise FormatError("WKC1 total field count exceeds frozen limit")
        parameters = []
        for ordinal in range(field_count):
            kind = reader.byte()
            if kind == NAMED:
                key_size = reader.varint()
                if key_size == 0 or key_size > limits.maximum_parameter_key_bytes:
                    raise FormatError("WKC1 parameter key exceeds frozen limit")
                key = reader.read(key_size)
                named = True
            elif kind == POSITIONAL:
                key = b""
                named = False
            else:
                raise FormatError("unknown WKC1 parameter kind")
            reference = (
                (reader.varint(), reader.varint())
                if columnarize
                else (reader.varint(),)
            )
            parameters.append(
                Parameter(
                    named=named,
                    key=key,
                    ordinal=ordinal,
                    value=Document([]),
                    reference=reference,
                )
            )
        nodes.append(TemplateNode(name=name, parameters=parameters))
    reader.finish()
    return Document(nodes)


def _read_sections(
    metadata: bytes,
    values: bytes,
    *,
    columnarize: bool,
    limits: Limits,
) -> tuple[Document, list[tuple[bytes, bytes]], list[list[Document]], DecodeState]:
    state = DecodeState()
    metadata_reader = Reader(metadata)
    schema_count = metadata_reader.varint()
    if (columnarize and schema_count > limits.maximum_total_fields) or (
        not columnarize and schema_count != 0
    ):
        raise FormatError("WKC1 schema count differs")
    schemas = []
    for _ in range(schema_count):
        name_size = metadata_reader.varint()
        if name_size == 0 or name_size > limits.maximum_template_name_bytes:
            raise FormatError("WKC1 schema name exceeds frozen limit")
        name = metadata_reader.read(name_size)
        key_size = metadata_reader.varint()
        if key_size == 0 or key_size > limits.maximum_parameter_key_bytes + 11:
            raise FormatError("WKC1 schema key exceeds frozen limit")
        key = metadata_reader.read(key_size)
        schemas.append((name, key))
    if schemas != sorted(set(schemas), key=_serialized_schema):
        raise FormatError("WKC1 schema table is noncanonical")
    root_size = metadata_reader.varint()
    root_raw = metadata_reader.read(root_size)
    metadata_reader.finish()
    root = _read_document(
        root_raw, columnarize=columnarize, limits=limits, state=state
    )

    value_reader = Reader(values)
    columns = []
    if columnarize:
        if value_reader.varint() != len(schemas):
            raise FormatError("WKC1 value column count differs")
        total_values = 0
        for _ in schemas:
            count = value_reader.varint()
            total_values += count
            if total_values > limits.maximum_total_fields:
                raise FormatError("WKC1 value count exceeds frozen limit")
            column = []
            for _ in range(count):
                size = value_reader.varint()
                if size > limits.maximum_input_bytes:
                    raise FormatError("WKC1 value document exceeds frozen limit")
                column.append(
                    _read_document(
                        value_reader.read(size),
                        columnarize=columnarize,
                        limits=limits,
                        state=state,
                    )
                )
            columns.append(column)
    else:
        count = value_reader.varint()
        if count > limits.maximum_total_fields:
            raise FormatError("WKC1 value count exceeds frozen limit")
        column = []
        for _ in range(count):
            size = value_reader.varint()
            if size > limits.maximum_input_bytes:
                raise FormatError("WKC1 value document exceeds frozen limit")
            column.append(
                _read_document(
                    value_reader.read(size),
                    columnarize=columnarize,
                    limits=limits,
                    state=state,
                )
            )
        columns.append(column)
    value_reader.finish()
    return root, schemas, columns, state


def _validate_references(
    root: Document,
    schemas: list[tuple[bytes, bytes]],
    columns: list[list[Document]],
    *,
    columnarize: bool,
) -> None:
    observed: list[tuple[int, ...]] = []
    next_row = [0 for _ in columns]

    def visit(document: Document, depth: int) -> None:
        if depth > MAXIMUM_NESTING_DEPTH:
            raise FormatError("WKC1 reference depth exceeds frozen limit")
        for node in document.nodes:
            if not isinstance(node, TemplateNode):
                continue
            for parameter in node.parameters:
                if parameter.reference is None:
                    raise FormatError("missing WKC1 value reference")
                reference = parameter.reference
                if columnarize:
                    column, row = reference
                    if column >= len(columns) or row >= len(columns[column]):
                        raise FormatError("WKC1 value reference is out of range")
                    if row != next_row[column]:
                        raise FormatError("WKC1 column permutation is noncanonical")
                    if schemas[column] != _schema(parameter, node.name):
                        raise FormatError("WKC1 schema reference differs")
                    value = columns[column][row]
                else:
                    (row,) = reference
                    if row >= len(columns[0]):
                        raise FormatError("WKC1 value reference is out of range")
                    if row != next_row[0]:
                        raise FormatError("WKC1 value order is noncanonical")
                    value = columns[0][row]
                    column = 0
                next_row[column] += 1
                observed.append(reference)
                parameter.value = value
                visit(value, depth + 1)

    visit(root, 0)
    expected = (
        [(column, row) for column in range(len(columns)) for row in range(len(columns[column]))]
        if columnarize
        else [(row,) for row in range(len(columns[0]))]
    )
    if sorted(observed) != expected or len(set(observed)) != len(observed):
        raise FormatError("WKC1 value permutation is not a bijection")


def _reconstruct(document: Document, *, maximum_size: int, depth: int = 0) -> bytes:
    if depth > MAXIMUM_NESTING_DEPTH:
        raise FormatError("WKC1 reconstruction depth exceeds frozen limit")
    output = bytearray()

    def append(value: bytes) -> None:
        if len(value) > maximum_size - len(output):
            raise FormatError("WKC1 reconstruction exceeds declared source size")
        output.extend(value)

    for node in document.nodes:
        if isinstance(node, bytes):
            append(node)
            continue
        append(b"{{")
        append(node.name)
        for parameter in node.parameters:
            append(b"|")
            if parameter.named:
                append(parameter.key)
                append(b"=")
            append(
                _reconstruct(
                    parameter.value,
                    maximum_size=maximum_size - len(output),
                    depth=depth + 1,
                )
            )
        append(b"}}")
    return bytes(output)


def decode(frame: bytes, maximum_size: int) -> bytes:
    if type(maximum_size) is not int or maximum_size < 0:
        raise FormatError("maximum output size must be a nonnegative integer")
    if len(frame) < HEADER.size:
        raise FormatError("truncated WKC1 header")
    (
        magic,
        version,
        kind,
        source_size,
        source_sha256,
        metadata_size,
        values_size,
        declared_templates,
        declared_fields,
    ) = HEADER.unpack(frame[: HEADER.size])
    if magic != MAGIC or version != VERSION or kind not in VARIANTS_BY_KIND:
        raise FormatError("WKC1 header identity differs")
    if source_size > maximum_size or source_size > MAXIMUM_INPUT_BYTES:
        raise FormatError("WKC1 declared source size exceeds limit")
    if metadata_size + values_size != len(frame) - HEADER.size:
        raise FormatError("WKC1 section accounting differs")
    metadata_end = HEADER.size + metadata_size
    metadata = frame[HEADER.size:metadata_end]
    values = frame[metadata_end:]
    columnarize = kind == VARIANTS["wk-c1-full-schema-columns"]
    root, schemas, columns, state = _read_sections(
        metadata,
        values,
        columnarize=columnarize,
        limits=Limits(maximum_input_bytes=maximum_size),
    )
    if state.templates != declared_templates or state.fields != declared_fields:
        raise FormatError("WKC1 declared structure counts differ")
    _validate_references(
        root, schemas, columns, columnarize=columnarize
    )
    restored = _reconstruct(root, maximum_size=source_size)
    if len(restored) != source_size or hashlib.sha256(restored).digest() != source_sha256:
        raise FormatError("WKC1 reconstructed identity differs")
    return restored


def inspect_frame(frame: bytes) -> dict[str, Any]:
    if len(frame) < HEADER.size:
        raise FormatError("truncated WKC1 header")
    (
        magic,
        version,
        kind,
        source_size,
        source_sha256,
        metadata_size,
        values_size,
        templates,
        fields,
    ) = HEADER.unpack(frame[: HEADER.size])
    if magic != MAGIC or kind not in VARIANTS_BY_KIND:
        raise FormatError("WKC1 header identity differs")
    return {
        "magic": magic.decode("ascii"),
        "version": version,
        "variant": VARIANTS_BY_KIND[kind],
        "source_bytes": source_size,
        "source_sha256": source_sha256.hex(),
        "header_bytes": HEADER.size,
        "metadata_bytes": metadata_size,
        "value_stream_bytes": values_size,
        "complete_transform_bytes": len(frame),
        "template_count": templates,
        "field_count": fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    encode_parser = subparsers.add_parser("encode")
    encode_parser.add_argument("variant", choices=VARIANTS)
    encode_parser.add_argument("source", type=Path)
    encode_parser.add_argument("destination", type=Path)
    decode_parser = subparsers.add_parser("decode")
    decode_parser.add_argument("source", type=Path)
    decode_parser.add_argument("destination", type=Path)
    decode_parser.add_argument("--maximum-size", type=int, required=True)
    info_parser = subparsers.add_parser("info")
    info_parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "encode":
            args.destination.write_bytes(encode(args.source.read_bytes(), args.variant))
        elif args.command == "decode":
            args.destination.write_bytes(
                decode(args.source.read_bytes(), args.maximum_size)
            )
        else:
            print(json.dumps(inspect_frame(args.source.read_bytes()), sort_keys=True))
    except (OSError, FormatError) as error:
        raise SystemExit(f"WK-C1 transform failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
