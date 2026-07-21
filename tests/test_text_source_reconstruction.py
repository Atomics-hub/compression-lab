from __future__ import annotations

import bz2
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RECONSTRUCT_SCRIPT = ROOT / "scripts" / "reconstruct-text-source-development.py"
RULES = ROOT / "config" / "text-source-path-rules-v1.json"
FORBIDDEN_URL = "https://forbidden.invalid/must-not-be-read"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "reconstruct_text_source_development", RECONSTRUCT_SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


RECON = load_module()
FETCHER = RECON.FETCHER


def make_source_archive(path: Path) -> None:
    content = b"print('development')\r\n"
    with tarfile.open(path, "w:xz") as archive:
        member = tarfile.TarInfo("project/src/main.py")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))


def make_wiki_archive(path: Path) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        "<page><title>Development</title><ns>0</ns><id>1</id>"
        '<revision><id>2</id><text xml:space="preserve">Text</text></revision>'
        "</page></mediawiki>"
    ).encode()
    path.write_bytes(bz2.compress(xml))


def fixture_protocol(source_archive: Path, wiki_archive: Path, status: str) -> dict:
    rules_sha256 = hashlib.sha256(RULES.read_bytes()).hexdigest()
    return {
        "source_code": {
            "bundle_rule": {"path_rules_sha256": rules_sha256},
            "development": [
                {
                    "id": "fixture-source",
                    "release_url": "https://www.python.org/fixture-release",
                    "archive_url": "https://www.python.org/fixture-source.tar.xz",
                    "license_spdx": "MIT",
                    "license_url": "https://www.python.org/fixture-license",
                    "publisher_digest_algorithm": "sha256",
                    "publisher_digest": hashlib.sha256(source_archive.read_bytes()).hexdigest(),
                    "publisher_digest_source": "https://www.python.org/fixture.sha256",
                    "acquisition_status": status,
                }
            ],
            "public_validation": [
                {"archive_url": FORBIDDEN_URL, "acquisition_status": "sealed_unacquired"}
            ],
        },
        "natural_language": {
            "development": [
                {
                    "id": "fixture-wiki",
                    "dump_date": "20260701",
                    "archive_url": "https://dumps.wikimedia.org/fixture/fixture-wiki.xml.bz2",
                    "checksum_url": "https://dumps.wikimedia.org/fixture/fixture-sha1sums.txt",
                    "publisher_digest_algorithm": "sha1",
                    "publisher_digest": hashlib.sha1(wiki_archive.read_bytes()).hexdigest(),
                    "acquisition_status": status,
                }
            ],
            "public_validation": [
                {"archive_url": FORBIDDEN_URL, "acquisition_status": "sealed_unacquired"}
            ],
        },
    }


def install_fake_download(downloads: dict[str, Path]) -> list[str]:
    observed: list[str] = []

    def fake_download(url: str, destination: Path) -> None:
        observed.append(url)
        if destination.name not in downloads:
            raise AssertionError(f"unexpected download: {url}")
        shutil.copyfile(downloads[destination.name], destination)

    FETCHER.download = fake_download
    return observed


class Ground:
    """Ground-truth corpus produced by the verified first-acquisition fetcher."""

    def __init__(self, root: Path):
        self.root = root
        source_archive = root / "local-source.tar.xz"
        wiki_archive = root / "local-wiki.xml.bz2"
        make_source_archive(source_archive)
        make_wiki_archive(wiki_archive)
        checksum = root / "local-sha1sums.txt"
        checksum.write_text(
            f"{hashlib.sha1(wiki_archive.read_bytes()).hexdigest()}  fixture-wiki.xml.bz2\n",
            encoding="utf-8",
        )
        evidence = root / "local-source.sha256"
        evidence.write_text(
            hashlib.sha256(source_archive.read_bytes()).hexdigest() + "\n", encoding="utf-8"
        )
        self.downloads = {
            "fixture-source.tar.xz": source_archive,
            "fixture.sha256": evidence,
            "fixture-wiki.xml.bz2": wiki_archive,
            "fixture-sha1sums.txt": checksum,
        }
        self.cache = root / "cache"
        # Build a real corpus once with the verified fetcher to capture true hashes.
        acquire_protocol = root / "acquire-protocol.json"
        acquire_protocol.write_text(
            json.dumps(fixture_protocol(source_archive, wiki_archive, "declared_unacquired")),
            encoding="utf-8",
        )
        original = FETCHER.download
        install_fake_download(self.downloads)
        try:
            manifest_path = FETCHER.acquire_development(
                protocol_path=acquire_protocol,
                rules_path=RULES,
                output=root / "seed-output",
                cache=self.cache,
            )
        finally:
            FETCHER.download = original
        seed = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.items = {item["source_id"]: item for item in seed["items"]}
        self.source_archive = source_archive
        self.wiki_archive = wiki_archive

    def receipt(self) -> dict:
        items = [
            {
                "source_id": sid,
                "format": item["format"],
                "archive_sha256": item["archive_sha256"],
                "bundle_size_bytes": item["bundle_size_bytes"],
                "bundle_sha256": item["bundle_sha256"],
            }
            for sid, item in self.items.items()
        ]
        return {
            "schema_version": 1,
            "name": "text-source-development-acquisition-v1",
            "passed": True,
            "public_validation_accessed": False,
            "acquisition_commit": "0" * 40,
            "item_count": len(items),
            "items": items,
        }

    def acquired_protocol(self) -> dict:
        return fixture_protocol(self.source_archive, self.wiki_archive, "acquired_development")


