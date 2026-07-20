from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
CONTRACT = REPOSITORY / "config" / "source-python-gdb1-runtime-distribution-v1.json"
CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
DEPENDENCY_LOCK = REPOSITORY / "config" / "source-python-gdb1-dependency-lock-v1.json"
INVENTORY_SCRIPT = REPOSITORY / "scripts" / "inventory-source-python-gdb1-runtime.py"
VERIFY_SCRIPT = (
    REPOSITORY / "scripts" / "verify-source-python-gdb1-runtime-distribution.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


INVENTORY = load_module("source_python_gdb1_runtime_inventory_test", INVENTORY_SCRIPT)
VERIFY = load_module("source_python_gdb1_runtime_distribution_test", VERIFY_SCRIPT)


def tar_bytes(
    members: list[tuple[str, bytes | None, str | None]], *, mode: str = "w:gz"
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode=mode) as archive:
        for name, value, link in members:
            member = tarfile.TarInfo(name)
            member.mtime = 0
            member.mode = 0o755 if name.startswith("python/bin/") else 0o644
            if link is not None:
                member.type = tarfile.SYMTYPE
                member.linkname = link
                archive.addfile(member)
            else:
                payload = value or b""
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def minimal_macho(dependency: str = "/usr/lib/libSystem.B.dylib") -> bytes:
    name = dependency.encode() + b"\0"
    command_size = (24 + len(name) + 7) & ~7
    command = struct.pack("<IIIIII", 0xC, command_size, 24, 0, 0, 0)
    command += name + b"\0" * (command_size - 24 - len(name))
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0, 0, 0, 1, len(command), 0, 0)
    return header + command


