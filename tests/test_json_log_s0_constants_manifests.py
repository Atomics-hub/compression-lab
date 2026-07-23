"""Guards for the frozen S0 base and refined constants manifests.

The refined manifest must stay byte-identical to the base manifest except at
exactly the two predeclared table maxima, and every value both manifests share
with the frozen screen config must match it exactly.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-log-native-screen-s0-v1.json"
BASE = ROOT / "config" / "json-log-native-screen-s0-constants-base-v1.json"
REFINED = ROOT / "config" / "json-log-native-screen-s0-constants-refined-v1.json"

# Pinned in native/src/s0/fixed_log.rs by
# lookup_digest_matches_the_frozen_manifest_value.
LOSS_TABLE_SHA256 = "4684423d2b6feb82a598e925603811eb1b8d690027d4a05e20b219f13939c1de"


class ConstantsManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.base_bytes = BASE.read_bytes()
        cls.refined_bytes = REFINED.read_bytes()
        cls.base = json.loads(cls.base_bytes)
        cls.refined = json.loads(cls.refined_bytes)

    def test_refined_differs_only_at_the_two_predeclared_maxima(self) -> None:
        changes = [
            line
            for line in difflib.unified_diff(
                self.base_bytes.decode("utf-8").splitlines(),
                self.refined_bytes.decode("utf-8").splitlines(),
                lineterm="",
            )
            if line[:1] in {"+", "-"} and line[:3] not in {"+++", "---"}
        ]
        self.assertEqual(
            changes,
            [
                '-      "context_table_bytes_maximum": 201326592,',
                '+      "context_table_bytes_maximum": 251658240,',
                '-      "sse_table_bytes_maximum": 16777216,',
                '+      "sse_table_bytes_maximum": 25165824,',
            ],
        )

    def test_refined_values_match_the_frozen_single_refinement(self) -> None:
        declared = self.config["screen"]["single_refinement"]["changes"]
        ceilings = self.refined["table_sizes_and_memory"]["declared_ceilings"]
        self.assertEqual(
            ceilings["context_table_bytes_maximum"],
            declared["context_table_bytes_maximum"]["to"],
        )
        self.assertEqual(
            ceilings["sse_table_bytes_maximum"],
            declared["sse_table_bytes_maximum"]["to"],
        )

    def test_base_ceilings_and_limits_match_the_frozen_config(self) -> None:
        requirements = self.config["screen"]["engine_requirements"]
        ceilings = self.base["table_sizes_and_memory"]["declared_ceilings"]
        self.assertEqual(
            ceilings["context_table_bytes_maximum"],
            requirements["context_table_bytes_maximum"],
        )
        self.assertEqual(
            ceilings["mixer_table_bytes_maximum"],
            requirements["mixer_table_bytes_maximum"],
        )
        self.assertEqual(
            ceilings["sse_table_bytes_maximum"],
            requirements["sse_table_bytes_maximum"],
        )
        self.assertEqual(
            ceilings["total_model_state_bytes_maximum"],
            requirements["total_model_state_bytes_maximum"],
        )

        limits = self.base["stream_framing"]["declared_limits"]
        self.assertEqual(limits["record_limit_bytes"], requirements["record_limit_bytes"])
        self.assertEqual(limits["json_depth_limit"], requirements["json_depth_limit"])
        self.assertEqual(limits["field_count_limit"], requirements["field_count_limit"])
        self.assertEqual(
            self.base["cache_state_and_eviction"]["segment_semantics"]["segment_bytes"],
            requirements["segment_bytes"],
        )
        self.assertEqual(
            self.base["stream_framing"]["event_limit"]["per_record"],
            requirements["average_modeled_binary_event_limit_per_record"],
        )

        tables = self.base["table_sizes_and_memory"]
        self.assertEqual(
            tables["m3_session"]["session_slots"], requirements["session_slots"]
        )
        self.assertEqual(tables["m4_token"]["token_slots"], requirements["token_slots"])
        self.assertEqual(
            tables["m4_token"]["token_arena_bytes"],
            requirements["token_byte_arena_bytes_maximum"],
        )

    def test_arms_match_the_frozen_config_order_and_mechanisms(self) -> None:
        config_arms = self.config["screen"]["arms"]
        manifest_arms = self.base["arms"]["frozen_order"]
        self.assertEqual(self.base["arms"]["count"], len(config_arms))
        self.assertEqual(len(manifest_arms), len(config_arms))
        for index, (config_arm, manifest_arm) in enumerate(
            zip(config_arms, manifest_arms)
        ):
            self.assertEqual(manifest_arm["index"], index)
            self.assertEqual(manifest_arm["id"], index)
            self.assertEqual(manifest_arm["name"], config_arm["id"])
            self.assertEqual(manifest_arm["mechanisms"], config_arm["mechanisms"])
            self.assertEqual(manifest_arm["decides"], config_arm["id"] == "full")
            self.assertEqual(
                manifest_arm["event_limit_applies"], config_arm["id"] == "full"
            )

    def test_items_match_the_frozen_config_identities(self) -> None:
        config_items = self.config["references"]["items"]
        manifest_items = self.base["items"]["list"]
        self.assertEqual(len(manifest_items), len(config_items))
        for index, (config_item, manifest_item) in enumerate(
            zip(config_items, manifest_items)
        ):
            self.assertEqual(manifest_item["index"], index)
            self.assertEqual(manifest_item["id"], config_item["id"])
            self.assertEqual(
                manifest_item["source_bytes"], config_item["source_bytes"]
            )
            self.assertEqual(
                manifest_item["source_sha256"], config_item["source_sha256"]
            )
        self.assertEqual(
            self.base["items"]["per_item_kanzi_axe1o_reference_bytes"],
            [item["kanzi_single_item_axe1o_bytes"] for item in config_items],
        )

    def test_gates_match_the_frozen_config(self) -> None:
        config_gates = self.config["screen"]["gates"]
        manifest_gates = self.base["gates"]
        for key in (
            "advance_maximum_projected_complete_bytes",
            "advance_minimum_gain_basis_points",
            "permit_one_refinement_minimum_bytes",
            "permit_one_refinement_maximum_bytes",
            "kill_at_or_above_projected_complete_bytes",
            "mechanism_report_minimum_attribution_bytes",
            "mechanism_exact_build_minimum_attribution_bytes",
            "full_minus_m4_minimum_gain_basis_points",
        ):
            self.assertEqual(manifest_gates[key], config_gates[key], key)
        self.assertEqual(
            manifest_gates["kanzi_complete_bytes"],
            self.config["references"]["aggregate"]["kanzi_complete_bytes"],
        )

    def test_protocol_binding_and_loss_table_digest_are_pinned(self) -> None:
        freeze = self.config["screen"]["freeze_requirements_before_measurement"]
        self.assertEqual(
            self.base["engine_source"]["protocol_path"], freeze["protocol_path"]
        )
        self.assertEqual(
            self.base["engine_source"]["protocol_sha256"], freeze["protocol_sha256"]
        )
        self.assertEqual(
            self.base["probability_model"]["loss_table"]["sha256"], LOSS_TABLE_SHA256
        )

    def test_every_declared_engine_source_file_exists(self) -> None:
        files = self.base["source_toolchain_build_identity"]["engine_source_files"]
        self.assertEqual(files, sorted(files))
        for relative in files:
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
