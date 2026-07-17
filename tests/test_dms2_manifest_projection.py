from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "project-dms2-public-validation-manifest.py"
SPEC = importlib.util.spec_from_file_location("dms2_projection", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DMS2ManifestProjectionTests(unittest.TestCase):
    def inputs(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "manifest.json"
        lock = root / "lock.json"
        gates = root / "gates.json"
        items = [
            {"id": "extra", "family": "record", "track": "record_table"},
            {"id": "a", "family": "fa", "track": "dense_feature_matrix"},
            {"id": "b", "family": "fb", "track": "dense_feature_matrix"},
        ]
        for index, item in enumerate(items):
            item.update(
                size_bytes=index + 1,
                sha256=f"item-{index}",
                archive_sha256=f"archive-{index}",
                path=f"{item['id']}.table",
            )
        source.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "source_split": "public_validation",
                    "benchmark_split": "validation",
                    "config_sha256": "config",
                    "evaluation_tracks": ["dense_feature_matrix", "record_table"],
                    "items": items,
                }
            ),
            encoding="utf-8",
        )
        lock.write_text(
            json.dumps({"authorization": {"expected_item_ids": ["a", "b"]}}),
            encoding="utf-8",
        )
        gates.write_text(
            json.dumps(
                {
                    "validation": {
                        "expected_items": [
                            {"id": "a", "family": "fa", "track": "dense_feature_matrix"},
                            {"id": "b", "family": "fb", "track": "dense_feature_matrix"},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        return source, lock, gates

    def test_projects_only_predeclared_ids_and_records_excluded_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, lock, gates = self.inputs(root)
            output = root / "manifest.dms2.json"
            receipt = root / "receipt.json"
            MODULE.project(
                source_manifest_path=source,
                lock_path=lock,
                gates_path=gates,
                output_path=output,
                receipt_path=receipt,
            )
            projected = json.loads(output.read_text(encoding="utf-8"))
            recorded = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in projected["items"]], ["a", "b"])
            self.assertEqual(projected["evaluation_tracks"], ["dense_feature_matrix"])
            self.assertEqual(projected["pre_score_projection"]["excluded_item_ids"], ["extra"])
            self.assertEqual(recorded["scored_attempts_started_before_projection"], 0)
            self.assertEqual(
                [item["id"] for item in recorded["unexpectedly_acquired_but_unscored_items"]],
                ["extra"],
            )

    def test_refuses_missing_locked_item(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, lock, gates = self.inputs(root)
            manifest = json.loads(source.read_text(encoding="utf-8"))
            manifest["items"] = manifest["items"][:-1]
            source.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "locked items missing"):
                MODULE.project(
                    source_manifest_path=source,
                    lock_path=lock,
                    gates_path=gates,
                    output_path=root / "manifest.dms2.json",
                    receipt_path=root / "receipt.json",
                )

    def test_refuses_to_overwrite_first_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, lock, gates = self.inputs(root)
            output = root / "manifest.dms2.json"
            receipt = root / "receipt.json"
            output.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "replace"):
                MODULE.project(
                    source_manifest_path=source,
                    lock_path=lock,
                    gates_path=gates,
                    output_path=output,
                    receipt_path=receipt,
                )


if __name__ == "__main__":
    unittest.main()
