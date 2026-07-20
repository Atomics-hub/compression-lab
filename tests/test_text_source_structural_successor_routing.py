from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "route-text-source-structural-successor.py"
CONFIG = REPOSITORY / "config" / "text-source-successor-routing-v1.json"
SPEC = importlib.util.spec_from_file_location("structural_successor_routing", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load structural successor routing")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def candidate(
    variant: str, *, hypothesis: bool, admission: bool
) -> dict[str, object]:
    return {
        "kind": "axiom_candidate",
        "id": variant,
        "complete_bytes": 1_000,
        "gain_vs_kanzi_percent": 3.5 if admission else (1.0 if hypothesis else -0.1),
        "minimum_item_gain_percent": 0.2 if hypothesis else -0.2,
        "hypothesis_gate_passed": hypothesis,
        "final_specialist_admission_passed": admission,
        "exact_roundtrip": True,
        "deterministic_artifact": True,
        "decision": (
            "development admission passed"
            if admission
            else (
                "hypothesis passed; final admission missed"
                if hypothesis
                else "development hypothesis rejected"
            )
        ),
    }


def comparison(
    *, source_h1: tuple[bool, bool], source_h2: tuple[bool, bool], wiki_h1: tuple[bool, bool]
) -> dict[str, object]:
    return {
        "name": "text-source-structural-transform-development-publication-v1",
        "stage": "development structural representation probe",
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "structural_results_sha256": "a" * 64,
        "baseline_results_sha256": "b" * 64,
        "tracks": [
            {
                "track_id": "source_code_bundles",
                "rows": [
                    candidate(
                        "ts-h1-demux",
                        hypothesis=source_h1[0],
                        admission=source_h1[1],
                    ),
                    candidate(
                        "ts-h2-extension-lanes",
                        hypothesis=source_h2[0],
                        admission=source_h2[1],
                    ),
                ],
            },
            {
                "track_id": "english_wikimedia_wikitext",
                "rows": [
                    candidate(
                        "ts-h1-demux",
                        hypothesis=wiki_h1[0],
                        admission=wiki_h1[1],
                    )
                ],
            },
        ],
    }


class TextSourceStructuralSuccessorRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config_raw = CONFIG.read_bytes()
        cls.config = json.loads(cls.config_raw)
        MODULE.validate_config(cls.config)

    def decide(self, evidence: dict[str, object]) -> dict[str, object]:
        return MODULE.build_decision(
            config=self.config,
            comparison=evidence,
            config_sha256="c" * 64,
            comparison_sha256="d" * 64,
            publication_receipt_sha256="e" * 64,
        )

    def test_admitted_h2_and_h1_choose_the_material_channel_successors(self) -> None:
        result = self.decide(
            comparison(
                source_h1=(True, True),
                source_h2=(True, True),
                wiki_h1=(True, True),
            )
        )
        selected = {row["track_id"]: row for row in result["decisions"]}
        self.assertEqual(
            selected["source_code_bundles"]["selected_rule_id"],
            "source_h2_admitted",
        )
        self.assertEqual(
            selected["english_wikimedia_wikitext"]["selected_rule_id"],
            "wikimedia_h1_admitted",
        )
        self.assertEqual(result["axiom_wins"], 0)
        self.assertEqual(
            result["successor_gate"][
                "minimum_gain_vs_strongest_eligible_complete_baseline_percent"
            ],
            5.0,
        )

    def test_signal_only_and_rejection_routes_are_ordered_and_explicit(self) -> None:
        result = self.decide(
            comparison(
                source_h1=(True, False),
                source_h2=(True, False),
                wiki_h1=(False, False),
            )
        )
        selected = {row["track_id"]: row for row in result["decisions"]}
        self.assertEqual(
            selected["source_code_bundles"]["selected_rule_id"],
            "source_h2_signal_only",
        )
        self.assertEqual(
            selected["english_wikimedia_wikitext"]["selected_rule_id"],
            "wikimedia_structural_rejected",
        )
        h1_only = self.decide(
            comparison(
                source_h1=(True, False),
                source_h2=(False, False),
                wiki_h1=(False, False),
            )
        )
        self.assertEqual(
            h1_only["decisions"][0]["selected_rule_id"], "source_h1_signal_only"
        )
        all_rejected = self.decide(
            comparison(
                source_h1=(False, False),
                source_h2=(False, False),
                wiki_h1=(False, False),
            )
        )
        self.assertEqual(
            all_rejected["decisions"][0]["selected_rule_id"],
            "source_structural_rejected",
        )

    def test_inconsistent_admission_and_noncanonical_replacement_fail_closed(self) -> None:
        evidence = comparison(
            source_h1=(False, True),
            source_h2=(False, False),
            wiki_h1=(False, False),
        )
        with self.assertRaisesRegex(ValueError, "candidate outcome is invalid"):
            self.decide(evidence)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "decision.json"
            valid = self.decide(
                comparison(
                    source_h1=(False, False),
                    source_h2=(False, False),
                    wiki_h1=(False, False),
                )
            )
            MODULE.write_immutable(path, valid)
            MODULE.write_immutable(path, valid)
            valid["axiom_wins"] = 1
            with self.assertRaisesRegex(ValueError, "differing successor decision"):
                MODULE.write_immutable(path, valid)

    def test_checked_decision_reconstructs_and_rejects_an_injected_win(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            publication = root / "publication"
            publication.mkdir()
            evidence = comparison(
                source_h1=(False, False),
                source_h2=(True, False),
                wiki_h1=(True, False),
            )
            comparison_path = publication / "comparison.json"
            receipt_path = publication / "receipt.json"
            comparison_path.write_bytes(MODULE.json_bytes(evidence))
            receipt_path.write_bytes(MODULE.json_bytes({"fixture": True}))
            decision = MODULE.build_decision(
                config=self.config,
                comparison=evidence,
                config_sha256=hashlib.sha256(self.config_raw).hexdigest(),
                comparison_sha256=hashlib.sha256(
                    comparison_path.read_bytes()
                ).hexdigest(),
                publication_receipt_sha256=hashlib.sha256(
                    receipt_path.read_bytes()
                ).hexdigest(),
            )
            decision_path = root / "decision.json"
            decision_path.write_bytes(MODULE.json_bytes(decision))
            verification = {
                "verified": True,
                "public_evidence_sha256": "f" * 64,
            }
            with mock.patch.object(
                MODULE.PUBLICATION_VERIFY, "verify", return_value=verification
            ):
                result = MODULE.validate_decision(
                    CONFIG, publication, decision_path
                )
                self.assertTrue(result["verified"])
                self.assertEqual(result["axiom_wins"], 0)
                decision["axiom_wins"] = 1
                decision_path.write_bytes(MODULE.json_bytes(decision))
                with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                    MODULE.validate_decision(CONFIG, publication, decision_path)


if __name__ == "__main__":
    unittest.main()
