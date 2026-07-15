import json
import tempfile
import unittest
from pathlib import Path

from compresslab.corpus import (
    freeze_holdout,
    generate_corpus,
    import_corpus,
    load_corpus,
    verify_holdout,
)


class CorpusTests(unittest.TestCase):
    def test_generation_is_deterministic(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path = Path(first)
            second_path = Path(second)
            manifest_a = generate_corpus(first_path, size_scale=0.125, seed=7)
            manifest_b = generate_corpus(second_path, size_scale=0.125, seed=7)
            data_a = json.loads(manifest_a.read_text(encoding="utf-8"))
            data_b = json.loads(manifest_b.read_text(encoding="utf-8"))
            self.assertEqual(data_a, data_b)
            self.assertEqual(len(load_corpus(first_path)), 8)

    def test_integrity_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_corpus(root, size_scale=0.125)
            item = load_corpus(root)[0]
            item.path.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                load_corpus(root)

    def test_import_requires_provenance_and_freezes_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("licensed real data\n", encoding="utf-8")
            corpus = root / "corpus"
            manifest = import_corpus(
                source,
                corpus,
                category="documents",
                split="holdout",
                dataset="fixture",
                license_spdx="MIT",
                source_url="https://example.test/fixture",
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            item = load_corpus(corpus, ("holdout",))[0]
            self.assertEqual(item.license_spdx, "MIT")
            lock = freeze_holdout(corpus, root / "holdout-lock.json")
            self.assertTrue(verify_holdout(corpus, lock))
            item.path.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_holdout(corpus, lock)

    def test_import_rejects_missing_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"data")
            with self.assertRaises(ValueError):
                import_corpus(
                    source,
                    root / "corpus",
                    category="binary",
                    split="validation",
                    dataset="fixture",
                    license_spdx="",
                    source_url="https://example.test/fixture",
                )


if __name__ == "__main__":
    unittest.main()
