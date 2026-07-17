from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "text-source-baseline-toolchain-v1.json"
GATES = ROOT / "config" / "text-source-gates-v1.json"
SCRIPT = ROOT / "scripts" / "bootstrap-text-source-baselines.py"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "bootstrap_text_source_baselines", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BOOTSTRAP = load_module()


class TextSourceBaselineToolchainTests(unittest.TestCase):
    def test_practical_roster_exactly_matches_frozen_gates(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        expected = [
            row["codec_id"] for row in gates["baseline_tiers"]["practical_required"]
        ]
        self.assertEqual(config["practical_codec_ids"], expected)
        self.assertEqual(config["measurement_policy"]["repetitions"], 5)
        self.assertEqual(config["measurement_policy"]["threads"], 1)
        self.assertIn("Every byte", config["measurement_policy"]["artifact_accounting"])

    def test_source_builds_are_commit_and_archive_bound(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual({row["name"] for row in config["source_builds"]}, {"kanzi", "libbsc"})
        for row in config["source_builds"]:
            self.assertRegex(row["commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(row["archive_sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(row["archive_size_bytes"], 0)
            self.assertIn(row["commit"], row["archive_url"])

    def test_safe_extract_rejects_links_and_parent_traversal(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for name, member in (
                ("link.tar.gz", tarfile.TarInfo("root/link")),
                ("parent.tar.gz", tarfile.TarInfo("root/../escape")),
            ):
                archive_path = root / name
                if name.startswith("link"):
                    member.type = tarfile.SYMTYPE
                    member.linkname = "target"
                else:
                    payload = b"escape"
                    member.size = len(payload)
                with tarfile.open(archive_path, "w:gz") as archive:
                    if member.isfile():
                        archive.addfile(member, io.BytesIO(payload))
                    else:
                        archive.addfile(member)
                with self.assertRaisesRegex(ValueError, "unsafe|unsupported"):
                    BOOTSTRAP.safe_extract(archive_path, root / f"out-{name}")

    def test_cached_archive_must_match_frozen_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw)
            entry = {
                "name": "fixture",
                "commit": "a" * 40,
                "archive_size_bytes": 3,
                "archive_sha256": hashlib.sha256(b"abc").hexdigest(),
            }
            archive = cache / f"fixture-{entry['commit']}.tar.gz"
            archive.write_bytes(b"abc")
            self.assertEqual(BOOTSTRAP.acquire_archive(entry, cache), archive)
            archive.write_bytes(b"abd")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                BOOTSTRAP.acquire_archive(entry, cache)


if __name__ == "__main__":
    unittest.main()
