"""Guards for the S0 freeze record: it must always match the working tree."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "config" / "json-log-native-screen-s0-freeze-v1.json"
CONFIG = ROOT / "config" / "json-log-native-screen-s0-v1.json"
BASE_MANIFEST = ROOT / "config" / "json-log-native-screen-s0-constants-base-v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FreezeRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = json.loads(RECORD.read_bytes())
        cls.config = json.loads(CONFIG.read_bytes())
        cls.manifest = json.loads(BASE_MANIFEST.read_bytes())

    def test_protocol_and_config_bindings_match_the_tree(self) -> None:
        freeze = self.config["screen"]["freeze_requirements_before_measurement"]
        self.assertEqual(self.record["protocol_path"], freeze["protocol_path"])
        self.assertEqual(self.record["protocol_sha256"], freeze["protocol_sha256"])
        self.assertEqual(
            self.record["protocol_sha256"],
            sha256_file(ROOT / self.record["protocol_path"]),
        )
        self.assertEqual(
            self.record["screen_config_sha256"],
            sha256_file(ROOT / self.record["screen_config_path"]),
        )

    def test_engine_source_hashes_match_the_tree_and_the_manifest_list(self) -> None:
        declared = self.manifest["source_toolchain_build_identity"][
            "engine_source_files"
        ]
        recorded = self.record["engine_source_sha256"]
        self.assertEqual(sorted(recorded), sorted(declared))
        for relative, expected in recorded.items():
            self.assertEqual(
                expected, sha256_file(ROOT / relative), relative
            )

    def test_manifest_and_harness_hashes_match_the_tree(self) -> None:
        for path_key, sha_key in (
            ("base_constants_manifest_path", "base_constants_manifest_sha256"),
            ("refined_constants_manifest_path", "refined_constants_manifest_sha256"),
            ("runner_path", "runner_sha256"),
            ("verifier_path", "verifier_sha256"),
            ("confirmation_path", "confirmation_sha256"),
        ):
            self.assertEqual(
                self.record[sha_key],
                sha256_file(ROOT / self.record[path_key]),
                path_key,
            )

    def test_engine_commit_is_a_full_commit_id(self) -> None:
        commit = self.record["engine_commit"]
        self.assertEqual(len(commit), 40)
        self.assertTrue(all(char in "0123456789abcdef" for char in commit))

    def test_toolchain_build_receipt_is_complete(self) -> None:
        receipt = self.record["toolchain_build_receipt"]
        self.assertTrue(receipt["rustc"].startswith("rustc "))
        self.assertTrue(receipt["cargo"].startswith("cargo "))
        self.assertIn("clab-s0-kernel", receipt["build_command"])
        self.assertIn("lto=fat", receipt["build_profile"])


if __name__ == "__main__":
    unittest.main()
