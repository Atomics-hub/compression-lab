#!/usr/bin/env python3
"""Build a canonical, extraction-free inventory of a GDB1 runtime archive."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import tarfile
from typing import Any


LICENSE_TOKENS = ("license", "copying", "copyright")
MACHO_DYLIB_COMMANDS = {0xC, 0x20, 0x80000018, 0x8000001F, 0x80000023}
PT_LOAD = 1
PT_DYNAMIC = 2
DT_NULL = 0
DT_NEEDED = 1
DT_STRTAB = 5
DT_STRSZ = 10
MACHO_MAGICS = {
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path.name} must be an ordinary file")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"{path.name} is not canonical JSON")
    return raw, value


def safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or path.parts[0] != "python"
    ):
        raise ValueError(f"unsafe runtime archive member: {name!r}")
    return path


def safe_link_target(
    member: PurePosixPath, target: str, *, archive_root_relative: bool = False
) -> None:
    link = PurePosixPath(target)
    if not target or link.is_absolute() or "\\" in target:
        raise ValueError(f"unsafe runtime archive link: {member}")
    resolved: list[str] = [] if archive_root_relative else list(member.parent.parts)
    for part in link.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved:
                raise ValueError(f"runtime archive link escapes root: {member}")
            resolved.pop()
        else:
            resolved.append(part)
    if not resolved or resolved[0] != "python":
        raise ValueError(f"runtime archive link escapes python root: {member}")


def macho_dependencies(value: bytes) -> list[str] | None:
    if len(value) < 32 or value[:4] != b"\xcf\xfa\xed\xfe":
        if value[:4] in MACHO_MAGICS:
            raise ValueError("runtime Mach-O must be thin 64-bit little-endian")
        return None
    _magic, _cpu, _subcpu, _filetype, commands, command_bytes, _flags, _reserved = (
        struct.unpack_from("<IiiIIIII", value, 0)
    )
    if commands > 65_536 or command_bytes > len(value) - 32:
        raise ValueError("malformed Mach-O load-command bounds")
    offset = 32
    dependencies: list[str] = []
    for _ in range(commands):
        if offset + 8 > len(value):
            raise ValueError("truncated Mach-O load command")
        command, size = struct.unpack_from("<II", value, offset)
        if size < 8 or size % 8 != 0 or offset + size > len(value):
            raise ValueError("malformed Mach-O load command")
        if command in MACHO_DYLIB_COMMANDS:
            if size < 24:
                raise ValueError("truncated Mach-O dylib command")
            name_offset = struct.unpack_from("<I", value, offset + 8)[0]
            if name_offset < 24 or name_offset >= size:
                raise ValueError("malformed Mach-O dylib name")
            start = offset + name_offset
            end = value.find(b"\0", start, offset + size)
            if end < 0:
                raise ValueError("unterminated Mach-O dylib name")
            dependency = value[start:end].decode("utf-8")
            if not dependency:
                raise ValueError("empty Mach-O dylib name")
            dependencies.append(dependency)
        offset += size
    if offset != 32 + command_bytes:
        raise ValueError("Mach-O load-command size differs")
    return sorted(set(dependencies))


def elf_dependencies(value: bytes) -> list[str] | None:
    if len(value) < 64 or value[:4] != b"\x7fELF":
        return None
    if value[4] != 2 or value[5] != 1:
        raise ValueError("runtime ELF must be 64-bit little-endian")
    program_offset = struct.unpack_from("<Q", value, 32)[0]
    program_size = struct.unpack_from("<H", value, 54)[0]
    program_count = struct.unpack_from("<H", value, 56)[0]
    if (
        program_size < 56
        or program_count > 65_536
        or program_offset + program_size * program_count > len(value)
    ):
        raise ValueError("malformed ELF program-header bounds")
    loads: list[tuple[int, int, int, int]] = []
    dynamic: tuple[int, int] | None = None
    for index in range(program_count):
        offset = program_offset + index * program_size
        kind = struct.unpack_from("<I", value, offset)[0]
        file_offset, virtual_address, _physical_address, file_size, memory_size = (
            struct.unpack_from("<QQQQQ", value, offset + 8)
        )
        if file_offset + file_size > len(value):
            raise ValueError("ELF segment exceeds file")
        if kind == PT_LOAD:
            loads.append((virtual_address, file_offset, file_size, memory_size))
        elif kind == PT_DYNAMIC:
            dynamic = (file_offset, file_size)
    if dynamic is None:
        return []
    string_address: int | None = None
    string_size: int | None = None
    needed_offsets: list[int] = []
    start, size = dynamic
    if size % 16 != 0:
        raise ValueError("malformed ELF dynamic table")
    terminated = False
    for offset in range(start, start + size, 16):
        tag, entry = struct.unpack_from("<QQ", value, offset)
        if tag == DT_NULL:
            terminated = True
            break
        if tag == DT_NEEDED:
            needed_offsets.append(entry)
        elif tag == DT_STRTAB:
            string_address = entry
        elif tag == DT_STRSZ:
            string_size = entry
    if not terminated:
        raise ValueError("ELF dynamic table is not terminated")
    if needed_offsets and (string_address is None or string_size is None):
        raise ValueError("ELF dynamic table lacks string-table bounds")
    if string_address is None:
        return []
    if string_size is None:
        string_size = 0
    string_chunks: list[bytes] = []
    cursor = string_address
    remaining = string_size
    while remaining:
        mapped = False
        for virtual_address, file_offset, file_size, _memory_size in loads:
            if virtual_address <= cursor < virtual_address + file_size:
                relative_offset = cursor - virtual_address
                take = min(remaining, file_size - relative_offset)
                start = file_offset + relative_offset
                string_chunks.append(value[start : start + take])
                cursor += take
                remaining -= take
                mapped = True
                break
        if not mapped:
            raise ValueError("ELF string table is not fully file-backed")
    string_table = b"".join(string_chunks)
    dependencies = []
    for relative in needed_offsets:
        if relative >= string_size:
            raise ValueError("ELF needed string is out of bounds")
        end = string_table.find(b"\0", relative)
        if end < 0:
            raise ValueError("unterminated ELF needed string")
        dependency = string_table[relative:end].decode("utf-8")
        if not dependency:
            raise ValueError("empty ELF needed string")
        dependencies.append(dependency)
    return sorted(set(dependencies))


def native_dependencies(value: bytes) -> tuple[str, list[str]] | None:
    macho = macho_dependencies(value)
    if macho is not None:
        return "mach-o-64-little", macho
    elf = elf_dependencies(value)
    if elf is not None:
        return "elf-64-little", elf
    return None


def digest_records(records: list[dict[str, Any]]) -> str:
    return sha256_bytes(b"".join(json_bytes(record) for record in records))


def inventory(
    archive: Path,
    *,
    target_id: str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("runtime archive must be an ordinary file")
    archive_raw = archive.read_bytes()
    archive_sha256 = sha256_bytes(archive_raw)
    if expected_size is not None and len(archive_raw) != expected_size:
        raise ValueError("runtime archive size differs")
    if expected_sha256 is not None and archive_sha256 != expected_sha256:
        raise ValueError("runtime archive SHA-256 differs")
    records: list[dict[str, Any]] = []
    native_records: list[dict[str, Any]] = []
    license_records: list[dict[str, Any]] = []
    observed: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as tar:
            for member in tar:
                path = safe_member_path(member.name)
                name = path.as_posix()
                if name in observed:
                    raise ValueError(f"duplicate runtime archive member: {name}")
                observed.add(name)
                base = {
                    "mode": member.mode & 0o7777,
                    "path": name,
                }
                if member.isdir():
                    record = {**base, "type": "directory"}
                elif member.isfile():
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        raise ValueError(f"runtime member has no bytes: {name}")
                    value = extracted.read(member.size + 1)
                    if len(value) != member.size:
                        raise ValueError(f"runtime member size differs: {name}")
                    record = {
                        **base,
                        "bytes": len(value),
                        "sha256": sha256_bytes(value),
                        "type": "file",
                    }
                    native = native_dependencies(value)
                    if native is None and name.endswith((".so", ".dylib")):
                        raise ValueError(f"unrecognized runtime native object: {name}")
                    if native is not None:
                        native_records.append(
                            {
                                "dependencies": native[1],
                                "format": native[0],
                                "path": name,
                                "sha256": record["sha256"],
                            }
                        )
                    lowered = name.lower()
                    if any(token in PurePosixPath(lowered).name for token in LICENSE_TOKENS):
                        license_records.append(
                            {
                                "bytes": len(value),
                                "path": name,
                                "sha256": record["sha256"],
                            }
                        )
                elif member.issym() or member.islnk():
                    safe_link_target(
                        path,
                        member.linkname,
                        archive_root_relative=member.islnk(),
                    )
                    record = {
                        **base,
                        "target": member.linkname,
                        "type": "symlink" if member.issym() else "hardlink",
                    }
                else:
                    raise ValueError(f"unsupported runtime archive member type: {name}")
                records.append(record)
    except tarfile.TarError as error:
        raise ValueError("runtime archive is not a valid gzip tar") from error
    records.sort(key=lambda row: row["path"].encode())
    native_records.sort(key=lambda row: row["path"].encode())
    license_records.sort(key=lambda row: row["path"].encode())
    stdlib = [
        row
        for row in records
        if row["path"].startswith("python/lib/python3.12/")
        and not row["path"].startswith("python/lib/python3.12/site-packages/")
    ]
    regular = [row for row in records if row["type"] == "file"]
    external_dependencies = sorted(
        {dependency for row in native_records for dependency in row["dependencies"]}
    )
    critical_paths = [
        "python/bin/python3.12",
        "python/lib/python3.12/LICENSE.txt",
    ]
    critical = {row["path"]: row for row in records if row["path"] in critical_paths}
    if set(critical) != set(critical_paths):
        raise ValueError("runtime archive lacks a critical interpreter member")
    return {
        "archive": {
            "filename": archive.name,
            "sha256": archive_sha256,
            "size_bytes": len(archive_raw),
        },
        "claim_ceiling": "Runtime distribution identity only; no corpus access or measurement.",
        "critical_members": critical,
        "external_system_dependencies": external_dependencies,
        "inventory": {
            "directory_count": sum(row["type"] == "directory" for row in records),
            "hardlink_count": sum(row["type"] == "hardlink" for row in records),
            "manifest_sha256": digest_records(records),
            "member_count": len(records),
            "regular_file_bytes": sum(row["bytes"] for row in regular),
            "regular_file_count": len(regular),
            "symlink_count": sum(row["type"] == "symlink" for row in records),
        },
        "licenses": {
            "manifest_sha256": digest_records(license_records),
            "members": license_records,
        },
        "name": "source-python-gdb1-runtime-inventory-v1",
        "native": {
            "manifest_sha256": digest_records(native_records),
            "object_count": len(native_records),
            "records": native_records,
        },
        "schema_version": 1,
        "stdlib": {
            "manifest_sha256": digest_records(stdlib),
            "member_count": len(stdlib),
            "regular_file_bytes": sum(
                row["bytes"] for row in stdlib if row["type"] == "file"
            ),
        },
        "target_id": target_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--expected-size", type=int)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = inventory(
            args.archive,
            target_id=args.target_id,
            expected_size=args.expected_size,
            expected_sha256=args.expected_sha256,
        )
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"GDB1 runtime inventory failed: {error}") from error
    raw = json_bytes(result)
    if args.output is None:
        print(raw.decode(), end="")
    else:
        if args.output.is_symlink() or args.output.exists():
            raise SystemExit("GDB1 runtime inventory output already exists or is a symlink")
        args.output.write_bytes(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
