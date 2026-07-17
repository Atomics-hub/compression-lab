import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "fetch_tabular_corpus.py"
SPEC = importlib.util.spec_from_file_location("fetch_tabular_corpus", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_zip(path: Path, member: str, data: bytes) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_for(archive: Path, digest: str, compression: str = "none"):
    item = {
        "id": "fixture",
        "family": "fixture_family",
        "doi": "10.1234/example",
        "page_url": "https://example.test/dataset",
        "archive_url": archive.as_uri(),
        "archive_sha256": digest,
        "member": "data.csv" if compression == "none" else "data.csv.gz",
        "member_compression": compression,
    }
    return {
        "schema_version": 1,
        "name": "fixture-tabular",
        "category": "tabular_csv",
        "claim_ceiling": "test only",
        "provider": {"license_spdx": "CC-BY-4.0"},
        "selection": {"max_item_bytes": 12},
        "development": [item],
        "public_validation": [item | {"id": "validation-fixture"}],
    }


class TabularCorpusTests(unittest.TestCase):
    def test_build_verifies_archive_and_selects_record_aligned_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            archive = cache / "fixture.zip"
            digest = write_zip(archive, "data.csv", b"a,b\n1,2\n333,444\n")
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive, digest)))

            manifest_path = MODULE.build(
                config,
                "development",
                root / "output",
                cache,
            )
            manifest = json.loads(manifest_path.read_text())
            item = (root / "output" / "fixture.table").read_bytes()
            self.assertEqual(item, b"a,b\n1,2\n")
            self.assertFalse(manifest["items"][0]["source_complete"])
            self.assertEqual(
                manifest["items"][0]["item_sha256"],
                hashlib.sha256(item).hexdigest(),
            )

    def test_nested_gzip_member_is_decompressed_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            archive = cache / "fixture.zip"
            compressed = io.BytesIO()
            with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as output:
                output.write(b"x;y\n1;2\n")
            digest = write_zip(archive, "data.csv.gz", compressed.getvalue())
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive, digest, "gzip")))

            MODULE.build(config, "development", root / "output", cache)
            self.assertEqual(
                (root / "output" / "fixture.table").read_bytes(),
                b"x;y\n1;2\n",
            )

    def test_validation_is_refused_before_output_or_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.zip"
            digest = write_zip(archive, "data.csv", b"a,b\n")
            config = root / "config.json"
            config.write_text(json.dumps(config_for(archive, digest)))
            output = root / "output"

            with self.assertRaisesRegex(ValueError, "refusing to acquire"):
                MODULE.build(
                    config,
                    "public-validation",
                    output,
                    root / "cache",
                )
            self.assertFalse(output.exists())

    def test_checksum_mismatch_and_unsafe_member_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "fixture.zip"
            write_zip(archive, "../data.csv", b"a,b\n")
            with zipfile.ZipFile(archive) as opened:
                with self.assertRaisesRegex(ValueError, "unsafe member"):
                    MODULE._validated_member(opened, "../data.csv")

            cache = root / "cache"
            cache.mkdir()
            cached = cache / "fixture.zip"
            cached.write_bytes(archive.read_bytes())
            config = root / "config.json"
            payload = config_for(archive, "0" * 64)
            payload["development"][0]["member"] = "../data.csv"
            config.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                MODULE.build(config, "development", root / "output", cache)


if __name__ == "__main__":
    unittest.main()
