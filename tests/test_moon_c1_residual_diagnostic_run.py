#!/usr/bin/env python3
"""Lifecycle tests for the authorized C1 diagnostic runner."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts/moon-c1-residual-diagnostic-run.py"
SPEC = importlib.util.spec_from_file_location("moon_c1_residual_run", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import C1 diagnostic runner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CLAIM = (
    "mechanism-local attribution and hindsight upper bounds only; no input-class, "
    "ratio, corpus, realizable-gain, candidate, SOTA, or product claim"
)


def valid_report(source: bytes, item: int = 0) -> dict:
    n = len(source)
    modeled = max(n, 1)
    events = 9 * n + 1

    def partition(labels: tuple[str, ...]) -> list[dict]:
        return [
            {
                "label": label,
                "bytes": n if index == 0 else 0,
                "loss_q24": modeled if index == 0 else 0,
            }
            for index, label in enumerate(labels)
        ]

    payload = (events + 7) // 8
    state = {
        "canonical_c1_declared_bytes": 136_773_760,
        "c1_derived_stretch_tables_bytes": 786_432,
        "shared_loss_table_bytes": 262_144,
        "shadow_table_bytes": 67_108_864,
        "source_input_bytes": n,
        "classification_bytes": n,
        "overlay_bit_payload_bytes": 3 * ((n + 7) // 8),
        "aggregation_struct_bytes": 952,
        "retained_observed_tape_payload_bytes": payload,
        "comparison_tape_payload_bytes": payload,
    }
    state["accounted_concurrent_logical_bytes"] = sum(state.values())
    state["semantics"] = MODULE.STATE_SEMANTICS
    return {
        "schema": "clab-moon-c1-residual-diagnostic-v2",
        "evidence_stage": "mechanism_local_diagnostic",
        "claim_ceiling": CLAIM,
        "arm": "c1-match-mixer",
        "kernel_version": "0.1.0",
        "q24_scale": 1 << 24,
        "source_sha256": digest(source),
        "tape_sha256": "1" * 64,
        "charged_event_digest_sha256": "2" * 64,
        "source_bytes": n,
        "tape_bytes": 54 + (events + 7) // 8,
        "item_index": item,
        "sse_bucket_bits": 17,
        "identity_guard": {
            "shared_canonical_event_generator": True,
            "canonical_tape_equal": True,
            "canonical_ledger_equal": True,
        },
        "state_accounting": state,
        "ledger": {
            "records": source.count(b"\n"),
            "modeled_binary_events": events,
            "modeled_loss_q24": modeled + 7,
            "raw_literal_bytes": 0,
        },
        "loss": {
            "modeled_bits_q24": modeled,
            "framing_q24_including_terminal": 7,
            "terminal_q24": 7,
        },
        "primary_partition": partition(
            (
                "structural",
                "field_name",
                "string_value",
                "number_value",
                "literal_value",
                "whitespace",
                "unclassified",
            )
        ),
        "live_match_partition": partition(("live", "not_live")),
        "match_length_buckets": partition(
            ("0-5", "6-7", "8-15", "16-31", "32-63", "64+")
        ),
        "match_distance_buckets": partition(
            (
                "none",
                "1-64",
                "65-256",
                "257-1024",
                "1025-4096",
                "4097-65536",
                "65537-1048576",
                "1048577+",
            )
        ),
        "overlays": {
            "partition": False,
            "repeat_signal": MODULE.REPEAT_SIGNAL,
            "rows": [
                {"label": label, "bytes": 0, "loss_q24": 0}
                for label in ("digits", "timestamp", "hex_id")
            ],
        },
        "match_bits": {"valid": 0, "correct": 0},
        "match_lifecycle": {
            "breaks": 2,
            "total_acquisitions": 3,
            "initial_acquisitions": 1,
            "post_break_reacquisitions": 2,
            "unresolved_breaks": 0,
            "terminal_censored_lag": None,
            "acquisition_disposition": {
                "empty_slot": max(n - 5, 0) - 3,
                "prefix_verification_failed": 0,
                "window_expired": 0,
                "live_match_suppressed": 0,
            },
            "reacquisition_lag_buckets": [1, 1, 0, 0, 0, 0],
        },
        "shadow_oracle": {
            "selection_semantics": MODULE.SHADOW_SELECTION,
            "candidate_opportunity_semantics": MODULE.SHADOW_OPPORTUNITY,
            "self_overlap": MODULE.SHADOW_SELF_OVERLAP,
            "raw_overlapping_matched_bytes_reported": False,
            "rows": [
                {
                    "depth": 1,
                    "candidate_opportunities_upper_bound": 1,
                    "any_correct_bytes_upper_bound": 1,
                    "any_correct_loss_q24_upper_bound": 2,
                    "incremental_any_correct_bytes_upper_bound": 1,
                    "incremental_any_correct_loss_q24_upper_bound": 2,
                },
                {
                    "depth": 2,
                    "candidate_opportunities_upper_bound": 2,
                    "any_correct_bytes_upper_bound": 1,
                    "any_correct_loss_q24_upper_bound": 2,
                    "incremental_any_correct_bytes_upper_bound": 0,
                    "incremental_any_correct_loss_q24_upper_bound": 0,
                },
                {
                    "depth": 4,
                    "candidate_opportunities_upper_bound": 3,
                    "any_correct_bytes_upper_bound": 2,
                    "any_correct_loss_q24_upper_bound": 4,
                    "incremental_any_correct_bytes_upper_bound": 1,
                    "incremental_any_correct_loss_q24_upper_bound": 2,
                },
            ],
        },
    }


def fake_kernel(root: Path) -> Path:
    path = root / "fake-kernel.py"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib,json,os,sys\n"
        "a=sys.argv[1:]\n"
        "assert a[0]=='diagnose-c1'\n"
        "assert 'DYLD_INSERT_LIBRARIES' not in os.environ\n"
        "assert 'OWNER_CREDENTIAL' not in os.environ\n"
        "item=int(a[a.index('--item-index')+1])\n"
        "if os.environ.get('FAIL_ITEM')==str(item): sys.exit(2)\n"
        "source=open(a[a.index('--input')+1],'rb').read()\n"
        "out=a[a.index('--report-out')+1]\n"
        "budget=json.load(open(os.environ['TEST_BUDGET']))['runs_consumed']\n"
        "open(os.environ['TEST_OBSERVED'],'a').write(str(budget)+'\\n')\n"
        "n=len(source); loss=max(n,1); events=9*n+1; framing=7; payload=(events+7)//8\n"
        "def rows(labels): return [{'label':x,'bytes':n if i==0 else 0,'loss_q24':loss if i==0 else 0} for i,x in enumerate(labels)]\n"
        "report={'schema':'clab-moon-c1-residual-diagnostic-v2',"
        "'evidence_stage':'mechanism_local_diagnostic',"
        "'claim_ceiling':'mechanism-local attribution and hindsight upper bounds only; no input-class, ratio, corpus, realizable-gain, candidate, SOTA, or product claim',"
        "'arm':'c1-match-mixer','kernel_version':'0.1.0','q24_scale':16777216,"
        "'source_sha256':hashlib.sha256(source).hexdigest(),'tape_sha256':'1'*64,"
        "'charged_event_digest_sha256':'2'*64,'source_bytes':n,'tape_bytes':54+(events+7)//8,"
        "'item_index':item,'sse_bucket_bits':17,"
        "'identity_guard':{'shared_canonical_event_generator':True,'canonical_tape_equal':True,'canonical_ledger_equal':True},"
        "'state_accounting':{'semantics':'checked peak-phase logical payload accounting; Vec capacity, allocator overhead, stack, and RSS are not claimed','canonical_c1_declared_bytes':136773760,'c1_derived_stretch_tables_bytes':786432,"
        "'shared_loss_table_bytes':262144,'shadow_table_bytes':67108864,'source_input_bytes':n,"
        "'classification_bytes':n,'overlay_bit_payload_bytes':3*((n+7)//8),'aggregation_struct_bytes':952,"
        "'retained_observed_tape_payload_bytes':payload,'comparison_tape_payload_bytes':payload,"
        "'accounted_concurrent_logical_bytes':136773760+786432+262144+67108864+n+n+3*((n+7)//8)+952+payload+payload},"
        "'ledger':{'records':source.count(b'\\n'),'modeled_binary_events':events,'modeled_loss_q24':loss+framing,'raw_literal_bytes':0},"
        "'loss':{'modeled_bits_q24':loss,'framing_q24_including_terminal':framing,'terminal_q24':framing},"
        "'primary_partition':rows(('structural','field_name','string_value','number_value','literal_value','whitespace','unclassified')),"
        "'live_match_partition':rows(('live','not_live')),'match_length_buckets':rows(('0-5','6-7','8-15','16-31','32-63','64+')),'match_distance_buckets':rows(('none','1-64','65-256','257-1024','1025-4096','4097-65536','65537-1048576','1048577+')),"
        "'overlays':{'partition':False,'repeat_signal':'canonical live_match_partition is the bounded causal repeat signal; no separate unbounded repeat overlay is retained','rows':[{'label':x,'bytes':0,'loss_q24':0} for x in ('digits','timestamp','hex_id')]},"
        "'match_bits':{'valid':0,'correct':0},"
        "'match_lifecycle':{'breaks':0,'total_acquisitions':0,'initial_acquisitions':0,"
        "'post_break_reacquisitions':0,'unresolved_breaks':0,'terminal_censored_lag':None,"
        "'acquisition_disposition':{'empty_slot':max(n-5,0),'prefix_verification_failed':0,"
        "'window_expired':0,'live_match_suppressed':0},"
        "'reacquisition_lag_buckets':[0,0,0,0,0,0]},"
        "'shadow_oracle':{'selection_semantics':'at each position, any retained verified candidate may supply the current byte; candidates may change every byte, so all fields are non-causal hindsight upper bounds prohibited as direct funding evidence','candidate_opportunity_semantics':'per-position verified-candidate opportunity count, not span mass','self_overlap':'legal because every candidate byte is strictly earlier than the current position','raw_overlapping_matched_bytes_reported':False,'rows':[{'depth':d,'candidate_opportunities_upper_bound':0,"
        "'any_correct_bytes_upper_bound':0,'any_correct_loss_q24_upper_bound':0,"
        "'incremental_any_correct_bytes_upper_bound':0,'incremental_any_correct_loss_q24_upper_bound':0} for d in (1,2,4)]},"
        "}\n"
        "open(out,'w').write(json.dumps(report,sort_keys=True)+'\\n')\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class RunnerTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, list[Path], Path, Path]:
        root = root.resolve()
        snapshots = []
        paths = []
        for index in range(2):
            data = (f'{{"item":{index}}}\n' * 5).encode()
            path = root / f"snapshot-{index}.ndjson"
            path.write_bytes(data)
            paths.append(path)
            snapshots.append(
                {
                    "name": f"snapshot-{index}",
                    "item_index": index,
                    "source_bytes": len(data),
                    "source_sha256": digest(data),
                }
            )
        references = root / "references.json"
        references.write_text(
            json.dumps(
                {
                    "schema": "moon-local-references-v1",
                    "snapshots": {
                        row["name"]: {
                            "source_bytes": row["source_bytes"],
                            "source_sha256": row["source_sha256"],
                        }
                        for row in snapshots
                    },
                }
            ),
            encoding="utf-8",
        )
        config = {
            "schema": MODULE.SCHEMA,
            "identity": {"implementation_commit": "b" * 40},
            "retained_snapshot_identity": {
                "metadata_sources": [],
                "snapshots": snapshots,
            },
            "runtime": {
                "references": "references.json",
                "shared_budget_path": str(root / "budget.json"),
                "expected_consumed_before": 0,
                "durable_attempt_ref": "refs/moon/test/attempt",
                "kernel_runtime_environment_names": ["LC_ALL", "PATH", "TMPDIR"],
                "toolchain": {"fixed_path": "/usr/bin:/bin:/usr/sbin:/sbin"},
            },
            "instrument": {
                "report_schema": "clab-moon-c1-residual-diagnostic-v2",
                "evidence_stage": "mechanism_local_diagnostic",
                "kernel_version": "0.1.0",
                "report_claim_ceiling": "mechanism-local attribution and hindsight upper bounds only; no input-class, ratio, corpus, realizable-gain, candidate, SOTA, or product claim",
                "sse_bucket_bits": 17,
            },
            "memory_and_claim_ceiling": {
                "accounted_concurrent_logical_bytes_max": 536870912,
                "aggregation_struct_bytes_frozen_target": 952,
            },
            "output_roster": [
                "out/a.report.json",
                "out/b.report.json",
                "out/sweep-summary.json",
                "out/SHA256SUMS",
            ],
        }
        config_path = root / MODULE.CONFIG_RELATIVE
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        MODULE.charge_budget(root / "budget.json", 0)
        return config_path, paths, root / "budget.json", fake_kernel(root)

    def execute(self, root: Path, *, fail_item: str | None = None) -> tuple[dict, Path]:
        config, snapshots, budget, kernel = self.fixture(root)
        environment = {
            "TEST_BUDGET": str(budget),
            "TEST_OBSERVED": str(root / "observed.txt"),
        }
        if fail_item is not None:
            environment["FAIL_ITEM"] = fail_item
        with (
            mock.patch.object(MODULE, "ROOT", root),
            mock.patch.object(MODULE, "validate_bindings", return_value=None),
            mock.patch.dict(os.environ, environment, clear=False),
        ):
            summary = MODULE.run(
                config,
                "a" * 40,
                "literal",
                budget,
                snapshots,
                kernel_override=[str(kernel)],
                attempt_create=lambda _config, _commit: "f" * 40,
                attempt_check=lambda _ref: False,
            )
        return summary, budget

    def test_success_charges_before_each_dispatch_and_publishes_roster(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, budget = self.execute(root)
            self.assertEqual(summary["budget"]["consumed_before"], 0)
            self.assertEqual(summary["budget"]["consumed_after"], 2)
            self.assertEqual(json.loads(budget.read_text())["runs_consumed"], 2)
            self.assertEqual(
                [row["status"] for row in summary["runs"]], ["measured"] * 2
            )
            self.assertEqual(
                (root / "observed.txt").read_text().splitlines(), ["1", "2"]
            )
            self.assertTrue((root / "out/sweep-summary.json").is_file())
            self.assertTrue((root / "out/SHA256SUMS").is_file())
            self.assertFalse(summary["scoring"])
            self.assertFalse(summary["candidate_execution"])
            self.assertFalse(summary["corpus_advancement"])

    def test_kernel_child_drops_dyld_and_credential_environment(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                os.environ,
                {
                    "DYLD_INSERT_LIBRARIES": "/attacker/inject.dylib",
                    "OWNER_CREDENTIAL": "must-not-reach-child",
                },
                clear=False,
            ),
        ):
            summary, _budget = self.execute(Path(tmp))
            self.assertEqual(
                [row["status"] for row in summary["runs"]], ["measured", "measured"]
            )
            self.assertNotIn(
                "DYLD_INSERT_LIBRARIES",
                summary["runtime_identity"]["kernel_environment_names"],
            )
            self.assertNotIn(
                "OWNER_CREDENTIAL",
                summary["runtime_identity"]["kernel_environment_names"],
            )

    def test_dispatched_failure_stays_charged_and_stops_second_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, budget = self.execute(root, fail_item="0")
            self.assertEqual(json.loads(budget.read_text())["runs_consumed"], 1)
            self.assertEqual(len(summary["runs"]), 1)
            self.assertEqual(summary["runs"][0]["status"], "failed")
            self.assertTrue((root / "out/sweep-summary.json").is_file())
            self.assertFalse((root / "out/SHA256SUMS").exists())
            self.assertFalse((root / "out/b.report.json").exists())

    def test_snapshot_mismatch_refuses_without_charging_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, budget, kernel = self.fixture(root)
            snapshots[0].write_bytes(b"tampered")
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                self.assertRaises(MODULE.Refused),
            ):
                MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                    attempt_create=lambda _config, _commit: "f" * 40,
                    attempt_check=lambda _ref: False,
                )
            self.assertEqual(json.loads(budget.read_text())["runs_consumed"], 0)
            self.assertFalse((root / "out/a.report.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_dangling_output_symlink_refuses_before_snapshot_read_or_charge(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, budget, kernel = self.fixture(root)
            (root / "out").mkdir()
            os.symlink(root / "missing", root / "out/a.report.json")
            snapshots[0].chmod(0)
            try:
                with (
                    mock.patch.object(MODULE, "ROOT", root),
                    mock.patch.object(MODULE, "validate_bindings", return_value=None),
                    self.assertRaises(MODULE.Refused),
                ):
                    MODULE.run(
                        config,
                        "a" * 40,
                        "literal",
                        budget,
                        snapshots,
                        kernel_override=[str(kernel)],
                    )
            finally:
                snapshots[0].chmod(stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(json.loads(budget.read_text())["runs_consumed"], 0)

    def test_insufficient_two_run_capacity_refuses_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, budget, kernel = self.fixture(root)
            MODULE.charge_budget(budget, MODULE.BUDGET_CAP - 1)
            config_value = json.loads(config.read_text())
            config_value["runtime"]["expected_consumed_before"] = MODULE.BUDGET_CAP - 1
            config.write_text(json.dumps(config_value), encoding="utf-8")
            before = budget.read_bytes()
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                self.assertRaises(MODULE.Refused),
            ):
                MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                    attempt_check=lambda _ref: False,
                )
            self.assertEqual(budget.read_bytes(), before)

    def test_real_validate_bindings_accepts_zero_attempts_and_false_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bound = root / "bound.txt"
            metadata = root / "metadata.json"
            package = root / "package.py"
            for path, data in (
                (bound, b"bound\n"),
                (metadata, b"{}\n"),
                (package, b"package\n"),
            ):
                path.write_bytes(data)
            commit = "a" * 40
            implementation = "b" * 40
            config = {
                "schema": MODULE.SCHEMA,
                "authority": {
                    "attempts_authorized": 0,
                    "execution_currently_authorized": False,
                    "retained_snapshot_read_authorized": False,
                    "candidate_execution_authorized": False,
                    "scoring_authorized": False,
                    "corpus_advancement_authorized": False,
                    "run_budget_advancement_authorized": False,
                    "ledger_advancement_authorized": False,
                    "exact_owner_literal_template": "Authorize {FINAL_READINESS_COMMIT}",
                    "binding_rule": "test binding",
                },
                "identity": {
                    "implementation_commit": implementation,
                    "implementation_base_commit": "c" * 40,
                    "implementation_tree": "d" * 40,
                    "readiness_diff_roster": sorted(MODULE.READINESS_FILES),
                    "source_sha256": {"bound.txt": digest(bound.read_bytes())},
                    "build_inputs_sha256": {},
                },
                "retained_snapshot_identity": {
                    "metadata_sources": [
                        {
                            "path": "metadata.json",
                            "sha256": digest(metadata.read_bytes()),
                            "git_blob": "e" * 40,
                        }
                    ]
                },
                "package_bindings": {"package.py": digest(package.read_bytes())},
                "runtime": {
                    "shared_budget_path": "/Users/guts/Documents/axiom-moonshot-corpora/run-budget.json",
                    "shared_budget_schema": MODULE.BUDGET_SCHEMA,
                    "shared_budget_cap": MODULE.BUDGET_CAP,
                    "expected_consumed_before": 52,
                    "expected_consumed_after": 54,
                },
            }

            def fake_git(*arguments: str) -> str:
                values = {
                    ("rev-parse", "HEAD"): commit,
                    ("status", "--porcelain"): "",
                    ("rev-parse", f"{implementation}^"): "c" * 40,
                    ("rev-parse", f"{implementation}^{{tree}}"): "d" * 40,
                    ("rev-parse", f"{implementation}:metadata.json"): "e" * 40,
                    ("diff", "--name-only", f"{implementation}..HEAD"): "\n".join(
                        sorted(MODULE.READINESS_FILES)
                    ),
                }
                return values[arguments]

            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "git", side_effect=fake_git),
                mock.patch.object(MODULE, "verify_git_identity", return_value=None),
                mock.patch.object(
                    MODULE.subprocess, "run", return_value=mock.Mock(returncode=0)
                ),
            ):
                MODULE.validate_bindings(config, commit, f"Authorize {commit}")
                removed = config["authority"].pop("scoring_authorized")
                with self.assertRaises(MODULE.Refused):
                    MODULE.validate_bindings(config, commit, f"Authorize {commit}")
                config["authority"]["scoring_authorized"] = removed
                config["authority"]["attempts_authorized"] = 1
                with self.assertRaises(MODULE.Refused):
                    MODULE.validate_bindings(config, commit, f"Authorize {commit}")
                config["authority"]["attempts_authorized"] = False
                with self.assertRaises(MODULE.Refused):
                    MODULE.validate_bindings(config, commit, f"Authorize {commit}")

    def test_complete_report_validator_refuses_each_malformed_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = b"synthetic-report-source\n"
            snapshot = {
                "source_bytes": len(source),
                "source_sha256": digest(source),
                "item_index": 0,
            }
            config = {
                "instrument": {
                    "report_schema": "clab-moon-c1-residual-diagnostic-v2",
                    "evidence_stage": "mechanism_local_diagnostic",
                    "kernel_version": "0.1.0",
                    "report_claim_ceiling": CLAIM,
                    "sse_bucket_bits": 17,
                },
                "memory_and_claim_ceiling": {
                    "accounted_concurrent_logical_bytes_max": 1 << 29,
                    "aggregation_struct_bytes_frozen_target": 952,
                },
            }
            path = root / "report.json"
            baseline = valid_report(source)
            path.write_text(json.dumps(baseline), encoding="utf-8")
            MODULE.validate_report(config, snapshot, source.count(b"\n"), baseline)

            mutations = {
                "injected_scoring_field": lambda r: r.__setitem__("PASS", True),
                "stage": lambda r: r.__setitem__("evidence_stage", "scoring"),
                "claim": lambda r: r.__setitem__("claim_ceiling", "broader"),
                "arm": lambda r: r.__setitem__("arm", "c1-other"),
                "kernel_version": lambda r: r.__setitem__("kernel_version", "0.1.1"),
                "q24_scale": lambda r: r.__setitem__("q24_scale", (1 << 24) - 1),
                "source_bytes": lambda r: r.__setitem__(
                    "source_bytes", len(source) + 1
                ),
                "digest_shape": lambda r: r.__setitem__("tape_sha256", "A" * 64),
                "identity_bool_int": lambda r: r["identity_guard"].__setitem__(
                    "canonical_tape_equal", 1
                ),
                "identity_extra": lambda r: r["identity_guard"].__setitem__(
                    "extra", True
                ),
                "state_sum": lambda r: r["state_accounting"].__setitem__(
                    "accounted_concurrent_logical_bytes", 0
                ),
                "state_semantics": lambda r: r["state_accounting"].__setitem__(
                    "semantics", "RSS measured"
                ),
                "state_exact_component": lambda r: (
                    r["state_accounting"].__setitem__(
                        "canonical_c1_declared_bytes", 136_773_761
                    ),
                    r["state_accounting"].__setitem__(
                        "accounted_concurrent_logical_bytes",
                        r["state_accounting"]["accounted_concurrent_logical_bytes"] + 1,
                    ),
                ),
                "multi_record_count": lambda r: r["ledger"].__setitem__(
                    "records", source.count(b"\n") + 1
                ),
                "nested_extra": lambda r: r["ledger"].__setitem__("ratio", 1),
                "event_formula": lambda r: r["ledger"].__setitem__(
                    "modeled_binary_events", 9 * len(source)
                ),
                "raw_literal": lambda r: r["ledger"].__setitem__(
                    "raw_literal_bytes", 1
                ),
                "ledger_loss": lambda r: r["ledger"].__setitem__(
                    "modeled_loss_q24", 999
                ),
                "terminal_loss": lambda r: r["loss"].__setitem__("terminal_q24", 8),
                "tape_formula": lambda r: r.__setitem__("tape_bytes", 54),
                "partition_bytes": lambda r: r["primary_partition"][0].__setitem__(
                    "bytes", 0
                ),
                "partition_label": lambda r: r["primary_partition"][0].__setitem__(
                    "label", "funding"
                ),
                "partition_loss_type": lambda r: r["live_match_partition"][
                    0
                ].__setitem__("loss_q24", True),
                "overlay_bound": lambda r: r["overlays"]["rows"][0].__setitem__(
                    "bytes", len(source) + 1
                ),
                "overlay_semantics": lambda r: r["overlays"].__setitem__(
                    "repeat_signal", "broader"
                ),
                "match_bit_bound": lambda r: r["match_bits"].__setitem__("correct", 1),
                "lifecycle_acquisition": lambda r: r["match_lifecycle"].__setitem__(
                    "total_acquisitions", 4
                ),
                "lifecycle_break": lambda r: r["match_lifecycle"].__setitem__(
                    "unresolved_breaks", 1
                ),
                "lifecycle_unresolved_cardinality": lambda r: (
                    r["match_lifecycle"].__setitem__("unresolved_breaks", 2),
                    r["match_lifecycle"].__setitem__("breaks", 4),
                    r["match_lifecycle"].__setitem__("terminal_censored_lag", 1),
                ),
                "lifecycle_initial_cardinality": lambda r: (
                    r["match_lifecycle"].__setitem__("initial_acquisitions", 2),
                    r["match_lifecycle"].__setitem__("total_acquisitions", 4),
                ),
                "lifecycle_lag": lambda r: r["match_lifecycle"].__setitem__(
                    "reacquisition_lag_buckets", [0, 0, 0, 0, 0, 0]
                ),
                "terminal_censor": lambda r: r["match_lifecycle"].__setitem__(
                    "terminal_censored_lag", 0
                ),
                "disposition_formula": lambda r: r["match_lifecycle"][
                    "acquisition_disposition"
                ].__setitem__("empty_slot", 0),
                "shadow_depth": lambda r: r["shadow_oracle"]["rows"][1].__setitem__(
                    "depth", 3
                ),
                "shadow_semantics": lambda r: r["shadow_oracle"].__setitem__(
                    "selection_semantics", "realizable gain"
                ),
                "shadow_raw_flag": lambda r: r["shadow_oracle"].__setitem__(
                    "raw_overlapping_matched_bytes_reported", True
                ),
                "shadow_monotone": lambda r: r["shadow_oracle"]["rows"][1].__setitem__(
                    "candidate_opportunities_upper_bound", 0
                ),
                "shadow_increment": lambda r: r["shadow_oracle"]["rows"][2].__setitem__(
                    "incremental_any_correct_bytes_upper_bound", 0
                ),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    report = copy.deepcopy(baseline)
                    mutate(report)
                    path.write_text(json.dumps(report), encoding="utf-8")
                    with self.assertRaises(MODULE.Refused):
                        MODULE.validate_report(
                            config, snapshot, source.count(b"\n"), report
                        )

    def test_real_producer_synthetic_report_passes_python_validator_and_golden(
        self,
    ) -> None:
        config = json.loads(
            (REPOSITORY / MODULE.CONFIG_RELATIVE).read_text(encoding="utf-8")
        )
        golden = config["instrument"]["synthetic_complete_event_golden"]
        source = golden["source_utf8"].encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "synthetic.ndjson"
            report_path = root / "report.json"
            input_path.write_bytes(source)
            first_private_root = root / "exact-build"
            first_private_root.mkdir()

            def replace_checked_path(path: Path) -> None:
                path.write_bytes(b"#!/bin/sh\nexit 99\n")
                path.chmod(0o700)

            kernel, runtime_identity, kernel_fd = MODULE.materialize_and_build(
                config, first_private_root, after_verify_hook=replace_checked_path
            )
            second_private_root = root / "independent-exact-build"
            second_private_root.mkdir()
            second_kernel, second_identity, second_fd = MODULE.materialize_and_build(
                config, second_private_root
            )
            self.assertIsNone(kernel_fd)
            self.assertIsNone(second_fd)
            self.assertEqual(
                runtime_identity["implementation_commit"],
                config["identity"]["implementation_commit"],
            )
            self.assertEqual(
                runtime_identity["binary_sha256"],
                config["runtime"]["toolchain"]["expected_release_binary_sha256"],
            )
            self.assertEqual(
                second_identity["binary_sha256"], runtime_identity["binary_sha256"]
            )
            MODULE.verify_kernel_before_dispatch(
                Path(second_kernel[0]), second_identity["binary_sha256"]
            )
            MODULE.verify_kernel_before_dispatch(
                Path(kernel[0]), runtime_identity["binary_sha256"]
            )
            subprocess.run(
                [
                    *kernel,
                    "diagnose-c1",
                    "--item-index",
                    str(golden["item_index"]),
                    "--input",
                    str(input_path),
                    "--report-out",
                    str(report_path),
                ],
                check=True,
                env=MODULE.kernel_environment(config, root / "real-kernel-env"),
            )
            verified_path = Path(kernel[0])
            verified_path.chmod(0o700)
            verified_path.write_bytes(b"#!/bin/sh\nexit 0\n")
            with self.assertRaises(MODULE.Refused):
                MODULE.verify_kernel_before_dispatch(
                    verified_path, runtime_identity["binary_sha256"]
                )
            retained = report_path.read_bytes()
            report = json.loads(retained)
            snapshot = {
                "source_bytes": len(source),
                "source_sha256": golden["real_cli_source_sha256"],
                "item_index": golden["item_index"],
            }
            self.assertEqual(
                hashlib.sha256(retained).hexdigest(),
                golden["real_cli_complete_report_sha256"],
            )
            self.assertEqual(
                report["charged_event_digest_sha256"],
                golden["charged_event_digest_sha256"],
            )
            self.assertEqual(report["tape_sha256"], golden["real_cli_tape_sha256"])
            MODULE.validate_report(config, snapshot, source.count(b"\n"), report)

    def test_budget_path_equal_to_first_report_refuses_before_charge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, old_budget, kernel = self.fixture(root)
            budget = root / "out/a.report.json"
            config_value = json.loads(config.read_text())
            config_value["runtime"]["shared_budget_path"] = str(budget)
            config.write_text(json.dumps(config_value), encoding="utf-8")
            old_budget.unlink()
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                self.assertRaises(MODULE.Refused),
            ):
                MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                )
            self.assertFalse(budget.exists())

    def test_existing_budget_hardlink_to_snapshot_refuses_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, budget, kernel = self.fixture(root)
            budget.unlink()
            os.link(snapshots[0], budget)
            before = snapshots[0].read_bytes()
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                self.assertRaises(MODULE.Refused),
            ):
                MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                )
            self.assertEqual(snapshots[0].read_bytes(), before)

    def test_budget_schema_rejects_extra_keys_and_boolean_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            budget = Path(tmp) / "budget.json"
            with self.assertRaises(MODULE.Refused):
                MODULE.read_budget(budget)
            budget.write_text(
                json.dumps(
                    {
                        "schema": MODULE.BUDGET_SCHEMA,
                        "runs_consumed": 52,
                        "cap": MODULE.BUDGET_CAP,
                        "ratio": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(MODULE.Refused):
                MODULE.read_budget(budget)
            budget.write_text(
                json.dumps(
                    {
                        "schema": MODULE.BUDGET_SCHEMA,
                        "runs_consumed": True,
                        "cap": MODULE.BUDGET_CAP,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(MODULE.Refused):
                MODULE.read_budget(budget)

    def test_controlled_build_environment_drops_ambient_injection(self) -> None:
        config = json.loads((REPOSITORY / MODULE.CONFIG_RELATIVE).read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            marker = root / "wrapper-ran"
            for name in ("cargo", "rustc", "clang", "git"):
                wrapper = fake_bin / name
                wrapper.write_text(
                    f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8"
                )
                wrapper.chmod(0o700)
            injected = {
                "PATH": str(fake_bin),
                "CARGO_TARGET_DIR": "/attacker/target",
                "RUSTC_WRAPPER": "/attacker/wrapper",
                "RUSTFLAGS": "-C linker=/attacker/linker",
                "CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER": "/attacker/linker",
            }
            with mock.patch.dict(os.environ, injected, clear=False):
                child = MODULE.controlled_environment(config, root / "child")
                _, identities = MODULE.verify_toolchain(config, root / "verify")
                MODULE.verify_git_identity(config)
            self.assertFalse(marker.exists())
            self.assertEqual(set(identities), {"cargo", "rustc", "clang"})
        for name in injected:
            if name not in (
                "PATH",
                "CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER",
                "RUSTFLAGS",
            ):
                self.assertNotIn(name, child)
        self.assertNotEqual(child["RUSTFLAGS"], injected["RUSTFLAGS"])
        self.assertIn("--remap-path-prefix=", child["RUSTFLAGS"])
        self.assertEqual(child["RUSTC"], config["runtime"]["toolchain"]["rustc_path"])
        self.assertEqual(child["PATH"], config["runtime"]["toolchain"]["fixed_path"])
        config["runtime"]["build_environment_allowlist"].append("RUSTFLAGS")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(MODULE.Refused):
            MODULE.controlled_environment(config, Path(tmp))

    def test_release_digest_refuses_placeholder_malformed_missing_and_mismatch(
        self,
    ) -> None:
        actual = "a" * 64
        self.assertEqual(MODULE.require_release_digest(actual, actual), actual)
        for expected in ("TO_BE_REFRESHED", "abc", None, "b" * 64):
            with self.subTest(expected=expected), self.assertRaises(MODULE.Refused):
                MODULE.require_release_digest(actual, expected)

    def test_duplicate_keys_refuse_in_report_budget_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            stage.mkdir()
            stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                top_level = stage / "report.json"
                top_level.write_bytes(
                    b'{"claim_ceiling":"funding","claim_ceiling":"canonical"}\n'
                )
                with self.assertRaises(MODULE.Refused):
                    MODULE.read_report_once(stage_fd, top_level.name)
                top_level.write_bytes(
                    b'{"identity_guard":{"canonical_tape_equal":false,'
                    b'"canonical_tape_equal":true}}\n'
                )
                with self.assertRaises(MODULE.Refused):
                    MODULE.read_report_once(stage_fd, top_level.name)
            finally:
                os.close(stage_fd)

            budget = root / "budget.json"
            budget.write_bytes(
                b'{"schema":"moon-prescreen-budget-v1","runs_consumed":52,'
                b'"runs_consumed":0,"cap":160}\n'
            )
            with self.assertRaises(MODULE.Refused):
                MODULE.read_budget(budget)

            config = root / "config.json"
            config.write_bytes(b'{"schema":"first","schema":"second"}\n')
            with self.assertRaises(MODULE.Refused):
                MODULE.load_object(config, "readiness config")
            for token in (b"NaN", b"Infinity", b"-Infinity"):
                with self.subTest(token=token), self.assertRaises(MODULE.Refused):
                    MODULE.strict_json_loads(b'{"value":' + token + b"}", "test JSON")

    def test_budget_argument_typo_refuses_exact_bound_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config_path, snapshots, budget, _ = self.fixture(root)
            config = json.loads(config_path.read_text())
            with self.assertRaises(MODULE.Refused):
                MODULE.validate_budget_path(
                    config, budget.with_name("run-budegt.json"), snapshots, []
                )

    def test_durable_attempt_ref_blocks_repeat_even_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["/usr/bin/git", "init", "-q", str(root)], check=True)
            attacker = root.parent / f"{root.name}-attacker"
            subprocess.run(["/usr/bin/git", "init", "-q", str(attacker)], check=True)
            fake_bin = root.parent / f"{root.name}-fake-bin"
            fake_bin.mkdir()
            marker = root.parent / f"{root.name}-fake-git-ran"
            fake_git = fake_bin / "git"
            fake_git.write_text(
                f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8"
            )
            fake_git.chmod(0o700)
            config = {
                "runtime": {
                    "durable_attempt_ref": "refs/moon/test/attempt",
                    "expected_consumed_before": 52,
                },
                "retained_snapshot_identity": {"snapshots": []},
            }
            malicious = {
                "PATH": str(fake_bin),
                "GIT_DIR": str(attacker / ".git"),
                "GIT_WORK_TREE": str(attacker),
                "GIT_OBJECT_DIRECTORY": str(attacker / ".git/objects"),
            }
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.dict(os.environ, malicious, clear=False),
            ):
                blob = MODULE.create_attempt_ref(config, "a" * 40)
                self.assertRegex(blob, r"^[0-9a-f]{40}$")
                self.assertTrue(MODULE.attempt_ref_exists("refs/moon/test/attempt"))
                with self.assertRaises(MODULE.Refused):
                    MODULE.create_attempt_ref(config, "a" * 40)
            self.assertFalse(marker.exists())
            self.assertNotEqual(
                subprocess.run(
                    [
                        "/usr/bin/git",
                        "show-ref",
                        "--verify",
                        "--quiet",
                        "refs/moon/test/attempt",
                    ],
                    cwd=attacker,
                ).returncode,
                0,
            )

    def test_cli_exit_is_nonzero_for_incomplete_summary(self) -> None:
        arguments = [
            "config.json",
            "--authorized-readiness-commit",
            "a" * 40,
            "--owner-literal",
            "literal",
            "--budget-state",
            "/exact/budget.json",
            "--snapshot-a",
            "a.ndjson",
            "--snapshot-b",
            "b.ndjson",
        ]
        incomplete = {"runs": [{"status": "failed"}]}
        complete = {"runs": [{"status": "measured"}, {"status": "measured"}]}
        with mock.patch.object(MODULE, "run", return_value=incomplete):
            self.assertEqual(MODULE.main(arguments), 1)
        with mock.patch.object(MODULE, "run", return_value=complete):
            self.assertEqual(MODULE.main(arguments), 0)

    def test_report_and_summary_publication_use_retained_bytes_after_stage_swap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            output.mkdir()
            stage = root / "stage"
            stage.mkdir()
            report_stage = stage / "report.json"
            summary_stage = stage / "summary.json"
            report_bytes = b'{"schema":"report","scoring":false}\n'
            summary_bytes = b'{"schema":"summary","scoring":false}\n'
            report_stage.write_bytes(report_bytes)
            summary_stage.write_bytes(summary_bytes)
            retained_report = report_stage.read_bytes()
            retained_summary = summary_stage.read_bytes()
            report_stage.unlink()
            summary_stage.unlink()
            report_stage.write_bytes(b'{"PASS":true}\n')
            summary_stage.write_bytes(b'{"funding":true}\n')
            output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            identity_info = os.fstat(output_fd)
            identity = (identity_info.st_dev, identity_info.st_ino)
            try:
                MODULE.publish_validated_bytes(
                    output_fd,
                    "report.json",
                    retained_report,
                    digest(retained_report),
                    output,
                    identity,
                )
                MODULE.publish_validated_bytes(
                    output_fd,
                    "summary.json",
                    retained_summary,
                    digest(retained_summary),
                    output,
                    identity,
                )
            finally:
                os.close(output_fd)
            self.assertEqual((output / "report.json").read_bytes(), report_bytes)
            self.assertEqual((output / "summary.json").read_bytes(), summary_bytes)
            self.assertNotIn(b"PASS", (output / "report.json").read_bytes())
            self.assertNotIn(b"funding", (output / "summary.json").read_bytes())

    def test_before_publish_stage_swap_cannot_change_run_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config, snapshots, budget, kernel = self.fixture(root)
            environment = {
                "TEST_BUDGET": str(budget),
                "TEST_OBSERVED": str(root / "observed.txt"),
            }
            original: bytes | None = None

            def replace_staged_report(stage: str, _index: int) -> None:
                nonlocal original
                if stage != "before_publish":
                    return
                staged = next(root.glob(".moon-c1-private-*/stage/report-0.json"))
                original = staged.read_bytes()
                staged.write_bytes(b'{"PASS":true,"funding":true}\n')

            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                mock.patch.dict(os.environ, environment, clear=False),
            ):
                summary = MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                    boundary_hook=replace_staged_report,
                    attempt_create=lambda _config, _commit: "f" * 40,
                    attempt_check=lambda _ref: False,
                )
            self.assertIsNotNone(original)
            published = root / summary["runs"][0]["report"]
            self.assertEqual(published.read_bytes(), original)
            self.assertEqual(
                digest(published.read_bytes()), summary["runs"][0]["report_sha256"]
            )
            published_object = json.loads(published.read_bytes())
            self.assertNotIn("PASS", published_object)
            self.assertNotIn("funding", published_object)

    def test_publication_refuses_preplanted_pending_and_final_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(output_fd)
            identity = (info.st_dev, info.st_ino)
            data = b"validated\n"
            pending = f".moon-c1-{os.getpid()}-{'a' * 32}.pending"
            try:
                (output / pending).write_bytes(b"attacker pending\n")
                with (
                    mock.patch.object(
                        MODULE.secrets, "token_hex", return_value="a" * 32
                    ),
                    self.assertRaises(MODULE.Refused),
                ):
                    MODULE.publish_validated_bytes(
                        output_fd, "report.json", data, digest(data), output, identity
                    )
                self.assertEqual((output / pending).read_bytes(), b"attacker pending\n")
                self.assertFalse((output / "report.json").exists())
                (output / pending).unlink()
                (output / "report.json").write_bytes(b"attacker final\n")
                with self.assertRaises(MODULE.Refused):
                    MODULE.publish_validated_bytes(
                        output_fd, "report.json", data, digest(data), output, identity
                    )
                self.assertEqual(
                    (output / "report.json").read_bytes(), b"attacker final\n"
                )
            finally:
                os.close(output_fd)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_output_directory_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, budget, kernel = self.fixture(root)
            real = root / "real-output"
            real.mkdir()
            os.symlink(real, root / "out")
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                self.assertRaises(MODULE.Refused),
            ):
                MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                )
            self.assertTrue(budget.exists())
            self.assertEqual(list(real.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_output_parent_swap_refuses_before_dispatch_and_publication(self) -> None:
        for attack_stage in ("before_dispatch", "before_publish"):
            with (
                self.subTest(attack_stage=attack_stage),
                tempfile.TemporaryDirectory() as tmp,
                tempfile.TemporaryDirectory() as outside_tmp,
            ):
                root = Path(tmp).resolve()
                outside = Path(outside_tmp)
                config, snapshots, budget, kernel = self.fixture(root)
                environment = {
                    "TEST_BUDGET": str(budget),
                    "TEST_OBSERVED": str(root / "observed.txt"),
                }
                fired = False

                def swap(stage: str, _index: int) -> None:
                    nonlocal fired
                    if stage == attack_stage and not fired:
                        fired = True
                        (root / "out").rename(root / "held-output")
                        os.symlink(outside, root / "out")

                with (
                    mock.patch.object(MODULE, "ROOT", root),
                    mock.patch.object(MODULE, "validate_bindings", return_value=None),
                    mock.patch.dict(os.environ, environment, clear=False),
                    self.assertRaises(MODULE.Refused),
                ):
                    MODULE.run(
                        config,
                        "a" * 40,
                        "literal",
                        budget,
                        snapshots,
                        kernel_override=[str(kernel)],
                        boundary_hook=swap,
                        attempt_create=lambda _config, _commit: "f" * 40,
                        attempt_check=lambda _ref: False,
                    )
                self.assertTrue(fired)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((root / "held-output/a.report.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_existing_budget_symlink_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, snapshots, budget, kernel = self.fixture(root)
            target = root / "real-budget.json"
            budget.unlink()
            os.symlink(target, budget)
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "validate_bindings", return_value=None),
                self.assertRaises(MODULE.Refused),
            ):
                MODULE.run(
                    config,
                    "a" * 40,
                    "literal",
                    budget,
                    snapshots,
                    kernel_override=[str(kernel)],
                )
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
