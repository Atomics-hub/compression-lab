import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-text-source-research-ceiling.py"
SPEC = importlib.util.spec_from_file_location("research_ceiling_runner", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load research-ceiling runner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


FAKE_CODEC = """#!/usr/bin/env python3
import pathlib
import shutil
import sys

mode, source, destination, *rest = sys.argv[1:]
if mode == "empty-compress":
    pathlib.Path(destination).write_bytes(b"")
    raise SystemExit(0)
shutil.copyfile(source, destination)
if mode == "bad-decode":
    payload = pathlib.Path(destination).read_bytes()
    pathlib.Path(destination).write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
"""


class TextSourceResearchCeilingRunnerTests(unittest.TestCase):
    def prepare(
        self, root: Path, *, bad_decode: bool = False, empty_payload: bool = False
    ):
        tools = root / "tools"
        executable = tools / "bin" / "fixture-codec"
        executable.parent.mkdir(parents=True)
        executable.write_text(FAKE_CODEC, encoding="utf-8")
        executable.chmod(0o755)
        source = root / "source.bin"
        source.write_bytes((b"deterministic research ceiling fixture\n" * 64))
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        task = {
            "task_id": "fixture-profile/fixture-item",
            "profile_id": "fixture-profile",
            "codec_id": "fixture-codec",
            "formal_ceiling_eligible": True,
            "item_id": "fixture-item",
            "track": "source_code_bundles",
            "source_bytes": source.stat().st_size,
            "source_sha256": source_sha256,
            "compression_command": [
                "fixture-codec",
                "empty-compress" if empty_payload else "compress",
                "$WORK/input.bin",
                "$WORK/payload.bin",
            ],
            "decompression_command": [
                "fixture-codec",
                "bad-decode" if bad_decode else "decompress",
                "$WORK/payload.bin",
                "$WORK/restored.bin",
            ],
            "counted_side_asset_bytes": 17,
            "counted_side_asset_sha256": "a" * 64,
            "staged_input_name": None,
            "staged_input_mtime_utc": None,
            "second_host_decode_required": False,
        }
        bindings = {
            "plan_sha256": "b" * 64,
            "toolchain_receipt_sha256": "c" * 64,
            "corpus_manifest_sha256": "d" * 64,
            "repository_commit": "e" * 40,
        }
        return tools, executable, source, task, bindings

    def run_once(
        self,
        root: Path,
        *,
        task: dict,
        source: Path,
        executable: Path,
        tools: Path,
        bindings: dict,
        repetition: int,
    ) -> dict:
        return MODULE.run_trial(
            output=root / "output",
            task=task,
            source=source,
            executable=executable,
            tools_root=tools,
            repetition=repetition,
            bindings=bindings,
            timeout_seconds=10.0,
            family_budget_seconds=10.0,
            max_address_bytes=None,
        )

    def test_exact_trials_are_resumable_deterministic_and_fully_accounted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tools, executable, source, task, bindings = self.prepare(root)
            trials = [
                self.run_once(
                    root,
                    task=task,
                    source=source,
                    executable=executable,
                    tools=tools,
                    bindings=bindings,
                    repetition=repetition,
                )
                for repetition in range(3)
            ]
            self.assertTrue(all(row["passed"] for row in trials))
            self.assertTrue(all(row["exact_roundtrip"] for row in trials))
            self.assertTrue(
                all(
                    row["complete_artifact_bytes"]
                    == row["payload_bytes"] + task["counted_side_asset_bytes"]
                    for row in trials
                )
            )
            summary = MODULE.summarize_task(task, trials)
            self.assertTrue(summary["complete"])
            self.assertTrue(summary["deterministic"])
            self.assertTrue(summary["formal_ceiling_admitted"])
            self.assertEqual(summary["axiom_outcome"], "baseline_measurement_only")
            second_host_task = task | {"second_host_decode_required": True}
            second_host_summary = MODULE.summarize_task(second_host_task, trials)
            self.assertTrue(second_host_summary["deterministic"])
            self.assertFalse(second_host_summary["formal_ceiling_admitted"])
            self.assertEqual(
                second_host_summary["portability_status"],
                "pending_second_host_decode",
            )
            resumed = self.run_once(
                root,
                task=task,
                source=source,
                executable=executable,
                tools=tools,
                bindings=bindings,
                repetition=2,
            )
            self.assertEqual(resumed, trials[2])

    def test_resumed_receipt_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tools, executable, source, task, bindings = self.prepare(root)
            self.run_once(
                root,
                task=task,
                source=source,
                executable=executable,
                tools=tools,
                bindings=bindings,
                repetition=0,
            )
            receipt_path = MODULE.trial_path(root / "output", task, 0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["payload_sha256"] = "not-a-digest"
            receipt_path.write_bytes(MODULE.PLANNER.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "successful research trial"):
                self.run_once(
                    root,
                    task=task,
                    source=source,
                    executable=executable,
                    tools=tools,
                    bindings=bindings,
                    repetition=0,
                )

    def test_inexact_decoder_is_visible_and_never_an_axiom_win(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tools, executable, source, task, bindings = self.prepare(
                root, bad_decode=True
            )
            trials = [
                self.run_once(
                    root,
                    task=task,
                    source=source,
                    executable=executable,
                    tools=tools,
                    bindings=bindings,
                    repetition=repetition,
                )
                for repetition in range(3)
            ]
            self.assertTrue(all(not row["passed"] for row in trials))
            self.assertTrue(all(row["error"] == "restored digest mismatch" for row in trials))
            self.assertEqual({row["axiom_outcome"] for row in trials}, {"untested"})
            summary = MODULE.summarize_task(task, trials)
            self.assertFalse(summary["complete"])
            self.assertFalse(summary["deterministic"])
            self.assertEqual(summary["axiom_outcome"], "untested")

    def test_empty_payload_failure_is_canonical_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tools, executable, source, task, bindings = self.prepare(
                root, empty_payload=True
            )
            receipt = self.run_once(
                root,
                task=task,
                source=source,
                executable=executable,
                tools=tools,
                bindings=bindings,
                repetition=0,
            )
            self.assertFalse(receipt["passed"])
            self.assertEqual(receipt["payload_bytes"], 0)
            self.assertEqual(receipt["error"], "compression produced an empty payload")
            resumed = self.run_once(
                root,
                task=task,
                source=source,
                executable=executable,
                tools=tools,
                bindings=bindings,
                repetition=0,
            )
            self.assertEqual(resumed, receipt)

    def test_failed_error_classification_and_source_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tools, executable, source, task, bindings = self.prepare(
                root, bad_decode=True
            )
            receipt = self.run_once(
                root,
                task=task,
                source=source,
                executable=executable,
                tools=tools,
                bindings=bindings,
                repetition=0,
            )
            receipt_path = MODULE.trial_path(root / "output", task, 0)
            receipt["error"] = "compression timed out"
            receipt_path.write_bytes(MODULE.PLANNER.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "classification is inconsistent"):
                self.run_once(
                    root,
                    task=task,
                    source=source,
                    executable=executable,
                    tools=tools,
                    bindings=bindings,
                    repetition=0,
                )
            source.write_bytes(b"changed source")
            with self.assertRaisesRegex(ValueError, "source identity differs"):
                self.run_once(
                    root,
                    task=task,
                    source=source,
                    executable=executable,
                    tools=tools,
                    bindings=bindings,
                    repetition=1,
                )

    def test_unavailable_profile_remains_visible_without_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _tools, _executable, _source, task, _bindings = self.prepare(root)
            row = MODULE.unavailable_task(task, "host lacks enough memory")
            self.assertEqual(row["execution_status"], "unavailable")
            self.assertEqual(row["measured_repetitions"], 0)
            self.assertFalse(row["complete"])
            self.assertEqual(row["axiom_outcome"], "untested")

    def test_host_benchmark_writes_bound_results_with_zero_axiom_wins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tools, executable, source, task, _bindings = self.prepare(root)
            manifest = root / "manifest.json"
            manifest.write_text("fixture manifest\n", encoding="utf-8")
            manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
            plan = {
                "schema_version": 1,
                "name": "text-source-research-ceiling-execution-plan-v1",
                "bindings": {
                    "repository_commit": "e" * 40,
                    "corpus_manifest_sha256": manifest_sha256,
                },
                "measurement_policy": {
                    "warmups": 1,
                    "measured_repetitions": 2,
                    "local_peak_rss_cap_gib": 18.0,
                    "maximum_wall_hours_per_family_per_codec": 12.0,
                },
                "tasks": [task | {"host_class": "fixture-host"}],
                "claim_ceiling": "fixture development evidence only",
            }
            plan_path = root / "plan.json"
            plan_path.write_bytes(MODULE.PLANNER.json_bytes(plan))
            executable_record = {
                "path": executable.relative_to(tools).as_posix(),
                "bytes": executable.stat().st_size,
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
            toolchain = {
                "schema_version": 1,
                "name": "text-source-research-ceiling-toolchain-v1",
                "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "host": {
                    "host_id": "fixture-host-1",
                    "host_class": "fixture-host",
                    "platform": "fixture-os",
                    "machine": "fixture-machine",
                    "cpu": "fixture-cpu",
                    "logical_cpus": 4,
                    "memory_bytes": 8 * 1024**3,
                    "gpu": None,
                    "cuda": None,
                },
                "profiles": [
                    {
                        "profile_id": task["profile_id"],
                        "codec_id": task["codec_id"],
                        "status": "available",
                        "axiom_outcome": "untested",
                        "source_identity": {"version": "fixture"},
                        "executable": executable_record,
                        "runtime_assets": [],
                        "build_commands": [["fixture-build"]],
                        "compiler": "fixture-compiler",
                    }
                ],
                "claim_ceiling": (
                    "Toolchain availability is not a compression result or an Axiom win."
                ),
            }
            toolchain_path = root / "toolchain.json"
            toolchain_path.write_bytes(MODULE.PLANNER.json_bytes(toolchain))
            item = {
                "id": task["item_id"],
                "track": task["track"],
                "format": "source-bundle-v1",
                "path": str(source),
                "source_bytes": task["source_bytes"],
                "source_sha256": task["source_sha256"],
            }
            validation = {
                "verified": True,
                "host_id": "fixture-host-1",
                "host_class": "fixture-host",
                "available_profiles": 1,
                "unavailable_profiles": 0,
                "axiom_wins": 0,
                "plan_sha256": toolchain["plan_sha256"],
            }
            with (
                mock.patch.object(MODULE.TOOLCHAIN, "validate", return_value=validation),
                mock.patch.object(
                    MODULE.BASELINE_RUNNER,
                    "verify_manifest",
                    return_value=(manifest, {}, [item]),
                ),
            ):
                result_path = MODULE.benchmark(
                    plan_path=plan_path,
                    toolchain_receipt_path=toolchain_path,
                    tools_root=tools,
                    corpus=root,
                    output=root / "host-run",
                    timeout_seconds=10.0,
                )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(result["completed"])
            self.assertEqual(result["trial_count"], 3)
            self.assertTrue(result["all_host_formal_tasks_complete"])
            self.assertEqual(result["retained_artifact_count"], 1)
            self.assertEqual(result["axiom_wins"], 0)
            self.assertEqual(
                result["tasks"][0]["execution_status"],
                "measured_exact_deterministic",
            )
            with mock.patch.object(
                MODULE.TOOLCHAIN, "validate", return_value=validation
            ):
                verified = MODULE.validate_output(
                    plan_path=plan_path,
                    toolchain_receipt_path=toolchain_path,
                    tools_root=tools,
                    output=root / "host-run",
                )
                self.assertTrue(verified["verified"])
                self.assertEqual(verified["axiom_wins"], 0)

                result["axiom_wins"] = 1
                result_path.write_bytes(MODULE.PLANNER.json_bytes(result))
                with self.assertRaisesRegex(ValueError, "do not reconstruct"):
                    MODULE.validate_output(
                        plan_path=plan_path,
                        toolchain_receipt_path=toolchain_path,
                        tools_root=tools,
                        output=root / "host-run",
                    )
                result["axiom_wins"] = 0
                result_path.write_bytes(MODULE.PLANNER.json_bytes(result))

                extra = root / "host-run" / "trials" / "extra"
                extra.mkdir()
                with self.assertRaisesRegex(ValueError, "directory roster"):
                    MODULE.validate_output(
                        plan_path=plan_path,
                        toolchain_receipt_path=toolchain_path,
                        tools_root=tools,
                        output=root / "host-run",
                    )


if __name__ == "__main__":
    unittest.main()
