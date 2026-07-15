import json
import tempfile
import unittest
from pathlib import Path

from compresslab.corpus import generate_corpus, load_corpus


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


if __name__ == "__main__":
    unittest.main()
