import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
LOCK = REPOSITORY / "config" / "source-python-gdb1-dependency-lock-v1.json"
CONFIG = REPOSITORY / "config" / "source-python-grammar-binding-gdb1-v1.json"
SCRIPT = REPOSITORY / "scripts" / "verify-source-python-gdb1-dependency-lock.py"
ACQUIRE_SCRIPT = REPOSITORY / "scripts" / "acquire-source-python-gdb1-dependencies.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load_module("source_python_gdb1_dependency_lock_verifier", SCRIPT)
ACQUIRE = load_module("source_python_gdb1_dependency_acquirer", ACQUIRE_SCRIPT)


def record_hash(value: bytes) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()
    )


def synthetic_wheel(
    *,
    symlink: bool = False,
    malformed_record: bool = False,
    composite_license: bool = False,
) -> tuple[bytes, dict, dict]:
    prefix = "demo-1.0.dist-info"
    requirements = (
        [
            'pyyaml>=5.2; python_version < "3.13"',
            'pyyaml-ft>=8.0.0; python_version == "3.13"',
            'pyyaml>=6.0.3; python_version >= "3.14"',
            'typing-extensions; python_version < "3.10"',
        ]
        if composite_license
        else []
    )
    license_header = (
        b"License: MIT licensed\n"
        b" PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n"
        b" APACHE LICENSE, VERSION 2.0\n"
        if composite_license
        else b"License: MIT\n"
    )
    requirement_headers = b"".join(
        f"Requires-Dist: {requirement}\n".encode() for requirement in requirements
    )
    members = {
        "demo/__init__.py": b"VALUE = 1\n",
        f"{prefix}/METADATA": (
            b"Metadata-Version: 2.4\nName: Demo\nVersion: 1.0\n"
            b"Requires-Python: >=3.12\n"
            + license_header
            + b"License-File: LICENSE\n"
            + requirement_headers
            + b"\n"
        ),
        f"{prefix}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
            b"Tag: cp312-cp312-macosx_11_0_arm64\n\n"
        ),
        f"{prefix}/licenses/LICENSE": b"Synthetic MIT fixture\n",
    }
    if symlink:
        members["demo/link"] = b"target"
    record_member = f"{prefix}/RECORD"
    rows = [
        [name, "sha256=" + record_hash(value), str(len(value))]
        for name, value in members.items()
    ]
    if malformed_record:
        rows.append([])
    rows.append([record_member, "", ""])
    record = io.StringIO()
    csv.writer(record, lineterminator="\n").writerows(rows)
    members[record_member] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, value in members.items():
            info = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
            if symlink and name == "demo/link":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, value)
    raw = output.getvalue()
    artifact = {
        "filename": "demo-1.0-cp312-cp312-macosx_11_0_arm64.whl",
        "internal": {
            "license": {
                "bytes": len(members[f"{prefix}/licenses/LICENSE"]),
                "member": f"{prefix}/licenses/LICENSE",
                "sha256": hashlib.sha256(
                    members[f"{prefix}/licenses/LICENSE"]
                ).hexdigest(),
            },
            "metadata": {
                "bytes": len(members[f"{prefix}/METADATA"]),
                "member": f"{prefix}/METADATA",
                "sha256": hashlib.sha256(members[f"{prefix}/METADATA"]).hexdigest(),
            },
            "record": {
                "bytes": len(members[record_member]),
                "member": record_member,
                "sha256": hashlib.sha256(members[record_member]).hexdigest(),
            },
            "wheel": {
                "bytes": len(members[f"{prefix}/WHEEL"]),
                "member": f"{prefix}/WHEEL",
                "sha256": hashlib.sha256(members[f"{prefix}/WHEEL"]).hexdigest(),
            },
        },
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "wheel_tags": ["cp312-cp312-macosx_11_0_arm64"],
    }
    package = {
        "license_files": ["LICENSE"],
        "name": "Demo",
        "normalized_name": "libcst" if composite_license else "pyyaml",
        "requires_dist": requirements,
        "requires_python": ">=3.12",
        "version": "1.0",
    }
    return raw, package, artifact


