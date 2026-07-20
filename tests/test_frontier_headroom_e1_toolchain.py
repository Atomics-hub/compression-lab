from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "frontier-headroom-e1-toolchain-v1.json"
E1_CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load(
    "frontier_headroom_e1_toolchain_test_verifier",
    ROOT / "scripts" / "verify-frontier-headroom-e1-toolchain.py",
)
PREPARE = load(
    "frontier_headroom_e1_toolchain_test_prepare",
    ROOT / "scripts" / "prepare-frontier-headroom-e1-toolchain.py",
)
EXECUTION = load(
    "frontier_headroom_e1_toolchain_test_execution",
    ROOT / "scripts" / "prepare-frontier-headroom-e1-execution.py",
)


class FrontierHeadroomE1ToolchainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(CONFIG.read_bytes())
        self.e1 = json.loads(E1_CONFIG.read_bytes())

    def test_declaration_binds_frozen_e1_sources_binaries_and_runtime(self) -> None:
        self.assertEqual(VERIFIER.validate_declaration(self.config), self.e1)
        self.assertEqual(
            [row["codec_id"] for row in self.config["sources"]],
            list(VERIFIER.EXPECTED_SOURCE_IDS),
        )
        self.assertEqual(
            [row["codec_id"] for row in self.config["executables"]],
            list(VERIFIER.EXPECTED_EXECUTABLE_IDS),
        )
        e1_hashes = {row["id"]: row["binary_sha256"] for row in self.e1["codecs"]}
        for row in self.config["executables"]:
            self.assertEqual(row["sha256"], e1_hashes[row["codec_id"]])
        self.assertEqual(
            {row["path"] for row in self.config["runtime_assets"]},
            set(VERIFIER.EXPECTED_RUNTIME_IDS),
        )
        self.assertEqual(
            {
                row["codec_id"]: (row["bytes"], row["sha256"])
                for row in self.config["executables"]
            },
            VERIFIER.EXPECTED_EXECUTABLE_IDS,
        )
        self.assertEqual(
            {
                row["path"]: (row["bytes"], row["sha256"])
                for row in self.config["runtime_assets"]
            },
            VERIFIER.EXPECTED_RUNTIME_IDS,
        )

    def test_source_and_build_drift_fail_closed(self) -> None:
        drifted = copy.deepcopy(self.config)
        drifted["sources"][1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source identity differs"):
            VERIFIER.validate_declaration(drifted)
        drifted = copy.deepcopy(self.config)
        drifted["sources"][0]["build_commands"][0].append("-DUNDECLARED=ON")
        with self.assertRaisesRegex(ValueError, "metadata or build commands differ"):
            VERIFIER.validate_declaration(drifted)
        drifted = copy.deepcopy(self.config)
        drifted["executables"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "executable identity differs"):
            VERIFIER.validate_declaration(drifted)
        drifted = copy.deepcopy(self.config)
        drifted["runtime_assets"][0]["bytes"] += 1
        with self.assertRaisesRegex(ValueError, "runtime asset identities differ"):
            VERIFIER.validate_declaration(drifted)

    def test_only_official_https_hosts_are_admitted(self) -> None:
        hosts = set(self.config["security_boundary"]["allowed_hosts"])
        PREPARE.require_official_url(
            "https://release-assets.githubusercontent.com/asset", hosts
        )
        for url in (
            "http://github.com/file",
            "https://example.com/file",
            "https://user:secret@github.com/file",
        ):
            with self.assertRaisesRegex(ValueError, "official allowlist"):
                PREPARE.require_official_url(url, hosts)

    def test_tool_roster_rejects_extra_files_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "extra").write_bytes(b"x")
            self.assertEqual(VERIFIER.directory_roster(root), ["extra"])
            (root / "link").symlink_to(root / "extra")
            with self.assertRaisesRegex(ValueError, "symlink"):
                VERIFIER.directory_roster(root)

    def test_process_policy_closes_timeout_group_rss_and_output(self) -> None:
        policy = self.config["platform_lock"]["measurement_process_policy"]
        self.assertEqual(policy["jobs"], 1)
        self.assertEqual(policy["timeout_seconds"], 86400)
        self.assertTrue(policy["new_session_per_process"])
        self.assertTrue(policy["kill_process_group_on_timeout"])
        self.assertEqual(policy["final_signal"], "SIGKILL")
        self.assertEqual(
            policy["peak_rss_source"], "POSIX wait4 direct-child ru_maxrss"
        )
        self.assertEqual(policy["darwin_rss_unit_bytes"], 1)
        self.assertEqual(policy["linux_rss_unit_bytes"], 1024)
        self.assertEqual(policy["stdout_stderr_limit_bytes_each"], 1024 * 1024)

    def test_offline_execution_matrix_is_complete_and_exactly_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tool_root = Path(raw)
            receipt = tool_root / "receipt.json"
            receipt.write_bytes(b"sealed-receipt")
            plan = EXECUTION.build_plan(
                self.config,
                self.e1,
                tool_root=tool_root,
                config_sha256=VERIFIER.sha256_file(CONFIG),
                e1_config_sha256=VERIFIER.sha256_file(E1_CONFIG),
                receipt_sha256=VERIFIER.sha256_file(receipt),
                repository_commit="0" * 40,
            )
            VERIFIER.validate_plan(plan, self.config, receipt)
            self.assertEqual(len(plan["whole_item_tasks"]), 68)
            self.assertEqual(len(plan["sample_tasks"]), 68)
            self.assertEqual(len(plan["conditional_segment_templates"]), 68)
            self.assertFalse(plan["corpus_accessed"])
            self.assertFalse(plan["measurements_exist"])
            self.assertTrue(
                all(not row["corpus_accessed"] for row in plan["whole_item_tasks"])
            )
            self.assertTrue(
                all(
                    "$WORK" in " ".join(row["compress"])
                    for row in plan["whole_item_tasks"]
                )
            )
            zpaq_task = next(
                row
                for row in plan["whole_item_tasks"]
                if row["codec_id"] == "zpaq-5-m510"
            )
            to_index = zpaq_task["decompress"].index("-to")
            self.assertEqual(zpaq_task["decompress"][to_index + 1], "$WORK/restored")
            self.assertNotIn("$WORK/restored.bin_DIRECTORY", zpaq_task["decompress"])

            drifted = copy.deepcopy(plan)
            drifted["whole_item_tasks"][0]["compress"].append("--unfrozen")
            with self.assertRaisesRegex(ValueError, "whole-item execution matrix"):
                VERIFIER.validate_plan(drifted, self.config, receipt)
            drifted = copy.deepcopy(plan)
            drifted["sample_tasks"][0]["ranges"][0]["offset"] += 1
            with self.assertRaisesRegex(ValueError, "sample execution matrix"):
                VERIFIER.validate_plan(drifted, self.config, receipt)
            drifted = copy.deepcopy(plan)
            drifted["conditional_segment_templates"][0]["status"] = "executed"
            with self.assertRaisesRegex(ValueError, "segment template matrix"):
                VERIFIER.validate_plan(drifted, self.config, receipt)

    def test_sample_range_helper_rejects_malformed_sizes(self) -> None:
        with self.assertRaisesRegex(ValueError, "sample size differs"):
            VERIFIER.e1_sample_ranges(0)
        with self.assertRaisesRegex(ValueError, "sample size differs"):
            VERIFIER.e1_sample_ranges(True)

    def test_corpus_barrier_and_claim_ceiling_are_explicit(self) -> None:
        boundary = self.config["security_boundary"]
        self.assertIn("No corpus path", boundary["corpus_barrier"])
        self.assertIn("performs zero corpus access", boundary["failure_policy"])
        claim = self.config["execution_plan"]["claim_ceiling"]
        self.assertIn("no compression result", claim)
        self.assertIn("state-of-the-art", claim)


if __name__ == "__main__":
    unittest.main()
