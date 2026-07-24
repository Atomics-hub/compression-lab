#!/usr/bin/env python3
"""Off-ledger synthetic exactness/throughput precheck for moonshot arms.

The default item is exactly 4 MiB and seed-pinned. The kernel itself writes
the modeled-bit tape, rereads those exact bytes, and immediately decodes them;
this wrapper adds clean child RSS/wall measurement and the binding 24 MiB
projection. It never imports the public prescreen runner or touches its budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
MEASURE = REPOSITORY / "scripts" / "measure-clean-rss.py"
SCHEMA = "moon-synthetic-precheck-v1"
GENERATOR = "axiom-nonstationary-json-v1"
DEFAULT_BYTES = 4 * 1024 * 1024
DEFAULT_SEED = 0xC3A7105EED
PUBLIC_BASIS_BYTES = 24 * 1024 * 1024
WALL_LIMIT_SECONDS = 600
REQUIRED_MARGIN_NUMERATOR = 3
REQUIRED_MARGIN_DENOMINATOR = 2
C3_ARM_ID = 104
C3_DECLARED_STATE_BYTES = 126_238_720
C3_KILL_CRITERION = (
    "Kill if C3 complete bytes are at least 0.97x H1 complete bytes on both "
    "public snapshots, OR any exactness, identity, ledger, unaccounted-state, "
    "600-second wall, or 512 MiB decode-RSS gate fails."
)
C1_ARM_ID = 105
C1_DECLARED_STATE_BYTES = 136_773_760
C1_KILL_CRITERION = (
    "Kill if C1 complete bytes are at least 0.90x H1 complete bytes on both "
    "public snapshots, OR any exactness, identity, ledger, unaccounted-state, "
    "600-second wall, or 512 MiB decode-RSS gate fails."
)
C2_ARM_ID = 106
C2_DECLARED_STATE_BYTES = 220_676_096
C2_KILL_CRITERION = (
    "Kill if C2 complete bytes are at least 0.95x H1 complete bytes on both "
    "public snapshots, or if C2 is no smaller than C1 on both public "
    "snapshots, OR any exactness, identity, ledger, unaccounted-state, "
    "600-second wall, or 512 MiB decode-RSS gate fails."
)
C8_ARM_ID = 107
C8_DECLARED_STATE_BYTES = 119_963_648
C8_KILL_CRITERION = (
    "Kill if C8 complete bytes are at least 0.93x H1 complete bytes on both "
    "public snapshots, OR any exactness, identity, ledger, unaccounted-state, "
    "600-second wall, or 512 MiB decode-RSS gate fails."
)


def xorshift64(state: int) -> int:
    state ^= (state << 13) & ((1 << 64) - 1)
    state ^= state >> 7
    state ^= (state << 17) & ((1 << 64) - 1)
    return state & ((1 << 64) - 1)


def generate(size: int = DEFAULT_BYTES, seed: int = DEFAULT_SEED) -> bytes:
    """Generate deterministic JSON/log regimes and truncate to exact size."""
    if size < 0:
        raise ValueError("size must be nonnegative")
    output = bytearray()
    state = seed
    row = 0
    while len(output) < size:
        state = xorshift64(state)
        quarter = min(3, (len(output) * 4) // max(1, size))
        if quarter == 0:
            line = '{"level":"info","service":"api","event":"heartbeat","ok":true}\n'
        elif quarter == 1:
            line = (
                f'{{"ts":{1_800_000_000 + row},"user":{state % 100_003},'
                f'"path":"/v2/items/{state & 4095}","latency":{(state >> 17) % 997}}}\n'
            )
        elif quarter == 2:
            line = (
                f'{1_800_000_000 + row} WARN worker={state & 63} '
                f'job={state:016x} retry={(state >> 23) & 7}\n'
            )
        else:
            line = (
                f'{{"metric":"cpu.{state & 31}","value":{(state >> 11) % 10_000},'
                f'"tags":{{"host":"h{(state >> 29) & 255}","zone":"z{row % 7}"}}}}\n'
            )
        output.extend(line.encode("ascii"))
        row += 1
    return bytes(output[:size])


def run(kernel: Path, arm: str, output_dir: Path, size: int, seed: int) -> dict:
    if size <= 0:
        raise ValueError("precheck size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    kernel = kernel.resolve()
    if not kernel.is_file():
        raise ValueError(f"kernel not found: {kernel}")
    kernel_sha = hashlib.sha256(kernel.read_bytes()).hexdigest()
    source = generate(size, seed)
    source_path = output_dir / "synthetic.bin"
    tape_path = output_dir / "synthetic.tape"
    kernel_receipt_path = output_dir / "kernel-receipt.json"
    rss_path = output_dir / "clean-rss.json"
    source_path.write_bytes(source)

    command = [
        str(kernel),
        "encode",
        "--arm",
        arm,
        "--item-index",
        "0",
        "--input",
        str(source_path),
        "--tape-out",
        str(tape_path),
        "--receipt-out",
        str(kernel_receipt_path),
        "--force",
    ]
    completed = subprocess.run(
        [sys.executable, str(MEASURE), "--json-out", str(rss_path), "--", *command],
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"synthetic precheck kernel exited {completed.returncode}")
    measurement = json.loads(rss_path.read_text(encoding="utf-8"))
    kernel_receipt = json.loads(kernel_receipt_path.read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(source).hexdigest()
    expected_kernel_fields = {
        "schema": "clab-moon-kernel-encode-receipt-v1",
        "evidence_stage": "development_only_prescreen",
        "arm": arm,
        "item_index": 0,
        "source_bytes": size,
        "source_sha256": source_sha,
        "decoded_sha256": source_sha,
        "decode_matches_source": True,
    }
    for field, expected in expected_kernel_fields.items():
        if kernel_receipt.get(field) != expected:
            raise SystemExit(
                f"kernel receipt {field} mismatch: "
                f"{kernel_receipt.get(field)!r} != {expected!r}"
            )
    if arm == "c3-live-adaptation":
        c3_fields = {
            "arm_id": C3_ARM_ID,
            "declared_model_state_bytes": C3_DECLARED_STATE_BYTES,
            "predicted_kill_criterion": C3_KILL_CRITERION,
            "quarter_diagnostics_q24_scale": 1 << 24,
        }
        for field, expected in c3_fields.items():
            if kernel_receipt.get(field) != expected:
                raise SystemExit(f"C3 kernel receipt {field} mismatch")
    if arm == "c1-match-mixer":
        c1_fields = {
            "arm_id": C1_ARM_ID,
            "declared_model_state_bytes": C1_DECLARED_STATE_BYTES,
            "predicted_kill_criterion": C1_KILL_CRITERION,
        }
        for field, expected in c1_fields.items():
            if kernel_receipt.get(field) != expected:
                raise SystemExit(f"C1 kernel receipt {field} mismatch")
    if arm == "c2-value-context":
        c2_fields = {
            "arm_id": C2_ARM_ID,
            "declared_model_state_bytes": C2_DECLARED_STATE_BYTES,
            "predicted_kill_criterion": C2_KILL_CRITERION,
        }
        for field, expected in c2_fields.items():
            if kernel_receipt.get(field) != expected:
                raise SystemExit(f"C2 kernel receipt {field} mismatch")
    if arm == "c8-expert-mixture":
        c8_fields = {
            "arm_id": C8_ARM_ID,
            "declared_model_state_bytes": C8_DECLARED_STATE_BYTES,
            "predicted_kill_criterion": C8_KILL_CRITERION,
        }
        for field, expected in c8_fields.items():
            if kernel_receipt.get(field) != expected:
                raise SystemExit(f"C8 kernel receipt {field} mismatch")
    tape_bytes = tape_path.read_bytes()
    if kernel_receipt.get("tape_bytes") != len(tape_bytes):
        raise SystemExit("kernel receipt tape length mismatch")
    if kernel_receipt.get("tape_sha256") != hashlib.sha256(tape_bytes).hexdigest():
        raise SystemExit("kernel receipt tape digest mismatch")
    expected_measurement = {
        "schema": "clean-rss-measurement-v1",
        "exit_code": 0,
        "command": command,
    }
    for field, expected in expected_measurement.items():
        if measurement.get(field) != expected:
            raise SystemExit(f"clean RSS receipt {field} mismatch")

    # Integer nanoseconds avoid float boundary drift. Scale linearly from the
    # chosen synthetic size; the frozen default is exactly 1/6 of 24 MiB.
    wall_ns = int(measurement["wall_ns"])
    projected_wall_ns = (wall_ns * PUBLIC_BASIS_BYTES + size - 1) // size
    margin_ceiling_ns = (
        WALL_LIMIT_SECONDS * 1_000_000_000 * REQUIRED_MARGIN_DENOMINATOR
    ) // REQUIRED_MARGIN_NUMERATOR
    passed = projected_wall_ns <= margin_ceiling_ns
    receipt = {
        "schema": SCHEMA,
        "evidence_stage": "development_only_prescreen",
        "off_cycle_run_budget": True,
        "generator": GENERATOR,
        "seed": seed,
        "source_bytes": size,
        "source_sha256": source_sha,
        "arm": arm,
        "kernel_receipt_sha256": hashlib.sha256(
            kernel_receipt_path.read_bytes()
        ).hexdigest(),
        "clean_rss_receipt_sha256": hashlib.sha256(rss_path.read_bytes()).hexdigest(),
        "kernel_binary_sha256": kernel_sha,
        "decode_matches_source": True,
        "wall_ns": wall_ns,
        "peak_rss_bytes": measurement["maxrss_bytes"],
        "rss_shim_floor_bytes": measurement["shim_maxrss_bytes"],
        "public_basis_bytes": PUBLIC_BASIS_BYTES,
        "projected_public_wall_ns": projected_wall_ns,
        "margin_ceiling_ns": margin_ceiling_ns,
        "throughput_gate_passed": passed,
    }
    (output_dir / "precheck-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--arm", default="c3-live-adaptation")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bytes", type=int, default=DEFAULT_BYTES)
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=DEFAULT_SEED)
    arguments = parser.parse_args()
    receipt = run(
        arguments.kernel, arguments.arm, arguments.output_dir, arguments.bytes, arguments.seed
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["throughput_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
