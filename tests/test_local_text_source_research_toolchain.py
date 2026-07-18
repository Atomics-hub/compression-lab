import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "prepare-local-text-source-research-toolchain.py"
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
SPEC = importlib.util.spec_from_file_location("local_research_toolchain", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load local research toolchain builder")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LocalTextSourceResearchToolchainTests(unittest.TestCase):
    def plan(self, root: Path) -> Path:
        config_raw = CONFIG.read_bytes()
        config = json.loads(config_raw)
        plan = MODULE.PLANNER.build_plan(
            config,
            baseline_fixture(),
            config_sha256=hashlib.sha256(config_raw).hexdigest(),
            baseline_sha256="b" * 64,
            repository_commit="c" * 40,
        )
        path = root / "plan.json"
        path.write_bytes(MODULE.PLANNER.json_bytes(plan))
        return path

    @staticmethod
    def host() -> dict:
        return {
            "host_id": "local-macos-fixture",
            "host_class": MODULE.LOCAL_HOST_CLASS,
            "platform": "fixture-macos",
            "machine": "arm64",
            "cpu": "fixture-cpu",
            "logical_cpus": 10,
            "memory_bytes": 32 * 1024**3,
            "gpu": None,
            "cuda": None,
        }

    @staticmethod
    def fake_builder(candidate: dict, root: Path, **_kwargs) -> Path:
        name = (
            "zpaq-5-m510"
            if candidate["codec_id"] == "zpaq-5"
            else "paq8px-11L-local-screen"
        )
        destination = root / "bin" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"fixture {name}".encode())
        destination.chmod(0o755)
        return destination

    def test_builder_emits_an_immutable_validator_accepted_local_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = self.plan(root)
            tools = root / "tools"
            with (
                mock.patch.object(MODULE, "resolve_program", return_value=Path("/usr/bin/cc")),
                mock.patch.object(MODULE, "compiler_identity", return_value="fixture compiler"),
                mock.patch.object(MODULE, "host_record", return_value=self.host()),
                mock.patch.object(MODULE, "build_zpaq", side_effect=self.fake_builder),
                mock.patch.object(MODULE, "build_paq8px", side_effect=self.fake_builder),
            ):
                receipt_path = MODULE.prepare(
                    plan_path=plan, root=tools, allow_download=False
                )
                second = MODULE.prepare(
                    plan_path=plan, root=tools, allow_download=False
                )
            self.assertEqual(receipt_path, second)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["profile_id"] for row in receipt["profiles"]],
                MODULE.LOCAL_PROFILES,
            )
            self.assertEqual({row["status"] for row in receipt["profiles"]}, {"available"})
            self.assertTrue(
                all(row["build_commands"] for row in receipt["profiles"])
            )
            result = MODULE.VALIDATOR.validate(plan, receipt_path, tools)
            self.assertEqual(result["available_profiles"], 2)
            self.assertEqual(result["axiom_wins"], 0)

    def test_changed_predeclared_build_command_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = self.plan(root)
            tools = root / "tools"
            with (
                mock.patch.object(MODULE, "resolve_program", return_value=Path("/usr/bin/cc")),
                mock.patch.object(MODULE, "compiler_identity", return_value="fixture compiler"),
                mock.patch.object(MODULE, "host_record", return_value=self.host()),
                mock.patch.object(MODULE, "build_zpaq", side_effect=self.fake_builder),
                mock.patch.object(MODULE, "build_paq8px", side_effect=self.fake_builder),
            ):
                receipt_path = MODULE.prepare(
                    plan_path=plan, root=tools, allow_download=False
                )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["profiles"][0]["build_commands"][0].append("-march=native")
            receipt_path.write_bytes(MODULE.PLANNER.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "available profile record"):
                MODULE.VALIDATOR.validate(plan, receipt_path, tools)

    def test_unavailable_receipt_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = self.plan(root)
            tools = root / "tools"
            patches = (
                mock.patch.object(MODULE, "resolve_program", return_value=Path("/usr/bin/cc")),
                mock.patch.object(MODULE, "compiler_identity", return_value="fixture compiler"),
                mock.patch.object(MODULE, "host_record", return_value=self.host()),
                mock.patch.object(MODULE, "build_zpaq", side_effect=ValueError("offline")),
                mock.patch.object(MODULE, "build_paq8px", side_effect=ValueError("offline")),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                with self.assertRaisesRegex(ValueError, "local build unavailable"):
                    MODULE.prepare(
                        plan_path=plan,
                        root=tools,
                        allow_download=False,
                    )
            self.assertFalse((tools / "receipt.json").exists())

            patches = (
                mock.patch.object(MODULE, "resolve_program", return_value=Path("/usr/bin/cc")),
                mock.patch.object(MODULE, "compiler_identity", return_value="fixture compiler"),
                mock.patch.object(MODULE, "host_record", return_value=self.host()),
                mock.patch.object(MODULE, "build_zpaq", side_effect=ValueError("offline")),
                mock.patch.object(MODULE, "build_paq8px", side_effect=ValueError("offline")),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                receipt_path = MODULE.prepare(
                    plan_path=plan,
                    root=tools,
                    allow_download=False,
                    record_unavailable=True,
                )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {row["status"] for row in receipt["profiles"]}, {"unavailable"}
            )
            result = MODULE.VALIDATOR.validate(plan, receipt_path, tools)
            self.assertEqual(result["available_profiles"], 0)
            self.assertEqual(result["unavailable_profiles"], 2)
            self.assertEqual(result["axiom_wins"], 0)

    def test_zip_extraction_rejects_traversal_and_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as archive:
                archive.writestr("../escape", b"bad")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                MODULE.safe_extract_zip(traversal, root / "traversal-output")

            symlink = root / "symlink.zip"
            with zipfile.ZipFile(symlink, "w") as archive:
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = (0o120777 << 16) | 0xA000
                archive.writestr(info, "target")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                MODULE.safe_extract_zip(symlink, root / "symlink-output")
            self.assertFalse((root / "escape").exists())

    def test_installed_binary_must_remain_byte_identical_and_executable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            source.write_bytes(b"binary")
            source.chmod(0o755)
            destination = root / "tools" / "bin" / "codec"
            MODULE.install_binary(source, destination)
            self.assertEqual(destination.read_bytes(), b"binary")
            self.assertTrue(os.access(destination, os.X_OK))
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "differing tool binary"):
                MODULE.install_binary(source, destination)


if __name__ == "__main__":
    unittest.main()
