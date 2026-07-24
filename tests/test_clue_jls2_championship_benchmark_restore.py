"""Guards for the championship benchmark's opponent restore handling.

Attempt 2 crashed because zpaq `extract -to DIR` recreates the stored source path
as a directory tree and the harness assumed a file at a fixed path. These tests
lock in the fix: the payload is resolved as the single regular file under a
restore directory, and every opponent's decompression targets that restore
directory (never the process cwd).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "scripts" / "benchmark-clue-jls2-championship-screen-v1.py"


def load_bench():
    spec = importlib.util.spec_from_file_location("championship_benchmark", BENCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load_bench()


class ResolveRestoredTests(unittest.TestCase):
    def test_single_file_at_root(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "payload").write_bytes(b"data")
            self.assertEqual(B._resolve_restored(root), root / "payload")

    def test_single_file_nested_deep_like_zpaq_tree(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / "var" / "folders" / "corpora" / "clue-championship-e.jsonl"
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b"data")
            self.assertEqual(B._resolve_restored(root), nested)

    def test_empty_dir_is_none(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(B._resolve_restored(Path(raw)))

    def test_two_files_is_ambiguous_none(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a").write_bytes(b"a")
            (root / "b").write_bytes(b"b")
            self.assertIsNone(B._resolve_restored(root))

    def test_missing_directory_is_none(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(B._resolve_restored(Path(raw) / "absent"))


class OpponentTemplateRestoreTargetTests(unittest.TestCase):
    def test_every_opponent_restores_under_the_restore_dir(self):
        restore_dir = Path("/work/kanzi-max.clue_championship_e.restore")
        mapping = {
            "bin": "/bin/tool",
            "source": "/corpora/clue-championship-e.jsonl",
            "archive": "/work/tag.archive",
            "restored": str(restore_dir / "payload"),
            "restore_dir": str(restore_dir),
        }
        for codec_id, spec in B.OPPONENT_TEMPLATES.items():
            argv = [token.format(**mapping) for token in spec["decompress"]]
            stdout = (
                spec["decompress_stdout"].format(**mapping)
                if "decompress_stdout" in spec
                else ""
            )
            targets = " ".join(argv) + " " + stdout
            # The restore target must be under the controlled restore directory,
            # so no opponent (e.g. 7-Zip's bare `e`) extracts into the cwd.
            self.assertIn(
                str(restore_dir),
                targets,
                f"{codec_id} does not restore under the restore directory",
            )

    def test_zpaq_and_7zip_use_restore_dir_directly(self):
        for codec_id in ("zpaq-5-m54", "zpaq-5-m510", "7zip-9"):
            decompress = " ".join(B.OPPONENT_TEMPLATES[codec_id]["decompress"])
            self.assertIn("{restore_dir}", decompress, codec_id)

    def test_brotli_and_kanzi_long_option_forms_are_pinned(self):
        # The pinned brotli 1.2.0 / kanzi 2.5.3 CLIs reject space-separated long
        # options; these forms were verified against the built binaries.
        brotli = B.OPPONENT_TEMPLATES["brotli-11"]
        self.assertIn("-q", brotli["compress"])
        self.assertNotIn("--quality", " ".join(brotli["compress"]))
        kanzi = B.OPPONENT_TEMPLATES["kanzi-max"]
        self.assertIn("--level=9", kanzi["compress"])
        self.assertIn("--input={source}", kanzi["compress"])


if __name__ == "__main__":
    unittest.main()
