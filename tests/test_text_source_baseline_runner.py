from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark-text-source-baselines.py"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "benchmark_text_source_baselines", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


RUNNER = load_module()


class TextSourceBaselineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tools = {
            name: {"path": f"/tools/{name}"}
            for name in (
                "gzip",
                "bzip2",
                "bzip3",
                "zstd",
                "brotli",
                "xz",
                "7zz",
                "lz4",
                "kanzi",
                "libbsc",
            )
        }
        self.source = Path("/data/source")
        self.artifact = Path("/work/artifact")
        self.restored = Path("/work/restored")

    def command(self, codec_id):
        return RUNNER.codec_commands(
            codec_id, self.tools, self.source, self.artifact, self.restored
        )

    def test_strong_settings_are_explicit_and_single_threaded(self):
        bzip3 = self.command("bzip3-max")[0]
        self.assertIn("--block=511", bzip3)
        self.assertIn("--jobs=1", bzip3)
        ultra = self.command("zstd-22-ultra")[0]
        self.assertIn("--ultra", ultra)
        self.assertIn("-22", ultra)
        self.assertIn("-T1", ultra)
        kanzi = self.command("kanzi-max")[0]
        self.assertIn("--level=9", kanzi)
        self.assertIn("--block=1g", kanzi)
        self.assertIn("--jobs=1", kanzi)
        libbsc = self.command("libbsc-max")[0]
        self.assertIn("-b512", libbsc)
        self.assertIn("-e2", libbsc)

    def test_7zip_artifact_counts_the_complete_archive(self):
        for codec in ("7zip-lzma2-9", "7zip-ppmd-9"):
            compress, stdout, decompress, restored_stdout = self.command(codec)
            self.assertIn("-t7z", compress)
            self.assertIn(str(self.artifact), compress)
            self.assertIsNone(stdout)
            self.assertIn("-so", decompress)
            self.assertEqual(restored_stdout, self.restored)

    def test_summary_requires_exact_deterministic_repetitions(self):
        items = [
            {
                "id": "one",
                "track": "source_code_bundles",
                "source_bytes": 100,
            }
        ]

        def trial(repetition, digest="a" * 64, passed=True):
            return {
                "warmup": False,
                "codec_id": "store",
                "item_id": "one",
                "artifact_sha256": digest,
                "artifact_bytes": 100,
                "passed": passed,
                "error": None if passed else "failure",
                "compression": {"wall_ns": 1000, "peak_rss_bytes": 10},
                "decompression": {"wall_ns": 2000, "peak_rss_bytes": 20},
                "repetition": repetition,
            }

        valid = RUNNER.summarize(
            [trial(index) for index in range(1, 6)], ["store"], items, 5
        )
        row = valid["item_codec_rows"][0]
        self.assertTrue(row["passed"])
        self.assertTrue(row["deterministic_artifact"])
        self.assertEqual(
            valid["tracks"]["source_code_bundles"]["leader"]["codec_id"], "store"
        )
        invalid = RUNNER.summarize(
            [
                trial(index, digest=("b" * 64 if index == 5 else "a" * 64))
                for index in range(1, 6)
            ],
            ["store"],
            items,
            5,
        )
        self.assertFalse(invalid["item_codec_rows"][0]["passed"])

    def test_resumed_trial_requires_complete_frozen_identity(self):
        item = {
            "id": "one",
            "track": "source_code_bundles",
            "source_bytes": 100,
            "source_sha256": "a" * 64,
            "path": str(
                ROOT
                / "corpora"
                / "text-source-development-v1"
                / "one.axsrc"
            ),
        }
        bindings = {"repository_commit": "abc"}
        work = Path("$WORK")
        compress, _c_out, decompress, _d_out = RUNNER.codec_commands(
            "store",
            self.tools,
            Path(item["path"]),
            work / "artifact.bin",
            work / "restored.bin",
        )

        def process(command):
            return {
                "command": RUNNER.sanitize_process_record(
                    {"command": command}, work
                )["command"],
                "returncode": 0,
                "timed_out": False,
                "wall_ns": 1,
                "cpu_ns": 1,
                "peak_rss_bytes": 1,
                "stdout": "",
                "stderr": "",
            }

        existing = {
            "schema_version": 1,
            "bindings": bindings,
            "codec_id": "store",
            "item_id": "one",
            "track": "source_code_bundles",
            "repetition": 1,
            "warmup": False,
            "source_bytes": 100,
            "source_sha256": "a" * 64,
            "artifact_bytes": 100,
            "artifact_sha256": "b" * 64,
            "compression": process(compress),
            "decompression": process(decompress),
            "exact_roundtrip": True,
            "passed": True,
            "error": None,
        }
        RUNNER.validate_existing_trial(
            existing,
            bindings=bindings,
            codec_id="store",
            item=item,
            repetition=1,
            tools=self.tools,
            destination=Path("one.r1.json"),
        )
        existing["item_id"] = "different"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            RUNNER.validate_existing_trial(
                existing,
                bindings=bindings,
                codec_id="store",
                item=item,
                repetition=1,
                tools=self.tools,
                destination=Path("one.r1.json"),
            )

    def test_resumed_trial_rejects_changed_command(self):
        item = {
            "id": "one",
            "track": "source_code_bundles",
            "source_bytes": 100,
            "source_sha256": "a" * 64,
            "path": str(
                ROOT
                / "corpora"
                / "text-source-development-v1"
                / "one.axsrc"
            ),
        }
        bindings = {"repository_commit": "abc"}
        work = Path("$WORK")
        compress, _c_out, decompress, _d_out = RUNNER.codec_commands(
            "store",
            self.tools,
            Path(item["path"]),
            work / "artifact.bin",
            work / "restored.bin",
        )

        def process(command):
            return {
                "command": RUNNER.sanitize_process_record(
                    {"command": command}, work
                )["command"],
                "returncode": 0,
                "timed_out": False,
                "wall_ns": 1,
                "cpu_ns": 1,
                "peak_rss_bytes": 1,
                "stdout": "",
                "stderr": "",
            }

        receipt = {
            "schema_version": 1,
            "bindings": bindings,
            "codec_id": "store",
            "item_id": "one",
            "track": "source_code_bundles",
            "repetition": 1,
            "warmup": False,
            "source_bytes": 100,
            "source_sha256": "a" * 64,
            "artifact_bytes": 100,
            "artifact_sha256": "b" * 64,
            "compression": process(compress),
            "decompression": process(decompress),
            "exact_roundtrip": True,
            "passed": True,
            "error": None,
        }
        receipt["compression"]["command"][0] = "different"
        with self.assertRaisesRegex(ValueError, "compression record is invalid"):
            RUNNER.validate_existing_trial(
                receipt,
                bindings=bindings,
                codec_id="store",
                item=item,
                repetition=1,
                tools=self.tools,
                destination=Path("one.r1.json"),
            )


if __name__ == "__main__":
    unittest.main()
