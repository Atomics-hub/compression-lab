import importlib.util
from pathlib import Path
import unittest

from tests.test_text_source_baseline_publication import MODULE as PUBLICATION


REPOSITORY = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY / "scripts" / "benchmark-text-source-baselines.py"
SPEC = importlib.util.spec_from_file_location("baseline_runner_command_parity", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load baseline runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class TextSourceBaselineCommandParityTests(unittest.TestCase):
    def test_publisher_templates_equal_every_executable_runner_command(self) -> None:
        tools = {
            name: {
                "path": (
                    REPOSITORY
                    / ".baseline-tools"
                    / "text-source-v1"
                    / "bin"
                    / ("bsc" if name == "libbsc" else name)
                    if name in {"kanzi", "libbsc"}
                    else Path("/fixture-tools") / name
                )
            }
            for name in PUBLICATION.EXPECTED_TOOLS
        }
        work = Path("/private/tmp/baseline-command-parity")
        for item_id, track in PUBLICATION.EXPECTED_ITEMS:
            format_name, extension = (
                ("source-bundle-v1", "axsrc")
                if track == "source_code_bundles"
                else ("wikimedia-revision-text-v1", "axwkt")
            )
            item = {"id": item_id, "track": track, "format": format_name}
            source = (
                REPOSITORY
                / "corpora"
                / "text-source-development-v1"
                / f"{item_id}.{extension}"
            )
            artifact = work / "artifact.bin"
            restored = work / "restored.bin"
            for codec_id in PUBLICATION.EXPECTED_CODECS:
                compress, _c_out, decompress, _d_out = RUNNER.codec_commands(
                    codec_id, tools, source, artifact, restored
                )
                observed = {
                    "compression": RUNNER.sanitize_process_record(
                        {"command": compress}, work
                    )["command"],
                    "decompression": RUNNER.sanitize_process_record(
                        {"command": decompress}, work
                    )["command"],
                }
                self.assertEqual(
                    observed,
                    PUBLICATION.expected_commands(codec_id, item),
                    f"publisher/runner command drift for {codec_id}/{item_id}",
                )


if __name__ == "__main__":
    unittest.main()
