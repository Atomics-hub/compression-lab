from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit-jls2-a3-memory-plan.py"
NATIVE_JLS2 = ROOT / "native" / "src" / "jls2.rs"
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-19-jls2-declared-size-lifetime-a3-audit-protocol.md"
)
SPEC = importlib.util.spec_from_file_location("jls2_a3_memory_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def frame(mode: int, original_size: int, payload: bytes) -> bytes:
    return b"".join(
        (
            AUDIT.FRAME_MAGIC,
            bytes((AUDIT.VERSION, mode, 0, 0)),
            original_size.to_bytes(8, "big"),
            len(payload).to_bytes(8, "big"),
            hashlib.sha256(f"source:{original_size}".encode()).digest(),
            hashlib.sha256(payload).digest(),
            payload,
        )
    )


def direct_frame(original_size: int, payload_size: int = 1) -> bytes:
    return frame(AUDIT.MODE_DIRECT, original_size, b"d" * payload_size)


def columnar_frame(
    original_size: int,
    raw_sizes: list[int],
    encoded_sizes: list[int] | None = None,
) -> bytes:
    if encoded_sizes is None:
        encoded_sizes = [1] * len(raw_sizes)
    assert len(raw_sizes) == len(encoded_sizes)
    channel_count = len(raw_sizes) - 1
    header = b"".join(
        (
            AUDIT.COLUMN_MAGIC,
            bytes((AUDIT.VERSION, 0, 0, 0)),
            original_size.to_bytes(8, "big"),
            hashlib.sha256(f"column:{original_size}".encode()).digest(),
            channel_count.to_bytes(4, "big"),
            raw_sizes[0].to_bytes(8, "big"),
            encoded_sizes[0].to_bytes(8, "big"),
        )
    )
    table = b"".join(
        raw.to_bytes(8, "big") + encoded.to_bytes(8, "big")
        for raw, encoded in zip(raw_sizes[1:], encoded_sizes[1:])
    )
    payloads = b"".join(
        bytes((65 + index % 26,)) * size
        for index, size in enumerate(encoded_sizes)
    )
    return frame(AUDIT.MODE_COLUMNAR, original_size, header + table + payloads)


def stream(frames: list[tuple[int, bytes]]) -> bytes:
    segment_payload = b"".join(
        size.to_bytes(8, "big") + len(item).to_bytes(8, "big") + item
        for size, item in frames
    )
    original_size = sum(size for size, _ in frames)
    return b"".join(
        (
            AUDIT.STREAM_MAGIC,
            bytes((AUDIT.VERSION, 0, 0, 0)),
            original_size.to_bytes(8, "big"),
            hashlib.sha256(f"stream:{original_size}".encode()).digest(),
            hashlib.sha256(segment_payload).digest(),
            len(frames).to_bytes(4, "big"),
            segment_payload,
        )
    )


class JLS2A3MemoryPlanAuditTests(unittest.TestCase):
    def test_declared_column_buffers_make_hypothesis_measurable(self) -> None:
        mib = 1024 * 1024
        item = columnar_frame(16 * mib, [32 * mib, 32 * mib])
        encoded = stream([(16 * mib, item)] * 3)

        report = AUDIT.audit(encoded, logical_cpus=4)

        self.assertEqual(
            report["current_a2_plan"]["peak_declared_live_working_bytes"],
            240 * mib,
        )
        self.assertEqual(
            report["proposed_a3_plan"]["peak_declared_live_working_bytes"],
            80 * mib,
        )
        self.assertEqual(
            report["upper_bounds_not_observed"]["decoded_live_reduction_bytes"],
            160 * mib,
        )
        self.assertTrue(
            report["kill_gate"]["decoded_upper_bound_reaches_threshold"]
        )
        self.assertEqual(
            report["kill_gate"]["status"], "hosted_attribution_required"
        )
        self.assertFalse(report["kill_gate"]["passed"])
        self.assertFalse(report["authorization"]["product_ab_authorized"])
        self.assertIsNone(
            report["allocator_retained_pages"]["observed_bytes"]
        )

    def test_small_encoded_lifetime_requires_allocator_measurement(self) -> None:
        mib = 1024 * 1024
        encoded = stream([(16 * mib, direct_frame(16 * mib))])

        report = AUDIT.audit(encoded, logical_cpus=4)

        self.assertEqual(
            report["upper_bounds_not_observed"]["decoded_live_reduction_bytes"],
            0,
        )
        self.assertFalse(
            report["kill_gate"]["decoded_upper_bound_reaches_threshold"]
        )
        self.assertEqual(
            report["kill_gate"]["status"], "hosted_attribution_required"
        )
        self.assertEqual(
            report["kill_gate"]["preliminary_finding"],
            "decoded_concurrency_attribution_insufficient",
        )

    def test_encoded_lifetime_is_report_only_and_cannot_authorize(self) -> None:
        mib = 1024 * 1024
        encoded = stream(
            [
                (30 * mib, direct_frame(30 * mib, 40 * mib)),
                (30 * mib, direct_frame(30 * mib, 40 * mib)),
                (30 * mib, direct_frame(30 * mib, 40 * mib)),
                (30 * mib, direct_frame(30 * mib, 40 * mib)),
            ]
        )

        report = AUDIT.audit(encoded, logical_cpus=4)

        self.assertGreater(
            report["upper_bounds_not_observed"]["encoded_lifetime_reduction_bytes"],
            report["kill_gate"]["required_attributed_bytes"],
        )
        self.assertFalse(
            report["kill_gate"]["decoded_upper_bound_reaches_threshold"]
        )
        self.assertEqual(
            report["kill_gate"]["encoded_lifetime_authorization_credit_bytes"], 0
        )
        self.assertFalse(
            report["authorization"]["lifetime_only_release_can_authorize"]
        )

    def test_frozen_host_and_rss_inputs_reject_drift(self) -> None:
        encoded = stream([(1, direct_frame(1))])
        with self.assertRaisesRegex(ValueError, "logical CPU count drifted"):
            AUDIT.audit(encoded, logical_cpus=8)
        with self.assertRaisesRegex(ValueError, "baseline peak RSS drifted"):
            AUDIT.audit(
                encoded,
                logical_cpus=4,
                baseline_peak_rss_bytes=AUDIT.BASELINE_PEAK_RSS_BYTES - 1,
            )
        with self.assertRaisesRegex(ValueError, "development limit drifted"):
            AUDIT.audit(
                encoded,
                logical_cpus=4,
                development_limit_bytes=AUDIT.DEVELOPMENT_LIMIT_BYTES - 1,
            )
        with self.assertRaisesRegex(ValueError, "batch budget drifted"):
            AUDIT.audit(
                encoded,
                logical_cpus=4,
                batch_budget_bytes=AUDIT.BATCH_BUDGET_BYTES - 1,
            )

    def test_exact_a2_evidence_and_toolchain_are_locked(self) -> None:
        self.assertEqual(AUDIT.EXPECTED_A2_RUN_ID, 29_676_674_924)
        self.assertEqual(AUDIT.EXPECTED_A2_JOB_ID, 88_165_232_780)
        self.assertEqual(AUDIT.BASELINE_PEAK_RSS_BYTES, 657_682_432)
        self.assertEqual(AUDIT.EXPECTED_A2_LOGICAL_CPUS, 4)
        self.assertEqual(
            AUDIT.EXPECTED_A2_CANDIDATE_COMMIT,
            "0f3377dff647e8a6d99b65d8f8a269687faa8ec6",
        )
        self.assertEqual(AUDIT.EXPECTED_A2_ZSTD["libzstd"], "1.5.7")
        self.assertEqual(
            {item: row["segment_count"] for item, row in AUDIT.EXPECTED_A2_FIXTURES.items()},
            {
                "clue-early-development": 4,
                "clue-middle-development": 5,
                "clue-late-development": 5,
                "jls2-context-stress-256": 3,
            },
        )

    def test_rust_outer_concurrency_contract_is_locked(self) -> None:
        source = NATIVE_JLS2.read_text(encoding="utf-8")
        self.assertIn("const MAX_SEGMENT_WORKERS: usize = 8;", source)
        self.assertIn(
            "segments.len().min(available).clamp(1, MAX_SEGMENT_WORKERS)",
            source,
        )
        self.assertIn("segments.chunks(segment_workers)", source)
        self.assertIn("if segments.len() == 1", source)
        self.assertIn("MAX_ZSTD_WORKERS", source)
        self.assertIn("} else {\n        1\n    };", source)

    def test_proposed_batches_are_consecutive_and_budgeted(self) -> None:
        mib = 1024 * 1024
        frames = [(16 * mib, direct_frame(16 * mib))] * 3
        segments = AUDIT.parse_stream(stream(frames))

        batches = AUDIT.proposed_batches(segments, 32 * mib)

        self.assertEqual(batches, [[0, 1], [2]])

    def test_rejects_corrupt_outer_digest_and_oversized_raw_table(self) -> None:
        encoded = bytearray(stream([(10, direct_frame(10))]))
        encoded[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "encoded SHA-256 mismatch"):
            AUDIT.parse_stream(bytes(encoded))

        oversized = columnar_frame(10, [AUDIT.MAX_RAW_OVERHEAD + 41])
        with self.assertRaisesRegex(ValueError, "stream size exceeds"):
            AUDIT.parse_stream(stream([(10, oversized)]))

    def test_protocol_freezes_compound_and_data_boundaries(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("105,202,484 bytes", protocol)
        self.assertIn("32 MiB", protocol)
        self.assertIn("compound A1+A2+A3 candidate", protocol)
        self.assertIn("Neither experimental change replaces", protocol)
        self.assertIn("can never be acquired", protocol)
        self.assertIn("private holdout remains sealed", protocol)
        self.assertIn("hosted_attribution_required", protocol)
        self.assertIn("zero authorization credit", protocol)
        self.assertIn("657,682,432", protocol)
        self.assertIn("29676674924", protocol)
        self.assertIn("88165232780", protocol)
        self.assertIn("zstd-sys", protocol)
        self.assertIn("mallinfo2", protocol)


if __name__ == "__main__":
    unittest.main()
