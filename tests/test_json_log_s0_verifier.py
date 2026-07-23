"""Independent-verifier tests for the S0 screen, including tamper detection.

Synthetic in-test corpora only; no file under corpora/ is ever measured here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "benchmark-json-log-native-screen-s0.py"
VERIFIER_PATH = ROOT / "scripts" / "verify-json-log-native-screen-s0-run.py"
ITEM_IDS = (
    "clue-early-development",
    "clue-middle-development",
    "clue-late-development",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load_module("s0_verifier", VERIFIER_PATH)


def kernel_path() -> Path | None:
    for profile in ("release", "debug"):
        candidate = ROOT / "native" / "target" / profile / "clab-s0-kernel"
        if candidate.is_file():
            return candidate
    return None


def ensure_kernel() -> Path | None:
    existing = kernel_path()
    if existing is not None:
        return existing
    if shutil.which("cargo") is None:
        return None
    try:
        subprocess.run(
            ["cargo", "build", "--release", "--locked", "--bin", "clab-s0-kernel"],
            cwd=ROOT / "native",
            check=True,
            capture_output=True,
            timeout=1800,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return kernel_path()


def synthetic_item(index: int) -> bytes:
    lines = []
    for record in range(240):
        lines.append(
            json.dumps(
                {
                    "id": 1000 + index * 1000 + record,
                    "ts": f"2026-07-2{index}T10:{record % 60:02d}:{(record * 7) % 60:02d}Z",
                    "session": f"s{record % 13}",
                    "path": f"/api/v{index}/resource/{record % 19}",
                    "status": 200 + (record % 5),
                }
            )
        )
    lines.append("{ malformed record triggers fallback }")
    return ("\n".join(lines) + "\n").encode()


def make_corpus(directory: Path) -> tuple[Path, Path]:
    corpus = directory / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    items = []
    for index, item_id in enumerate(ITEM_IDS):
        data = synthetic_item(index)
        (corpus / f"{item_id}.jsonl").write_bytes(data)
        items.append(
            {
                "id": item_id,
                "source_bytes": len(data),
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "kanzi_single_item_axe1o_bytes": 10_000_000,
            }
        )
    items_config = directory / "items.json"
    items_config.write_text(json.dumps({"items": items}, indent=2))
    return corpus, items_config


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite_sha256sums(run_dir: Path, relative: str) -> None:
    sums = run_dir / "SHA256SUMS"
    lines = []
    for line in sums.read_text().splitlines():
        if line.endswith(f"  {relative}"):
            lines.append(f"{sha256_file(run_dir / relative)}  {relative}")
        else:
            lines.append(line)
    sums.write_text("\n".join(lines) + "\n")


class VerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = ensure_kernel()
        if cls.kernel is None:
            raise unittest.SkipTest("clab-s0-kernel is unavailable and cargo cannot build it")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="s0-verify-")
        self.tmp = Path(self._tmp.name)
        self.corpus, self.items_config = make_corpus(self.tmp)
        self.output = self.tmp / "run"
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER_PATH),
                "--output-dir",
                str(self.output),
                "--corpus-dir",
                str(self.corpus),
                "--items-config",
                str(self.items_config),
                "--kernel-binary",
                str(self.kernel),
                "--skip-build",
                "--segment-bytes",
                "4096",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build_verifier(self, redecode: str = "full") -> "VERIFIER.Verifier":
        return VERIFIER.Verifier(
            run_dir=self.output.resolve(),
            repo_root=ROOT,
            profile="base",
            items_config=self.items_config,
            kernel_binary=self.kernel,
            redecode=redecode,
        )

    def failed_checks(self, report: dict) -> set[str]:
        return {row["check"] for row in report["checks"] if not row["passed"]}

    def test_accepts_an_honest_run(self) -> None:
        report = self.build_verifier().run("advance")
        self.assertTrue(report["verified"], report["checks"])
        self.assertEqual(report["decision"], "advance")

    def test_verifier_cli_exits_zero_and_writes_verification_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--run-dir",
                str(self.output),
                "--items-config",
                str(self.items_config),
                "--kernel-binary",
                str(self.kernel),
                "--redecode",
                "full",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads((self.output / "verification.json").read_bytes())
        self.assertTrue(report["verified"])

    def test_expected_decision_mismatch_fails(self) -> None:
        report = self.build_verifier().run("kill")
        self.assertFalse(report["verified"])
        self.assertIn("expected_decision", self.failed_checks(report))

    def test_tamper_receipt_byte_is_detected(self) -> None:
        receipt = self.output / "receipts" / "full" / f"{ITEM_IDS[0]}.json"
        data = bytearray(receipt.read_bytes())
        data[-2] ^= 0x20
        receipt.write_bytes(bytes(data))
        report = self.build_verifier().run(None)
        self.assertFalse(report["verified"])
        self.assertIn("sha256sums", self.failed_checks(report))

    def test_tamper_tape_byte_is_detected(self) -> None:
        tape = self.output / "tapes" / "full" / f"{ITEM_IDS[0]}.tape"
        data = bytearray(tape.read_bytes())
        data[20] ^= 0x01
        tape.write_bytes(bytes(data))
        report = self.build_verifier().run(None)
        self.assertFalse(report["verified"])
        self.assertIn("sha256sums", self.failed_checks(report))

    def test_tamper_ledger_integer_is_detected(self) -> None:
        relative = f"receipts/full/{ITEM_IDS[0]}.json"
        receipt_path = self.output / relative
        receipt = json.loads(receipt_path.read_bytes())
        receipt["ledger"]["modeled_loss_q24"] += 1_000_000
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        rewrite_sha256sums(self.output, relative)
        report = self.build_verifier(redecode="none").run(None)
        self.assertFalse(report["verified"])
        self.assertIn("projections", self.failed_checks(report))

    def test_tamper_gate_value_in_result_is_detected(self) -> None:
        result_path = self.output / "result.json"
        result = json.loads(result_path.read_bytes())
        result["gates"]["decision"] = (
            "kill" if result["gates"]["decision"] != "kill" else "advance"
        )
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rewrite_sha256sums(self.output, "result.json")
        report = self.build_verifier(redecode="none").run(None)
        self.assertFalse(report["verified"])
        self.assertIn("gates", self.failed_checks(report))

    def test_tamper_attribution_value_in_result_is_detected(self) -> None:
        result_path = self.output / "result.json"
        result = json.loads(result_path.read_bytes())
        result["gates"]["attribution"]["m4_bytes"]["bytes"] += 5
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rewrite_sha256sums(self.output, "result.json")
        report = self.build_verifier(redecode="none").run(None)
        self.assertFalse(report["verified"])
        self.assertIn("gates", self.failed_checks(report))

    def test_redecode_full_reconstructs_the_source(self) -> None:
        # With re-decode enabled the full-arm tapes must reproduce the source SHA.
        report = self.build_verifier(redecode="full").run(None)
        self.assertTrue(report["verified"], report["checks"])
        self.assertTrue(
            next(row for row in report["checks"] if row["check"] == "redecode")["passed"]
        )

    def test_redecode_all_catches_a_tampered_non_full_arm(self) -> None:
        # A consistent tamper of a non-full arm (tape byte flipped, receipt hash
        # and SHA256SUMS regenerated) survives the hash checks but must be caught
        # by re-decoding every arm, not only the full arm.
        arm = "m1-m2"
        item_id = ITEM_IDS[1]
        tape_rel = f"tapes/{arm}/{item_id}.tape"
        receipt_rel = f"receipts/{arm}/{item_id}.json"
        tape_path = self.output / tape_rel
        data = bytearray(tape_path.read_bytes())
        data[len(data) // 2] ^= 0x01
        tape_path.write_bytes(bytes(data))
        receipt_path = self.output / receipt_rel
        receipt = json.loads(receipt_path.read_bytes())
        receipt["tape_sha256"] = sha256_file(tape_path)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        rewrite_sha256sums(self.output, tape_rel)
        rewrite_sha256sums(self.output, receipt_rel)

        # 'full' re-decode never touches this arm, so it slips through.
        full_report = self.build_verifier(redecode="full").run(None)
        self.assertNotIn("redecode", self.failed_checks(full_report))
        # 'all' re-decodes every arm and catches the tampered non-full tape.
        all_report = self.build_verifier(redecode="all").run(None)
        self.assertFalse(all_report["verified"])
        self.assertIn("redecode", self.failed_checks(all_report))

    def test_roster_catches_a_dropped_arm_row(self) -> None:
        result_path = self.output / "result.json"
        result = json.loads(result_path.read_bytes())
        result["arms"] = result["arms"][:-1]
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rewrite_sha256sums(self.output, "result.json")
        report = self.build_verifier(redecode="none").run(None)
        self.assertFalse(report["verified"])
        self.assertIn("roster", self.failed_checks(report))

    def test_roster_catches_a_dropped_item_row(self) -> None:
        result_path = self.output / "result.json"
        result = json.loads(result_path.read_bytes())
        result["arms"][0]["per_item"] = result["arms"][0]["per_item"][:-1]
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rewrite_sha256sums(self.output, "result.json")
        report = self.build_verifier(redecode="none").run(None)
        self.assertFalse(report["verified"])
        self.assertIn("roster", self.failed_checks(report))


if __name__ == "__main__":
    unittest.main()