class ReconstructionTests(unittest.TestCase):
    def _run(self, ground: Ground, receipt: dict, protocol: dict, *, fresh_cache=False):
        root = ground.root
        receipt_path = root / f"receipt-{id(receipt)}.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        protocol_path = root / f"protocol-{id(protocol)}.json"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        cache = (root / "empty-cache") if fresh_cache else ground.cache
        output = root / f"recon-{id(receipt)}"
        original = FETCHER.download
        observed = install_fake_download(ground.downloads)
        try:
            manifest_path = RECON.reconstruct_development(
                protocol_path=protocol_path,
                rules_path=RULES,
                receipt_path=receipt_path,
                output=output,
                cache=cache,
            )
        finally:
            FETCHER.download = original
        return manifest_path, output, observed

    def test_exact_reconstruction_from_acquired_receipt(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            manifest_path, output, _ = self._run(
                ground, ground.receipt(), ground.acquired_protocol()
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["reconstruction"])
            self.assertFalse(manifest["public_validation_accessed"])
            self.assertEqual(
                {item["source_id"] for item in manifest["items"]},
                {"fixture-source", "fixture-wiki"},
            )
            self.assertTrue((output / "fixture-source.axsrc").is_file())
            self.assertTrue((output / "fixture-wiki.axwkt").is_file())
            for item in manifest["items"]:
                self.assertEqual(
                    item["bundle_sha256"], ground.items[item["source_id"]]["bundle_sha256"]
                )

    def test_reconstruction_downloads_only_allowlisted_sources(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            (ground.root / "empty-cache").mkdir()
            _, _, observed = self._run(
                ground, ground.receipt(), ground.acquired_protocol(), fresh_cache=True
            )
            self.assertEqual(len(observed), 4)
            self.assertTrue(all("forbidden.invalid" not in url for url in observed))

    def test_roster_fails_before_any_download(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            receipt = ground.receipt()
            receipt["items"] = [i for i in receipt["items"] if i["source_id"] != "fixture-wiki"]
            receipt["item_count"] = 1
            root = ground.root
            receipt_path = root / "short-receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            protocol_path = root / "acq-protocol.json"
            protocol_path.write_text(json.dumps(ground.acquired_protocol()), encoding="utf-8")
            original = FETCHER.download
            observed = install_fake_download(ground.downloads)
            try:
                with self.assertRaisesRegex(ValueError, "roster"):
                    RECON.reconstruct_development(
                        protocol_path=protocol_path,
                        rules_path=RULES,
                        receipt_path=receipt_path,
                        output=root / "recon-short",
                        cache=root / "empty-cache",
                    )
            finally:
                FETCHER.download = original
            self.assertEqual(observed, [])

    def test_bundle_hash_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            receipt = ground.receipt()
            receipt["items"][0]["bundle_sha256"] = "0" * 64
            output = ground.root / "recon-tamper-bundle"
            with self.assertRaisesRegex(ValueError, "bundle SHA-256"):
                self._run_at(ground, receipt, ground.acquired_protocol(), output)
            self.assertFalse(output.exists())

    def test_archive_hash_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            receipt = ground.receipt()
            receipt["items"][0]["archive_sha256"] = "0" * 64
            output = ground.root / "recon-tamper-archive"
            with self.assertRaisesRegex(ValueError, "archive digest"):
                self._run_at(ground, receipt, ground.acquired_protocol(), output)
            self.assertFalse(output.exists())

    def test_byte_size_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            receipt = ground.receipt()
            receipt["items"][0]["bundle_size_bytes"] += 1
            output = ground.root / "recon-tamper-size"
            with self.assertRaisesRegex(ValueError, "byte count"):
                self._run_at(ground, receipt, ground.acquired_protocol(), output)
            self.assertFalse(output.exists())

    def test_extra_receipt_item_fails_roster(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            receipt = ground.receipt()
            extra = copy.deepcopy(receipt["items"][0])
            extra["source_id"] = "fixture-extra"
            receipt["items"].append(extra)
            receipt["item_count"] = len(receipt["items"])
            with self.assertRaisesRegex(ValueError, "roster"):
                self._run_at(ground, receipt, ground.acquired_protocol(), ground.root / "x")

    def test_unacquired_development_row_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            protocol = ground.acquired_protocol()
            protocol["source_code"]["development"][0]["acquisition_status"] = "declared_unacquired"
            with self.assertRaisesRegex(ValueError, "not fully acquired"):
                self._run_at(ground, ground.receipt(), protocol, ground.root / "u")

    def test_refuses_to_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as raw:
            ground = Ground(Path(raw))
            manifest_path, output, _ = self._run(
                ground, ground.receipt(), ground.acquired_protocol()
            )
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                self._run_at(ground, ground.receipt(), ground.acquired_protocol(), output)

    def _run_at(self, ground: Ground, receipt: dict, protocol: dict, output: Path):
        root = ground.root
        receipt_path = root / f"receipt-at-{id(receipt)}.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        protocol_path = root / f"protocol-at-{id(protocol)}.json"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        original = FETCHER.download
        install_fake_download(ground.downloads)
        try:
            return RECON.reconstruct_development(
                protocol_path=protocol_path,
                rules_path=RULES,
                receipt_path=receipt_path,
                output=output,
                cache=ground.cache,
            )
        finally:
            FETCHER.download = original


if __name__ == "__main__":
    unittest.main()
