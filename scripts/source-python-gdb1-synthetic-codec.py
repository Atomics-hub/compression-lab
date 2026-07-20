#!/usr/bin/env python3
"""Corpus-disabled AXPG1 A0/A1/A2 reference codec for synthetic fixtures."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import keyword
from pathlib import PurePosixPath
import struct
import token
import tokenize


MAGIC = b"AXPG1\0"
ARMS = {
    "a0-token-trivia-range": 0,
    "a1-flat-identifiers": 1,
    "a2-scope-bindings": 2,
}
ARM_IDS = {value: key for key, value in ARMS.items()}
TOP = 1 << 24
BOTTOM = 1 << 16
MASK = (1 << 32) - 1
MODEL_LIMIT = 16_384
MAX_HEADER_BYTES = 16 * 1024 * 1024
MAX_STREAM_BYTES = 1 << 32
MAX_FILES = 1_000_000


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def put_uint(value: int) -> bytes:
    if type(value) is not int or value < 0 or value >= 1 << 64:
        raise ValueError("unsigned integer is outside uint64")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def get_uint(raw: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(raw):
            raise ValueError("truncated unsigned integer")
        byte = raw[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            if put_uint(value) != raw[offset - (shift // 7 + 1) : offset]:
                raise ValueError("noncanonical unsigned integer")
            return value, offset
    raise ValueError("unsigned integer exceeds uint64")


class AdaptiveBytes:
    def __init__(self) -> None:
        self.counts = [1] * 256
        self.total = 256

    def interval(self, symbol: int) -> tuple[int, int, int]:
        return sum(self.counts[:symbol]), self.counts[symbol], self.total

    def symbol(self, count: int) -> tuple[int, int, int]:
        cumulative = 0
        for symbol, frequency in enumerate(self.counts):
            if count < cumulative + frequency:
                return symbol, cumulative, frequency
            cumulative += frequency
        raise ValueError("range-coded count is outside the model")

    def update(self, symbol: int) -> None:
        self.counts[symbol] += 1
        self.total += 1
        if self.total >= MODEL_LIMIT:
            self.counts = [(count + 1) // 2 for count in self.counts]
            self.total = sum(self.counts)


def range_encode(raw: bytes) -> bytes:
    if not raw:
        return b""
    low = 0
    width = MASK
    output = bytearray()
    cache = 0
    cache_size = 1
    model = AdaptiveBytes()

    def shift_low() -> None:
        nonlocal low, cache, cache_size
        carry = low >> 32
        low32 = low & MASK
        if low32 < 0xFF000000 or carry != 0:
            pending = cache
            while cache_size:
                output.append((pending + carry) & 0xFF)
                pending = 0xFF
                cache_size -= 1
            cache = (low32 >> 24) & 0xFF
        cache_size += 1
        low = (low32 << 8) & MASK

    for symbol in raw:
        cumulative, frequency, total = model.interval(symbol)
        unit = width // total
        if unit == 0:
            raise ValueError("range coder interval collapsed")
        low += cumulative * unit
        width = unit * frequency
        while width < TOP:
            width = (width << 8) & MASK
            shift_low()
        model.update(symbol)
    for _ in range(5):
        shift_low()
    return bytes(output)


def range_decode(coded: bytes, raw_size: int) -> bytes:
    if raw_size == 0:
        if coded:
            raise ValueError("empty stream has coded bytes")
        return b""
    if len(coded) < 5:
        raise ValueError("truncated range-coded stream")
    cursor = 5
    code = int.from_bytes(coded[:5], "big") & MASK
    width = MASK
    output = bytearray()
    model = AdaptiveBytes()
    for _ in range(raw_size):
        unit = width // model.total
        if unit == 0:
            raise ValueError("range decoder interval collapsed")
        count = code // unit
        if count >= model.total:
            raise ValueError("range-coded count exceeds model total")
        symbol, cumulative, frequency = model.symbol(count)
        output.append(symbol)
        code = (code - cumulative * unit) & MASK
        width = unit * frequency
        while width < TOP:
            next_byte = coded[cursor] if cursor < len(coded) else 0
            cursor += cursor < len(coded)
            code = ((code << 8) | next_byte) & MASK
            width = (width << 8) & MASK
        model.update(symbol)
    if cursor < len(coded):
        raise ValueError("range-coded stream has unexplained trailing bytes")
    return bytes(output)


@dataclass(frozen=True)
class SourceToken:
    kind: int
    spelling: bytes
    trivia: bytes


@dataclass(frozen=True)
class ScopeUse:
    scope: int
    parent: int | None
    binding: bool
    unresolved: bool = False


def is_identifier(part: SourceToken) -> bool:
    if part.kind != token.NAME:
        return False
    try:
        return not keyword.iskeyword(part.spelling.decode("utf-8"))
    except UnicodeDecodeError:
        return True


def _line_offsets(data: bytes, encoding: str) -> tuple[list[int], list[str], int]:
    bom = 3 if encoding.lower().replace("_", "-") == "utf-8-sig" else 0
    codec = "utf-8" if bom else encoding
    body = data[bom:]
    raw_lines = body.splitlines(keepends=True)
    if not raw_lines or (body and not raw_lines[-1]):
        raw_lines.append(b"")
    decoded = [line.decode(codec) for line in raw_lines]
    offsets: list[int] = []
    cursor = bom
    for line in raw_lines:
        offsets.append(cursor)
        cursor += len(line)
    return offsets, decoded, bom


def tokenize_exact(data: bytes) -> list[SourceToken]:
    encoding, _lines = tokenize.detect_encoding(io.BytesIO(data).readline)
    offsets, decoded, bom = _line_offsets(data, encoding)
    codec = "utf-8" if bom else encoding

    def position(row: int, column: int) -> int:
        if row < 1 or row > len(decoded) or column < 0 or column > len(decoded[row - 1]):
            raise ValueError("token position is outside decoded source")
        return offsets[row - 1] + len(decoded[row - 1][:column].encode(codec))

    cursor = 0
    output: list[SourceToken] = []
    for item in tokenize.tokenize(io.BytesIO(data).readline):
        if item.type in (token.ENCODING, token.ENDMARKER):
            continue
        start = position(*item.start)
        end = position(*item.end)
        if start < cursor or end < start:
            raise ValueError("overlapping token positions")
        output.append(SourceToken(item.type, data[start:end], data[cursor:start]))
        cursor = end
    output.append(SourceToken(token.ENDMARKER, b"", data[cursor:]))
    if b"".join(part.trivia + part.spelling for part in output) != data:
        raise ValueError("token/trivia partition is not byte exact")
    return output


def add_blob(output: bytearray, value: bytes) -> None:
    output.extend(put_uint(len(value)))
    output.extend(value)


def take_blob(raw: bytes, offset: int, maximum: int) -> tuple[bytes, int]:
    size, offset = get_uint(raw, offset)
    if size > maximum or offset + size > len(raw):
        raise ValueError("length-delimited value is out of bounds")
    return raw[offset : offset + size], offset + size


def encode_flat_identifiers(tokens: list[SourceToken]) -> tuple[bytes, bytes, bytes]:
    spellings = bytearray()
    lexicon = bytearray()
    occurrences = bytearray()
    seen: dict[bytes, int] = {}
    mtf: list[int] = []
    for part in tokens:
        if not is_identifier(part):
            add_blob(spellings, part.spelling)
            continue
        lexicon_id = seen.get(part.spelling)
        if lexicon_id is None:
            lexicon_id = len(seen)
            seen[part.spelling] = lexicon_id
            add_blob(lexicon, part.spelling)
            occurrences.extend(put_uint(0))
            occurrences.extend(put_uint(lexicon_id))
            mtf.insert(0, lexicon_id)
        else:
            rank = mtf.index(lexicon_id)
            occurrences.extend(put_uint(1))
            occurrences.extend(put_uint(rank))
            mtf.pop(rank)
            mtf.insert(0, lexicon_id)
    return bytes(spellings), bytes(lexicon), bytes(occurrences)


def encode_scoped_identifiers(
    tokens: list[SourceToken], uses: list[ScopeUse]
) -> tuple[bytes, bytes, bytes]:
    names = [part for part in tokens if is_identifier(part)]
    if len(names) != len(uses):
        raise ValueError("A2 scope plan count differs from identifier count")
    spellings = bytearray()
    lexicon = bytearray()
    occurrences = bytearray()
    lexicon_ids: dict[bytes, int] = {}
    parents: dict[int, int | None] = {0: None}
    tables: dict[int, list[int]] = {0: []}
    use_cursor = 0
    for part in tokens:
        if not is_identifier(part):
            add_blob(spellings, part.spelling)
            continue
        use = uses[use_cursor]
        use_cursor += 1
        if use.scope <= 0 or use.parent == use.scope:
            raise ValueError("invalid A2 lexical scope")
        if use.scope not in parents:
            if use.parent not in parents:
                raise ValueError("A2 scope parent is not yet declared")
            parents[use.scope] = use.parent
            tables[use.scope] = []
            occurrences.extend(put_uint(use.scope))
            occurrences.extend(put_uint((use.parent or 0) + 1))
        else:
            if parents[use.scope] != use.parent:
                raise ValueError("A2 scope parent changed")
            occurrences.extend(put_uint(use.scope))
            occurrences.extend(put_uint(0))
        lexicon_id = lexicon_ids.get(part.spelling)
        if lexicon_id is None:
            lexicon_id = len(lexicon_ids)
            lexicon_ids[part.spelling] = lexicon_id
            add_blob(lexicon, part.spelling)
        current = tables[use.scope]
        if use.unresolved:
            table = tables[0]
            if lexicon_id in table:
                rank = table.index(lexicon_id)
                occurrences.extend(put_uint(1))  # FREE
                occurrences.extend(put_uint(1))  # module-free selector
                occurrences.extend(put_uint(rank))
                table.pop(rank)
            else:
                occurrences.extend(put_uint(0))  # NEW
                occurrences.extend(put_uint(1))  # module-free selector
                occurrences.extend(put_uint(lexicon_id))
            table.insert(0, lexicon_id)
        elif use.binding:
            if lexicon_id in current:
                rank = current.index(lexicon_id)
                occurrences.extend(put_uint(2))  # MTF
                occurrences.extend(put_uint(rank))
                current.pop(rank)
            else:
                occurrences.extend(put_uint(0))  # NEW
                occurrences.extend(put_uint(0))  # current selector
                occurrences.extend(put_uint(lexicon_id))
            current.insert(0, lexicon_id)
        else:
            target_scope: int | None = use.scope
            distance = 0
            while target_scope is not None and lexicon_id not in tables[target_scope]:
                target_scope = parents[target_scope]
                distance += 1
            if target_scope is None:
                raise ValueError("resolved A2 name has no lexical binding")
            table = tables[target_scope]
            rank = table.index(lexicon_id)
            if distance == 0:
                occurrences.extend(put_uint(2))  # MTF
                occurrences.extend(put_uint(rank))
            else:
                occurrences.extend(put_uint(1))  # FREE
                occurrences.extend(put_uint(0))  # ancestor selector
                occurrences.extend(put_uint(distance))
                occurrences.extend(put_uint(rank))
            table.pop(rank)
            table.insert(0, lexicon_id)
    return bytes(spellings), bytes(lexicon), bytes(occurrences)


def decode_lexicon(raw: bytes) -> list[bytes]:
    output = []
    offset = 0
    while offset < len(raw):
        value, offset = take_blob(raw, offset, 1 << 20)
        output.append(value)
    return output


def decode_flat_occurrences(raw: bytes, lexicon: list[bytes], count: int) -> list[bytes]:
    output = []
    mtf: list[int] = []
    offset = 0
    for _ in range(count):
        event, offset = get_uint(raw, offset)
        value, offset = get_uint(raw, offset)
        if event == 0:
            if value != len(mtf) or value >= len(lexicon):
                raise ValueError("noncanonical A1 NEW event")
            lexicon_id = value
        elif event == 1 and value < len(mtf):
            lexicon_id = mtf.pop(value)
        else:
            raise ValueError("invalid A1 occurrence event")
        mtf.insert(0, lexicon_id)
        output.append(lexicon[lexicon_id])
    if offset != len(raw) or len(mtf) != len(lexicon):
        raise ValueError("A1 occurrence stream is incomplete")
    return output


def decode_scoped_occurrences(raw: bytes, lexicon: list[bytes], count: int) -> list[bytes]:
    output = []
    parents: dict[int, int | None] = {0: None}
    tables: dict[int, list[int]] = {0: []}
    offset = 0
    for _ in range(count):
        scope, offset = get_uint(raw, offset)
        parent_declaration, offset = get_uint(raw, offset)
        if scope == 0:
            raise ValueError("A2 occurrence cannot use module-free as current scope")
        if scope not in parents:
            if parent_declaration == 0:
                raise ValueError("A2 scope lacks first parent declaration")
            parent = parent_declaration - 1
            if parent not in parents or parent == scope:
                raise ValueError("invalid A2 parent declaration")
            parents[scope] = parent
            tables[scope] = []
        elif parent_declaration != 0:
            raise ValueError("duplicate A2 parent declaration")
        event, offset = get_uint(raw, offset)
        if event == 0:  # NEW
            selector, offset = get_uint(raw, offset)
            lexicon_id, offset = get_uint(raw, offset)
            event_target = 0 if selector == 1 else scope if selector == 0 else -1
            if (
                event_target < 0
                or lexicon_id >= len(lexicon)
                or lexicon_id in tables[event_target]
            ):
                raise ValueError("invalid A2 NEW event")
            tables[event_target].insert(0, lexicon_id)
        elif event == 1:  # FREE
            selector, offset = get_uint(raw, offset)
            if selector == 1:
                free_target: int | None = 0
            elif selector == 0:
                distance, offset = get_uint(raw, offset)
                if distance == 0:
                    raise ValueError("A2 FREE ancestor distance must be positive")
                free_target = scope
                for _ in range(distance):
                    free_target = parents.get(free_target)
                    if free_target is None:
                        raise ValueError("A2 FREE escapes lexical ancestors")
            else:
                raise ValueError("invalid A2 FREE selector")
            rank, offset = get_uint(raw, offset)
            if free_target is None:
                raise ValueError("A2 FREE target is missing")
            if rank >= len(tables[free_target]):
                raise ValueError("A2 FREE rank is out of bounds")
            lexicon_id = tables[free_target].pop(rank)
            tables[free_target].insert(0, lexicon_id)
        elif event == 2:  # MTF
            rank, offset = get_uint(raw, offset)
            if rank >= len(tables[scope]):
                raise ValueError("A2 MTF rank is out of bounds")
            lexicon_id = tables[scope].pop(rank)
            tables[scope].insert(0, lexicon_id)
        else:
            raise ValueError("invalid A2 occurrence event")
        output.append(lexicon[lexicon_id])
    if offset != len(raw):
        raise ValueError("A2 occurrence stream has trailing bytes")
    return output


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("unsafe synthetic bundle path")
    encoded = value.encode("utf-8")
    if encoded.decode("utf-8") != value:
        raise ValueError("noncanonical synthetic bundle path")
    return value


def encode(
    files: list[tuple[str, int, bytes]],
    arm: str,
    scope_plans: dict[str, list[ScopeUse]] | None = None,
) -> bytes:
    if arm not in ARMS or len(files) > MAX_FILES:
        raise ValueError("invalid arm or file count")
    if [safe_path(path) for path, _mode, _data in files] != sorted(
        path for path, _mode, _data in files
    ):
        raise ValueError("synthetic files must be unique and byte-lexicographically sorted")
    streams: dict[str, bytearray] = {
        "token_kinds": bytearray(),
        "spellings": bytearray(),
        "trivia": bytearray(),
        "identifier_lexicon": bytearray(),
        "identifier_occurrences": bytearray(),
        "raw_fallback": bytearray(),
    }
    manifest = []
    for path, mode, data in files:
        if type(mode) is not int or mode < 0 or mode > 0o7777 or len(data) > 134_217_728:
            raise ValueError("synthetic file mode or size exceeds AXPG1 limits")
        fallback_reason: str | None = None
        try:
            parts = tokenize_exact(data)
            if sum(is_identifier(part) for part in parts) > 16_777_216:
                raise ValueError("identifier limit exceeded")
            local_kinds = b"".join(
                put_uint((part.kind << 1) | is_identifier(part)) for part in parts
            )
            local_trivia = bytearray()
            for part in parts:
                add_blob(local_trivia, part.trivia)
            if arm == "a0-token-trivia-range":
                spelling_buffer = bytearray()
                for part in parts:
                    add_blob(spelling_buffer, part.spelling)
                local_spellings = bytes(spelling_buffer)
                local_lexicon = b""
                local_occurrences = b""
            elif arm == "a1-flat-identifiers":
                local_spellings, local_lexicon, local_occurrences = encode_flat_identifiers(parts)
            else:
                if scope_plans is None or path not in scope_plans:
                    raise ValueError("A2 synthetic scope plan is missing")
                local_spellings, local_lexicon, local_occurrences = encode_scoped_identifiers(
                    parts, scope_plans[path]
                )
        except (IndentationError, LookupError, SyntaxError, tokenize.TokenError, UnicodeError, ValueError) as error:
            fallback_reason = type(error).__name__
        offsets = {name: len(value) for name, value in streams.items()}
        if fallback_reason is not None:
            add_blob(streams["raw_fallback"], data)
            counts = {name: 0 for name in streams}
            counts["raw_fallback"] = len(streams["raw_fallback"]) - offsets["raw_fallback"]
            token_count = 0
            identifier_count = 0
            mode_name = "raw"
        else:
            locals_by_name = {
                "token_kinds": local_kinds,
                "spellings": local_spellings,
                "trivia": bytes(local_trivia),
                "identifier_lexicon": local_lexicon,
                "identifier_occurrences": local_occurrences,
            }
            for name, value in locals_by_name.items():
                streams[name].extend(value)
            counts = {name: len(value) for name, value in locals_by_name.items()}
            counts["raw_fallback"] = 0
            token_count = len(parts)
            identifier_count = sum(is_identifier(part) for part in parts)
            mode_name = "tokenized"
        manifest.append(
            {
                "bytes": len(data),
                "fallback_reason": fallback_reason,
                "identifier_count": identifier_count,
                "mode": mode_name,
                "path": path,
                "permissions": mode,
                "sha256": sha256(data),
                "stream_bytes": counts,
                "stream_offsets": offsets,
                "token_count": token_count,
            }
        )
    directory = []
    payload = bytearray()
    for name in streams:
        raw = bytes(streams[name])
        coded = range_encode(raw)
        directory.append(
            {
                "coded_bytes": len(coded),
                "coded_sha256": sha256(coded),
                "name": name,
                "raw_bytes": len(raw),
                "raw_sha256": sha256(raw),
            }
        )
        payload.extend(coded)
    header = {
        "arm": arm,
        "coder": "axiom-int-range-v1",
        "dependency_lock_sha256": "d31eda5ed923263a7a76f5a3d85cbf35a9e26b78bd3f8cdd7f627863e9f65108",
        "files": manifest,
        "format": "AXPG1",
        "measurement_authorized": False,
        "parser": "LibCST-1.8.6-synthetic-scope-plan",
        "schema_version": 1,
        "streams": directory,
        "synthetic_only": True,
    }
    header_raw = json_bytes(header)
    return MAGIC + bytes([ARMS[arm]]) + struct.pack(">I", len(header_raw)) + header_raw + payload


def decode(archive: bytes) -> list[tuple[str, int, bytes]]:
    if len(archive) < len(MAGIC) + 5 or archive[: len(MAGIC)] != MAGIC:
        raise ValueError("AXPG1 magic differs")
    arm_number = archive[len(MAGIC)]
    if arm_number not in ARM_IDS:
        raise ValueError("AXPG1 arm is unknown")
    header_size = struct.unpack_from(">I", archive, len(MAGIC) + 1)[0]
    header_start = len(MAGIC) + 5
    if header_size > MAX_HEADER_BYTES or header_start + header_size > len(archive):
        raise ValueError("AXPG1 header is out of bounds")
    header_raw = archive[header_start : header_start + header_size]
    header = json.loads(header_raw)
    if not isinstance(header, dict) or json_bytes(header) != header_raw:
        raise ValueError("AXPG1 header is not canonical JSON")
    if (
        header.get("arm") != ARM_IDS[arm_number]
        or header.get("format") != "AXPG1"
        or header.get("coder") != "axiom-int-range-v1"
        or header.get("synthetic_only") is not True
        or header.get("measurement_authorized") is not False
    ):
        raise ValueError("AXPG1 header identity differs")
    cursor = header_start + header_size
    streams: dict[str, bytes] = {}
    expected_names = [
        "token_kinds",
        "spellings",
        "trivia",
        "identifier_lexicon",
        "identifier_occurrences",
        "raw_fallback",
    ]
    rows = header.get("streams")
    if not isinstance(rows, list) or [row.get("name") for row in rows] != expected_names:
        raise ValueError("AXPG1 stream directory differs")
    for row in rows:
        coded_size = row.get("coded_bytes")
        raw_size = row.get("raw_bytes")
        if (
            type(coded_size) is not int
            or type(raw_size) is not int
            or coded_size < 0
            or raw_size < 0
            or coded_size > MAX_STREAM_BYTES
            or raw_size > MAX_STREAM_BYTES
            or cursor + coded_size > len(archive)
        ):
            raise ValueError("AXPG1 stream size is out of bounds")
        coded = archive[cursor : cursor + coded_size]
        cursor += coded_size
        if sha256(coded) != row.get("coded_sha256"):
            raise ValueError("AXPG1 coded stream hash differs")
        raw = range_decode(coded, raw_size)
        if sha256(raw) != row.get("raw_sha256"):
            raise ValueError("AXPG1 raw stream hash differs")
        streams[row["name"]] = raw
    if cursor != len(archive):
        raise ValueError("AXPG1 archive has trailing bytes")
    files = header.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError("AXPG1 file manifest differs")
    positions = {name: 0 for name in expected_names}
    output = []
    previous_path: str | None = None
    for record in files:
        path = safe_path(record.get("path"))
        if previous_path is not None and path <= previous_path:
            raise ValueError("AXPG1 file order differs")
        previous_path = path
        counts = record.get("stream_bytes")
        offsets = record.get("stream_offsets")
        if not isinstance(counts, dict) or not isinstance(offsets, dict):
            raise ValueError("AXPG1 file stream map differs")
        pieces = {}
        for name in expected_names:
            count = counts.get(name)
            if type(count) is not int or count < 0 or offsets.get(name) != positions[name]:
                raise ValueError("AXPG1 file stream offset differs")
            end = positions[name] + count
            if end > len(streams[name]):
                raise ValueError("AXPG1 file stream slice is out of bounds")
            pieces[name] = streams[name][positions[name] : end]
            positions[name] = end
        if record.get("mode") == "raw":
            data, end = take_blob(pieces["raw_fallback"], 0, 134_217_728)
            if end != len(pieces["raw_fallback"]):
                raise ValueError("AXPG1 raw fallback has trailing bytes")
        elif record.get("mode") == "tokenized":
            token_count = record.get("token_count")
            identifier_count = record.get("identifier_count")
            if type(token_count) is not int or type(identifier_count) is not int:
                raise ValueError("AXPG1 token counts differ")
            kinds: list[tuple[int, bool]] = []
            offset = 0
            for _ in range(token_count):
                kind_record, offset = get_uint(pieces["token_kinds"], offset)
                kinds.append((kind_record >> 1, bool(kind_record & 1)))
            if offset != len(pieces["token_kinds"]):
                raise ValueError("AXPG1 token-kind stream has trailing bytes")
            trivia = []
            offset = 0
            for _ in range(token_count):
                value, offset = take_blob(pieces["trivia"], offset, 134_217_728)
                trivia.append(value)
            if offset != len(pieces["trivia"]):
                raise ValueError("AXPG1 trivia stream has trailing bytes")
            if arm_number == 0:
                spellings = []
                offset = 0
                for _ in range(token_count):
                    value, offset = take_blob(pieces["spellings"], offset, 134_217_728)
                    spellings.append(value)
                if offset != len(pieces["spellings"]):
                    raise ValueError("AXPG1 A0 spelling stream has trailing bytes")
                identifiers: list[bytes] = []
            else:
                lexicon = decode_lexicon(pieces["identifier_lexicon"])
                identifiers = (
                    decode_flat_occurrences(
                        pieces["identifier_occurrences"], lexicon, identifier_count
                    )
                    if arm_number == 1
                    else decode_scoped_occurrences(
                        pieces["identifier_occurrences"], lexicon, identifier_count
                    )
                )
                spellings = []
                spelling_offset = 0
                identifier_offset = 0
                for _kind, identifier in kinds:
                    if identifier:
                        if identifier_offset >= len(identifiers):
                            raise ValueError("AXPG1 identifier count is short")
                        spellings.append(identifiers[identifier_offset])
                        identifier_offset += 1
                    else:
                        value, spelling_offset = take_blob(
                            pieces["spellings"], spelling_offset, 134_217_728
                        )
                        spellings.append(value)
                if spelling_offset != len(pieces["spellings"]) or identifier_offset != len(identifiers):
                    raise ValueError("AXPG1 spelling streams have trailing bytes")
            data = b"".join(gap + spelling for gap, spelling in zip(trivia, spellings))
        else:
            raise ValueError("AXPG1 file mode differs")
        if len(data) != record.get("bytes") or sha256(data) != record.get("sha256"):
            raise ValueError("AXPG1 reconstructed file identity differs")
        permissions = record.get("permissions")
        if type(permissions) is not int or permissions < 0 or permissions > 0o7777:
            raise ValueError("AXPG1 file permissions differ")
        output.append((path, permissions, data))
    if any(positions[name] != len(streams[name]) for name in expected_names):
        raise ValueError("AXPG1 unclaimed stream bytes remain")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        raise SystemExit("This reference codec is corpus-disabled; use --self-test only.")
    fixture = [("fixture.py", 0o644, b"x = 1\nprint(x)\n")]
    for arm in ("a0-token-trivia-range", "a1-flat-identifiers"):
        if decode(encode(fixture, arm)) != fixture:
            raise SystemExit(f"{arm} self-test failed")
    print("AXPG1 synthetic A0/A1 self-test passed; corpus access remains disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
