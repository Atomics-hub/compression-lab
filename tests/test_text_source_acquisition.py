from __future__ import annotations

import bz2
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
SCRIPT = ROOT / "scripts" / "fetch-text-source-development.py"
RULES = ROOT / "config" / "text-source-path-rules-v1.json"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "fetch_text_source_development", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


FETCHER = load_module()


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


def fixture_protocol(source_archive: Path, wiki_archive: Path) -> dict:
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
                    "acquisition_status": "declared_unacquired",
                }
            ],
            "public_validation": [
                {
                    "archive_url": "https://forbidden.invalid/must-not-be-read",
                    "acquisition_status": "sealed_unacquired",
                }
            ],
        },
        "natural_language": {
            "development": [
                {
                    "id": "fixture-wiki",
                    "dump_date": "20260701",
                    "archive_url": (
                        "https://dumps.wikimedia.org/fixture/fixture-wiki.xml.bz2"
                    ),
                    "checksum_url": (
                        "https://dumps.wikimedia.org/fixture/fixture-sha1sums.txt"
                    ),
                    "publisher_digest_algorithm": "sha1",
                    "publisher_digest": hashlib.sha1(wiki_archive.read_bytes()).hexdigest(),
                    "acquisition_status": "declared_unacquired",
                }
            ],
            "public_validation": [
                {
                    "archive_url": "https://forbidden.invalid/must-not-be-read",
                    "acquisition_status": "sealed_unacquired",
                }
            ],
        },
    }


class TextSourceAcquisitionTests(unittest.TestCase):
    def test_acquires_only_development_and_atomically_builds_bound_manifest(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_archive = root / "local-source.tar.xz"
            wiki_archive = root / "local-wiki.xml.bz2"
            make_source_archive(source_archive)
            make_wiki_archive(wiki_archive)
            checksum = root / "local-sha1sums.txt"
            checksum.write_text(
                f"{hashlib.sha1(wiki_archive.read_bytes()).hexdigest()}  "
                "fixture-wiki.xml.bz2\n",
                encoding="utf-8",
            )
            source_evidence = root / "local-source.sha256"
            source_evidence.write_text(
                hashlib.sha256(source_archive.read_bytes()).hexdigest() + "\n",
                encoding="utf-8",
            )
            protocol_path = root / "protocol.json"
            protocol_path.write_text(
                json.dumps(fixture_protocol(source_archive, wiki_archive)),
                encoding="utf-8",
            )
            downloads = {
                "fixture-source.tar.xz": source_archive,
                "fixture.sha256": source_evidence,
                "fixture-wiki.xml.bz2": wiki_archive,
                "fixture-sha1sums.txt": checksum,
            }
            observed_urls: list[str] = []
            original_download = FETCHER.download

            def fake_download(url: str, destination: Path) -> None:
                observed_urls.append(url)
                shutil.copyfile(downloads[destination.name], destination)

            FETCHER.download = fake_download
            try:
                manifest_path = FETCHER.acquire_development(
                    protocol_path=protocol_path,
                    rules_path=RULES,
                    output=root / "output",
                    cache=root / "cache",
                )
            finally:
                FETCHER.download = original_download

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["public_validation_accessed"])
            self.assertEqual(
                [item["format"] for item in manifest["items"]],
                ["source-bundle-v1", "wikimedia-revision-text-v1"],
            )
            self.assertEqual(len(observed_urls), 4)
            self.assertTrue(all("forbidden.invalid" not in url for url in observed_urls))
            self.assertTrue((root / "output" / "fixture-source.axsrc").is_file())
            self.assertTrue((root / "output" / "fixture-wiki.axwkt").is_file())
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                FETCHER.acquire_development(
                    protocol_path=protocol_path,
                    rules_path=RULES,
                    output=root / "output",
                    cache=root / "cache",
                )

    def test_checksum_failure_removes_staged_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_archive = root / "local-source.tar.xz"
            wiki_archive = root / "local-wiki.xml.bz2"
            make_source_archive(source_archive)
            make_wiki_archive(wiki_archive)
            protocol = fixture_protocol(source_archive, wiki_archive)
            protocol["natural_language"]["development"][0]["publisher_digest"] = "0" * 40
            protocol_path = root / "protocol.json"
            protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
            cache = root / "cache"
            cache.mkdir()
            shutil.copyfile(source_archive, cache / "fixture-source.tar.xz")
            (cache / "fixture.sha256").write_text("fixture evidence\n", encoding="utf-8")
            shutil.copyfile(wiki_archive, cache / "fixture-wiki.xml.bz2")
            (cache / "fixture-sha1sums.txt").write_text(
                f"{hashlib.sha1(wiki_archive.read_bytes()).hexdigest()}  "
                "fixture-wiki.xml.bz2\n",
                encoding="utf-8",
            )
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "checksum declaration drifted"):
                FETCHER.acquire_development(
                    protocol_path=protocol_path,
                    rules_path=RULES,
                    output=output,
                    cache=cache,
                )
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".output.*")), [])


if __name__ == "__main__":
    unittest.main()
