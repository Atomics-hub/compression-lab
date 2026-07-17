from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "config" / "text-source-category-protocol-v1.json"
ACQUISITION = ROOT / "config" / "text-source-development-acquisition-v1.json"
RECEIPT = ROOT / "runs" / "text-source-development-acquisition-v1.json"


def digest_at_commit(commit: str, relative: str) -> str:
    content = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


class TextSourceDevelopmentEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        cls.acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
        cls.receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_receipt_is_bound_to_the_historical_pre_acquisition_surface(self) -> None:
        receipt = self.receipt
        acquisition = self.acquisition
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["acquisition_commit"], acquisition["acquisition_commit"])
        self.assertEqual(
            receipt["aggregate_manifest_sha256"],
            acquisition["aggregate_manifest_sha256"],
        )
        self.assertEqual(receipt["protocol_sha256"], acquisition["protocol_sha256"])
        self.assertEqual(receipt["rules_sha256"], acquisition["rules_sha256"])
        self.assertEqual(
            digest_at_commit(
                receipt["acquisition_commit"],
                "config/text-source-category-protocol-v1.json",
            ),
            receipt["protocol_sha256"],
        )
        self.assertEqual(
            digest_at_commit(
                receipt["acquisition_commit"],
                "config/text-source-path-rules-v1.json",
            ),
            receipt["rules_sha256"],
        )
        ancestor = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                receipt["acquisition_commit"],
                "HEAD",
            ],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_exact_seven_item_development_result_is_frozen(self) -> None:
        expected = {
            "cpython-3.14.6-source": (
                23_921_184,
                "143b1dddefaec3bd2e21e3b839b34a2b7fb9842272883c576420d605e9f30c63",
                44_506_231,
                "a5148815b1257d5e9f040a6995b09493ceaeecd1f1791c2cb4a858f177cbf1c3",
                2_032,
                2_032,
                False,
            ),
            "typescript-6.0.3-source": (
                33_864_358,
                "43d388f7fc6511ae105f23f4779e1c8df96f6dfa003025b70249816089609f5b",
                25_693_307,
                "4c35679d66dc77e54cc87ee7b6fe17cf2262bc3242c37eff3fa527e385d64480",
                819,
                819,
                False,
            ),
            "rust-1.97.1-source": (
                242_787_896,
                "0ed06fdaffd4722a7702e0b4eebfafc897ab8f513e8e1b247cdd7e5c6df6ded2",
                190_921_859,
                "655025f34d7887305c90af2bf0936bbacc92ffeaef5d790c5ba566da0cd32659",
                16_445,
                16_445,
                False,
            ),
            "llvm-22.1.8-source": (
                167_061_596,
                "922f1817a0df7b1489272d18134ee0087a8b068828f87ac63b9861b1a9965888",
                268_328_176,
                "8a54e60b4c022683a0261ada2a2203f9d56fd3e5e48a7fc36c9de97050c31509",
                20_660,
                27_356,
                True,
            ),
            "enwikibooks-20260701": (
                207_098_222,
                "cb6487326d55e0f017ca75f2174af7cf5ab3f39fd1a9140c046e1d899dd02c29",
                67_107_953,
                "d4e99fa76d224995f03512df7fe2d9b0411e283b21157c934be6c10e2059998a",
                9_813,
                9_813,
                None,
            ),
            "enwikinews-20260701": (
                54_157_210,
                "ba76e5215a517ef565b5400d7ad458c3766c29fa496a7f000a90d2ac699268a6",
                67_105_968,
                "ac803f7c66400659801b4dd72576ad88602952db4dbc78e82c1c4c4d39c92b9e",
                18_698,
                18_698,
                None,
            ),
            "enwikiversity-20260701": (
                119_592_609,
                "305548abb494e23e83b18d4e8542aaa6ab9eb658a54c53716f7744a75bb9083b",
                67_097_252,
                "35d42b7137f5d85772cb44ea214dcf1f6df9c0bb59f65dde3170df8c0a8dfbe4",
                12_904,
                12_904,
                None,
            ),
        }
        observed = {
            item["source_id"]: (
                item["archive_size_bytes"],
                item["archive_sha256"],
                item["bundle_size_bytes"],
                item["bundle_sha256"],
                item["record_count"],
                item["selected_record_count"],
                item["truncated_at_byte_cap"],
            )
            for item in self.receipt["items"]
        }
        self.assertEqual(observed, expected)
        self.assertEqual(self.receipt["item_count"], 7)
        self.assertEqual(self.receipt["total_derived_bytes"], 730_760_746)
        for item in self.receipt["items"]:
            self.assertRegex(item["manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(item["ordered_manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_protocol_is_synchronized_but_validation_remains_sealed(self) -> None:
        receipt_items = {item["source_id"]: item for item in self.receipt["items"]}
        development = (
            self.protocol["source_code"]["development"]
            + self.protocol["natural_language"]["development"]
        )
        for row in development:
            receipt = receipt_items[row["id"]]
            self.assertEqual(row["acquisition_status"], "acquired_development")
            self.assertEqual(row["archive_sha256"], receipt["archive_sha256"])
            self.assertEqual(row["derived_item_bytes"], receipt["bundle_size_bytes"])
            self.assertEqual(row["derived_item_sha256"], receipt["bundle_sha256"])
        validation = (
            self.protocol["source_code"]["public_validation"]
            + self.protocol["natural_language"]["public_validation"]
        )
        for row in validation:
            self.assertEqual(row["acquisition_status"], "sealed_unacquired")
            self.assertIsNone(row["archive_sha256"])
            self.assertIsNone(row["derived_item_bytes"])
            self.assertIsNone(row["derived_item_sha256"])
        self.assertFalse(self.receipt["public_validation_accessed"])

    def test_attempt_history_and_claim_ceiling_are_transparent(self) -> None:
        attempts = self.receipt["attempts"]
        self.assertEqual([row["attempt"] for row in attempts], [1, 2, 3, 4, 5])
        self.assertEqual([row["output_promoted"] for row in attempts], [False] * 4 + [True])
        self.assertEqual(attempts[-1]["result"], "completed")
        ceiling = self.receipt["claim_ceiling"].lower()
        self.assertIn("development", ceiling)
        self.assertIn("no codec probe", ceiling)
        self.assertIn("no", ceiling)
        self.assertIn("state-of-the-art", ceiling)


if __name__ == "__main__":
    unittest.main()
