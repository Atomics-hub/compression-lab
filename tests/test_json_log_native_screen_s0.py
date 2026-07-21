from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-log-native-screen-s0-v1.json"
E2_CONFIG = ROOT / "config" / "json-context-ceiling-e2-a-v1.json"
PROTOCOL = (
    ROOT / "docs" / "benchmarks" / "2026-07-21-json-log-native-screen-s0-protocol.md"
)


def packed_size(value: str) -> int:
    return 2 + len(value.encode("utf-8"))


def single_item_axe1o_size(category: str, item: dict, codec_id: str) -> int:
    field_prefix = {"kanzi-max": "kanzi", "zpaq-5-m510": "zpaq_510"}[codec_id]
    return (
        5
        + 1
        + packed_size(category)
        + 32
        + 4
        + packed_size(item["id"])
        + packed_size(codec_id)
        + 8
        + 32
        + 8
        + 32
        + item[f"{field_prefix}_artifact_bytes"]
    )


class JsonLogNativeScreenS0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG.read_bytes())
        cls.e2 = json.loads(E2_CONFIG.read_bytes())

    def test_protocol_is_frozen_before_measurement_and_keeps_boundaries(self):
        self.assertTrue(PROTOCOL.is_file())
        self.assertEqual(
            self.config["status"],
            "refrozen_after_adversarial_review_before_any_s0_measurement",
        )
        boundary = self.config["information_boundary"]
        self.assertEqual(boundary["fresh_public_validation_status"], "none_frozen")
        self.assertTrue(boundary["private_holdout_status"].startswith("sealed"))
        self.assertIn("until E2-A completes", boundary["measurement_authorization"])
        freeze = self.config["screen"]["freeze_requirements_before_measurement"]
        self.assertIn("base_constants_manifest_sha256", freeze)
        self.assertIn("refined_constants_manifest_sha256", freeze)
        self.assertEqual(freeze["protocol_path"], PROTOCOL.relative_to(ROOT).as_posix())
        self.assertEqual(
            freeze["protocol_sha256"], hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
        )

    def test_e1_result_bindings_and_exact_per_item_references_are_pinned(self):
        source = self.config["source"]
        e2_source = self.e2["source_run"]
        self.assertEqual(
            source["practical_artifact"]["result_sha256"],
            e2_source["e1_practical_json_artifact"]["result_sha256"],
        )
        self.assertEqual(
            source["ceiling_artifact"]["result_sha256"],
            e2_source["e1_zpaq_json_artifact"]["result_sha256"],
        )
        self.assertEqual(
            source["training_manifest_sha256"],
            e2_source["training_manifest_sha256"],
        )
        items = self.config["references"]["items"]
        e2_items = {row["id"]: row for row in self.e2["items"]}
        self.assertEqual(sum(row["source_bytes"] for row in items), 203578132)
        self.assertEqual(sum(row["kanzi_artifact_bytes"] for row in items), 1711751)
        self.assertEqual(sum(row["zpaq_510_artifact_bytes"] for row in items), 1346660)
        for row in items:
            self.assertEqual(row["source_bytes"], e2_items[row["id"]]["bytes"])
            self.assertEqual(row["source_sha256"], e2_items[row["id"]]["sha256"])
            self.assertEqual(
                row["kanzi_single_item_axe1o_bytes"],
                single_item_axe1o_size("json_logs", row, "kanzi-max"),
            )
            self.assertEqual(
                row["zpaq_510_single_item_axe1o_bytes"],
                single_item_axe1o_size("json_logs", row, "zpaq-5-m510"),
            )
        extraction = source["per_item_reference_extraction"]
        self.assertEqual(
            extraction["status"],
            "verified_from_recoverable_GitHub_artifacts_before_freeze",
        )

    def test_integer_gates_are_exact_and_cover_every_byte(self):
        baseline = self.config["references"]["aggregate"]["kanzi_complete_bytes"]
        gates = self.config["screen"]["gates"]

        def gain(size: int) -> int:
            return (baseline - size) * 10000 // baseline

        self.assertEqual(gain(gates["advance_maximum_projected_complete_bytes"]), 1500)
        self.assertEqual(
            gates["permit_one_refinement_minimum_bytes"],
            gates["advance_maximum_projected_complete_bytes"] + 1,
        )
        self.assertEqual(gain(gates["permit_one_refinement_minimum_bytes"]), 1499)
        self.assertEqual(gain(gates["permit_one_refinement_maximum_bytes"]), 1000)
        self.assertEqual(
            gates["kill_at_or_above_projected_complete_bytes"],
            gates["permit_one_refinement_maximum_bytes"] + 1,
        )
        self.assertEqual(gain(gates["kill_at_or_above_projected_complete_bytes"]), 999)

    def test_matrix_and_resource_limits_are_closed(self):
        screen = self.config["screen"]
        self.assertEqual(screen["primary_arm"], "full")
        self.assertEqual(len(screen["arms"]), 10)
        self.assertEqual(len({row["id"] for row in screen["arms"]}), 10)
        limits = screen["engine_requirements"]
        self.assertEqual(limits["average_modeled_binary_event_limit_per_record"], 96)
        self.assertIn("96 * record_count", limits["event_limit_scope"])
        self.assertIn("kills S0", limits["event_limit_failure"])
        self.assertIn("Every source byte", limits["exact_reconstruction"])
        self.assertIn("charged exactly 8 bits", limits["event_limit_scope"])
        self.assertEqual(limits["session_slots"], 65536)
        self.assertEqual(limits["token_slots"], 262144)
        self.assertEqual(limits["total_model_state_bytes_maximum"], 384 * 2**20)
        self.assertIn("Deterministic CLOCK", limits["eviction"])
        self.assertEqual(limits["static_or_shipped_dictionary_bytes"], 0)
        self.assertIn(
            "single fully specified capacity refinement", screen["look_budget"]
        )

    def test_projection_charges_and_attribution_are_frozen(self):
        projection = self.config["screen"]["projection"]
        item_count = len(self.config["references"]["items"])
        self.assertIn("raw_literal_bytes * 8 * 2^24", projection["charged_loss_q24"])
        item_blocks = sum(
            math.ceil(item["source_bytes"] / 2**20)
            for item in self.config["references"]["items"]
        )
        self.assertEqual(projection["block_allowance_bytes"], 32 * item_blocks)
        self.assertEqual(projection["stream_metadata_bytes"], 24 * item_count)
        self.assertEqual(projection["fixed_framing_bytes"], 4096)

        gates = self.config["screen"]["gates"]
        baseline = self.config["references"]["aggregate"]["kanzi_complete_bytes"]
        self.assertEqual(
            gates["mechanism_report_minimum_attribution_bytes"],
            math.ceil(baseline * 5 / 1000),
        )
        self.assertEqual(
            gates["mechanism_exact_build_minimum_attribution_bytes"],
            math.ceil(baseline / 100),
        )
        self.assertIn("Only the full arm", gates["decision_scope"])
        self.assertEqual(
            set(gates["attribution"]),
            {
                "m1_bytes",
                "m2_bytes",
                "m3_bytes",
                "m4_bytes",
                "m5_bytes",
                "interaction_policy",
            },
        )

    def test_single_refinement_is_fully_bounded(self):
        screen = self.config["screen"]
        refinement = screen["single_refinement"]
        changes = refinement["changes"]
        limits = screen["engine_requirements"]
        self.assertEqual(
            changes["context_table_bytes_maximum"]["from"],
            limits["context_table_bytes_maximum"],
        )
        self.assertEqual(
            changes["sse_table_bytes_maximum"]["from"],
            limits["sse_table_bytes_maximum"],
        )
        self.assertIn("1455327 through 1540934", refinement["authorization"])
        self.assertIn("1455326-byte advance maximum", refinement["decision"])
        self.assertIn("No second refinement", refinement["decision"])
        self.assertIn("separately pre-pinned", refinement["confirmation"])

        base_component_bytes = (
            limits["context_table_bytes_maximum"]
            + limits["sse_table_bytes_maximum"]
            + limits["mixer_table_bytes_maximum"]
            + limits["session_slots"] * limits["session_slot_bytes_maximum"]
            + limits["token_slots"] * limits["token_slot_bytes_maximum"]
            + limits["token_byte_arena_bytes_maximum"]
        )
        refined_component_bytes = (
            base_component_bytes
            - changes["context_table_bytes_maximum"]["from"]
            + changes["context_table_bytes_maximum"]["to"]
            - changes["sse_table_bytes_maximum"]["from"]
            + changes["sse_table_bytes_maximum"]["to"]
        )
        self.assertEqual(base_component_bytes, 264 * 2**20)
        self.assertEqual(refined_component_bytes, 320 * 2**20)
        self.assertLessEqual(
            refined_component_bytes, limits["total_model_state_bytes_maximum"]
        )


if __name__ == "__main__":
    unittest.main()
