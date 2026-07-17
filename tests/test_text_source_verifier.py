from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-text-source-development.py"
U64 = struct.Struct("<Q")


def load_module():
    specification = importlib.util.spec_from_file_location("verify_text_source", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


VERIFIER = load_module()


class TextSourceVerifierTests(unittest.TestCase):
    def test_source_verifier_recomputes_content_and_terminal_manifest_hashes(self):
        path_bytes = b"main.py"
        content = b"print('exact')\r\n"
        content_digest = hashlib.sha256(content).digest()
        manifest_input = (
            U64.pack(len(path_bytes))
            + path_bytes
            + U64.pack(len(content))
            + content_digest
        )
        encoded = (
            VERIFIER.SOURCE_MAGIC
            + U64.pack(1)
            + U64.pack(len(path_bytes))
            + path_bytes
            + U64.pack(len(content))
            + content
            + hashlib.sha256(manifest_input).digest()
        )
        manifest = {
            "items": [
                {
                    "path": "main.py",
                    "size_bytes": len(content),
                    "sha256": content_digest.hex(),
                }
            ],
            "ordered_manifest_sha256": hashlib.sha256(manifest_input).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "source.axsrc"
            path.write_bytes(encoded)
            result = VERIFIER.verify_source_bundle(path, manifest)
            self.assertEqual(result["record_count"], 1)
            tampered = bytearray(encoded)
            tampered[-33] ^= 1
            path.write_bytes(tampered)
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                VERIFIER.verify_source_bundle(path, manifest)

    def test_wikimedia_verifier_rejects_trailing_bytes(self):
        page_id = 1
        revision_id = 2
        title = "Title".encode()
        text = "Text β".encode()
        text_digest = hashlib.sha256(text).digest()
        manifest_input = (
            U64.pack(page_id)
            + U64.pack(revision_id)
            + U64.pack(len(title))
            + title
            + U64.pack(len(text))
            + text_digest
        )
        encoded = (
            VERIFIER.WIKIMEDIA_MAGIC
            + U64.pack(1)
            + U64.pack(page_id)
            + U64.pack(revision_id)
            + U64.pack(len(title))
            + title
            + U64.pack(len(text))
            + text
            + hashlib.sha256(manifest_input).digest()
        )
        manifest = {
            "items": [
                {
                    "page_id": page_id,
                    "revision_id": revision_id,
                    "title": "Title",
                    "title_sha256": hashlib.sha256(title).hexdigest(),
                    "text_size_bytes": len(text),
                    "text_sha256": text_digest.hex(),
                }
            ],
            "ordered_manifest_sha256": hashlib.sha256(manifest_input).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "wiki.axwkt"
            path.write_bytes(encoded)
            result = VERIFIER.verify_wikimedia_bundle(path, manifest)
            self.assertEqual(result["record_count"], 1)
            path.write_bytes(encoded + b"unexpected")
            with self.assertRaisesRegex(ValueError, "trailing Wikimedia"):
                VERIFIER.verify_wikimedia_bundle(path, manifest)


if __name__ == "__main__":
    unittest.main()
