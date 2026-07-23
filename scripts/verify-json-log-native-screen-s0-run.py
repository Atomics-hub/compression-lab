#!/usr/bin/env python3
"""Independently verify a frozen S0 JSON/log native screen run.

This verifier shares no formula code with the runner. It recomputes every Q24
projection, gain, gate, quarantine, and attribution from the raw receipt ledger
integers, re-checks the SHA256SUMS manifest, and optionally re-runs the kernel
decoder on the full arm. It emits verification.json with a pass/fail entry per
check and exits nonzero on any failure. The host-specific environment.json is
never consulted for byte comparisons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]

# Independent copy of the frozen projection and gate constants.
_Q24 = 1 << 24
_MIB = 1 << 20
_AGG_BLOCK = 6_272
_AGG_META = 72
_FRAMING = 4_096
_ITEM_META = 24
_BLOCK_PER_MIB = 32
_EVENT_PER_RECORD = 96
_KANZI = 1_712_149
_ADVANCE_MAX = 1_455_326
_ADVANCE_MIN_GAIN = 1_500
_REFINE_MAX = 1_540_934
_MINUS_M4_MIN_GAIN = 700
_REPORT_BYTES = 8_561
_EXACT_BYTES = 17_122
_LEDGER_KEYS = (
    "records",
    "modeled_binary_events",
    "modeled_loss_q24",
    "raw_literal_bytes",
)


class VerificationError(Exception):
    """A single failed verification check."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise VerificationError(f"expected ordinary file: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    _ordinary(path)
    return json.loads(path.read_bytes())


