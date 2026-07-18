from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "aggregate-text-source-research-ceiling.py"
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
SPEC = importlib.util.spec_from_file_location("research_ceiling_aggregate", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load research-ceiling aggregate")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourceResearchCeilingAggregateTests(unittest.TestCase):
    def prepare(self, root: Path):
        config_raw = CONFIG.read_bytes()
        plan = MODULE.RUNNER.PLANNER.build_plan(
            json.loads(config_raw),
            baseline_fixture(),
            config_sha256=hashlib.sha256(config_raw).hexdigest(),
            baseline_sha256="b" * 64,
            repository_commit="c" * 40,
        )
        plan_path = root / "plan.json"
        plan_path.write_bytes(MODULE.RUNNER.PLANNER.json_bytes(plan))

        host_runs = []
        host_validations = {}
        for host_index, host_class in enumerate(MODULE.HOST_CLASS_ORDER):
            host_id = f"fixture-host-{host_index}"
            host = {
                "host_id": host_id,
                "host_class": host_class,
                "platform": "fixture-os",
                "machine": "fixture-machine",
                "cpu": "fixture-cpu",
                "logical_cpus": 8,
                "memory_bytes": 64 * 1024**3,
                "gpu": "fixture-gpu" if "cuda" in host_class else None,
                "cuda": "fixture-cuda" if "cuda" in host_class else None,
            }
            tasks = [row for row in plan["tasks"] if row["host_class"] == host_class]
            profiles = list(dict.fromkeys(row["profile_id"] for row in tasks))
            toolchain_path = root / f"toolchain-{host_index}.json"
            toolchain_path.write_bytes(
                MODULE.RUNNER.PLANNER.json_bytes({"host": host, "profiles": []})
            )
            output = root / f"host-run-{host_index}"
            output.mkdir()
            summaries = []
            for task_index, task in enumerate(tasks):
                formal_admitted = (
                    task["formal_ceiling_eligible"]
                    and task["profile_id"] != MODULE.NNCP_PROFILE
                )
                summaries.append(
                    {
                        "task_id": task["task_id"],
                        "profile_id": task["profile_id"],
                        "codec_id": task["codec_id"],
                        "item_id": task["item_id"],
                        "track": task["track"],
                        "formal_ceiling_eligible": task["formal_ceiling_eligible"],
                        "source_bytes": task["source_bytes"],
                        "measured_repetitions": 2,
                        "complete": True,
                        "deterministic": True,
                        "complete_artifact_bytes": task["source_bytes"] // 2 + 1,
                        "payload_sha256": f"{task_index + 1:064x}",
                        "exact_roundtrip": True,
                        "portability_status": (
                            "pending_second_host_decode"
                            if task["profile_id"] == MODULE.NNCP_PROFILE
                            else "not_required_by_research_protocol"
                        ),
                        "formal_ceiling_admitted": formal_admitted,
                        "execution_status": "measured_exact_deterministic",
                        "axiom_outcome": "baseline_measurement_only",
                    }
                )
                for repetition, wall in ((1, 100 + task_index), (2, 200 + task_index)):
                    receipt = {
                        "passed": True,
                        "decompression": {
                            "wall_ns": wall + 20,
                            "cpu_ns": wall + 10,
                            "peak_rss_bytes": 2_000 + repetition,
                        },
                        "compression": {
                            "wall_ns": wall,
                            "cpu_ns": wall - 10,
                            "peak_rss_bytes": 1_000 + repetition,
                        },
                    }
                    path = MODULE.RUNNER.trial_path(output, task, repetition)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(MODULE.RUNNER.PLANNER.json_bytes(receipt))
            results = {
                "host": host,
                "profile_ids": profiles,
                "tasks": summaries,
                "trial_count": len(tasks) * 3,
                "retained_artifact_count": len(tasks),
                "retained_artifact_manifest_sha256": f"{host_index + 1:064x}",
                "all_host_formal_tasks_complete": all(
                    row["formal_ceiling_admitted"]
                    for row in summaries
                    if row["formal_ceiling_eligible"]
                ),
                "axiom_wins": 0,
            }
            (output / "results.json").write_bytes(
                MODULE.RUNNER.PLANNER.json_bytes(results)
            )
            host_run = MODULE.HostRun(toolchain_path, root, output)
            host_runs.append(host_run)
            host_validations[toolchain_path] = {
                "verified": True,
                "host_id": host_id,
            }

        second_toolchain = root / "second-toolchain.json"
        second_toolchain.write_bytes(MODULE.RUNNER.PLANNER.json_bytes({"fixture": True}))
        second_output = root / "second-host-run"
        second_output.mkdir()
        second_tasks = []
        for task_index, task in enumerate(
            row for row in plan["tasks"] if row["profile_id"] == MODULE.NNCP_PROFILE
        ):
            second_tasks.append(
                {
                    "task_id": task["task_id"],
                    "exact_second_host_decode": True,
                }
            )
            receipt = {
                "decompression": {
                    "wall_ns": 300 + task_index,
                    "cpu_ns": 250 + task_index,
                    "peak_rss_bytes": 3_000 + task_index,
                }
            }
            path = MODULE.SECOND_HOST.receipt_path(second_output, task)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(MODULE.RUNNER.PLANNER.json_bytes(receipt))
        (second_output / "results.json").write_bytes(
            MODULE.RUNNER.PLANNER.json_bytes({"tasks": second_tasks})
        )
        second_run = MODULE.SecondHostRun(second_toolchain, root, second_output)
        second_validation = {
            "verified": True,
            "primary_host_id": "fixture-host-3",
            "second_host_id": "fixture-host-second",
            "receipt_count": 7,
            "all_nncp_second_host_decodes_exact": True,
            "formal_nncp_ceiling_admitted": True,
            "axiom_wins": 0,
        }
        return plan_path, host_runs, host_validations, second_run, second_validation

    def test_all_host_rows_and_second_host_evidence_form_one_exact_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, host_runs, validations, second_run, second_validation = self.prepare(root)

            def validate_host(**kwargs):
                return validations[kwargs["toolchain_receipt_path"]]

            with (
                mock.patch.object(MODULE.RUNNER, "validate_output", side_effect=validate_host),
                mock.patch.object(
                    MODULE.SECOND_HOST,
                    "validate_output",
                    return_value=second_validation,
                ),
            ):
                aggregate = MODULE.build_aggregate(
                    plan_path=plan,
                    host_runs=host_runs,
                    second_host_run=second_run,
                )
                self.assertEqual(aggregate["task_count"], 35)
                self.assertEqual(aggregate["formal_task_count"], 28)
                self.assertTrue(aggregate["all_formal_ceiling_tasks_admitted"])
                self.assertEqual(aggregate["research_ceiling_status"], "formal_complete")
                self.assertEqual(aggregate["axiom_wins"], 0)
                first = aggregate["tasks"][0]
                self.assertEqual(first["compression_wall_ns_median"], 150)
                self.assertEqual(first["decompression_wall_ns_median"], 170)
                self.assertEqual(first["compression_peak_rss_bytes"], 1_002)
                nncp = next(
                    row for row in aggregate["tasks"] if row["profile_id"] == MODULE.NNCP_PROFILE
                )
                self.assertEqual(nncp["second_host_decode_status"], "exact")
                self.assertTrue(nncp["formal_ceiling_admitted"])

                path = MODULE.write_immutable(root / "aggregate.json", aggregate)
                verified = MODULE.validate_aggregate(
                    aggregate_path=path,
                    plan_path=plan,
                    host_runs=host_runs,
                    second_host_run=second_run,
                )
                self.assertTrue(verified["verified"])
                self.assertEqual(verified["axiom_wins"], 0)

                aggregate["axiom_wins"] = 1
                path.write_bytes(MODULE.RUNNER.PLANNER.json_bytes(aggregate))
                with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                    MODULE.validate_aggregate(
                        aggregate_path=path,
                        plan_path=plan,
                        host_runs=host_runs,
                        second_host_run=second_run,
                    )

    def test_missing_host_class_and_missing_second_host_stay_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, host_runs, validations, _second_run, _second_validation = self.prepare(root)

            def validate_host(**kwargs):
                return validations[kwargs["toolchain_receipt_path"]]

            with mock.patch.object(
                MODULE.RUNNER, "validate_output", side_effect=validate_host
            ):
                with self.assertRaisesRegex(ValueError, "all four host classes"):
                    MODULE.build_aggregate(
                        plan_path=plan,
                        host_runs=host_runs[:-1],
                        second_host_run=None,
                    )
                aggregate = MODULE.build_aggregate(
                    plan_path=plan,
                    host_runs=host_runs,
                    second_host_run=None,
                )
            self.assertFalse(aggregate["all_formal_ceiling_tasks_admitted"])
            self.assertEqual(aggregate["research_ceiling_status"], "incomplete_or_unavailable")
            nncp = next(
                row for row in aggregate["tasks"] if row["profile_id"] == MODULE.NNCP_PROFILE
            )
            self.assertEqual(nncp["second_host_decode_status"], "pending")
            self.assertFalse(nncp["formal_ceiling_admitted"])


if __name__ == "__main__":
    unittest.main()
