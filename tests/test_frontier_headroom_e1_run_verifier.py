from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-frontier-headroom-e1-run.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load("frontier_headroom_e1_run_verifier_test", SCRIPT)


class FrontierHeadroomE1RunVerifierTests(unittest.TestCase):
    def test_legacy_recovery_is_explicit_and_pinned_to_one_run(self) -> None:
        schedule = {
            "repository_commit": "ee0b98180393034da73afc5eee139036f87b91b0"
        }
        self.assertIsNone(VERIFIER.load_recovery_receipt(None, schedule))
        with self.assertRaisesRegex(ValueError, "not the pinned failed run"):
            VERIFIER.load_recovery_receipt(1, schedule)
        receipt = VERIFIER.load_recovery_receipt(29846879040, schedule)
        self.assertEqual(receipt["source_run_attempt"], 1)
        self.assertEqual(len(receipt["artifacts"]), 28)

    def test_legacy_warmup_logs_are_exactly_inventoried_and_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            task_id = "whole/kanzi-max/fixture"
            base = root / "logs" / task_id.replace("/", "__") / "-1"
            base.mkdir(parents=True)
            expected = []
            for name in (
                "compress.stderr",
                "compress.stdout",
                "decompress.stderr",
                "decompress.stdout",
            ):
                path = base / name
                payload = name.encode()
                path.write_bytes(payload)
                expected.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            bound = {"result.json"}
            records = VERIFIER.bind_discarded_warmup_logs(
                {"trials": [{"task_id": task_id, "codec_id": "kanzi-max"}]},
                root,
                bound,
                {"measurement": {"warmups_practical": 1}},
            )
            self.assertEqual(
                sorted(records, key=lambda row: row["path"]),
                sorted(expected, key=lambda row: row["path"]),
            )
            self.assertEqual(bound, {"result.json", *(row["path"] for row in expected)})

    def test_legacy_warmup_binding_requires_the_full_expected_roster(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "logs" / "whole__kanzi-max__fixture" / "-1"
            base.mkdir(parents=True)
            (base / "compress.stderr").write_bytes(b"")
            with self.assertRaises(ValueError):
                VERIFIER.bind_discarded_warmup_logs(
                    {
                        "trials": [
                            {
                                "task_id": "whole/kanzi-max/fixture",
                                "codec_id": "kanzi-max",
                            }
                        ]
                    },
                    root,
                    {"result.json"},
                    {"measurement": {"warmups_practical": 1}},
                )

    def test_xz_legacy_warmup_roster_has_no_stdout_logs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            task_id = "whole/xz-lzma2-9e/fixture"
            base = root / "logs" / task_id.replace("/", "__") / "-1"
            base.mkdir(parents=True)
            for name in ("compress.stderr", "decompress.stderr"):
                (base / name).write_bytes(b"")
            records = VERIFIER.bind_discarded_warmup_logs(
                {"trials": [{"task_id": task_id, "codec_id": "xz-lzma2-9e"}]},
                root,
                {"result.json"},
                {"measurement": {"warmups_practical": 1}},
            )
            self.assertEqual(len(records), 2)
            self.assertTrue(all(row["path"].endswith("stderr") for row in records))

    def test_zpaq_has_no_legacy_warmup_roster(self) -> None:
        records = VERIFIER.bind_discarded_warmup_logs(
            {
                "trials": [
                    {"task_id": "whole/zpaq-5-m510/fixture", "codec_id": "zpaq-5-m510"}
                ]
            },
            Path("/does/not/need/to/exist"),
            {"result.json"},
            {"measurement": {"warmups_practical": 1}},
        )
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
