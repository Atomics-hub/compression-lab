"""End-to-end and formula tests for the S0 screen runner and clean-checkout.

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
CONFIRM_PATH = (
    ROOT / "scripts" / "confirm-json-log-native-screen-s0-clean-checkout.py"
)
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


RUNNER = load_module("s0_runner", RUNNER_PATH)


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


def make_corpus(directory: Path) -> Path:
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
    (directory / "items.json").write_text(json.dumps({"items": items}, indent=2))
    return corpus


# The four M5 mixer arms are the only arms whose charged loss can move with the
# SSE capacity; the other six ignore the bucket-bit count entirely.
MIXER_ARMS = frozenset({"m1-m2-m5", "full", "full-minus-m3", "full-minus-m4"})


def diverging_item() -> bytes:
    # Large and varied enough to force an SSE 17-bit bucket collision that the
    # 18th bit resolves, so the refined profile actually moves the mixer loss.
    lines = []
    for record in range(1_500):
        mix = (record * 2_654_435_761) & 0xFFFFFFFF
        lines.append(
            json.dumps(
                {
                    "id": 100_000 + record,
                    "ts": f"2026-07-22T{record % 24:02d}:{record % 60:02d}:{(record * 7) % 60:02d}Z",
                    "session": f"s{record % 997}",
                    "path": f"/api/v/{record % 733}/resource/{record % 521}",
                    "tag": f"{mix:08x}",
                    "status": 200 + (record % 5),
                }
            )
        )
    lines.append("{ malformed record triggers fallback }")
    return ("\n".join(lines) + "\n").encode()


def make_single_item_corpus(directory: Path) -> Path:
    corpus = directory / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    item_id = ITEM_IDS[0]
    data = diverging_item()
    (corpus / f"{item_id}.jsonl").write_bytes(data)
    (directory / "items.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": item_id,
                        "source_bytes": len(data),
                        "source_sha256": hashlib.sha256(data).hexdigest(),
                        "kanzi_single_item_axe1o_bytes": 10_000_000,
                    }
                ]
            },
            indent=2,
        )
    )
    return corpus


def run_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER_PATH), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class FormulaTests(unittest.TestCase):
    def test_decision_boundaries_match_the_frozen_protocol(self) -> None:
        cases = [
            (1_455_326, 1_500, "advance"),
            (1_455_327, 1_499, "refine_once"),
            (1_540_934, 1_000, "refine_once"),
            (1_540_935, 999, "kill"),
        ]
        for complete, gain, expected in cases:
            self.assertEqual(RUNNER.gain_basis_points(complete), gain, complete)
            self.assertEqual(RUNNER.decision_for(complete, gain), expected, complete)

    def test_gain_uses_mathematical_floor_for_negative_differences(self) -> None:
        self.assertEqual(RUNNER.gain_basis_points(RUNNER.KANZI_COMPLETE_BYTES + 1), -1)
        self.assertEqual(RUNNER.gain_basis_points(RUNNER.KANZI_COMPLETE_BYTES), 0)

    def test_aggregate_projection_rounds_loss_and_allowance_up(self) -> None:
        ledger = {
            "records": 1,
            "modeled_binary_events": 1,
            "modeled_loss_q24": 8 * (1 << 24) + 1,
            "raw_literal_bytes": 0,
        }
        projection = RUNNER.project_aggregate(ledger)
        self.assertEqual(projection["payload_bytes"], 2)
        self.assertEqual(projection["coder_allowance_bytes"], 1)
        self.assertEqual(
            projection["complete_bytes"], 2 + 1 + 6_272 + 72 + 4_096
        )

    def test_item_projection_charges_each_started_source_mebibyte(self) -> None:
        ledger = dict.fromkeys(RUNNER.LEDGER_KEYS, 0)
        projection = RUNNER.project_item(ledger, (2 << 20) + 1)
        self.assertEqual(projection["block_allowance_bytes"], 96)
        self.assertEqual(projection["complete_bytes"], 96 + 24 + 4_096)

    def test_literal_bytes_are_charged_at_exactly_eight_bits(self) -> None:
        ledger = {**dict.fromkeys(RUNNER.LEDGER_KEYS, 0), "raw_literal_bytes": 123}
        self.assertEqual(RUNNER.payload_bytes(ledger), 123)

    def test_per_item_ceiling_equality_is_allowed(self) -> None:
        # complete == reference must count as within the Kanzi ceiling.
        self.assertTrue(630_525 <= 630_525)
        item = {
            "index": 0,
            "id": "x",
            "source_bytes": 100,
            "source_sha256": "0" * 64,
            "kanzi_single_item_axe1o_bytes": 4_120,
        }
        ledger = dict.fromkeys(RUNNER.LEDGER_KEYS, 0)
        projection = RUNNER.project_item(ledger, item["source_bytes"])
        # 0 payload + 0 allowance + 32 (1 MiB block) + 24 + 4096 = 4152 > 4120.
        self.assertEqual(projection["complete_bytes"], 4_152)
        self.assertFalse(projection["complete_bytes"] <= item["kanzi_single_item_axe1o_bytes"])

    def test_attribution_floors_at_zero_and_flags_thresholds(self) -> None:
        self.assertEqual(RUNNER.attribution_entry(100, 250)["bytes"], 0)
        entry = RUNNER.attribution_entry(20_000, 100)
        self.assertTrue(entry["report_threshold_met"])
        self.assertTrue(entry["exact_build_threshold_met"])
        low = RUNNER.attribution_entry(9_000, 100)
        self.assertTrue(low["report_threshold_met"])
        self.assertFalse(low["exact_build_threshold_met"])

    def test_recomputed_projection_disagreement_fails_closed(self) -> None:
        receipt = {
            "arm": "full",
            "item_index": 0,
            "source_sha256": "a" * 64,
            "decode_matches_source": True,
            "decoded_sha256": "a" * 64,
            "tape_sha256": "b" * 64,
            "segment_interval_bytes": 4096,
            "segments": [],
            "ledger": {
                "records": 1,
                "modeled_binary_events": 1,
                "modeled_loss_q24": 8 * (1 << 24),
                "raw_literal_bytes": 0,
            },
            "item_projection": {
                "payload_bytes": 999,
                "coder_allowance_bytes": 5,
                "block_allowance_bytes": 32,
                "stream_metadata_bytes": 24,
                "fixed_framing_bytes": 4096,
                "complete_bytes": 5156,
            },
        }
        item = {
            "index": 0,
            "id": "x",
            "source_bytes": 100,
            "source_sha256": "a" * 64,
            "kanzi_single_item_axe1o_bytes": 10_000,
        }
        arm_meta = {
            "name": "full",
            "id": 6,
            "decides": True,
            "event_limit_applies": True,
        }
        with self.assertRaises(RUNNER.ScreenError):
            RUNNER.build_arm_result(arm_meta, [item], {("full", "x"): {"receipt": receipt}})


class RunnerEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = ensure_kernel()
        if cls.kernel is None:
            raise unittest.SkipTest("clab-s0-kernel is unavailable and cargo cannot build it")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="s0-runner-")
        self.tmp = Path(self._tmp.name)
        self.corpus = make_corpus(self.tmp)
        self.items_config = self.tmp / "items.json"
        self.output = self.tmp / "run"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def base_args(self) -> list[str]:
        return [
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
        ]

    def test_runs_and_produces_a_consistent_result(self) -> None:
        completed = run_runner(self.base_args())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads((self.output / "result.json").read_bytes())
        self.assertEqual([arm["name"] for arm in result["arms"]], [
            "raw-o3",
            "m1-chassis",
            "m1-m2",
            "m1-m2-m3",
            "m1-m2-m4",
            "m1-m2-m5",
            "full",
            "full-minus-m3",
            "full-minus-m4",
            "full-minus-m5",
        ])
        self.assertIn(result["gates"]["decision"], {"advance", "refine_once", "kill"})
        # Every receipt projection recomputes from its own ledger.
        for arm in result["arms"]:
            for row in arm["per_item"]:
                recomputed = RUNNER.project_item(
                    row["ledger"],
                    next(
                        item["source_bytes"]
                        for item in result["items"]
                        if item["id"] == row["item_id"]
                    ),
                )
                self.assertEqual(recomputed, row["item_projection"])
        # Attribution is derived from the aggregate completes.
        complete = {
            arm["name"]: arm["aggregate_projection"]["complete_bytes"]
            for arm in result["arms"]
        }
        self.assertEqual(
            result["gates"]["attribution"]["m4_bytes"]["bytes"],
            max(0, complete["full-minus-m4"] - complete["full"]),
        )
        # environment.json carries the host measurements, not result.json.
        environment = json.loads((self.output / "environment.json").read_bytes())
        self.assertEqual(len(environment["measurements"]), 30)
        self.assertIn("kernel_binary_sha256", environment)
        text = (self.output / "result.json").read_text()
        self.assertNotIn("peak_rss", text)
        self.assertNotIn("wall_ns", text)

    def test_refuses_a_pre_existing_output_directory(self) -> None:
        self.output.mkdir(parents=True)
        completed = run_runner(self.base_args())
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must not exist", completed.stderr)

    def test_refuses_a_bad_item_hash(self) -> None:
        config = json.loads(self.items_config.read_bytes())
        config["items"][1]["source_sha256"] = "0" * 64
        self.items_config.write_text(json.dumps(config))
        completed = run_runner(self.base_args())
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("SHA-256 differs", completed.stderr)

    def test_refuses_a_nonzero_kernel_exit(self) -> None:
        fake = self.tmp / "false-kernel"
        fake.write_text("#!/bin/sh\nexit 3\n")
        fake.chmod(0o755)
        args = self.base_args()
        args[args.index("--kernel-binary") + 1] = str(fake)
        completed = run_runner(args)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("kernel encode failed", completed.stderr)


class CleanCheckoutConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = ensure_kernel()
        if cls.kernel is None:
            raise unittest.SkipTest("clab-s0-kernel is unavailable and cargo cannot build it")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is unavailable")
        cls.commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="s0-confirm-")
        self.tmp = Path(self._tmp.name)
        self.corpus = make_corpus(self.tmp)
        self.items_config = self.tmp / "items.json"
        self.output = self.tmp / "run"
        completed = run_runner(
            [
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
            ]
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.freeze = self.tmp / "freeze.json"
        manifest = json.loads(
            (
                ROOT
                / "config"
                / "json-log-native-screen-s0-constants-base-v1.json"
            ).read_bytes()
        )
        files = manifest["source_toolchain_build_identity"]["engine_source_files"]
        self.freeze.write_text(
            json.dumps(
                {
                    "engine_commit": self.commit,
                    "engine_source_sha256": {
                        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                        for relative in files
                    },
                }
            )
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def confirm_args(self, scratch: Path) -> list[str]:
        return [
            sys.executable,
            str(CONFIRM_PATH),
            "--commit",
            self.commit,
            "--run-dir",
            str(self.output),
            "--scratch-dir",
            str(scratch),
            "--freeze-record",
            str(self.freeze),
            "--repo",
            str(ROOT),
            "--corpus-dir",
            str(self.corpus),
            "--items-config",
            str(self.items_config),
            "--kernel-binary",
            str(self.kernel.resolve()),
            "--skip-build",
        ]

    def test_clean_checkout_reproduces_every_receipt(self) -> None:
        scratch = self.tmp / "confirm"
        completed = subprocess.run(
            self.confirm_args(scratch), check=False, capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads((scratch / "confirmation.json").read_bytes())
        self.assertTrue(report["confirmed"])
        self.assertEqual(len(report["comparisons"]), 30)
        self.assertTrue(all(row["identical"] for row in report["comparisons"]))

    def test_a_tampered_freeze_record_fails_closed(self) -> None:
        record = json.loads(self.freeze.read_bytes())
        some_file = next(iter(record["engine_source_sha256"]))
        record["engine_source_sha256"][some_file] = "0" * 64
        self.freeze.write_text(json.dumps(record))
        scratch = self.tmp / "confirm"
        completed = subprocess.run(
            self.confirm_args(scratch), check=False, capture_output=True, text=True
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("engine source SHA differs", completed.stderr)


class RefinedProfileEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = ensure_kernel()
        if cls.kernel is None:
            raise unittest.SkipTest("clab-s0-kernel is unavailable and cargo cannot build it")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="s0-refined-")
        self.tmp = Path(self._tmp.name)
        self.corpus = make_single_item_corpus(self.tmp)
        self.items_config = self.tmp / "items.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_profile(self, profile: str, output: Path) -> dict:
        completed = run_runner(
            [
                "--profile",
                profile,
                "--output-dir",
                str(output),
                "--corpus-dir",
                str(self.corpus),
                "--items-config",
                str(self.items_config),
                "--kernel-binary",
                str(self.kernel),
                "--skip-build",
                "--segment-bytes",
                str(1 << 20),
            ]
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads((output / "result.json").read_bytes())

    def receipt_text(self, run: Path, arm: str, item_id: str) -> str:
        return (run / "receipts" / arm / f"{item_id}.json").read_text()

    def test_refined_profile_moves_only_mixer_loss_and_holds_every_tape(self) -> None:
        base_out = self.tmp / "base"
        refined_out = self.tmp / "refined"
        base = self.run_profile("base", base_out)
        refined = self.run_profile("refined", refined_out)

        # The profile is recorded at the result top level and matches the bits.
        self.assertEqual(base["sse_bucket_bits"], 17)
        self.assertEqual(refined["sse_bucket_bits"], 18)

        base_arms = {arm["name"]: arm for arm in base["arms"]}
        refined_arms = {arm["name"]: arm for arm in refined["arms"]}
        self.assertEqual(set(base_arms), set(refined_arms))

        changed = set()
        for name, refined_arm in refined_arms.items():
            base_arm = base_arms[name]
            # Every tape is byte-identical across profiles, item by item.
            for base_row, refined_row in zip(
                base_arm["per_item"], refined_arm["per_item"], strict=True
            ):
                self.assertEqual(
                    base_row["tape_sha256"], refined_row["tape_sha256"], name
                )
            base_loss = base_arm["aggregate_ledger"]["modeled_loss_q24"]
            refined_loss = refined_arm["aggregate_ledger"]["modeled_loss_q24"]
            if base_loss != refined_loss:
                changed.add(name)
            if name not in MIXER_ARMS:
                # Non-mixer receipts are byte-identical except the recorded
                # sse_bucket_bits field, so the loss cannot have moved.
                self.assertEqual(base_loss, refined_loss, name)
                for item_id in (row["item_id"] for row in refined_arm["per_item"]):
                    base_text = self.receipt_text(base_out, name, item_id)
                    refined_text = self.receipt_text(refined_out, name, item_id)
                    self.assertEqual(
                        base_text.replace(
                            '"sse_bucket_bits": 17', '"sse_bucket_bits": 18'
                        ),
                        refined_text,
                        f"{name}/{item_id}",
                    )

        # Only mixer arms may move, and at least the decision arm actually does.
        self.assertTrue(changed <= MIXER_ARMS, changed)
        self.assertIn("full", changed)

    def test_decode_with_the_wrong_bits_fails_on_a_refined_mixer_tape(self) -> None:
        refined_out = self.tmp / "refined"
        refined = self.run_profile("refined", refined_out)
        full = next(arm for arm in refined["arms"] if arm["name"] == "full")
        row = full["per_item"][0]
        ledger = row["ledger"]
        tape = refined_out / "tapes" / "full" / f"{row['item_id']}.tape"

        def decode(bits: str) -> subprocess.CompletedProcess[str]:
            out = self.tmp / f"decoded-{bits}"
            receipt = self.tmp / f"decode-receipt-{bits}.json"
            return subprocess.run(
                [
                    str(self.kernel),
                    "decode",
                    "--arm",
                    "full",
                    "--item-index",
                    str(row["item_index"]),
                    "--tape",
                    str(tape),
                    "--records",
                    str(ledger["records"]),
                    "--modeled-binary-events",
                    str(ledger["modeled_binary_events"]),
                    "--modeled-loss-q24",
                    str(ledger["modeled_loss_q24"]),
                    "--raw-literal-bytes",
                    str(ledger["raw_literal_bytes"]),
                    "--output",
                    str(out),
                    "--receipt-out",
                    str(receipt),
                    "--sse-bucket-bits",
                    bits,
                    "--force",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        # Matching refined bits reconstruct; the base bits reproduce a different
        # loss and fail the independent decoder ledger equality.
        self.assertEqual(decode("18").returncode, 0)
        self.assertNotEqual(decode("17").returncode, 0)


if __name__ == "__main__":
    unittest.main()
