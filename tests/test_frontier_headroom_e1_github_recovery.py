from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-frontier-headroom-e1-github-recovery.py"
PINNED = ROOT / "config" / "frontier-headroom-e1-run-29846879040-recovery.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY = load("frontier_headroom_e1_github_recovery_test", SCRIPT)


class FrontierHeadroomE1GitHubRecoveryTests(unittest.TestCase):
    def test_pinned_live_metadata_verifies_and_digest_drift_fails(self) -> None:
        pinned = json.loads(PINNED.read_bytes())
        run = {
            "id": pinned["source_run_id"],
            "run_attempt": pinned["source_run_attempt"],
            "head_sha": pinned["source_head_sha"],
            "event": pinned["source_event"],
            "conclusion": pinned["source_conclusion"],
            "html_url": pinned["source_url"],
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run_path = root / "run.json"
            artifacts_path = root / "artifacts.json"
            run_path.write_text(json.dumps(run), encoding="utf-8")
            artifacts_path.write_text(
                json.dumps({"artifacts": pinned["artifacts"]}), encoding="utf-8"
            )
            self.assertEqual(
                RECOVERY.verify(PINNED, run_path, artifacts_path), pinned
            )
            changed = json.loads(artifacts_path.read_text(encoding="utf-8"))
            changed["artifacts"][0]["digest"] = "sha256:" + "0" * 64
            artifacts_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "roster or digest"):
                RECOVERY.verify(PINNED, run_path, artifacts_path)


if __name__ == "__main__":
    unittest.main()