def _ceil(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _payload(ledger: dict[str, int]) -> int:
    charged = ledger["modeled_loss_q24"] + ledger["raw_literal_bytes"] * 8 * _Q24
    return _ceil(charged, 8 * _Q24)


def _allowance(payload: int) -> int:
    return _ceil(payload * 5, 1_000)


def _aggregate_projection(ledger: dict[str, int]) -> dict[str, int]:
    payload = _payload(ledger)
    allowance = _allowance(payload)
    return {
        "payload_bytes": payload,
        "coder_allowance_bytes": allowance,
        "block_allowance_bytes": _AGG_BLOCK,
        "stream_metadata_bytes": _AGG_META,
        "fixed_framing_bytes": _FRAMING,
        "complete_bytes": payload + allowance + _AGG_BLOCK + _AGG_META + _FRAMING,
    }


def _item_projection(ledger: dict[str, int], source_bytes: int) -> dict[str, int]:
    payload = _payload(ledger)
    allowance = _allowance(payload)
    block = _ceil(source_bytes, _MIB) * _BLOCK_PER_MIB
    return {
        "payload_bytes": payload,
        "coder_allowance_bytes": allowance,
        "block_allowance_bytes": block,
        "stream_metadata_bytes": _ITEM_META,
        "fixed_framing_bytes": _FRAMING,
        "complete_bytes": payload + allowance + block + _ITEM_META + _FRAMING,
    }


def _gain(complete: int) -> int:
    return (_KANZI - complete) * 10_000 // _KANZI


def _event_ok(ledger: dict[str, int]) -> bool:
    return ledger["modeled_binary_events"] <= _EVENT_PER_RECORD * ledger["records"]


def _decision(complete: int, gain: int) -> str:
    if complete <= _ADVANCE_MAX and gain >= _ADVANCE_MIN_GAIN:
        return "advance"
    if complete <= _REFINE_MAX:
        return "refine_once"
    return "kill"


def _attribution(minuend: int, subtrahend: int) -> dict[str, Any]:
    value = max(0, minuend - subtrahend)
    return {
        "bytes": value,
        "report_threshold_met": value >= _REPORT_BYTES,
        "exact_build_threshold_met": value >= _EXACT_BYTES,
    }


def _load_items(config: dict[str, Any], items_config: Path | None) -> list[dict[str, Any]]:
    raw = (
        _read_json(items_config)["items"]
        if items_config is not None
        else config["references"]["items"]
    )
    items = []
    for index, entry in enumerate(raw):
        items.append(
            {
                "index": index,
                "id": entry["id"],
                "source_bytes": int(entry["source_bytes"]),
                "source_sha256": entry["source_sha256"],
                "kanzi_single_item_axe1o_bytes": int(
                    entry["kanzi_single_item_axe1o_bytes"]
                ),
            }
        )
    return items


def _ledger(receipt: dict[str, Any]) -> dict[str, int]:
    return {key: int(receipt["ledger"][key]) for key in _LEDGER_KEYS}


class Verifier:
    def __init__(
        self,
        run_dir: Path,
        repo_root: Path,
        profile: str,
        items_config: Path | None,
        kernel_binary: Path | None,
        redecode: str,
    ) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root
        self.profile = profile
        self.redecode = redecode
        self.result_path = run_dir / "result.json"
        self.result = _read_json(self.result_path)
        self.config_path = (
            repo_root / "config" / "json-log-native-screen-s0-v1.json"
        )
        self.protocol_path = (
            repo_root / "docs" / "benchmarks"
            / "2026-07-21-json-log-native-screen-s0-protocol.md"
        )
        self.manifest_path = (
            repo_root
            / "config"
            / f"json-log-native-screen-s0-constants-{profile}-v1.json"
        )
        self.config = _read_json(self.config_path)
        self.items = _load_items(self.config, items_config)
        self.item_by_id = {item["id"]: item for item in self.items}
        # The frozen roster and capacity profile are read from the bound manifest
        # (check_bindings independently proves the manifest SHA and protocol
        # binding, so these expectations are grounded, not assumed).
        self.manifest = _read_json(self.manifest_path)
        self.frozen_arm_names = [
            arm["name"] for arm in self.manifest["arms"]["frozen_order"]
        ]
        self.item_ids = [item["id"] for item in self.items]
        mixer = self.manifest["mixer_and_sse"]
        self.expected_sse_bucket_bits = int(
            mixer["sse_base_bucket_bits"]
            if profile == "base"
            else mixer["sse_refined_bucket_bits"]
        )
        if kernel_binary is not None:
            self.kernel = kernel_binary.resolve()
        else:
            self.kernel = (
                repo_root / "native" / "target" / "release" / "clab-s0-kernel"
            )
        self._receipts: dict[tuple[str, str], dict[str, Any]] = {}

    def receipt(self, arm: str, item_id: str) -> dict[str, Any]:
        key = (arm, item_id)
        if key not in self._receipts:
            self._receipts[key] = _read_json(
                self.run_dir / "receipts" / arm / f"{item_id}.json"
            )
        return self._receipts[key]

    # --- individual checks ------------------------------------------------
    def check_roster(self) -> None:
        # The run must present exactly the ten frozen arms in order, each over
        # exactly the frozen items in order; a dropped or reordered arm or item
        # row cannot slip past the projection/gate checks unnoticed.
        actual_arms = [arm["name"] for arm in self.result["arms"]]
        if actual_arms != self.frozen_arm_names:
            raise VerificationError(
                f"result arms differ from the frozen roster: "
                f"{actual_arms} != {self.frozen_arm_names}"
            )
        for arm in self.result["arms"]:
            actual_items = [row["item_id"] for row in arm["per_item"]]
            if actual_items != self.item_ids:
                raise VerificationError(
                    f"arm {arm['name']} items differ from the config roster: "
                    f"{actual_items} != {self.item_ids}"
                )

    def check_bindings(self) -> None:
        bindings = self.result["bindings"]
        if bindings["config_sha256"] != _sha256_file(self.config_path):
            raise VerificationError("config SHA-256 differs from result claim")
        if bindings["protocol_sha256"] != _sha256_file(self.protocol_path):
            raise VerificationError("protocol SHA-256 differs from result claim")
        if bindings["constants_manifest_sha256"] != _sha256_file(self.manifest_path):
            raise VerificationError("constants manifest SHA-256 differs from result claim")
        if bindings["constants_manifest_profile"] != self.profile:
            raise VerificationError("result profile differs from the verified profile")
        freeze = self.config["screen"]["freeze_requirements_before_measurement"]
        if bindings["protocol_sha256"] != freeze["protocol_sha256"]:
            raise VerificationError("protocol SHA-256 differs from the frozen config")
        manifest = _read_json(self.manifest_path)
        if manifest["engine_source"]["protocol_sha256"] != freeze["protocol_sha256"]:
            raise VerificationError("constants manifest protocol binding differs")

    def check_sha256sums(self) -> None:
        sums_path = self.run_dir / "SHA256SUMS"
        _ordinary(sums_path)
        entries: dict[str, str] = {}
        for line in sums_path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            digest, _, relative = line.partition("  ")
            if not relative:
                raise VerificationError(f"malformed SHA256SUMS line: {line}")
            entries[relative] = digest
        expected = {"result.json"}
        for arm in self.result["arms"]:
            for row in arm["per_item"]:
                expected.add(f"tapes/{arm['name']}/{row['item_id']}.tape")
                expected.add(f"receipts/{arm['name']}/{row['item_id']}.json")
        if set(entries) != expected:
            raise VerificationError("SHA256SUMS roster differs from the run contents")
        for relative, digest in entries.items():
            path = self.run_dir / relative
            _ordinary(path)
            if _sha256_file(path) != digest:
                raise VerificationError(f"SHA256SUMS entry differs: {relative}")

    def check_receipts(self) -> None:
        for arm in self.result["arms"]:
            for row in arm["per_item"]:
                item = self.item_by_id[row["item_id"]]
                receipt = self.receipt(arm["name"], row["item_id"])
                if receipt["schema"] != "clab-s0-kernel-encode-receipt-v1":
                    raise VerificationError("receipt schema differs")
                if int(receipt["sse_bucket_bits"]) != self.expected_sse_bucket_bits:
                    raise VerificationError(
                        f"receipt sse_bucket_bits differs from the {self.profile} profile "
                        f"for {arm['name']}/{row['item_id']}: "
                        f"{receipt['sse_bucket_bits']} != {self.expected_sse_bucket_bits}"
                    )
                if (
                    receipt["arm"] != arm["name"]
                    or int(receipt["arm_id"]) != arm["id"]
                    or int(receipt["item_index"]) != item["index"]
                ):
                    raise VerificationError(
                        f"receipt identity differs for {arm['name']}/{row['item_id']}"
                    )
                if int(receipt["source_bytes"]) != item["source_bytes"]:
                    raise VerificationError("receipt source byte count differs")
                if receipt["source_sha256"] != item["source_sha256"]:
                    raise VerificationError("receipt source SHA differs from item")
                if not receipt["decode_matches_source"]:
                    raise VerificationError("receipt decode did not match source")
                if receipt["decoded_sha256"] != item["source_sha256"]:
                    raise VerificationError("receipt decoded SHA differs from item source")
                tape = self.run_dir / "tapes" / arm["name"] / f"{row['item_id']}.tape"
                _ordinary(tape)
                if _sha256_file(tape) != receipt["tape_sha256"]:
                    raise VerificationError("tape file SHA differs from receipt")

    def check_redecode(self) -> None:
        if self.redecode == "none":
            return
        arms = (
            [row for row in self.result["arms"] if row["name"] == "full"]
            if self.redecode == "full"
            else self.result["arms"]
        )
        _ordinary(self.kernel)
        for arm in arms:
            for row in arm["per_item"]:
                item = self.item_by_id[row["item_id"]]
                receipt = self.receipt(arm["name"], row["item_id"])
                ledger = _ledger(receipt)
                tape = (
                    self.run_dir / "tapes" / arm["name"] / f"{row['item_id']}.tape"
                )
                with tempfile.TemporaryDirectory(prefix="s0-verify-") as raw:
                    out = Path(raw) / "decoded"
                    receipt_out = Path(raw) / "decode-receipt.json"
                    completed = subprocess.run(
                        [
                            str(self.kernel),
                            "decode",
                            "--arm",
                            arm["name"],
                            "--item-index",
                            str(item["index"]),
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
                            str(receipt_out),
                            "--sse-bucket-bits",
                            str(self.expected_sse_bucket_bits),
                        ],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                    )
                    if completed.returncode != 0:
                        raise VerificationError(
                            f"kernel decode failed for {arm['name']}/{row['item_id']}: "
                            f"{completed.stderr.strip()}"
                        )
                    _ordinary(out)
                    if _sha256_file(out) != item["source_sha256"]:
                        raise VerificationError(
                            f"re-decoded output SHA differs for {arm['name']}/{row['item_id']}"
                        )

    def _rebuild_arm(self, arm: dict[str, Any]) -> dict[str, Any]:
        aggregate = dict.fromkeys(_LEDGER_KEYS, 0)
        per_item = []
        for row in arm["per_item"]:
            item = self.item_by_id[row["item_id"]]
            receipt = self.receipt(arm["name"], row["item_id"])
            ledger = _ledger(receipt)
            projection = _item_projection(ledger, item["source_bytes"])
            receipt_projection = {
                key: int(value) for key, value in receipt["item_projection"].items()
            }
            if projection != receipt_projection:
                raise VerificationError(
                    f"item projection differs from receipt for {arm['name']}/{row['item_id']}"
                )
            for key in _LEDGER_KEYS:
                aggregate[key] += ledger[key]
            per_item.append(
                {
                    "item_index": item["index"],
                    "item_id": item["id"],
                    "ledger": ledger,
                    "item_projection": projection,
                    "source_sha256": item["source_sha256"],
                    "tape_sha256": receipt["tape_sha256"],
                    "decoded_sha256": receipt["decoded_sha256"],
                    "segment_interval_bytes": receipt["segment_interval_bytes"],
                    "segments": receipt["segments"],
                }
            )
        aggregate_projection = _aggregate_projection(aggregate)
        return {
            "name": arm["name"],
            "id": arm["id"],
            "decides": arm["decides"],
            "event_limit_applies": arm["event_limit_applies"],
            "per_item": per_item,
            "aggregate_ledger": aggregate,
            "aggregate_projection": aggregate_projection,
            "aggregate_gain_basis_points": _gain(
                aggregate_projection["complete_bytes"]
            ),
        }

    def check_projections(self) -> None:
        rebuilt = [self._rebuild_arm(arm) for arm in self.result["arms"]]
        if rebuilt != self.result["arms"]:
            raise VerificationError("recomputed arms differ from result.json")

    def check_gates(self) -> None:
        arms_by_name = {arm["name"]: self._rebuild_arm(arm) for arm in self.result["arms"]}
        full = arms_by_name["full"]
        full_complete = full["aggregate_projection"]["complete_bytes"]
        full_gain = full["aggregate_gain_basis_points"]

        event_per_item = [_event_ok(row["ledger"]) for row in full["per_item"]]
        event_aggregate = _event_ok(full["aggregate_ledger"])
        event_passes = all(event_per_item) and event_aggregate

        per_item_rows = []
        for row in full["per_item"]:
            item = self.item_by_id[row["item_id"]]
            complete = row["item_projection"]["complete_bytes"]
            reference = item["kanzi_single_item_axe1o_bytes"]
            per_item_rows.append(
                {
                    "item_id": item["id"],
                    "complete_bytes": complete,
                    "kanzi_reference_bytes": reference,
                    "within_reference": complete <= reference,
                }
            )
        per_item_passes = all(row["within_reference"] for row in per_item_rows)

        minus_m4_gain = arms_by_name["full-minus-m4"]["aggregate_gain_basis_points"]
        quarantine = {
            "gain_basis_points": minus_m4_gain,
            "minimum_gain_basis_points": _MINUS_M4_MIN_GAIN,
            "passes": minus_m4_gain >= _MINUS_M4_MIN_GAIN,
            "vocabulary_carried": minus_m4_gain < _MINUS_M4_MIN_GAIN,
        }

        def complete(name: str) -> int:
            return arms_by_name[name]["aggregate_projection"]["complete_bytes"]

        attribution = {
            "m1_bytes": _attribution(complete("raw-o3"), complete("m1-chassis")),
            "m2_bytes": _attribution(complete("m1-chassis"), complete("m1-m2")),
            "m3_bytes": _attribution(complete("full-minus-m3"), full_complete),
            "m4_bytes": _attribution(complete("full-minus-m4"), full_complete),
            "m5_bytes": _attribution(complete("full-minus-m5"), full_complete),
        }

        decision = _decision(full_complete, full_gain)
        if not event_passes or not per_item_passes:
            decision = "kill"

        gates = {
            "decision": decision,
            "full_arm_complete_bytes": full_complete,
            "full_arm_gain_basis_points": full_gain,
            "advance_minimum_gain_basis_points": _ADVANCE_MIN_GAIN,
            "advance_minimum_gain_satisfied": full_gain >= _ADVANCE_MIN_GAIN,
            "event_gate": {
                "passes": event_passes,
                "per_item": event_per_item,
                "aggregate": event_aggregate,
            },
            "per_item_rule": {
                "passes": per_item_passes,
                "items": per_item_rows,
            },
            "full_minus_m4_quarantine": quarantine,
            "attribution": attribution,
        }
        if gates != self.result["gates"]:
            raise VerificationError("recomputed gates differ from result.json")

    def check_segments(self) -> None:
        for arm in self.result["arms"]:
            for row in arm["per_item"]:
                item = self.item_by_id[row["item_id"]]
                receipt = self.receipt(arm["name"], row["item_id"])
                interval = int(receipt["segment_interval_bytes"])
                final = _ledger(receipt)
                previous_records = 0
                previous_bytes = 0
                for index, snapshot in enumerate(receipt["segments"]):
                    records = int(snapshot["records"])
                    source_bytes = int(snapshot["source_bytes"])
                    if records <= previous_records or source_bytes <= previous_bytes:
                        raise VerificationError("segment snapshots not monotonic")
                    if source_bytes < (index + 1) * interval:
                        raise VerificationError("segment snapshot precedes its interval")
                    if source_bytes > item["source_bytes"]:
                        raise VerificationError("segment snapshot exceeds the source")
                    previous_records = records
                    previous_bytes = source_bytes
                if receipt["segments"]:
                    last = receipt["segments"][-1]["ledger"]
                    for key in _LEDGER_KEYS:
                        if int(last[key]) > final[key]:
                            raise VerificationError(
                                "final segment snapshot exceeds the final ledger"
                            )

    def check_event_limit(self) -> None:
        full = self._rebuild_arm(
            next(arm for arm in self.result["arms"] if arm["name"] == "full")
        )
        for row in full["per_item"]:
            if not _event_ok(row["ledger"]):
                raise VerificationError(
                    f"full-arm item over the event limit: {row['item_id']}"
                )
        if not _event_ok(full["aggregate_ledger"]):
            raise VerificationError("full-arm aggregate over the event limit")

    def run(self, expect_decision: str | None) -> dict[str, Any]:
        checks: list[tuple[str, Callable[[], None]]] = [
            ("roster", self.check_roster),
            ("bindings", self.check_bindings),
            ("sha256sums", self.check_sha256sums),
            ("receipts", self.check_receipts),
            ("redecode", self.check_redecode),
            ("projections", self.check_projections),
            ("gates", self.check_gates),
            ("segments", self.check_segments),
            ("event_limit", self.check_event_limit),
        ]
        rows = []
        passed = True
        for name, function in checks:
            try:
                function()
                rows.append({"check": name, "passed": True, "detail": ""})
            except (VerificationError, OSError, KeyError, ValueError) as error:
                passed = False
                rows.append({"check": name, "passed": False, "detail": str(error)})
        decision = self.result.get("gates", {}).get("decision")
        if expect_decision is not None:
            match = decision == expect_decision
            rows.append(
                {
                    "check": "expected_decision",
                    "passed": match,
                    "detail": ""
                    if match
                    else f"decision {decision} != expected {expect_decision}",
                }
            )
            passed = passed and match
        return {
            "verified": passed,
            "profile": self.profile,
            "decision": decision,
            "checks": rows,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--profile", choices=("base", "refined"), default="base")
    parser.add_argument("--items-config", type=Path, default=None)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--kernel-binary", type=Path, default=None)
    parser.add_argument("--redecode", choices=("none", "full", "all"), default="all")
    parser.add_argument(
        "--expect-decision", choices=("advance", "refine_once", "kill"), default=None
    )
    args = parser.parse_args()
    # --corpus-dir is accepted for symmetry with the runner; the verifier proves
    # reconstruction by re-decoding tapes and comparing to the frozen item SHA,
    # so it never needs to open the corpus itself.
    del args.corpus_dir

    verifier = Verifier(
        run_dir=args.run_dir.resolve(),
        repo_root=args.repo_root.resolve(),
        profile=args.profile,
        items_config=args.items_config,
        kernel_binary=args.kernel_binary,
        redecode=args.redecode,
    )
    report = verifier.run(args.expect_decision)
    (args.run_dir / "verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verified": report["verified"], "decision": report["decision"]}))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
