#!/usr/bin/env python3
"""Static, no-data guards for the prospective C1 residual diagnostic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/moon-c1-residual-diagnostic-readiness-v1.json"
CHARTER_PATH = (
    ROOT / "docs/benchmarks/2026-08-23-moon-c1-residual-diagnostic-readiness-v1.md"
)
IMPLEMENTATION = "f264c53da7d9d15aed1333efefcaabc113395793"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


class C1ResidualDiagnosticReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_bytes())
        cls.charter = CHARTER_PATH.read_text(encoding="utf-8")

    def test_package_is_prospective_and_has_no_authority(self) -> None:
        self.assertEqual(
            set(self.config),
            {
                "schema",
                "status",
                "evidence_stage",
                "identity",
                "instrument",
                "retained_snapshot_identity",
                "output_roster",
                "runtime",
                "memory_and_claim_ceiling",
                "authority",
                "accepted_limitations",
                "procedure",
                "package_bindings",
            },
        )
        self.assertEqual(
            self.config["schema"], "moon-c1-residual-diagnostic-readiness-v1"
        )
        self.assertEqual(self.config["status"], "READY_TO_AUTHORIZE_PROSPECTIVE")
        authority = self.config["authority"]
        self.assertEqual(
            set(authority),
            {
                "attempts_authorized",
                "execution_currently_authorized",
                "retained_snapshot_read_authorized",
                "candidate_execution_authorized",
                "scoring_authorized",
                "corpus_advancement_authorized",
                "run_budget_advancement_authorized",
                "ledger_advancement_authorized",
                "exact_owner_literal_template",
                "binding_rule",
            },
        )
        self.assertEqual(authority["attempts_authorized"], 0)
        for key, value in authority.items():
            if key.endswith("_authorized") and key != "attempts_authorized":
                self.assertIs(value, False, key)
        self.assertEqual(
            authority["exact_owner_literal_template"],
            "Authorize Moon C1 residual diagnostic at readiness commit "
            "{FINAL_READINESS_COMMIT}",
        )
        self.assertIn("full 40-hex final readiness commit", authority["binding_rule"])
        for publication in (
            "two listed diagnostic reports",
            "sweep-summary.json",
            "SHA256SUMS",
        ):
            self.assertIn(publication, authority["binding_rule"])
        self.assertRegex(
            self.charter,
            r"Authorize Moon C1 residual diagnostic at readiness commit "
            r"\{FINAL_READINESS_COMMIT\}",
        )

    def test_implementation_commit_tree_parent_and_sources_are_exact(self) -> None:
        identity = self.config["identity"]
        self.assertEqual(identity["implementation_commit"], IMPLEMENTATION)
        self.assertEqual(
            git("rev-parse", f"{IMPLEMENTATION}^"),
            identity["implementation_base_commit"],
        )
        self.assertEqual(
            git("rev-parse", f"{IMPLEMENTATION}^{{tree}}"),
            identity["implementation_tree"],
        )
        self.assertEqual(
            identity["readiness_diff_roster"],
            [
                "config/moon-c1-residual-diagnostic-readiness-v1.json",
                "docs/benchmarks/2026-08-23-moon-c1-residual-diagnostic-readiness-v1.md",
                "scripts/moon-c1-residual-diagnostic-run.py",
                "tests/test_moon_c1_residual_diagnostic_readiness.py",
                "tests/test_moon_c1_residual_diagnostic_run.py",
            ],
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", IMPLEMENTATION, "HEAD"],
            cwd=ROOT,
            check=True,
        )
        for relative, expected in identity["source_sha256"].items():
            path = ROOT / relative
            self.assertEqual(sha256(path), expected, relative)
            committed = subprocess.check_output(
                ["git", "show", f"{IMPLEMENTATION}:{relative}"], cwd=ROOT
            )
            self.assertEqual(hashlib.sha256(committed).hexdigest(), expected, relative)
        for relative, expected in identity["build_inputs_sha256"].items():
            self.assertEqual(sha256(ROOT / relative), expected, relative)

    def test_cli_schema_and_complete_synthetic_golden_are_bound(self) -> None:
        instrument = self.config["instrument"]
        self.assertEqual(instrument["subcommand"], "diagnose-c1")
        self.assertEqual(
            instrument["report_schema"], "clab-moon-c1-residual-diagnostic-v2"
        )
        self.assertEqual(instrument["sse_bucket_bits"], 17)
        self.assertEqual(instrument["kernel_version"], "0.1.0")
        self.assertIn(
            'version = "0.1.0"',
            (ROOT / "native/Cargo.toml").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            instrument["report_claim_ceiling"],
            "mechanism-local attribution and hindsight upper bounds only; no "
            "input-class, ratio, corpus, realizable-gain, candidate, SOTA, or "
            "product claim",
        )
        golden = instrument["synthetic_complete_event_golden"]
        self.assertEqual(golden["item_index"], 7)
        self.assertEqual(golden["source_utf8"], "aaaaaa-aaaaaaXaaaaaa\n")
        self.assertEqual(
            golden["real_cli_complete_report_sha256"],
            "ae5502fd1e3248d54249a63edc8e6bfca7a0bb6ad5e533780c7c97da84b90862",
        )
        self.assertEqual(
            golden["real_cli_tape_sha256"],
            "66b9015b8f2d0f2b161be21f6f6b0326a57b1636ff3a02bd664108b76c952ddd",
        )
        source = (ROOT / "native/src/moon/c1_diagnose.rs").read_text(encoding="utf-8")
        for value in (
            instrument["report_schema"],
            golden["charged_event_digest_sha256"],
            golden["complete_report_sha256"],
        ):
            self.assertIn(value, source)
        cli = (ROOT / "native/src/bin/clab-moon-kernel.rs").read_text(encoding="utf-8")
        self.assertIn('Some((&"diagnose-c1", rest))', cli)

    def test_readiness_runner_charter_and_tests_are_content_bound(self) -> None:
        bindings = self.config["package_bindings"]
        self.assertEqual(
            set(bindings),
            {
                "scripts/moon-c1-residual-diagnostic-run.py",
                "docs/benchmarks/2026-08-23-moon-c1-residual-diagnostic-readiness-v1.md",
                "tests/test_moon_c1_residual_diagnostic_run.py",
                "tests/test_moon_c1_residual_diagnostic_readiness.py",
            },
        )
        for relative, expected in bindings.items():
            self.assertEqual(sha256(ROOT / relative), expected, relative)

    def test_retained_identities_reconcile_without_reading_snapshot_files(self) -> None:
        retained = self.config["retained_snapshot_identity"]
        for metadata in retained["metadata_sources"]:
            path = ROOT / metadata["path"]
            self.assertEqual(sha256(path), metadata["sha256"])
            self.assertEqual(
                git("rev-parse", f"{IMPLEMENTATION}:{metadata['path']}"),
                metadata["git_blob"],
            )
        prescreen = json.loads(
            (ROOT / retained["metadata_sources"][0]["path"]).read_bytes()
        )
        references = json.loads(
            (ROOT / retained["metadata_sources"][1]["path"]).read_bytes()
        )["snapshots"]
        self.assertEqual(len(retained["snapshots"]), 2)
        for expected in retained["snapshots"]:
            rows = [
                row for row in prescreen["snapshots"] if row["name"] == expected["name"]
            ]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            for key in ("item_index", "source_bytes", "source_sha256"):
                self.assertEqual(row[key], expected[key], (expected["name"], key))
            reference = references[expected["name"]]
            self.assertEqual(reference["source_bytes"], expected["source_bytes"])
            self.assertEqual(reference["source_sha256"], expected["source_sha256"])

    def test_output_roster_memory_and_claim_ceiling_are_exact(self) -> None:
        self.assertEqual(
            self.config["output_roster"],
            [
                "runs/moon-c1-residual-diagnostic-v1/"
                "gharchive-2026-05-15-14-s24__c1-residual-diagnostic.report.json",
                "runs/moon-c1-residual-diagnostic-v1/"
                "gharchive-2026-06-15-14-s24__c1-residual-diagnostic.report.json",
                "runs/moon-c1-residual-diagnostic-v1/sweep-summary.json",
                "runs/moon-c1-residual-diagnostic-v1/SHA256SUMS",
            ],
        )
        ceiling = self.config["memory_and_claim_ceiling"]
        self.assertEqual(ceiling["accounted_concurrent_logical_bytes_max"], 1 << 29)
        self.assertIn("not an RSS measurement", ceiling["memory_semantics"])
        for forbidden in (
            "input-class",
            "ratio",
            "realizable-gain",
            "candidate",
            "SOTA",
            "championship",
            "product",
            "funding",
        ):
            self.assertIn(forbidden, ceiling["claim_ceiling"])
        self.assertIs(ceiling["shadow_rows_direct_funding_evidence"], False)
        self.assertIs(ceiling["shadow_rows_realizable_gain_evidence"], False)
        self.assertEqual(ceiling["aggregation_struct_bytes_frozen_target"], 952)

    def test_runtime_budget_toolchain_and_attempt_identity_are_exact(self) -> None:
        runtime = self.config["runtime"]
        self.assertEqual(
            set(runtime),
            {
                "references",
                "shared_budget_path",
                "shared_budget_schema",
                "shared_budget_cap",
                "expected_consumed_before",
                "expected_consumed_after",
                "durable_attempt_ref",
                "build_environment_allowlist",
                "kernel_runtime_environment_names",
                "toolchain",
                "charge_timing",
                "concurrency_rule",
            },
        )
        self.assertEqual(
            runtime["shared_budget_path"],
            "/Users/guts/Documents/axiom-moonshot-corpora/run-budget.json",
        )
        self.assertEqual(
            (runtime["expected_consumed_before"], runtime["expected_consumed_after"]),
            (52, 54),
        )
        self.assertEqual(
            runtime["durable_attempt_ref"],
            "refs/moon/c1-residual-diagnostic-v1/attempt",
        )
        self.assertEqual(
            set(runtime["toolchain"]),
            {
                "cargo_path",
                "cargo_sha256",
                "cargo_version",
                "rustc_path",
                "rustc_sha256",
                "rustc_version",
                "clang_path",
                "clang_sha256",
                "clang_version",
                "git_path",
                "git_sha256",
                "git_version",
                "fixed_path",
                "developer_dir",
                "sdkroot",
                "cargo_source_home",
                "rustup_home",
                "fixed_build_root",
                "remap_path_prefix",
                "expected_release_binary_sha256",
            },
        )
        self.assertEqual(runtime["build_environment_allowlist"], [])
        self.assertEqual(
            runtime["kernel_runtime_environment_names"], ["LC_ALL", "PATH", "TMPDIR"]
        )
        for key in (
            "cargo_sha256",
            "rustc_sha256",
            "clang_sha256",
            "git_sha256",
            "expected_release_binary_sha256",
        ):
            self.assertRegex(runtime["toolchain"][key], r"^[0-9a-f]{64}$")
        self.assertIn("does consume exactly two", self.charter)
        self.assertNotIn("consume a Moon run-budget entry", self.charter)

    def test_all_four_accepted_limitations_are_prominent_and_lockstep(self) -> None:
        limitations = self.config["accepted_limitations"]
        self.assertEqual(len(limitations), 4)
        required = (
            "Acc size wording tension",
            "Post-link cleanup ambiguity",
            "Shadow collision-test evidence limitation",
            "prohibited as direct funding evidence",
        )
        for phrase, limitation in zip(required, limitations):
            self.assertIn(phrase, limitation)
            self.assertIn(phrase, self.charter)
        self.assertIn("not a direct allocation or RSS measurement", limitations[0])
        self.assertIn("destination may already be validly published", limitations[1])
        self.assertIn("full production-width end-to-end", limitations[2])
        self.assertIn("realizable-gain evidence", limitations[3])

    def test_authorized_runner_and_procedure_are_fail_closed(self) -> None:
        procedure = self.config["procedure"]
        self.assertEqual(
            procedure["runner"], "scripts/moon-c1-residual-diagnostic-run.py"
        )
        self.assertIn("temporary synthetic snapshots", procedure["rehearsal"])
        self.assertIn("materializes f264c53", procedure["rehearsal"])
        self.assertIn("complete report/event/tape goldens", procedure["rehearsal"])
        self.assertIn("not claimed as producer parity", procedure["rehearsal"])
        self.assertEqual(
            procedure["charter"], CHARTER_PATH.relative_to(ROOT).as_posix()
        )
        required_commands = (
            'test "$(git rev-parse HEAD)" = "$AUTHORIZED_READINESS_COMMIT"',
            'test -z "$(git status --porcelain)"',
            "git diff --exit-code f264c53da7d9d15aed1333efefcaabc113395793",
            "moon-c1-residual-diagnostic-run.py",
            "--authorized-readiness-commit",
            "--owner-literal",
            "--budget-state",
            "--snapshot-a",
            "--snapshot-b",
        )
        for command in required_commands:
            self.assertIn(command, self.charter)
        runner = ROOT / procedure["runner"]
        self.assertTrue(runner.is_file())
        runner_text = runner.read_text(encoding="utf-8")
        self.assertNotIn('"--force"', runner_text)
        for structural_binding in (
            '"archive", "--format=tar", implementation, "native"',
            '"--target-dir"',
            "str(target)",
            "read_report_once(",
            "stage_fd, stage_name",
            "O_DIRECTORY",
            "O_NOFOLLOW",
            "durable_attempt_ref",
        ):
            self.assertIn(structural_binding, runner_text)

    def test_charter_has_no_filled_authorization_or_scoring_language(self) -> None:
        self.assertNotRegex(
            self.charter,
            r"Authorize Moon C1 residual diagnostic at readiness commit [0-9a-f]{40}",
        )
        self.assertIn("non-scoring diagnostic", self.charter)
        self.assertIn("do not authorize either read", self.charter)
        self.assertIn("creates no permission to rerun", self.charter)
        self.assertIsNone(re.search(r"\bPASS or KILL\b", self.charter))


if __name__ == "__main__":
    unittest.main()
