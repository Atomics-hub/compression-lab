from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
IMPORT_SCRIPT = ROOT / "scripts" / "import-clue-jls2-public-validation-v2.py"
PUBLISH_SCRIPT = ROOT / "scripts" / "publish-clue-jls2-public-validation-v2.py"
GATES = ROOT / "config" / "clue-jls2-public-validation-v2-gates.json"
MIB = 1024 * 1024


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IMPORTER = load_module("clue_jls2_v2_import", IMPORT_SCRIPT)
PUBLISHER = load_module("clue_jls2_v2_publish_for_import", PUBLISH_SCRIPT)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def decision_payload() -> dict:
    return {
        "schema_version": 1,
        "name": IMPORTER.DECISION_NAME,
        "result": "not_passed",
        "category_gate_passed": False,
        "aggregate": {
            "original_bytes": 1000,
            "candidate_bytes": 360,
            "strongest_eligible_codec": "pbc-only",
            "strongest_eligible_bytes": 350,
            "gain_vs_strongest_eligible_percent": -10 / 35,
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
                "compressed_bytes": 360,
                "ratio": 1000 / 360,
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
                "ratio": 1000 / 350,
                "compression_mbps": 10.0,
                "decompression_mbps": 50.0,
                "exact_roundtrip": True,
                "candidate_smaller": False,
                "size_runner": "identical bytes; separate pinned specialist run",
                "speed_runner": "separate pinned specialist run; contextual",
            },
        ],
        "family_rows": [
            {
                "family": "clue_validation_v2_c",
                "original_bytes": 1000,
                "candidate_bytes": 360,
                "strongest_eligible_codec": "pbc-only",
                "strongest_eligible_bytes": 350,
                "gain_vs_strongest_eligible_percent": -10 / 35,
                "ratio_gate_passed": False,
            }
        ],
        "gate_results": {"aggregate_ratio": False, "exact_roundtrip": True},
        "claim_ceiling": "Category-scoped v2 public validation only.",
        "sources": {},
    }


def make_evidence(root: Path) -> Path:
    evidence = root / "evidence"
    receipt = evidence / "jls2" / "receipt.json"
    performance = evidence / "jls2" / "performance" / "results.json"
    pbc = evidence / "pbc-result.json"
    manifest = evidence / "validation-manifest.json"
    gates = root / "gates.json"
    write_json(receipt, {"completed": True})
    write_json(performance, {"name": "performance"})
    write_json(pbc, {"name": "pbc"})
    write_json(manifest, {"name": "manifest"})
    write_json(gates, {"name": "gates"})
    write_json(evidence / "readiness-lock-receipt.json", {"verified": True})

    decision = decision_payload()
    decision["sources"] = {
        "receipt_sha256": digest(receipt),
        "performance_sha256": digest(performance),
        "pbc_sha256": digest(pbc),
        "gates_sha256": digest(gates),
    }
    decision_path = evidence / "decision.json"
    write_json(decision_path, decision)
    PUBLISHER.publish(
        decision_path=decision_path,
        receipt_path=receipt,
        performance_path=performance,
        pbc_path=pbc,
        manifest_path=manifest,
        gates_path=gates,
        output=evidence / "publication",
    )
    files = sorted(
        path
        for path in evidence.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    lines = [
        f"{digest(path)}  ./{path.relative_to(evidence).as_posix()}" for path in files
    ]
    (evidence / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gates


class ClueJLS2V2ImportTests(unittest.TestCase):
    def test_verifies_and_atomically_imports_complete_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gates = make_evidence(root)
            evidence = root / "evidence"
            output = root / "imported"
            receipt = root / "import-receipt.json"
            result = IMPORTER.import_evidence(
                evidence=evidence,
                output=output,
                import_receipt=receipt,
                expected_gates=gates,
                expected_result="not_passed",
                repository=IMPORTER.EXPECTED_REPOSITORY,
                workflow_run_id=IMPORTER.EXPECTED_RUN_ID,
                head_sha=IMPORTER.EXPECTED_HEAD_SHA,
                artifact_id=1234,
                artifact_name=IMPORTER.EXPECTED_ARTIFACT_NAME,
                artifact_digest="sha256:" + "a" * 64,
            )
            self.assertEqual(result, receipt)
            self.assertEqual(
                (evidence / "SHA256SUMS").read_bytes(),
                (output / "SHA256SUMS").read_bytes(),
            )
            imported = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(imported["result"], "not_passed")
            self.assertFalse(imported["category_gate_passed"])
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                IMPORTER.import_evidence(
                    evidence=evidence,
                    output=output,
                    import_receipt=receipt,
                    expected_gates=gates,
                    expected_result="not_passed",
                    repository=IMPORTER.EXPECTED_REPOSITORY,
                    workflow_run_id=IMPORTER.EXPECTED_RUN_ID,
                    head_sha=IMPORTER.EXPECTED_HEAD_SHA,
                    artifact_id=1234,
                    artifact_name=IMPORTER.EXPECTED_ARTIFACT_NAME,
                    artifact_digest="sha256:" + "a" * 64,
                )

    def test_rejects_tampering_and_unlisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gates = make_evidence(root)
            evidence = root / "evidence"
            (evidence / "decision.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                IMPORTER.validate_evidence(
                    evidence,
                    expected_gates=gates,
                    expected_result="not_passed",
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gates = make_evidence(root)
            evidence = root / "evidence"
            (evidence / "unbound.txt").write_text(
                "not in the manifest\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "unlisted file"):
                IMPORTER.validate_evidence(
                    evidence,
                    expected_gates=gates,
                    expected_result="not_passed",
                )

    def test_rejects_wrong_run_provenance_before_copying(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gates = make_evidence(root)
            with self.assertRaisesRegex(ValueError, "unexpected workflow run"):
                IMPORTER.import_evidence(
                    evidence=root / "evidence",
                    output=root / "imported",
                    import_receipt=root / "receipt.json",
                    expected_gates=gates,
                    expected_result="not_passed",
                    repository=IMPORTER.EXPECTED_REPOSITORY,
                    workflow_run_id=IMPORTER.EXPECTED_RUN_ID + 1,
                    head_sha=IMPORTER.EXPECTED_HEAD_SHA,
                    artifact_id=1234,
                    artifact_name=IMPORTER.EXPECTED_ARTIFACT_NAME,
                    artifact_digest="sha256:" + "a" * 64,
                )
            self.assertFalse((root / "imported").exists())


if __name__ == "__main__":
    unittest.main()