class SourcePythonGdb1DependencyLockTests(unittest.TestCase):
    def lock(self) -> dict:
        return json.loads(LOCK.read_bytes())

    def test_lock_is_canonical_complete_and_bound_to_frozen_protocol(self) -> None:
        raw = LOCK.read_bytes()
        lock = json.loads(raw)
        self.assertEqual(raw, MODULE.json_bytes(lock))
        result = MODULE.verify()
        self.assertTrue(result["verified"])
        self.assertFalse(result["artifact_bytes_verified"])
        self.assertEqual(result["package_count"], 2)
        self.assertEqual(result["artifact_count"], 4)
        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["lock_sha256"], hashlib.sha256(raw).hexdigest())

    def test_exact_closure_targets_official_urls_and_runtime_boundary(self) -> None:
        lock = self.lock()
        self.assertEqual(
            [row["normalized_name"] for row in lock["packages"]],
            ["libcst", "pyyaml"],
        )
        self.assertEqual(
            {row["python_version"] for row in lock["targets"]}, {"3.12.12"}
        )
        self.assertTrue(lock["resolution"]["package_set_complete"])
        self.assertIn(
            "never authorizes measurement",
            lock["resolution"]["runtime_distribution_boundary"],
        )
        for package, artifact in MODULE.artifact_rows(lock):
            self.assertTrue(
                MODULE.safe_https_host(package["pypi_json_url"], "pypi.org")
            )
            self.assertTrue(
                MODULE.safe_https_host(artifact["url"], "files.pythonhosted.org")
            )

    def test_config_binding_package_substitution_and_url_escape_fail_closed(
        self,
    ) -> None:
        config_raw = CONFIG.read_bytes()
        mutations = []
        changed = self.lock()
        changed["protocol_config_sha256"] = "0" * 64
        mutations.append(changed)
        changed = self.lock()
        changed["packages"].pop()
        mutations.append(changed)
        changed = self.lock()
        changed["packages"][0]["artifacts"][0]["url"] = (
            "https://example.com/substitute.whl"
        )
        mutations.append(changed)
        changed = self.lock()
        changed["targets"][0]["python_version"] = "3.12.11"
        mutations.append(changed)
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                MODULE.validate_lock(mutation, config_raw)

    def test_target_to_wheel_compatibility_and_lock_trust_anchor_are_enforced(
        self,
    ) -> None:
        config_raw = CONFIG.read_bytes()
        changed = self.lock()
        changed["packages"][0]["artifacts"][0]["target_id"] = (
            "cpython-3.12.12-linux-x86_64"
        )
        with self.assertRaises(ValueError):
            MODULE.validate_lock(changed, config_raw)
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "changed-lock.json"
            changed = self.lock()
            changed["claim_ceiling"] += " changed"
            lock_path.write_bytes(MODULE.json_bytes(changed))
            with self.assertRaisesRegex(ValueError, "frozen trust anchor"):
                MODULE.verify(lock_path)

    def test_synthetic_wheel_record_and_embedded_identity_are_verified(self) -> None:
        raw, package, artifact = synthetic_wheel()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / artifact["filename"]
            path.write_bytes(raw)
            MODULE.verify_wheel(path, package, artifact)
            mutated = bytearray(raw)
            mutated[-1] ^= 1
            path.write_bytes(mutated)
            with self.assertRaisesRegex(ValueError, "size or SHA-256 differs"):
                MODULE.verify_wheel(path, package, artifact)

    def test_libcst_composite_license_and_marker_metadata_are_verified(self) -> None:
        raw, package, artifact = synthetic_wheel(composite_license=True)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / artifact["filename"]
            path.write_bytes(raw)
            MODULE.verify_wheel(path, package, artifact)
            self.assertEqual(len(package["requires_dist"]), 4)

    def test_symlinked_wheel_member_file_and_cache_are_rejected(self) -> None:
        raw, package, artifact = synthetic_wheel(symlink=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / artifact["filename"]
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "unsafe ZIP member"):
                MODULE.verify_wheel(path, package, artifact)
            path.unlink()
            target = root / "target.whl"
            target.write_bytes(raw)
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "ordinary wheel file"):
                MODULE.verify_wheel(path, package, artifact)
            cache = root / "cache"
            cache.mkdir()
            symlink_cache = root / "cache-link"
            symlink_cache.symlink_to(cache, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "ordinary directory"):
                MODULE.verify_artifact_directory(symlink_cache, {"packages": []})

    def test_malformed_record_fails_cleanly(self) -> None:
        raw, package, artifact = synthetic_wheel(malformed_record=True)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / artifact["filename"]
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "RECORD row differs"):
                MODULE.verify_wheel(path, package, artifact)

    def test_network_redirect_metadata_and_download_bounds_fail_closed(self) -> None:
        class FakeResponse:
            def __init__(self, *, url: str, chunks: list[bytes], length: int | None):
                self.url = url
                self.chunks = list(chunks)
                self.headers = {} if length is None else {"Content-Length": str(length)}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self) -> str:
                return self.url

            def read(self, _size: int = -1) -> bytes:
                return self.chunks.pop(0) if self.chunks else b""

        escaped = FakeResponse(
            url="https://example.com/metadata", chunks=[b"{}"], length=2
        )
        with mock.patch.object(ACQUIRE, "urlopen", return_value=escaped):
            with self.assertRaisesRegex(ValueError, "redirect escaped"):
                ACQUIRE.fetch_bytes(
                    "https://pypi.org/pypi/demo/1/json",
                    host="pypi.org",
                    maximum_bytes=1024,
                )

        package = self.lock()["packages"][0]
        metadata = {
            "info": {
                "name": package["name"],
                "project_urls": {"Source": package["source_url"]},
                "requires_dist": package["requires_dist"],
                "requires_python": package["requires_python"],
                "version": package["version"],
            },
            "urls": [],
        }
        response = FakeResponse(
            url=package["pypi_json_url"],
            chunks=[json.dumps(metadata).encode()],
            length=None,
        )
        with mock.patch.object(ACQUIRE, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "artifact metadata differs"):
                ACQUIRE.verify_pypi_metadata(package)

        artifact = {
            "filename": "demo.whl",
            "sha256": hashlib.sha256(b"abc").hexdigest(),
            "size_bytes": 3,
            "url": "https://files.pythonhosted.org/packages/demo.whl",
        }
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / artifact["filename"]
            wrong_length = FakeResponse(url=artifact["url"], chunks=[b"abc"], length=4)
            with mock.patch.object(ACQUIRE, "urlopen", return_value=wrong_length):
                with self.assertRaisesRegex(ValueError, "Content-Length differs"):
                    ACQUIRE.download_artifact(artifact, destination)
            self.assertFalse(destination.exists())

            overflow = FakeResponse(
                url=artifact["url"], chunks=[b"abcd", b""], length=None
            )
            with mock.patch.object(ACQUIRE, "urlopen", return_value=overflow):
                with self.assertRaisesRegex(ValueError, "exceeds locked byte size"):
                    ACQUIRE.download_artifact(artifact, destination)
            self.assertFalse(destination.exists())

            success = FakeResponse(
                url=artifact["url"], chunks=[b"ab", b"c", b""], length=3
            )
            with mock.patch.object(ACQUIRE, "urlopen", return_value=success):
                ACQUIRE.download_artifact(artifact, destination)
            self.assertEqual(destination.read_bytes(), b"abc")

    def test_acquirer_rejects_unlisted_destination_content_without_network(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / "substitution.whl").write_bytes(b"not allowed")
            with self.assertRaisesRegex(ValueError, "unlisted files"):
                ACQUIRE.acquire(LOCK, CONFIG, destination)

    def test_acquirer_checks_trust_anchor_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            changed = self.lock()
            changed["claim_ceiling"] += " changed"
            lock_path = root / "changed-lock.json"
            lock_path.write_bytes(MODULE.json_bytes(changed))
            destination = root / "cache"
            with mock.patch.object(ACQUIRE, "urlopen") as network:
                with self.assertRaisesRegex(ValueError, "frozen trust anchor"):
                    ACQUIRE.acquire(lock_path, CONFIG, destination)
                network.assert_not_called()

    def test_noncanonical_and_symlinked_lock_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            noncanonical = root / "lock.json"
            noncanonical.write_bytes(LOCK.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "not canonical JSON"):
                MODULE.verify(noncanonical)
            symlink = root / "lock-link.json"
            symlink.symlink_to(LOCK)
            with self.assertRaisesRegex(ValueError, "ordinary file"):
                MODULE.verify(symlink)


if __name__ == "__main__":
    unittest.main()
