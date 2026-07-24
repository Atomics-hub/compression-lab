from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPRODUCE = ROOT / "scripts" / "reproduce-jls2-v2.py"

spec = importlib.util.spec_from_file_location("reproduce_jls2_v2", REPRODUCE)
assert spec is not None and spec.loader is not None
REPRO = importlib.util.module_from_spec(spec)
spec.loader.exec_module(REPRO)


def _hosted_family(item_id: str, candidate_bytes: int) -> dict[str, object]:
    return {"item_id": item_id, "candidate_bytes": candidate_bytes}


def _decision(
    *,
    result: str,
    candidate: int,
    strongest: int,
    original: int,
    families: list[dict[str, object]],
    gates: dict[str, bool],
) -> dict[str, object]:
    return {
        "result": result,
        "aggregate": {
            "candidate_bytes": candidate,
            "strongest_eligible_bytes": strongest,
            "original_bytes": original,
        },
        "family_rows": families,
        "gate_results": gates,
    }


HOSTED_GATES = {"aggregate_ratio": True, "exact_roundtrip": True}
HOSTED = _decision(
    result="passed",
    candidate=522423,
    strongest=1066789,
    original=97521725,
    families=[
        _hosted_family("clue-validation-v2-c", 301050),
        _hosted_family("clue-validation-v2-d", 221373),
    ],
    gates=dict(HOSTED_GATES),
)


class ReceiptBindingTests(unittest.TestCase):
    def test_bind_receipt_is_self_consistent(self) -> None:
        receipt = {"mode": "smoke", "value": 7, "nested": {"b": 2, "a": 1}}
        bound = REPRO.bind_receipt(receipt)
        body = {k: v for k, v in bound.items() if k != "receipt_sha256"}
        encoded = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False)
        expected = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.assertEqual(bound["receipt_sha256"], expected)

    def test_bind_receipt_ignores_prior_binding(self) -> None:
        first = REPRO.bind_receipt({"a": 1})
        second = REPRO.bind_receipt(dict(first))
        self.assertEqual(first["receipt_sha256"], second["receipt_sha256"])

    def test_binding_changes_when_content_changes(self) -> None:
        a = REPRO.bind_receipt({"a": 1})
        b = REPRO.bind_receipt({"a": 2})
        self.assertNotEqual(a["receipt_sha256"], b["receipt_sha256"])


class CompareToHostedTests(unittest.TestCase):
    def test_exact_reproduction_is_reproduced(self) -> None:
        reproduced = _decision(
            result="passed",
            candidate=522423,
            strongest=1066789,
            original=97521725,
            families=[
                _hosted_family("clue-validation-v2-c", 301050),
                _hosted_family("clue-validation-v2-d", 221373),
            ],
            gates=dict(HOSTED_GATES),
        )
        result = REPRO.compare_to_hosted(reproduced, HOSTED)
        self.assertTrue(result["reproduced"])
        self.assertTrue(all(result["checks"].values()))
        self.assertIn("REPRODUCED", result["verdict"])

    def test_speed_and_rss_do_not_affect_byte_verdict(self) -> None:
        # Byte counts and gates are identical; machine-dependent fields are absent
        # from the comparison entirely, so a match is still a reproduction.
        reproduced = json.loads(json.dumps(HOSTED))
        result = REPRO.compare_to_hosted(reproduced, HOSTED)
        self.assertTrue(result["reproduced"])

    def test_diverging_candidate_bytes_is_not_reproduced(self) -> None:
        reproduced = _decision(
            result="passed",
            candidate=522424,
            strongest=1066789,
            original=97521725,
            families=[
                _hosted_family("clue-validation-v2-c", 301051),
                _hosted_family("clue-validation-v2-d", 221373),
            ],
            gates=dict(HOSTED_GATES),
        )
        result = REPRO.compare_to_hosted(reproduced, HOSTED)
        self.assertFalse(result["reproduced"])
        self.assertFalse(result["checks"]["aggregate_candidate_bytes_match"])
        self.assertFalse(result["checks"]["family_candidate_bytes_match"])
        self.assertIn("NOT REPRODUCED", result["verdict"])

    def test_failed_gate_is_not_reproduced(self) -> None:
        reproduced = _decision(
            result="not_passed",
            candidate=522423,
            strongest=1066789,
            original=97521725,
            families=[
                _hosted_family("clue-validation-v2-c", 301050),
                _hosted_family("clue-validation-v2-d", 221373),
            ],
            gates={"aggregate_ratio": True, "exact_roundtrip": False},
        )
        result = REPRO.compare_to_hosted(reproduced, HOSTED)
        self.assertFalse(result["reproduced"])
        self.assertFalse(result["checks"]["all_gates_passed"])


class MachineIdentityTests(unittest.TestCase):
    def test_machine_identity_has_required_fields(self) -> None:
        identity = REPRO.machine_identity()
        for field in ("system", "machine", "cpu_count", "python_version"):
            self.assertIn(field, identity)


class FrozenPointerTests(unittest.TestCase):
    def test_hosted_decision_is_the_immutable_run(self) -> None:
        self.assertTrue(REPRO.HOSTED_DECISION_PATH.is_file())
        hosted = REPRO.load_json(REPRO.HOSTED_DECISION_PATH)
        self.assertEqual(hosted["result"], "passed")
        self.assertEqual(int(hosted["aggregate"]["candidate_bytes"]), 522423)

    def test_gates_pins_are_readable(self) -> None:
        gates = REPRO.load_json(REPRO.GATES_PATH)
        sources = gates["baselines"]["required_external_sources"]
        for name in ("zstd", "lz4", "brotli", "7zip"):
            self.assertIn(name, sources)


if __name__ == "__main__":
    unittest.main()
