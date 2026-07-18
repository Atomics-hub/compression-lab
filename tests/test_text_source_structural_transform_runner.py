import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

from tests.test_text_source_baseline_publication import (
    fixture as baseline_fixture,
    write_trial_receipts as write_baseline_receipts,
)
REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-text-source-structural-transform.py"
SPEC = importlib.util.spec_from_file_location("text_source_structural_runner", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load structural transform runner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def source_bundle() -> bytes:
    path = b"src/example.py"
    content = b"def example(value):\n    return value + 1\n"
    output = bytearray(MODULE.text_source_transform.SOURCE_MAGIC)
    output.extend(struct.pack("<Q", 1))
    output.extend(struct.pack("<Q", len(path)))
    output.extend(path)
    output.extend(struct.pack("<Q", len(content)))
    output.extend(content)
    manifest = hashlib.sha256()
    manifest.update(path)
    manifest.update(content)
    output.extend(manifest.digest())
    return bytes(output)


def valid_process(
    *, command: list[str] | None = None, wall_ns: int, peak_rss_bytes: int
) -> dict[str, object]:
    return {
        "command": command or ["tool", "operation"],
        "returncode": 0,
        "timed_out": False,
        "wall_ns": wall_ns,
        "cpu_ns": 1,
        "peak_rss_bytes": peak_rss_bytes,
        "stdout": "",
        "stderr": "",
    }


def valid_resumed_receipt(bindings: dict[str, str]) -> dict[str, object]:
    item = {
        "path": str(REPOSITORY / "corpora" / "source.axsrc"),
        "source_bytes": 1234,
        "source_sha256": "ab" * 32,
    }
    commands = MODULE.expected_process_commands(
        item,
        "ts-h1-demux",
        REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi",
    )
    compression = [
        valid_process(
            command=commands["compression"][index],
            wall_ns=value,
            peak_rss_bytes=value * 10,
        )
        for index, value in enumerate((1, 2, 3))
    ]
    decompression = [
        valid_process(
            command=commands["decompression"][index],
            wall_ns=value,
            peak_rss_bytes=value * 10,
        )
        for index, value in enumerate((4, 5, 6))
    ]
    return {
        "schema_version": 1,
        "bindings": bindings,
        "variant": "ts-h1-demux",
        "item_id": "source",
        "track": "source_code_bundles",
        "repetition": 1,
        "warmup": False,
        "source_bytes": 1234,
        "source_sha256": "ab" * 32,
        "baseline_codec": "kanzi-max",
        "baseline_bytes": 500,
        "transformed_bytes": 700,
        "backend_payload_bytes": 400,
        "candidate_bytes": MODULE.FRAME_HEADER.size + 400,
        "candidate_sha256": "cd" * 32,
        "compression_wall_ns": 6,
        "decompression_wall_ns": 15,
        "compression_peak_rss_bytes": 30,
        "decompression_peak_rss_bytes": 60,
        "processes": {
            "compression": compression,
            "decompression": decompression,
        },
        "exact_roundtrip": True,
        "passed": True,
        "error": None,
    }


class TextSourceStructuralTransformRunnerTests(unittest.TestCase):
    def test_run_trial_executes_frozen_chain_and_resumes_its_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.axsrc"
            source.write_bytes(source_bundle())
            kanzi = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
            item = {
                "id": "source",
                "path": str(source),
                "format": "source-bundle-v1",
                "track": "source_code_bundles",
                "source_bytes": source.stat().st_size,
                "source_sha256": MODULE.file_digest(source),
                "baseline_bytes": source.stat().st_size,
                "baseline_compression_peak_rss_bytes": 1,
                "baseline_decompression_peak_rss_bytes": 1,
            }
            calls = []

            def fake_run_process(command, *, timeout_seconds):
                del timeout_seconds
                calls.append(command)
                if command[2] == "--worker-encode":
                    MODULE.worker_encode(Path(command[4]), Path(command[5]), command[3])
                elif command[1] == "--compress":
                    source_path = Path(command[-2].split("=", 1)[1])
                    destination = Path(command[-1].split("=", 1)[1])
                    destination.write_bytes(source_path.read_bytes())
                elif command[2] == "--worker-wrap":
                    MODULE.worker_wrap(
                        command[3],
                        command[4],
                        int(command[5]),
                        command[6],
                        Path(command[7]),
                        Path(command[8]),
                    )
                elif command[2] == "--worker-unwrap":
                    MODULE.worker_unwrap(
                        command[3],
                        command[4],
                        int(command[5]),
                        command[6],
                        Path(command[7]),
                        Path(command[8]),
                    )
                elif command[1] == "--decompress":
                    source_path = Path(command[-2].split("=", 1)[1])
                    destination = Path(command[-1].split("=", 1)[1])
                    destination.write_bytes(source_path.read_bytes())
                elif command[2] == "--worker-decode":
                    MODULE.worker_decode(Path(command[4]), Path(command[5]), int(command[3]))
                else:
                    raise AssertionError(f"unexpected command: {command}")
                return {
                    "command": command,
                    "returncode": 0,
                    "timed_out": False,
                    "wall_ns": 1,
                    "cpu_ns": 1,
                    "peak_rss_bytes": 1,
                    "stdout": "",
                    "stderr": "",
                }

            original = MODULE.run_process
            MODULE.run_process = fake_run_process
            try:
                receipt = MODULE.run_trial(
                    output=root / "run",
                    item=item,
                    variant="ts-h1-demux",
                    repetition=1,
                    kanzi=kanzi,
                    bindings={"repository_commit": "a" * 40},
                )
                resumed = MODULE.run_trial(
                    output=root / "run",
                    item=item,
                    variant="ts-h1-demux",
                    repetition=1,
                    kanzi=kanzi,
                    bindings={"repository_commit": "a" * 40},
                )
            finally:
                MODULE.run_process = original
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt, resumed)
            self.assertEqual(len(calls), 6)
            self.assertEqual(
                [row["command"] for row in receipt["processes"]["compression"]],
                MODULE.expected_process_commands(item, "ts-h1-demux", kanzi)[
                    "compression"
                ],
            )

    def test_process_receipt_sanitizes_repository_and_work_paths(self) -> None:
        work = Path("/private/var/folders/example/work")
        record = valid_process(wall_ns=1, peak_rss_bytes=1)
        record["command"] = [
            sys.executable,
            str(REPOSITORY / "scripts" / "worker.py"),
            str(work / "input.bin"),
        ]
        record["stdout"] = f"read {work / 'input.bin'}\n"
        record["stderr"] = f"runner {REPOSITORY}\n"
        sanitized = MODULE.sanitize_process_record(record, work)
        encoded = json.dumps(sanitized, sort_keys=True)
        self.assertNotIn(str(REPOSITORY), encoded)
        self.assertNotIn(str(work), encoded)
        self.assertEqual(sanitized["command"][0], "python")
        self.assertIn("$REPOSITORY/scripts/worker.py", sanitized["command"])
        self.assertIn("$WORK/input.bin", sanitized["stdout"])

    def test_baseline_dependency_requires_all_verified_trial_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            baseline = baseline_fixture()
            baseline_path = root / "results.json"
            baseline_path.write_text(
                json.dumps(baseline, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            write_baseline_receipts(root, baseline)
            MODULE.BASELINE_PUBLICATION.validate_trial_receipts(
                baseline_path, baseline
            )
            next((root / "trials").glob("*/*.r1.json")).unlink()
            with self.assertRaisesRegex(ValueError, "1 missing"):
                MODULE.BASELINE_PUBLICATION.validate_trial_receipts(
                    baseline_path, baseline
                )

    def test_candidate_frame_counts_header_and_backend_payload_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            payload.write_bytes(b"backend-payload" * 10)
            frame = root / "candidate.axtp"
            MODULE.build_frame(
                frame,
                variant="ts-h1-demux",
                backend="kanzi-max",
                source_bytes=1234,
                source_sha256="ab" * 32,
                payload=payload,
            )
            extracted = root / "extracted.knz"
            info = MODULE.extract_frame(
                frame,
                extracted,
                expected_variant="ts-h1-demux",
                expected_backend="kanzi-max",
            )
            self.assertEqual(
                frame.stat().st_size, MODULE.FRAME_HEADER.size + payload.stat().st_size
            )
            self.assertEqual(extracted.read_bytes(), payload.read_bytes())
            self.assertEqual(info["source_bytes"], 1234)
            self.assertEqual(info["source_sha256"], "ab" * 32)
            self.assertEqual(info["backend"], "kanzi-max")
            self.assertEqual(info["payload_sha256"], MODULE.file_digest(payload))

    def test_candidate_frame_rejects_corrupted_backend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            payload.write_bytes(b"backend-payload" * 10)
            frame = root / "candidate.axtp"
            MODULE.build_frame(
                frame,
                variant="ts-h1-demux",
                backend="kanzi-max",
                source_bytes=1234,
                source_sha256="ab" * 32,
                payload=payload,
            )
            corrupted = bytearray(frame.read_bytes())
            corrupted[-1] ^= 1
            frame.write_bytes(corrupted)
            extracted = root / "extracted.knz"
            with self.assertRaisesRegex(ValueError, "payload SHA-256 mismatch"):
                MODULE.extract_frame(
                    frame,
                    extracted,
                    expected_variant="ts-h1-demux",
                    expected_backend="kanzi-max",
                )
            self.assertFalse(extracted.exists())

    def test_candidate_frame_rejects_source_identity_and_removes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            payload.write_bytes(b"backend-payload" * 10)
            frame = root / "candidate.axtp"
            MODULE.build_frame(
                frame,
                variant="ts-h1-demux",
                backend="kanzi-max",
                source_bytes=1234,
                source_sha256="ab" * 32,
                payload=payload,
            )
            extracted = root / "extracted.knz"
            with self.assertRaisesRegex(ValueError, "source identity mismatch"):
                MODULE.worker_unwrap(
                    "ts-h1-demux",
                    "kanzi-max",
                    1234,
                    "cd" * 32,
                    frame,
                    extracted,
                )
            self.assertFalse(extracted.exists())

    def test_candidate_frame_rejects_every_one_bit_header_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            payload.write_bytes(b"backend-payload" * 10)
            frame = root / "candidate.axtp"
            MODULE.build_frame(
                frame,
                variant="ts-h1-demux",
                backend="kanzi-max",
                source_bytes=1234,
                source_sha256="ab" * 32,
                payload=payload,
            )
            original = frame.read_bytes()
            for offset in range(MODULE.FRAME_HEADER.size):
                for bit in range(8):
                    corrupted = bytearray(original)
                    corrupted[offset] ^= 1 << bit
                    frame.write_bytes(corrupted)
                    extracted = root / "extracted.knz"
                    with self.assertRaises(ValueError):
                        MODULE.worker_unwrap(
                            "ts-h1-demux",
                            "kanzi-max",
                            1234,
                            "ab" * 32,
                            frame,
                            extracted,
                        )
                    self.assertFalse(extracted.exists())

    def test_candidate_frame_rejects_truncation_append_and_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            payload.write_bytes(b"backend-payload" * 10)
            frame = root / "candidate.axtp"
            MODULE.build_frame(
                frame,
                variant="ts-h1-demux",
                backend="kanzi-max",
                source_bytes=1234,
                source_sha256="ab" * 32,
                payload=payload,
            )
            original = frame.read_bytes()
            extracted = root / "extracted.knz"

            for length in range(MODULE.FRAME_HEADER.size):
                frame.write_bytes(original[:length])
                extracted.write_bytes(b"stale")
                with self.assertRaisesRegex(ValueError, "header is truncated"):
                    MODULE.extract_frame(
                        frame,
                        extracted,
                        expected_variant="ts-h1-demux",
                        expected_backend="kanzi-max",
                    )
                self.assertFalse(extracted.exists())

            for corrupted in (original[:-1], original + b"appended"):
                frame.write_bytes(corrupted)
                extracted.write_bytes(b"stale")
                with self.assertRaisesRegex(ValueError, "payload length mismatch"):
                    MODULE.extract_frame(
                        frame,
                        extracted,
                        expected_variant="ts-h1-demux",
                        expected_backend="kanzi-max",
                    )
                self.assertFalse(extracted.exists())

    def test_resumed_receipt_must_match_every_frozen_identity(self) -> None:
        item = {
            "id": "source",
            "track": "source_code_bundles",
            "source_bytes": 1234,
            "source_sha256": "ab" * 32,
            "baseline_bytes": 500,
            "path": str(REPOSITORY / "corpora" / "source.axsrc"),
        }
        bindings = {"repository_commit": "abc"}
        existing = valid_resumed_receipt(bindings)
        commands = MODULE.expected_process_commands(
            item,
            "ts-h1-demux",
            REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi",
        )
        MODULE.validate_existing_trial(
            existing,
            bindings=bindings,
            item=item,
            variant="ts-h1-demux",
            repetition=1,
            expected_commands=commands,
            destination=Path("receipt.json"),
        )
        existing["source_sha256"] = "cd" * 32
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            MODULE.validate_existing_trial(
                existing,
                bindings=bindings,
                item=item,
                variant="ts-h1-demux",
                repetition=1,
                expected_commands=commands,
                destination=Path("receipt.json"),
            )

    def test_resumed_receipt_rejects_tampered_process_accounting(self) -> None:
        item = {
            "id": "source",
            "track": "source_code_bundles",
            "source_bytes": 1234,
            "source_sha256": "ab" * 32,
            "baseline_bytes": 500,
            "path": str(REPOSITORY / "corpora" / "source.axsrc"),
        }
        bindings = {"repository_commit": "abc"}
        existing = valid_resumed_receipt(bindings)
        commands = MODULE.expected_process_commands(
            item,
            "ts-h1-demux",
            REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi",
        )
        existing["compression_wall_ns"] = 7
        with self.assertRaisesRegex(ValueError, "wall accounting is invalid"):
            MODULE.validate_existing_trial(
                existing,
                bindings=bindings,
                item=item,
                variant="ts-h1-demux",
                repetition=1,
                expected_commands=commands,
                destination=Path("receipt.json"),
            )

    def test_resumed_receipt_rejects_changed_process_command(self) -> None:
        item = {
            "id": "source",
            "track": "source_code_bundles",
            "source_bytes": 1234,
            "source_sha256": "ab" * 32,
            "baseline_bytes": 500,
            "path": str(REPOSITORY / "corpora" / "source.axsrc"),
        }
        bindings = {"repository_commit": "abc"}
        existing = valid_resumed_receipt(bindings)
        commands = MODULE.expected_process_commands(
            item,
            "ts-h1-demux",
            REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi",
        )
        existing["processes"]["compression"][1]["command"][2] = "--level=8"
        with self.assertRaisesRegex(ValueError, "process is invalid"):
            MODULE.validate_existing_trial(
                existing,
                bindings=bindings,
                item=item,
                variant="ts-h1-demux",
                repetition=1,
                expected_commands=commands,
                destination=Path("receipt.json"),
            )

    def test_envelope_worker_cli_round_trips_backend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            payload.write_bytes(b"backend" * 100)
            frame = root / "candidate.axtp"
            extracted = root / "extracted.knz"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--worker-wrap",
                    "ts-h1-demux",
                    "kanzi-max",
                    "1234",
                    "ab" * 32,
                    str(payload),
                    str(frame),
                ],
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--worker-unwrap",
                    "ts-h1-demux",
                    "kanzi-max",
                    "1234",
                    "ab" * 32,
                    str(frame),
                    str(extracted),
                ],
                check=True,
            )
            self.assertEqual(extracted.read_bytes(), payload.read_bytes())

    def test_variants_preserve_track_scope(self) -> None:
        source = {"format": "source-bundle-v1"}
        wiki = {"format": "wikimedia-revision-text-v1"}
        self.assertEqual(
            MODULE.variants_for(source),
            ["ts-h1-demux", "ts-h2-extension-lanes"],
        )
        self.assertEqual(MODULE.variants_for(wiki), ["ts-h1-demux"])

    def test_summary_applies_predeclared_ratio_item_and_resource_gates(self) -> None:
        item = {
            "id": "source",
            "format": "source-bundle-v1",
            "track": "source_code_bundles",
            "source_bytes": 10_000,
            "baseline_bytes": 1_000,
            "baseline_compression_peak_rss_bytes": 100,
            "baseline_decompression_peak_rss_bytes": 100,
        }
        trials = []
        for variant, candidate in (
            ("ts-h1-demux", 990),
            ("ts-h2-extension-lanes", 960),
        ):
            for repetition in (1, 2):
                trials.append(
                    {
                        "warmup": False,
                        "passed": True,
                        "item_id": "source",
                        "variant": variant,
                        "candidate_bytes": candidate,
                        "candidate_sha256": variant,
                        "compression_wall_ns": 10,
                        "decompression_wall_ns": 20,
                        "compression_peak_rss_bytes": 200,
                        "decompression_peak_rss_bytes": 200,
                    }
                )
        summary = MODULE.summarize(trials, [item])
        variants = {
            row["variant"]: row for row in summary["tracks"]["source_code_bundles"]
        }
        self.assertTrue(variants["ts-h1-demux"]["hypothesis_gate_passed"])
        self.assertFalse(variants["ts-h1-demux"]["final_specialist_admission_passed"])
        self.assertTrue(variants["ts-h2-extension-lanes"]["hypothesis_gate_passed"])
        self.assertTrue(
            variants["ts-h2-extension-lanes"]["final_specialist_admission_passed"]
        )

    def test_summary_rejects_nondeterministic_artifacts(self) -> None:
        item = {
            "id": "wiki",
            "format": "wikimedia-revision-text-v1",
            "track": "english_wikimedia_wikitext",
            "source_bytes": 10_000,
            "baseline_bytes": 1_000,
            "baseline_compression_peak_rss_bytes": 100,
            "baseline_decompression_peak_rss_bytes": 100,
        }
        trials = [
            {
                "warmup": False,
                "passed": True,
                "item_id": "wiki",
                "variant": "ts-h1-demux",
                "candidate_bytes": 900,
                "candidate_sha256": str(repetition),
                "compression_wall_ns": 10,
                "decompression_wall_ns": 20,
                "compression_peak_rss_bytes": 200,
                "decompression_peak_rss_bytes": 200,
            }
            for repetition in (1, 2)
        ]
        row = MODULE.summarize(trials, [item])["item_rows"][0]
        self.assertFalse(row["deterministic_artifact"])
        self.assertFalse(row["passed"])


if __name__ == "__main__":
    unittest.main()