def minimal_elf(dependency: str = "libc.so.6", *, unbacked_strtab: bool = False) -> bytes:
    header_size = 64
    program_size = 56
    program_count = 2
    dynamic_offset = header_size + program_size * program_count
    dynamic_size = 64
    strings = b"\0" + dependency.encode() + b"\0"
    string_offset = dynamic_offset + dynamic_size
    raw = bytearray(string_offset + len(strings))
    raw[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", raw, 32, header_size)
    struct.pack_into("<H", raw, 54, program_size)
    struct.pack_into("<H", raw, 56, program_count)
    file_size = string_offset if unbacked_strtab else len(raw)
    struct.pack_into(
        "<IIQQQQQQ",
        raw,
        header_size,
        1,
        0,
        0,
        0x400000,
        0,
        file_size,
        len(raw),
        0,
    )
    struct.pack_into(
        "<IIQQQQQQ",
        raw,
        header_size + program_size,
        2,
        0,
        dynamic_offset,
        0x400000 + dynamic_offset,
        0,
        dynamic_size,
        dynamic_size,
        0,
    )
    struct.pack_into("<QQ", raw, dynamic_offset, 5, 0x400000 + string_offset)
    struct.pack_into("<QQ", raw, dynamic_offset + 16, 10, len(strings))
    struct.pack_into("<QQ", raw, dynamic_offset + 32, 1, 1)
    struct.pack_into("<QQ", raw, dynamic_offset + 48, 0, 0)
    raw[string_offset:] = strings
    return bytes(raw)


class SourcePythonGdb1RuntimeDistributionTests(unittest.TestCase):
    def contract(self) -> dict:
        return json.loads(CONTRACT.read_bytes())

    def validate(self, contract: dict) -> None:
        dependency = json.loads(DEPENDENCY_LOCK.read_bytes())
        VERIFY.validate_contract(
            CONTRACT,
            contract,
            CONFIG.read_bytes(),
            DEPENDENCY_LOCK.read_bytes(),
            dependency,
        )

    def test_contract_is_canonical_bound_standalone_and_measurement_locked(self) -> None:
        raw = CONTRACT.read_bytes()
        contract = json.loads(raw)
        self.assertEqual(raw, INVENTORY.json_bytes(contract))
        result = VERIFY.verify()
        self.assertTrue(result["verified"])
        self.assertFalse(result["artifacts_verified"])
        self.assertFalse(result["measurement_authorized"])
        self.assertEqual(result["mode"], "standalone")
        self.assertEqual(
            result["targets"]["cpython-3.12.12-macos-arm64"]["base_distribution_bytes"],
            18_980_512,
        )
        self.assertEqual(
            result["targets"]["cpython-3.12.12-linux-x86_64"]["base_distribution_bytes"],
            36_431_318,
        )

    def test_checked_in_inventories_and_native_dependency_closure_are_bound(self) -> None:
        contract = self.contract()
        expected_extra = {
            "cpython-3.12.12-macos-arm64": "/usr/lib/libiconv.2.dylib",
            "cpython-3.12.12-linux-x86_64": "libgcc_s.so.1",
        }
        for target in contract["targets"]:
            path = CONTRACT.parent / target["inventory"]["filename"]
            raw, inventory = INVENTORY.read_canonical(path)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), target["inventory"]["sha256"])
            self.assertEqual(inventory["target_id"], target["target_id"])
            self.assertIn("python/bin/python3.12", inventory["critical_members"])
            self.assertIn("python/lib/python3.12/LICENSE.txt", inventory["critical_members"])
            self.assertGreater(inventory["stdlib"]["member_count"], 700)
            self.assertGreater(inventory["native"]["object_count"], 0)
            self.assertGreater(len(inventory["licenses"]["members"]), 0)
            self.assertIn(expected_extra[target["target_id"]], target["external_system_dependencies"])

    def test_contract_mutations_fail_closed(self) -> None:
        mutations = []
        changed = self.contract()
        changed["accounting"]["primary_mode"] = "installed-library"
        mutations.append(changed)
        changed = self.contract()
        changed["measurement_authorized"] = True
        mutations.append(changed)
        changed = self.contract()
        changed["targets"][0]["base_distribution_bytes"] -= 1
        mutations.append(changed)
        changed = self.contract()
        changed["targets"][0]["package_native"]["records"].pop()
        mutations.append(changed)
        changed = self.contract()
        changed["targets"][0]["external_system_dependencies"].pop()
        mutations.append(changed)
        changed = self.contract()
        changed["targets"][0]["package_native"]["records"][0]["dependencies"] = [1]
        mutations.append(changed)
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises((TypeError, ValueError)):
                self.validate(mutation)

    def test_contract_trust_anchor_rejects_canonical_drift(self) -> None:
        changed = self.contract()
        changed["claim_ceiling"] += " changed"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / CONTRACT.name
            path.write_bytes(INVENTORY.json_bytes(changed))
            with self.assertRaisesRegex(ValueError, "frozen trust anchor"):
                VERIFY.verify(contract_path=path)

    def test_synthetic_runtime_inventory_is_deterministic_and_extraction_free(self) -> None:
        raw = tar_bytes(
            [
                ("python/bin/python3.12", minimal_macho(), None),
                ("python/lib/python3.12/LICENSE.txt", b"PSF fixture\n", None),
                ("python/lib/python3.12/demo.py", b"VALUE = 1\n", None),
                ("python/bin/python3", None, "python3.12"),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.tar.gz"
            path.write_bytes(raw)
            first = INVENTORY.inventory(path, target_id="test")
            second = INVENTORY.inventory(path, target_id="test")
            self.assertEqual(first, second)
            self.assertEqual(first["inventory"]["member_count"], 4)
            self.assertEqual(first["native"]["object_count"], 1)
            self.assertEqual(
                first["external_system_dependencies"], ["/usr/lib/libSystem.B.dylib"]
            )

    def test_unsafe_runtime_tar_members_fail_closed(self) -> None:
        fixtures = [
            [("../escape", b"bad", None)],
            [("python/bin/python3.12", b"x", None), ("python/link", None, "../../escape")],
            [("python/bin/python3.12", b"x", None), ("python/bin/python3.12", b"y", None)],
        ]
        for index, members in enumerate(fixtures):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "runtime.tar.gz"
                path.write_bytes(tar_bytes(members))
                with self.assertRaises(ValueError):
                    INVENTORY.inventory(path, target_id="test")

    def test_native_parsers_read_dependencies_and_reject_unbacked_elf_strings(self) -> None:
        self.assertEqual(
            INVENTORY.macho_dependencies(minimal_macho()),
            ["/usr/lib/libSystem.B.dylib"],
        )
        self.assertEqual(INVENTORY.elf_dependencies(minimal_elf()), ["libc.so.6"])
        with self.assertRaisesRegex(ValueError, "not fully file-backed"):
            INVENTORY.elf_dependencies(minimal_elf(unbacked_strtab=True))
        with self.assertRaisesRegex(ValueError, "thin 64-bit"):
            INVENTORY.macho_dependencies(b"\xca\xfe\xba\xbe" + b"\0" * 28)

    def test_hardlinks_are_validated_from_archive_root(self) -> None:
        member = INVENTORY.PurePosixPath("python/lib/python3.12/hardlink")
        INVENTORY.safe_link_target(
            member,
            "python/lib/python3.12/target",
            archive_root_relative=True,
        )
        with self.assertRaisesRegex(ValueError, "escapes root"):
            INVENTORY.safe_link_target(
                member,
                "../outside",
                archive_root_relative=True,
            )

    def test_source_archive_identity_license_and_member_types_are_verified(self) -> None:
        license_value = b"PSF synthetic license\n"
        raw = tar_bytes(
            [("Python-3.12.12/LICENSE", license_value, None)], mode="w:xz"
        )
        source = {
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "license_member": "Python-3.12.12/LICENSE",
            "license_sha256": hashlib.sha256(license_value).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "Python-3.12.12.tar.xz"
            path.write_bytes(raw)
            VERIFY.validate_source_archive(path, source)
            unsafe = tar_bytes(
                [("Python-3.12.12/LICENSE", None, "../../outside")], mode="w:xz"
            )
            path.write_bytes(unsafe)
            unsafe_source = copy.deepcopy(source)
            unsafe_source["size_bytes"] = len(unsafe)
            unsafe_source["sha256"] = hashlib.sha256(unsafe).hexdigest()
            with self.assertRaisesRegex(ValueError, "member type is unsafe"):
                VERIFY.validate_source_archive(path, unsafe_source)

    def test_artifact_cache_symlink_and_roster_fail_before_artifact_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            link = root / "cache-link"
            link.symlink_to(cache, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "ordinary directory"):
                VERIFY.verify(artifact_dir=link)
            (cache / "unexpected").write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "roster differs"):
                VERIFY.verify(artifact_dir=cache)

    def test_wheel_native_inventory_binds_binary_bytes_and_dependencies(self) -> None:
        wheel_name = "demo.whl"
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("demo/native.so", minimal_elf("libdemo.so"))
        dependency = {
            "packages": [
                {
                    "artifacts": [
                        {"filename": wheel_name, "target_id": "test-target"}
                    ]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, wheel_name).write_bytes(wheel.getvalue())
            result = VERIFY.wheel_native_inventory(
                Path(temporary), dependency, "test-target"
            )
            self.assertEqual(result["object_count"], 1)
            self.assertEqual(result["records"][0]["dependencies"], ["libdemo.so"])
            self.assertEqual(
                result["records"][0]["sha256"],
                hashlib.sha256(minimal_elf("libdemo.so")).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
