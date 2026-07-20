from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "numeric-ar5-numr-training-v1.json"
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-20-numeric-ar5-numr-training-protocol.md"
)
VERIFIER_PATH = ROOT / "scripts" / "verify-numeric-ar5-numr-training-protocol.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("numeric_ar5_numr_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load numeric protocol verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier()


def config() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


class NumericAR5NUMRTrainingProtocolTests(unittest.TestCase):
    def test_frozen_protocol_verifies_without_authorizing_measurement(self) -> None:
        result = VERIFIER.verify(CONFIG, PROTOCOL)
        self.assertFalse(result["measurement_authorized"])
        self.assertFalse(result["results_present"])
        self.assertEqual(result["baseline_count"], 11)
        self.assertEqual(result["track_count"], 8)
        self.assertEqual(result["config_sha256"], VERIFIER.EXPECTED_CONFIG_SHA256)
        self.assertEqual(result["protocol_sha256"], VERIFIER.EXPECTED_PROTOCOL_SHA256)

    def test_candidate_contains_all_required_representation_families(self) -> None:
        payload = config()
        candidate = payload["candidate"]
        self.assertEqual(candidate["family"], "AR5/NUM-R")
        self.assertEqual(
            candidate["float_decimal_origin_recast"]["float32_exponents"],
            list(range(11)),
        )
        self.assertEqual(
            candidate["float_decimal_origin_recast"]["float64_exponents"],
            list(range(19)),
        )
        self.assertTrue(
            {
                "xor_previous_with_reused_front_and_trailing_zero_window",
                "delta",
                "delta2",
                "integer_lpc_order_1",
                "integer_lpc_order_2",
                "integer_lpc_order_4",
            }.issubset(candidate["predictors"])
        )
        self.assertIn("raw_word_byte_plane_plus_zstd", candidate["residual_encodings"])
        self.assertEqual(candidate["fallbacks"][-2:], ["direct_zstd", "store"])
        self.assertEqual(
            candidate["internal_zstd"]["revision"],
            VERIFIER.EXPECTED_BASELINES["zstd-19"][1],
        )
        self.assertEqual(candidate["internal_zstd"]["level"], 9)
        self.assertTrue(candidate["internal_zstd"]["frame_checksum"])

    def test_external_baselines_have_full_revisions_licenses_and_commands(self) -> None:
        payload = config()
        by_id = {row["id"]: row for row in payload["external_baselines"]}
        self.assertEqual(set(by_id), set(VERIFIER.EXPECTED_BASELINES))
        for baseline_id, row in by_id.items():
            self.assertTrue(row["license"])
            self.assertTrue(row["license_file"])
            self.assertIn("{input}", row["encode"])
            self.assertIn("{output}", row["encode"])
            self.assertIn("{input}", row["decode"])
            self.assertIn("{output}", row["decode"])
            self.assertIsNone(row["binary_sha256"])
            if baseline_id != "store":
                self.assertEqual(len(row["revision"]), 40)
        self.assertIn(
            "source-provided complete timestamp",
            payload["baseline_applicability_rule"],
        )
        self.assertIn("{timestamps}", by_id["chimp-paper"]["encode"])
        self.assertIn("{timestamps}", by_id["gorilla-reference-class"]["encode"])

    def test_gates_freeze_six_percent_advancement_and_five_percent_holdout(self) -> None:
        gates = config()["gates"]
        self.assertEqual(
            gates["training"][
                "aggregate_complete_bytes_at_most_fraction_of_strongest_applicable_baseline"
            ],
            0.94,
        )
        self.assertEqual(
            gates["training"][
                "each_declared_track_complete_bytes_at_most_fraction_of_strongest_applicable_baseline"
            ],
            0.94,
        )
        self.assertEqual(
            gates["future_validation"][
                "aggregate_and_each_track_advancement_fraction"
            ],
            0.06,
        )
        self.assertEqual(
            gates["future_private_holdout"][
                "aggregate_and_each_track_advancement_fraction"
            ],
            0.05,
        )

    def test_consumed_numeric_validation_and_future_splits_stay_sealed(self) -> None:
        evaluation = config()["evaluation"]
        self.assertEqual(evaluation["validation"], "sealed_and_unauthorized")
        self.assertEqual(evaluation["private_holdout"], "sealed_and_unauthorized")
        self.assertEqual(
            evaluation["forbidden_prior_numeric_validation_families"],
            ["UCI Gisette", "UCI Madelon"],
        )

    def test_verifier_rejects_authorization_or_premature_results(self) -> None:
        payload = config()
        payload["measurement_authorized"] = True
        with self.assertRaisesRegex(ValueError, "must not authorize"):
            VERIFIER.verify_config(payload)
        payload = config()
        payload["results"] = {"passed": True}
        with self.assertRaisesRegex(ValueError, "must not authorize"):
            VERIFIER.verify_config(payload)

    def test_verifier_rejects_weakened_ratio_or_holdout_gate(self) -> None:
        payload = config()
        payload["gates"]["training"][
            "aggregate_complete_bytes_at_most_fraction_of_strongest_applicable_baseline"
        ] = 0.95
        with self.assertRaisesRegex(ValueError, "at least 6%"):
            VERIFIER.verify_config(payload)
        payload = config()
        payload["gates"]["future_private_holdout"][
            "aggregate_and_each_track_advancement_fraction"
        ] = 0.04
        with self.assertRaisesRegex(ValueError, "remain 5%"):
            VERIFIER.verify_config(payload)

    def test_verifier_rejects_missing_specialist_or_unfrozen_binary(self) -> None:
        payload = config()
        payload["external_baselines"] = [
            row for row in payload["external_baselines"] if row["id"] != "fpzip-exact"
        ]
        with self.assertRaisesRegex(ValueError, "baseline roster"):
            VERIFIER.verify_config(payload)
        payload = config()
        payload["external_baselines"][0]["binary_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "remain null"):
            VERIFIER.verify_config(payload)

    def test_verifier_rejects_selector_overhead_or_extra_keys(self) -> None:
        payload = config()
        payload["candidate"]["selector"]["analysis_time_counted"] = False
        with self.assertRaisesRegex(ValueError, "overhead"):
            VERIFIER.verify_config(payload)
        payload = config()
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "keys mismatch"):
            VERIFIER.verify_config(payload)

    def test_verifier_rejects_internal_codec_or_applicability_drift(self) -> None:
        payload = config()
        payload["candidate"]["internal_zstd"]["revision"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "internal Zstandard lock"):
            VERIFIER.verify_config(payload)
        payload = config()
        payload["external_baselines"][0]["applies_to"] = ["unknown_track"]
        with self.assertRaisesRegex(ValueError, "applicability is invalid"):
            VERIFIER.verify_config(payload)
        payload = config()
        payload["external_baselines"][2]["encode"] = payload[
            "external_baselines"
        ][2]["encode"].replace(" --timestamps {timestamps}", "")
        with self.assertRaisesRegex(ValueError, "lacks timestamp input"):
            VERIFIER.verify_config(payload)

    def test_verifier_rejects_missing_protocol_boundary(self) -> None:
        text = " ".join(PROTOCOL.read_text(encoding="utf-8").split()).replace(
            "No benchmark command in this protocol is currently authorized to run.",
            "",
        )
        with self.assertRaisesRegex(ValueError, "missing frozen requirements"):
            VERIFIER.verify_protocol_text(text)

    def test_file_verifier_rejects_tampered_config(self) -> None:
        payload = copy.deepcopy(config())
        payload["evaluation"]["validation"] = "open"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "validation must remain sealed"):
                VERIFIER.verify(path, PROTOCOL)


if __name__ == "__main__":
    unittest.main()
