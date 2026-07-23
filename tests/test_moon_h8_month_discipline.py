#!/usr/bin/env python3
"""Locks the H8 static-mixer month discipline and weight provenance.

The frozen static mixer must be learned only on the pinned public month-A
slice; month B is an unseen holdout the sweep evaluates. This test pins that
discipline (helm tightening #3: no month shopping) and checks the committed
weight artifact's provenance against the trainer receipt, so a silent retrain
on a different month, or a weight file that does not match its receipt, fails
CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

REPOSITORY = Path(__file__).resolve().parents[1]
DATA_DIR = REPOSITORY / "native" / "src" / "moon" / "data"
DISCIPLINE = DATA_DIR / "h8-month-discipline.json"
RECEIPT = DATA_DIR / "h8-static-mixer-weights.receipt.json"
WEIGHTS = DATA_DIR / "h8-static-mixer-weights.bin"


class MoonH8MonthDisciplineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discipline = json.loads(DISCIPLINE.read_text(encoding="utf-8"))
        self.receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_train_and_eval_months_are_distinct(self) -> None:
        train = self.discipline["train_month_a"]
        evaluate = self.discipline["eval_month_b"]
        self.assertNotEqual(train["hour"], evaluate["hour"])
        self.assertNotEqual(train["sha256"], evaluate["sha256"])
        self.assertEqual(train["month"], "A")
        self.assertEqual(evaluate["month"], "B")

    def test_weights_were_trained_on_the_pinned_month_a_slice(self) -> None:
        # The trainer receipt's source SHA must be exactly the pinned month-A
        # slice: the shipped weights were learned on month A and nothing else.
        self.assertEqual(
            self.receipt["source_sha256"],
            self.discipline["train_month_a"]["sha256"],
        )
        self.assertEqual(self.receipt["train_month"], "A")

    def test_weight_artifact_matches_its_receipt_and_config(self) -> None:
        digest = hashlib.sha256(WEIGHTS.read_bytes()).hexdigest()
        self.assertEqual(digest, self.receipt["weight_file_sha256"])
        self.assertEqual(digest, self.discipline["weight_artifact"]["sha256"])
        self.assertEqual(
            self.receipt["procedure_version"],
            self.discipline["weight_artifact"]["procedure_version"],
        )

    def test_evidence_stage_is_development_only_prescreen(self) -> None:
        self.assertEqual(
            self.discipline["evidence_stage"], "development_only_prescreen"
        )
        self.assertEqual(self.receipt["evidence_stage"], "development_only_prescreen")


if __name__ == "__main__":
    unittest.main()
