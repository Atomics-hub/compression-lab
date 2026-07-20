import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from tests.test_text_source_baseline_publication import fixture as baseline_fixture


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPOSITORY / "scripts" / "prepare-external-text-source-research-toolchain.py"
)
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"
SPEC = importlib.util.spec_from_file_location("external_research_toolchain", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load external research toolchain builder")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExternalTextSourceResearchToolchainTests(unittest.TestCase):
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
    def host(host_class: str) -> dict:
        return {
            "host_id": f"fixture-{host_class}",
            "host_class": host_class,
            "platform": "fixture-linux",
            "machine": "x86_64",
            "cpu": "fixture-cpu",
            "logical_cpus": 32,
            "memory_bytes": 64 * 1024**3,
            "gpu": None,
            "cuda": None,
        }

    @staticmethod
    def fake_paq_builder(_candidate: dict, root: Path, **_kwargs):
        executable = root / "bin" / "paq8px-12L-absolute"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"fixture paq8px")
        executable.chmod(0o755)
        return executable, []

    def test_paq_larger_host_receipt_is_immutable_and_validator_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = self.plan(root)
            tools = root / "tools"
            host_class = MODULE.PROFILE_SPECS["paq8px-12L-absolute"]["host_class"]
            with (
                mock.patch.object(
                    MODULE.LOCAL, "resolve_program", return_value=Path("/usr/bin/cc")
                ),
                mock.patch.object(
                    MODULE.LOCAL, "compiler_identity", return_value="fixture compiler"
                ),
                mock.patch.object(
                    MODULE, "host_record", return_value=self.host(host_class)
                ),
                mock.patch.object(
                    MODULE, "build_paq8px", side_effect=self.fake_paq_builder
                ),
            ):
                receipt_path = MODULE.prepare(
                    plan_path=plan,
                    root=tools,
                    profile_id="paq8px-12L-absolute",
                    host_id="fixture-paq-host",
                    cxx_name="c++",
                    cc_name="cc",
                    gpu=None,
                    cuda=None,
                    allow_download=False,
                )
                second = MODULE.prepare(
                    plan_path=plan,
                    root=tools,
                    profile_id="paq8px-12L-absolute",
                    host_id="fixture-paq-host",
                    cxx_name="c++",
                    cc_name="cc",
                    gpu=None,
                    cuda=None,
                    allow_download=False,
                )
            self.assertEqual(receipt_path, second)
            result = MODULE.VALIDATOR.validate(plan, receipt_path, tools)
            self.assertEqual(result["host_class"], host_class)
            self.assertEqual(result["available_profiles"], 1)
            self.assertEqual(result["axiom_wins"], 0)

    def test_safe_nncp_tar_extraction_rejects_links_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            valid = root / "valid.tar.gz"
            with tarfile.open(valid, "w:gz") as archive:
                directory = tarfile.TarInfo("nncp-2024-06-05")
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
                payload = b"fixture"
                info = tarfile.TarInfo("nncp-2024-06-05/readme.txt")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            destination = root / "valid-output"
            MODULE.safe_extract_tar(valid, destination)
            self.assertEqual(
                (destination / "nncp-2024-06-05" / "readme.txt").read_bytes(),
                b"fixture",
            )

            traversal = root / "traversal.tar.gz"
            with tarfile.open(traversal, "w:gz") as archive:
                payload = b"bad"
                info = tarfile.TarInfo("nncp-2024-06-05/../../escape")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(ValueError, "unsafe"):
                MODULE.safe_extract_tar(traversal, root / "traversal-output")

            symlink = root / "symlink.tar.gz"
            with tarfile.open(symlink, "w:gz") as archive:
                info = tarfile.TarInfo("nncp-2024-06-05/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/target"
                archive.addfile(info)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                MODULE.safe_extract_tar(symlink, root / "symlink-output")
            self.assertFalse((root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
