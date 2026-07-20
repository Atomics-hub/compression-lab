from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-frontier-headroom-e1-plan.py"
CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-20-frontier-headroom-oracle-census-e1-protocol.md"
)
SPEC = importlib.util.spec_from_file_location("frontier_headroom_e1_plan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class FrontierHeadroomE1PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_frozen_plan_verifies_without_corpus_access(self) -> None:
        result = MODULE.validate(self.config)
        self.assertTrue(result["verified"])
        self.assertTrue(result["offline_plan_only"])
        self.assertEqual(result["item_count"], 17)
        self.assertEqual(result["whole_item_codec_count"], 4)
        self.assertEqual(result["maximum_sample_basis_points"], 500)
        self.assertFalse(result["measurements_exist"])
        self.assertFalse(result["public_validation_accessed"])
        self.assertFalse(result["private_holdout_accessed"])
        self.assertEqual(result["axiom_wins"], 0)

    def test_exact_codec_commands_and_binary_identities_are_closed(self) -> None:
        codecs = {row["id"]: row for row in self.config["codecs"]}
        self.assertEqual(tuple(codecs), MODULE.EXPECTED_CODEC_IDS)
        for codec_id in MODULE.EXPECTED_CODEC_IDS:
            self.assertEqual(
                codecs[codec_id]["binary_sha256"],
                MODULE.EXPECTED_BINARY_SHA256[codec_id],
            )
            self.assertEqual(
                {
                    "compress": codecs[codec_id]["compress"],
                    "decompress": codecs[codec_id]["decompress"],
                },
                MODULE.EXPECTED_COMMANDS[codec_id],
            )
        drifted = copy.deepcopy(self.config)
        drifted["codecs"][1]["compress"].remove("--long=31")
        with self.assertRaisesRegex(ValueError, "command differs"):
            MODULE.validate(drifted)
        drifted = copy.deepcopy(self.config)
        drifted["codecs"][0]["binary_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "binary identity differs"):
            MODULE.validate(drifted)

    def test_reserved_item_and_category_rebinding_fail_closed(self) -> None:
        drifted = copy.deepcopy(self.config)
        drifted["items"][0]["id"] = "clue-validation-a"
        with self.assertRaisesRegex(ValueError, "does not reconstruct"):
            MODULE.validate(drifted)
        drifted = copy.deepcopy(self.config)
        drifted["items"][0]["category"] = "source_code_bundles"
        drifted["items"][3]["category"] = "json_logs"
        with self.assertRaisesRegex(ValueError, "item category differs"):
            MODULE.validate(drifted)
        drifted = copy.deepcopy(self.config)
        drifted["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            MODULE.validate(drifted)

    def test_stratified_sample_is_exact_nonoverlapping_and_at_most_five_percent(
        self,
    ) -> None:
        for item in self.config["items"]:
            ranges = MODULE.sample_ranges(item["bytes"])
            self.assertEqual(len(ranges), 5)
            self.assertEqual(
                sum(length for _offset, length in ranges),
                item["bytes"] * 500 // 10_000,
            )
            self.assertLessEqual(
                sum(length for _offset, length in ranges) * 10_000,
                item["bytes"] * 500,
            )
            for previous, current in zip(ranges, ranges[1:]):
                self.assertLessEqual(previous[0] + previous[1], current[0])
        with self.assertRaisesRegex(ValueError, "frozen policy"):
            MODULE.sample_ranges(1000, basis_points=501)

    def choice(
        self, item_id: str, codec_id: str, artifact_bytes: int
    ) -> dict[str, object]:
        return {
            "item_id": item_id,
            "codec_id": codec_id,
            "decoded_bytes": 10_000,
            "decoded_sha256": digest(f"decoded:{item_id}"),
            "artifact_bytes": artifact_bytes,
            "artifact_sha256": digest(f"artifact:{item_id}:{codec_id}"),
        }

    def test_equal_oracle_framing_counts_every_artifact_and_metadata_byte(self) -> None:
        rows = [
            self.choice("a", "kanzi-max", 1000),
            self.choice("b", "zstd-19-long", 900),
        ]
        total = MODULE.axe1o_bytes("fixture", rows)
        expected = (
            5
            + 1
            + MODULE.string_bytes("fixture")
            + 32
            + 4
            + sum(
                MODULE.string_bytes(row["item_id"])
                + MODULE.string_bytes(row["codec_id"])
                + 8
                + 32
                + 8
                + 32
                + row["artifact_bytes"]
                for row in rows
            )
        )
        self.assertEqual(total, expected)
        duplicated = [rows[0], copy.deepcopy(rows[0])]
        with self.assertRaisesRegex(ValueError, "duplicated"):
            MODULE.axe1o_bytes("fixture", duplicated)

    def test_segment_overhead_can_erase_a_payload_only_win(self) -> None:
        segments = [
            {
                "segment_index": index,
                "codec_id": "xz-lzma2-9e",
                "decoded_bytes": 1024,
                "decoded_sha256": digest(f"decoded:{index}"),
                "artifact_bytes": 490,
                "artifact_sha256": digest(f"artifact:{index}"),
            }
            for index in range(2)
        ]
        payload_only = sum(row["artifact_bytes"] for row in segments)
        complete = MODULE.axe1g_bytes("item", segments)
        self.assertEqual(payload_only, 980)
        self.assertGreater(complete, 1000)
        self.assertLess(MODULE.gain_basis_points(1000, complete), 0)
        self.assertEqual(
            MODULE.gain_basis_points(1000, complete, clamp=True),
            0,
        )
        segments[1]["segment_index"] = 3
        with self.assertRaisesRegex(ValueError, "segment order"):
            MODULE.axe1g_bytes("item", segments)

    def test_commercial_speed_tiers_are_joint_speed_and_memory_gates(self) -> None:
        self.assertEqual(
            MODULE.attained_speed_tiers(
                self.config,
                compression_mbps=110.0,
                decompression_mbps=550.0,
                peak_rss_bytes=500 * 1024**2,
            ),
            ["interactive", "balanced", "archival"],
        )
        self.assertEqual(
            MODULE.attained_speed_tiers(
                self.config,
                compression_mbps=30.0,
                decompression_mbps=300.0,
                peak_rss_bytes=900 * 1024**2,
            ),
            ["balanced", "archival"],
        )
        self.assertEqual(
            MODULE.attained_speed_tiers(
                self.config,
                compression_mbps=1.0,
                decompression_mbps=90.0,
                peak_rss_bytes=100 * 1024**2,
            ),
            [],
        )

    def test_category_speed_uses_slowest_aggregate_repetition_and_max_rss(self) -> None:
        repetitions = [
            {
                "repetition": 0,
                "items": [
                    {
                        "item_id": "a",
                        "source_bytes": 100_000_000,
                        "encode_wall_ns": 250_000_000,
                        "decode_wall_ns": 100_000_000,
                        "peak_rss_bytes": 400 * 1024**2,
                    },
                    {
                        "item_id": "b",
                        "source_bytes": 200_000_000,
                        "encode_wall_ns": 2_750_000_000,
                        "decode_wall_ns": 400_000_000,
                        "peak_rss_bytes": 500 * 1024**2,
                    },
                ],
            },
            {
                "repetition": 1,
                "items": [
                    {
                        "item_id": "a",
                        "source_bytes": 100_000_000,
                        "encode_wall_ns": 2_000_000_000,
                        "decode_wall_ns": 250_000_000,
                        "peak_rss_bytes": 900 * 1024**2,
                    },
                    {
                        "item_id": "b",
                        "source_bytes": 200_000_000,
                        "encode_wall_ns": 4_000_000_000,
                        "decode_wall_ns": 750_000_000,
                        "peak_rss_bytes": 700 * 1024**2,
                    },
                ],
            },
        ]
        metrics = MODULE.aggregate_category_metrics(
            repetitions, expected_item_ids={"a", "b"}
        )
        self.assertEqual(metrics["compression_mbps"], 50.0)
        self.assertEqual(metrics["decompression_mbps"], 300.0)
        self.assertEqual(metrics["peak_rss_bytes"], 900 * 1024**2)
        self.assertEqual(
            MODULE.attained_speed_tiers(self.config, **metrics),
            ["balanced", "archival"],
        )
        drifted = copy.deepcopy(repetitions)
        drifted[1]["items"].pop()
        with self.assertRaisesRegex(ValueError, "item roster differs"):
            MODULE.aggregate_category_metrics(drifted, expected_item_ids={"a", "b"})
        zero_rss = copy.deepcopy(repetitions)
        zero_rss[0]["items"][0]["peak_rss_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "RSS differs"):
            MODULE.aggregate_category_metrics(zero_rss, expected_item_ids={"a", "b"})

    def test_untriggered_segment_stage_is_exactly_zero_for_decisions(self) -> None:
        self.assertEqual(
            MODULE.segment_gate_basis_points(
                triggered=False, measured_basis_points=None
            ),
            0,
        )
        self.assertEqual(
            MODULE.segment_gate_basis_points(triggered=True, measured_basis_points=-12),
            -12,
        )
        with self.assertRaisesRegex(ValueError, "must be absent"):
            MODULE.segment_gate_basis_points(triggered=False, measured_basis_points=0)
        self.assertIn(
            "untriggered optional segment stage contributes exactly 0 basis points",
            self.config["decision_gates"]["reject_routing_lane"],
        )

    def test_result_schema_and_artifact_policies_are_closed(self) -> None:
        self.assertEqual(self.config["result_schema"], MODULE.EXPECTED_RESULT_SCHEMA)
        self.assertIn("magic[5]=AXE1S", self.config["sample_ceiling"]["binary_layout"])
        self.assertIn(
            "fresh nonexistent path ending exactly in .zpaq",
            self.config["codecs"][-1]["artifact_path_policy"],
        )
        drifted = copy.deepcopy(self.config)
        drifted["result_schema"]["process_keys"].append("silent_extra")
        with self.assertRaisesRegex(ValueError, "result schema differs"):
            MODULE.validate(drifted)
        drifted = copy.deepcopy(self.config)
        del drifted["result_schema"]["binding_rule"]
        with self.assertRaisesRegex(ValueError, "result schema differs"):
            MODULE.validate(drifted)

    def test_protocol_preserves_claim_and_sealed_boundaries(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("No E1 codec invocation", protocol)
        self.assertIn("Hindsight oracles are upper bounds", protocol)
        self.assertIn("No E1 outcome is an Axiom win", protocol)
        self.assertIn("never more than 5%", protocol)
        self.assertIn("does not rerun codecs", protocol)
        self.assertIn("private holdouts", protocol)


if __name__ == "__main__":
    unittest.main()
