from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "benchmark-frontier-headroom-e1.py"
WORKFLOW = ROOT / ".github" / "workflows" / "frontier-headroom-e1-training.yml"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load("frontier_headroom_e1_runner_test", RUNNER_PATH)


class FrontierHeadroomE1RunnerTests(unittest.TestCase):
    def test_axe1s_counts_exact_header_metadata_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "source.bin"
            source.write_bytes(bytes(range(100)))
            item = {
                "id": "fixture",
                "bytes": 100,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            ranges = [{"offset": index * 20, "length": 1} for index in range(5)]
            frame = RUNNER.axe1s("fixture_category", item, source, ranges)
            self.assertEqual(frame[:6], b"AXE1S\x01")
            expected_header = (
                5
                + 1
                + len(RUNNER.packed_string("fixture_category"))
                + len(RUNNER.packed_string("fixture"))
                + 8
                + 32
                + 1
                + 5 * 16
                + 8
                + 32
            )
            self.assertEqual(len(frame), expected_header + 5)
            self.assertEqual(frame[-5:], bytes([0, 20, 40, 60, 80]))

    def test_axe1g_counts_complete_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "a.bin"
            second = root / "b.bin"
            first.write_bytes(b"abc")
            second.write_bytes(b"defgh")
            item = {
                "id": "item",
                "bytes": 8,
                "sha256": hashlib.sha256(b"abcdefgh").hexdigest(),
            }
            choices = []
            for codec, path, payload in (
                ("kanzi-max", first, b"abc"),
                ("xz-lzma2-9e", second, b"defgh"),
            ):
                choices.append(
                    {
                        "codec_id": codec,
                        "decoded_bytes": len(payload),
                        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
                        "artifact_bytes": len(payload),
                        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
                        "artifact_path": str(path),
                    }
                )
            frame = RUNNER.axe1g(item, 3, choices)
            self.assertEqual(frame[:6], b"AXE1G\x01")
            self.assertTrue(frame.endswith(b"abcdefgh"))
            self.assertGreater(
                len(frame), sum(row["artifact_bytes"] for row in choices)
            )

    @unittest.skipUnless(
        all(hasattr(os, name) for name in ("wait4", "killpg", "setsid")),
        "E1 hosted measurements require POSIX wait4 and process groups",
    )
    def test_bounded_process_records_wait4_and_exact_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = root / "result"
            result.mkdir()
            source = root / "source.bin"
            source.write_bytes(b"bounded-exact-data")
            task = {
                "task_id": "whole/kanzi-max/fixture",
                "phase": "whole_item",
                "codec_id": "kanzi-max",
                "item_id": "fixture",
                "category": "fixture",
                "compress": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('$WORK/artifact.bin').write_bytes(Path('$WORK/input.bin').read_bytes())",
                ],
                "decompress": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('$WORK/restored.bin').write_bytes(Path('$WORK/artifact.bin').read_bytes())",
                ],
            }
            row = RUNNER.run_repetition(
                task,
                source,
                root,
                result,
                0,
                retained=True,
                timeout_seconds=10,
            )
            self.assertTrue(row["exact"])
            self.assertEqual(row["artifact_bytes"], len(b"bounded-exact-data"))
            self.assertGreater(row["compress"]["wall_ns"], 0)
            self.assertGreater(row["compress"]["peak_rss_bytes"], 0)
            self.assertEqual(row["compress"]["declared_command"], task["compress"])

    def test_whole_trigger_uses_complete_axe1o_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = []
            codecs = ("kanzi-max", "zstd-19-long", "xz-lzma2-9e", "zpaq-5-m510")
            for index, codec in enumerate(codecs):
                path = Path(raw) / f"{codec}.json"
                trials = []
                for item_index, item in enumerate(("a", "b")):
                    size = 1000 + index * 20
                    if item_index == 1 and codec == "zstd-19-long":
                        size = 800
                    digest = hashlib.sha256(f"{codec}:{item}".encode()).hexdigest()
                    trials.append(
                        {
                            "codec_id": codec,
                            "item_id": item,
                            "exact": True,
                            "deterministic": True,
                            "repetitions": [
                                {
                                    "source_bytes": 2000,
                                    "source_sha256": "1" * 64,
                                    "artifact_bytes": size,
                                    "artifact_sha256": digest,
                                }
                            ],
                        }
                    )
                path.write_text(
                    json.dumps(
                        {
                            "phase": "whole",
                            "category": "fixture",
                            "trials": trials,
                            "public_validation_accessed": False,
                            "private_holdout_accessed": False,
                        }
                    )
                )
                paths.append(path)
            triggered, winners = RUNNER.whole_choices(paths, "fixture")
            self.assertTrue(triggered)
            self.assertEqual(winners["b"]["codec_id"], "zstd-19-long")

    def test_workflow_freezes_tools_before_training_and_is_manual_only(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("\n  push:", text)
        self.assertIn("needs: freeze-tools-and-schedule", text)
        self.assertIn("RUN_E1_TRAINING_ONLY", text)
        self.assertIn("--split development", text)
        self.assertNotIn("--allow-public-validation", text)
        self.assertIn("--phase segment", text)
        self.assertEqual(
            text.count("/opt/homebrew/Cellar/cmake/4.4.0/bin/cmake"), 2
        )
        self.assertIn("brew install cmake zstd xz lz4", text)
        self.assertIn(
            "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", text
        )


if __name__ == "__main__":
    unittest.main()
