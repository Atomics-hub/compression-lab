from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish-clue-jls2-public-validation-v2.py"
SPEC = importlib.util.spec_from_file_location("clue_jls2_v2_publication", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MIB = 1024 * 1024


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decision_payload(result: str) -> dict:
    passed = result == "passed"
    return {
        "schema_version": 1,
        "name": MODULE.DECISION_NAME,
        "result": result,
        "category_gate_passed": passed,
        "aggregate": {
            "original_bytes": 1000,
            "candidate_bytes": 300 if passed else 360,
            "strongest_eligible_codec": "pbc-only",
            "strongest_eligible_bytes": 350,
            "gain_vs_strongest_eligible_percent": 100 / 7 if passed else -10 / 35,
            "compression_mbps": 120.0,
            "standalone_decompression_mbps": 300.0,
            "compression_peak_rss_bytes": 128 * MIB,
            "standalone_decompression_peak_rss_bytes": 96 * MIB,
            "compression_shim_maxrss_bytes": 8 * MIB,
            "standalone_decompression_shim_maxrss_bytes": 8 * MIB,
        },
        "comparison_rows": [
            {
                "codec_id": "jls2",
                "role": "candidate",
                "compressed_bytes": 300 if passed else 360,
                "ratio": 10 / 3,
                "compression_mbps": 120.0,
                "decompression_mbps": 300.0,
                "exact_roundtrip": True,
                "candidate_smaller": None,
                "size_runner": "same-run complete-file",
                "speed_runner": "standalone native pass on same host and corpus",
            },
            {
                "codec_id": "pbc-only",
                "role": "eligible specialist",
                "compressed_bytes": 350,
                "ratio": 20 / 7,
                "compression_mbps": 10.0,
                "decompression_mbps": 50.0,
                "exact_roundtrip": True,
                "candidate_smaller": passed,
                "size_runner": "identical bytes; separate pinned specialist run",
                "speed_runner": "separate pinned specialist run; contextual",
            },
            {
                "codec_id": "LogFold",
                "role": "unavailable specialist context",
                "compressed_bytes": None,
                "ratio": None,
                "compression_mbps": None,
                "decompression_mbps": None,
                "exact_roundtrip": None,
                "candidate_smaller": None,
                "size_runner": "unavailable or ineligible",
                "speed_runner": "unavailable or ineligible",
            },
        ],
        "family_rows": [
            {
                "family": "clue_validation_v2_c",
                "original_bytes": 1000,
                "candidate_bytes": 300 if passed else 360,
                "strongest_eligible_codec": "pbc-only",
                "strongest_eligible_bytes": 350,
                "gain_vs_strongest_eligible_percent": 100 / 7 if passed else -10 / 35,
                "ratio_gate_passed": passed,
            }
        ],
        "gate_results": {"aggregate_ratio": passed, "exact_roundtrip": True},
        "claim_ceiling": "Category-scoped v2 public validation only.",
        "sources": {},
    }


class ClueJLS2V2PublicationTests(unittest.TestCase):
    def test_report_and_svg_pass_both_ways(self) -> None:
        for result, badge in (
            ("passed", "Status: **passed**"),
            ("not_passed", "Status: **not passed**"),
        ):
            decision = decision_payload(result)
            report = MODULE.render_report(decision)
            svg = MODULE.render_svg(decision)
            self.assertIn(badge, report)
            self.assertIn(
                "does not correct, replace, or reopen the immutable v1", report
            )
            self.assertIn("| pbc-only | eligible specialist", report)
            self.assertIn("| LogFold | unavailable specialist context", report)
            self.assertIn(
                "Unavailable rows are disclosures, not Atompress wins", report
            )
            self.assertIn("clean-child instrument", report)
            self.assertIn("jls2", svg)
            self.assertIn("Unavailable/ineligible (not wins): LogFold", svg)

    def test_publication_is_source_bound_and_immutable(self) -> None:
        for result in ("passed", "not_passed"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source_paths = {}
                for name in ("receipt", "performance", "pbc", "manifest", "gates"):
                    path = root / f"{name}.json"
                    path.write_text(json.dumps({"name": name}), encoding="utf-8")
                    source_paths[name] = path
                decision = decision_payload(result)
                decision["sources"] = {
                    "receipt_sha256": digest(source_paths["receipt"]),
                    "performance_sha256": digest(source_paths["performance"]),
                    "pbc_sha256": digest(source_paths["pbc"]),
                    "gates_sha256": digest(source_paths["gates"]),
                }
                decision_path = root / "decision.json"
                decision_path.write_text(json.dumps(decision), encoding="utf-8")
                output = root / "publication"
                bundle_path = MODULE.publish(
                    decision_path=decision_path,
                    receipt_path=source_paths["receipt"],
                    performance_path=source_paths["performance"],
                    pbc_path=source_paths["pbc"],
                    manifest_path=source_paths["manifest"],
                    gates_path=source_paths["gates"],
                    output=output,
                )
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                self.assertEqual(bundle["status"], result)
                self.assertEqual(bundle["category_gate_passed"], result == "passed")
                for name, expected in bundle["artifacts"].items():
                    self.assertEqual(digest(output / name), expected)
                with self.assertRaisesRegex(ValueError, "refusing to replace"):
                    MODULE.publish(
                        decision_path=decision_path,
                        receipt_path=source_paths["receipt"],
                        performance_path=source_paths["performance"],
                        pbc_path=source_paths["pbc"],
                        manifest_path=source_paths["manifest"],
                        gates_path=source_paths["gates"],
                        output=output,
                    )
                source_paths["receipt"].write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "does not bind"):
                    MODULE.publish(
                        decision_path=decision_path,
                        receipt_path=source_paths["receipt"],
                        performance_path=source_paths["performance"],
                        pbc_path=source_paths["pbc"],
                        manifest_path=source_paths["manifest"],
                        gates_path=source_paths["gates"],
                        output=root / "second-publication",
                    )


if __name__ == "__main__":
    unittest.main()
