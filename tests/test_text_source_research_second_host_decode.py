import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPOSITORY
    / "scripts"
    / "verify-text-source-research-second-host-decode.py"
)
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
SPEC = importlib.util.spec_from_file_location("research_second_host_decode", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load second-host decode verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


FAKE_NNCP = """#!/usr/bin/env python3
import shutil
import sys
shutil.copyfile(sys.argv[-2], sys.argv[-1])
"""


class TextSourceResearchSecondHostDecodeTests(unittest.TestCase):
    def prepare(self, root: Path):
        config_raw = CONFIG.read_bytes()
        config = json.loads(config_raw)
        plan = MODULE.PLANNER.build_plan(
            config,
            baseline_fixture(),
            config_sha256=hashlib.sha256(config_raw).hexdigest(),
            baseline_sha256="b" * 64,
            repository_commit="c" * 40,
        )
        nncp_tasks = [
            task for task in plan["tasks"] if task["profile_id"] == MODULE.PROFILE_ID
        ]
        payloads = {}
        for index, task in enumerate(nncp_tasks):
            payload = (f"second host fixture {index}\n".encode()) * (index + 2)
            payloads[task["task_id"]] = payload
            task["source_bytes"] = len(payload)
            task["source_sha256"] = hashlib.sha256(payload).hexdigest()

        candidate = next(
            row for row in plan["candidate_identities"] if row["codec_id"] == "nncp"
        )
        runtime_payloads = [b"fixture cpu runtime", b"fixture cuda runtime"]
        for identity, payload in zip(
            (
                candidate["bundled_runtime_identity"]["cpu_library"],
                candidate["bundled_runtime_identity"]["cuda_library"],
            ),
            runtime_payloads,
            strict=True,
        ):
            identity["bytes"] = len(payload)
            identity["sha256"] = hashlib.sha256(payload).hexdigest()

        plan_path = root / "plan.json"
        plan_path.write_bytes(MODULE.PLANNER.json_bytes(plan))
        primary = root / "primary"
        task_results = []
        artifact_paths = set()
        for task in nncp_tasks:
            artifact = MODULE.RUNNER.retained_artifact_path(primary, task)
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(payloads[task["task_id"]])
            artifact_paths.add(artifact)
            task_results.append(
                {
                    "task_id": task["task_id"],
                    "profile_id": MODULE.PROFILE_ID,
                    "codec_id": "nncp",
                    "item_id": task["item_id"],
                    "track": task["track"],
                    "formal_ceiling_eligible": True,
                    "source_bytes": task["source_bytes"],
                    "measured_repetitions": 2,
                    "complete": True,
                    "deterministic": True,
                    "complete_artifact_bytes": len(payloads[task["task_id"]]),
                    "payload_sha256": hashlib.sha256(
                        payloads[task["task_id"]]
                    ).hexdigest(),
                    "exact_roundtrip": True,
                    "portability_status": "pending_second_host_decode",
                    "formal_ceiling_admitted": False,
                    "execution_status": "measured_exact_deterministic",
                    "axiom_outcome": "baseline_measurement_only",
                }
            )
        artifact_count, artifact_manifest = MODULE.RUNNER.retained_artifact_manifest(
            primary, artifact_paths
        )
        primary_results = {
            "completed": True,
            "bindings": {"plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest()},
            "host": {
                "host_id": "primary-nncp-host",
                "host_class": MODULE.HOST_CLASS,
            },
            "profile_ids": [MODULE.PROFILE_ID],
            "tasks": task_results,
            "retained_artifact_count": artifact_count,
            "retained_artifact_manifest_sha256": artifact_manifest,
            "all_host_formal_tasks_complete": False,
            "axiom_wins": 0,
        }
        (primary / "results.json").write_bytes(
            MODULE.PLANNER.json_bytes(primary_results)
        )

        tools = root / "second-tools"
        executable = tools / "bin" / MODULE.PROFILE_ID
        executable.parent.mkdir(parents=True)
        executable.write_text(FAKE_NNCP, encoding="utf-8")
        executable.chmod(0o755)
        runtime_assets = []
        identities = (
            candidate["bundled_runtime_identity"]["cpu_library"],
            candidate["bundled_runtime_identity"]["cuda_library"],
        )
        for identity, payload in zip(identities, runtime_payloads, strict=True):
            path = tools / identity["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            runtime_assets.append(
                {
                    "path": identity["path"],
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        executable_record = {
            "path": executable.relative_to(tools).as_posix(),
            "bytes": executable.stat().st_size,
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        }
        source_identity = MODULE.TOOLCHAIN.expected_source_identity(candidate)
        toolchain = {
            "schema_version": 1,
            "name": "text-source-research-ceiling-toolchain-v1",
            "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "host": {
                "host_id": "second-nncp-host",
                "host_class": MODULE.HOST_CLASS,
                "platform": "fixture-linux",
                "machine": "x86_64",
                "cpu": "fixture-cpu",
                "logical_cpus": 32,
                "memory_bytes": 64 * 1024**3,
                "gpu": "fixture-gpu-2",
                "cuda": "fixture-cuda-2",
            },
            "profiles": [
                {
                    "profile_id": MODULE.PROFILE_ID,
                    "codec_id": "nncp",
                    "status": "available",
                    "axiom_outcome": "untested",
                    "source_identity": source_identity,
                    "executable": executable_record,
                    "runtime_assets": runtime_assets,
                    "build_commands": MODULE.TOOLCHAIN.expected_build_commands(
                        candidate
                    ),
                    "compiler": "fixture compiler",
                }
            ],
            "claim_ceiling": (
                "Toolchain availability is not a compression result or an Axiom win."
            ),
        }
        toolchain_path = root / "second-toolchain.json"
        toolchain_path.write_bytes(MODULE.PLANNER.json_bytes(toolchain))
        return plan_path, primary, toolchain_path, tools

    def test_distinct_second_host_decodes_every_retained_nncp_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, primary, toolchain, tools = self.prepare(root)
            output = root / "second-run"
            result_path = MODULE.execute(
                plan_path=plan,
                primary_output=primary,
                second_toolchain_receipt_path=toolchain,
                second_tools_root=tools,
                output=output,
                timeout_seconds=10.0,
            )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["receipt_count"], 7)
            self.assertTrue(result["all_nncp_second_host_decodes_exact"])
            self.assertTrue(result["formal_nncp_ceiling_admitted"])
            self.assertEqual(result["axiom_wins"], 0)
            verification = MODULE.validate_output(
                plan_path=plan,
                primary_output=primary,
                second_toolchain_receipt_path=toolchain,
                second_tools_root=tools,
                output=output,
            )
            self.assertTrue(verification["verified"])
            self.assertNotEqual(
                verification["primary_host_id"], verification["second_host_id"]
            )

            result["axiom_wins"] = 1
            result_path.write_bytes(MODULE.PLANNER.json_bytes(result))
            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                MODULE.validate_output(
                    plan_path=plan,
                    primary_output=primary,
                    second_toolchain_receipt_path=toolchain,
                    second_tools_root=tools,
                    output=output,
                )

    def test_same_host_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, primary, toolchain_path, tools = self.prepare(root)
            toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
            toolchain["host"]["host_id"] = "primary-nncp-host"
            toolchain_path.write_bytes(MODULE.PLANNER.json_bytes(toolchain))
            with self.assertRaisesRegex(ValueError, "not distinct"):
                MODULE.execute(
                    plan_path=plan,
                    primary_output=primary,
                    second_toolchain_receipt_path=toolchain_path,
                    second_tools_root=tools,
                    output=root / "second-run",
                    timeout_seconds=10.0,
                )


if __name__ == "__main__":
    unittest.main()
