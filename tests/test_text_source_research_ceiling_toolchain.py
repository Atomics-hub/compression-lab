import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
PLANNER_PATH = (
    REPOSITORY / "scripts" / "prepare-text-source-research-ceiling-execution.py"
)
VALIDATOR_PATH = (
    REPOSITORY / "scripts" / "validate-text-source-research-ceiling-toolchain.py"
)
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLANNER = load("research_ceiling_planner_for_toolchain_test", PLANNER_PATH)
VALIDATOR = load("research_ceiling_toolchain_validator", VALIDATOR_PATH)


def source_identity(candidate: dict) -> dict:
    return VALIDATOR.expected_source_identity(candidate)


def file_record(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class TextSourceResearchCeilingToolchainTests(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, dict]:
        config_raw = CONFIG.read_bytes()
        config = json.loads(config_raw)
        plan = PLANNER.build_plan(
            config,
            baseline_fixture(),
            config_sha256=PLANNER.sha256_bytes(config_raw),
            baseline_sha256="b" * 64,
            repository_commit="c" * 40,
        )
        plan_path = root / "plan.json"
        PLANNER.write_immutable(plan_path, plan)
        tools = root / "tools"
        (tools / "bin").mkdir(parents=True)
        candidates = {row["codec_id"]: row for row in plan["candidate_identities"]}
        profiles = []
        for profile_id, codec_id in (
            ("zpaq-5-m510", "zpaq-5"),
            ("paq8px-11L-local-screen", "paq8px-forcetext"),
        ):
            binary = tools / "bin" / profile_id
            binary.write_bytes(profile_id.encode())
            binary.chmod(0o755)
            profiles.append(
                {
                    "profile_id": profile_id,
                    "codec_id": codec_id,
                    "status": "available",
                    "axiom_outcome": "untested",
                    "source_identity": source_identity(candidates[codec_id]),
                    "executable": {
                        "path": binary.relative_to(tools).as_posix(),
                        "bytes": binary.stat().st_size,
                        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                    },
                    "runtime_assets": [],
                    "build_commands": VALIDATOR.expected_build_commands(
                        candidates[codec_id]
                    ),
                    "compiler": "fixture-c++ 1.0",
                }
            )
        receipt = {
            "schema_version": 1,
            "name": "text-source-research-ceiling-toolchain-v1",
            "plan_sha256": VALIDATOR.sha256_file(plan_path),
            "host": {
                "host_id": "fixture-local",
                "host_class": "local-macos-18-gib-rss-cap",
                "platform": "fixture-os",
                "machine": "arm64",
                "cpu": "fixture-cpu",
                "logical_cpus": 10,
                "memory_bytes": 32 * 1024**3,
                "gpu": None,
                "cuda": None,
            },
            "profiles": profiles,
            "claim_ceiling": (
                "Toolchain availability is not a compression result or an Axiom win."
            ),
        }
        receipt_path = root / "receipt.json"
        receipt_path.write_bytes(PLANNER.json_bytes(receipt))
        return plan_path, receipt_path, receipt

    def test_available_local_toolchain_binds_every_binary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, receipt, _payload = self.prepare(root)
            result = VALIDATOR.validate(plan, receipt, root / "tools")
            self.assertTrue(result["verified"])
            self.assertEqual(result["available_profiles"], 2)
            self.assertEqual(result["axiom_wins"], 0)

            binary = root / "tools" / "bin" / "zpaq-5-m510"
            binary.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "file identity differs"):
                VALIDATOR.validate(plan, receipt, root / "tools")

    def test_unavailable_profile_is_visible_but_never_a_win(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, receipt_path, receipt = self.prepare(root)
            candidate = receipt["profiles"][1]
            receipt["profiles"][1] = {
                "profile_id": candidate["profile_id"],
                "codec_id": candidate["codec_id"],
                "status": "unavailable",
                "axiom_outcome": "untested",
                "source_identity": candidate["source_identity"],
                "reason": "build failed on the declared host",
            }
            receipt_path.write_bytes(PLANNER.json_bytes(receipt))
            result = VALIDATOR.validate(plan, receipt_path, root / "tools")
            self.assertEqual(result["available_profiles"], 1)
            self.assertEqual(result["unavailable_profiles"], 1)
            self.assertEqual(result["axiom_wins"], 0)

    def test_host_class_cannot_omit_or_import_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, receipt_path, receipt = self.prepare(root)
            receipt["host"]["host_class"] = "larger-isolated-memory-host"
            receipt_path.write_bytes(PLANNER.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "profile roster differs"):
                VALIDATOR.validate(plan, receipt_path, root / "tools")

    def test_cmix_dictionary_is_a_required_byte_verified_runtime_asset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan_path, _local_receipt, _payload = self.prepare(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            candidates = {row["codec_id"]: row for row in plan["candidate_identities"]}
            dictionary_bytes = b"fixture cmix english dictionary"
            dictionary_sha = hashlib.sha256(dictionary_bytes).hexdigest()
            asset = candidates["cmix"]["required_decoder_assets"][0]
            asset["bytes"] = len(dictionary_bytes)
            asset["sha256"] = dictionary_sha
            for task in plan["tasks"]:
                if task["profile_id"] == "cmix-v21-strong-text":
                    task["counted_side_asset_bytes"] = len(dictionary_bytes)
                    task["counted_side_asset_sha256"] = dictionary_sha
            plan_path.write_bytes(PLANNER.json_bytes(plan))

            tools = root / "cmix-tools"
            executable = tools / "bin" / "cmix"
            dictionary = tools / "dictionary" / "english.dic"
            executable.parent.mkdir(parents=True)
            dictionary.parent.mkdir(parents=True)
            executable.write_bytes(b"cmix binary")
            executable.chmod(0o755)
            dictionary.write_bytes(dictionary_bytes)
            receipt = {
                "schema_version": 1,
                "name": "text-source-research-ceiling-toolchain-v1",
                "plan_sha256": VALIDATOR.sha256_file(plan_path),
                "host": {
                    "host_id": "fixture-cmix",
                    "host_class": "larger-isolated-memory-host-portable-o3-build",
                    "platform": "fixture-linux",
                    "machine": "x86_64",
                    "cpu": "fixture-cpu",
                    "logical_cpus": 16,
                    "memory_bytes": 64 * 1024**3,
                    "gpu": None,
                    "cuda": None,
                },
                "profiles": [
                    {
                        "profile_id": "cmix-v21-strong-text",
                        "codec_id": "cmix",
                        "status": "available",
                        "axiom_outcome": "untested",
                        "source_identity": source_identity(candidates["cmix"]),
                        "executable": file_record(executable, tools),
                        "runtime_assets": [file_record(dictionary, tools)],
                        "build_commands": VALIDATOR.expected_build_commands(
                            candidates["cmix"]
                        ),
                        "compiler": "fixture-c++ 1.0",
                    }
                ],
                "claim_ceiling": (
                    "Toolchain availability is not a compression result or an Axiom win."
                ),
            }
            receipt_path = root / "cmix-receipt.json"
            receipt_path.write_bytes(PLANNER.json_bytes(receipt))
            result = VALIDATOR.validate(plan_path, receipt_path, tools)
            self.assertEqual(result["available_profiles"], 1)
            dictionary.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "file identity differs"):
                VALIDATOR.validate(plan_path, receipt_path, tools)

    def test_nncp_availability_requires_pinned_libraries_gpu_and_cuda(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan_path, _local_receipt, _payload = self.prepare(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            candidates = {row["codec_id"]: row for row in plan["candidate_identities"]}
            tools = root / "nncp-tools"
            executable = tools / "bin" / "nncp"
            cpu_library = tools / "nncp-2024-06-05" / "libnc.so"
            cuda_library = tools / "nncp-2024-06-05" / "libnc_cuda.so"
            executable.parent.mkdir(parents=True)
            cpu_library.parent.mkdir(parents=True)
            executable.write_bytes(b"nncp binary")
            executable.chmod(0o755)
            cpu_library.write_bytes(b"cpu runtime")
            cuda_library.write_bytes(b"cuda runtime")
            runtime = candidates["nncp"]["bundled_runtime_identity"]
            for identity, path in (
                (runtime["cpu_library"], cpu_library),
                (runtime["cuda_library"], cuda_library),
            ):
                identity["bytes"] = path.stat().st_size
                identity["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            plan_path.write_bytes(PLANNER.json_bytes(plan))
            receipt = {
                "schema_version": 1,
                "name": "text-source-research-ceiling-toolchain-v1",
                "plan_sha256": VALIDATOR.sha256_file(plan_path),
                "host": {
                    "host_id": "fixture-nncp",
                    "host_class": "authorized-linux-cuda-host-plus-second-host-decode",
                    "platform": "fixture-linux",
                    "machine": "x86_64",
                    "cpu": "fixture-cpu",
                    "logical_cpus": 32,
                    "memory_bytes": 64 * 1024**3,
                    "gpu": None,
                    "cuda": None,
                },
                "profiles": [
                    {
                        "profile_id": "nncp-3.3-transformer",
                        "codec_id": "nncp",
                        "status": "available",
                        "axiom_outcome": "untested",
                        "source_identity": source_identity(candidates["nncp"]),
                        "executable": file_record(executable, tools),
                        "runtime_assets": [
                            file_record(cpu_library, tools),
                            file_record(cuda_library, tools),
                        ],
                        "build_commands": VALIDATOR.expected_build_commands(
                            candidates["nncp"]
                        ),
                        "compiler": "fixture-gcc 1.0",
                    }
                ],
                "claim_ceiling": (
                    "Toolchain availability is not a compression result or an Axiom win."
                ),
            }
            receipt_path = root / "nncp-receipt.json"
            receipt_path.write_bytes(PLANNER.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "requires GPU and CUDA"):
                VALIDATOR.validate(plan_path, receipt_path, tools)
            receipt["host"]["gpu"] = "fixture-gpu"
            receipt["host"]["cuda"] = "fixture-cuda"
            receipt_path.write_bytes(PLANNER.json_bytes(receipt))
            result = VALIDATOR.validate(plan_path, receipt_path, tools)
            self.assertEqual(result["available_profiles"], 1)


if __name__ == "__main__":
    unittest.main()
