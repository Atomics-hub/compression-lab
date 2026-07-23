#!/usr/bin/env python3
"""Tests for the H1 loss-decomposition counted-run wrapper."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest

REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "moon-h1-decomposition-run.py"
SPEC = importlib.util.spec_from_file_location("moon_h1_decomposition_run", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load the decomposition run wrapper")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fake_kernel(root: Path) -> Path:
    """A stand-in kernel that writes a stub report at --report-out and exits 0.

    It lets the wrapper's counting and integrity logic be tested without
    building the Rust binary or reading any real corpus.
    """
    script = root / "fake_kernel.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('--report-out') + 1]\n"
        "open(out, 'w').write('{\\n  \"schema\": \"stub\"\\n}\\n')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


class DecompositionRunTests(unittest.TestCase):
    def _fixture(self, root: Path, *, snapshots: int) -> Path:
        import sys

        entries = []
        for index in range(snapshots):
            data = (f'{{"n":{index}}}\n' * 10).encode("utf-8")
            snapshot_path = root / f"snap{index}.ndjson"
            snapshot_path.write_bytes(data)
            entries.append(
                {
                    "name": f"snap{index}",
                    "path": str(snapshot_path),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "item_index": index,
                }
            )
        config = {
            "schema": MODULE.CONFIG_SCHEMA,
            "kernel_command": [sys.executable, str(_fake_kernel(root))],
            "budget_state": str(root / "run-budget.json"),
            "output_dir": str(root / "out"),
            "snapshots": entries,
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return config_path

    def test_budget_increments_once_per_run_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._fixture(root, snapshots=2)
            summary = MODULE.run(config_path)
            self.assertEqual(summary["budget"]["consumed_before"], 0)
            self.assertEqual(summary["budget"]["consumed_after"], 2)
            budget = json.loads((root / "run-budget.json").read_text(encoding="utf-8"))
            # Reuses the sweep runner's schema and cap byte-for-byte.
            self.assertEqual(budget["schema"], "moon-prescreen-budget-v1")
            self.assertEqual(budget["runs_consumed"], 2)
            self.assertEqual(budget["cap"], MODULE.RUNNER.RUN_BUDGET_CAP)
            for entry in summary["runs"]:
                self.assertEqual(entry["status"], "measured")
                self.assertTrue(Path(entry["report_path"]).is_file())

    def test_budget_carries_forward_from_an_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._fixture(root, snapshots=2)
            MODULE.RUNNER.write_budget(root / "run-budget.json", 38)
            summary = MODULE.run(config_path)
            self.assertEqual(summary["budget"]["consumed_before"], 38)
            self.assertEqual(summary["budget"]["consumed_after"], 40)

    def test_sha_mismatch_refuses_before_touching_the_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._fixture(root, snapshots=1)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["snapshots"][0]["sha256"] = "00" * 32
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.run(config_path)
            self.assertFalse((root / "run-budget.json").exists())

    def test_exhausted_budget_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._fixture(root, snapshots=1)
            MODULE.RUNNER.write_budget(
                root / "run-budget.json", MODULE.RUNNER.RUN_BUDGET_CAP
            )
            with self.assertRaises(SystemExit):
                MODULE.run(config_path)


if __name__ == "__main__":
    unittest.main()
