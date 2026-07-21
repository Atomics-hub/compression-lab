from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-context-ceiling-e2-a-v1.json"
RUNNER = ROOT / "scripts" / "benchmark-json-context-ceiling-e2-a.py"
VERIFIER = ROOT / "scripts" / "verify-json-context-ceiling-e2-a.py"
WORKFLOW = ROOT / ".github" / "workflows" / "json-context-ceiling-e2-a.yml"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class JsonContextCeilingE2ATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG.read_bytes())
        cls.runner = load(RUNNER, "e2a_runner")
        cls.verifier = load(VERIFIER, "e2a_verifier")

    def test_information_boundary_and_matrix_are_frozen(self):
        self.assertEqual(self.config["evidence_stage"], "development_only_diagnostic")
        self.assertEqual(
            [row["id"] for row in self.config["items"]],
            [
                "clue-early-development",
                "clue-middle-development",
                "clue-late-development",
            ],
        )
        self.assertEqual(
            [row["method"] for row in self.config["methods"]],
            ["54", "55", "56", "57", "510"],
        )
        boundary = self.config["information_boundary"]
        self.assertEqual(boundary["logtrie_public_validation_status"], "consumed")
        self.assertEqual(boundary["clue_public_validation_status"], "consumed")
        self.assertEqual(boundary["fresh_public_validation_status"], "none_frozen")
        self.assertIn("sealed", boundary["private_holdout_status"])

    def test_gate_integer_boundaries(self):
        baseline = self.config["e1_fixed_reference"]["kanzi_complete_bytes"]
        gates = self.config["decision_gates"]

        def gain(size):
            return (baseline - size) * 10000 // baseline

        self.assertGreaterEqual(gain(gates["advance_maximum_complete_bytes"]), 1000)
        self.assertLess(gain(gates["advance_maximum_complete_bytes"] + 1), 1000)
        self.assertGreaterEqual(
            gain(gates["refinement_band_maximum_complete_bytes"]), 700
        )
        self.assertLess(gain(gates["kill_when_complete_bytes_at_least"]), 700)

    def test_source_receipt_bindings_are_current(self):
        source = self.config["source_run"]
        publication = self.config["e1_fixed_reference"]

        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        self.assertEqual(
            digest(ROOT / source["github_recovery_receipt"]),
            source["github_recovery_receipt_sha256"],
        )
        self.assertEqual(
            digest(ROOT / publication["publication_receipt"]),
            publication["publication_receipt_sha256"],
        )
        receipt = json.loads((ROOT / publication["publication_receipt"]).read_bytes())
        self.assertEqual(
            receipt["members"]["result.json"], publication["result_member_sha256"]
        )

    def test_axe2o_independent_implementations_match(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            trials = []
            runner_items = []
            for index, item_id in enumerate(("b", "a")):
                archive = root / f"{item_id}.zpaq"
                archive.write_bytes(bytes([index + 1]) * (index + 3))
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                trial = {
                    "item_id": item_id,
                    "source_bytes": 10 + index,
                    "source_sha256": "00" * 32,
                    "archive": {
                        "path": archive.name,
                        "bytes": archive.stat().st_size,
                        "sha256": digest,
                    },
                }
                trials.append(trial)
                runner_items.append(
                    {
                        "item_id": item_id,
                        "source_bytes": 10 + index,
                        "source_sha256": "00" * 32,
                        "archive_absolute": str(archive),
                    }
                )
            manifest_digest = "11" * 32
            one = self.runner.axe2o(
                "json_logs", manifest_digest, "zpaq-5-m54", runner_items
            )
            two = self.verifier.build_axe2o(
                "json_logs", manifest_digest, "zpaq-5-m54", trials, root
            )
            self.assertEqual(one, two)

    def test_e1_reference_recomputes_from_pinned_raw_results_when_available(self):
        practical = Path("/tmp/e1-practical-json/result.json")
        zpaq = Path("/tmp/e1-zpaq-json/result.json")
        if not practical.exists() or not zpaq.exists():
            self.skipTest("optional pinned E1 artifacts not downloaded")
        reference = self.runner.verify_e1_reference(self.config, practical, zpaq)
        self.assertEqual(reference["practical_complete_bytes"]["kanzi-max"], 1712149)
        self.assertEqual(reference["zpaq_510_complete_bytes"], 1347064)

    def test_workflow_is_manual_main_only_and_rechecks_decodes(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', workflow)
        self.assertIn("--recheck-decodes", workflow)
        self.assertIn("run-id: 29846879040", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)


if __name__ == "__main__":
    unittest.main()
