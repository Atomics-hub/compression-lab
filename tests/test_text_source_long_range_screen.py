import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-text-source-long-range-screen.py"
CONFIG = REPOSITORY / "config" / "text-source-long-range-screen-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-18-text-source-long-range-screen-protocol.md"
)
SPEC = importlib.util.spec_from_file_location("text_source_long_range_screen", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load text/source long-range screen module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourceLongRangeScreenTests(unittest.TestCase):
    def config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_protocol_is_canonical_frozen_and_keeps_evaluation_reserved(self) -> None:
        raw = CONFIG.read_bytes()
        config = json.loads(raw)
        self.assertEqual(raw, MODULE.json_bytes(config))
        MODULE.validate_config(config)
        for split in config["splits"].values():
            self.assertFalse(
                set(split["screen_items"])
                & set(split["reserved_evaluation_not_accessed_by_screen"])
            )
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("No screen result existed", protocol)
        self.assertIn("not accessed by this screen", protocol)
        self.assertIn("at least 2% smaller", protocol)
        self.assertIn("at least 5% smaller", protocol)

    def test_commands_are_exact_single_job_custom_kanzi_pipelines(self) -> None:
        config = self.config()
        for variant in config["variants"]:
            compression, decompression = MODULE.commands(
                kanzi=Path("/tool/kanzi"),
                variant=variant,
                source=Path("/data/source"),
                artifact=Path("/work/artifact.knz"),
                restored=Path("/work/restored"),
            )
            self.assertIn(f"--transform={variant['transform']}", compression)
            self.assertIn("--entropy=TPAQX", compression)
            self.assertIn("--block=1g", compression)
            self.assertIn("--jobs=1", compression)
            self.assertFalse(any(argument.startswith("--level") for argument in compression))
            self.assertIn("--jobs=1", decompression)

    def test_manifest_verification_never_opens_reserved_evaluation_bytes(self) -> None:
        config = self.config()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            rows = []
            for track, split in config["splits"].items():
                del track
                for item_id in split["screen_items"]:
                    payload = (item_id + "\n").encode()
                    path = root / f"{item_id}.bin"
                    path.write_bytes(payload)
                    rows.append(
                        {
                            "source_id": item_id,
                            "bundle_path": path.name,
                            "bundle_size_bytes": len(payload),
                            "bundle_sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    )
                for item_id in split["reserved_evaluation_not_accessed_by_screen"]:
                    rows.append(
                        {
                            "source_id": item_id,
                            "bundle_path": f"missing-{item_id}.bin",
                            "bundle_size_bytes": 1,
                            "bundle_sha256": "a" * 64,
                        }
                    )
            manifest = {
                "schema_version": 1,
                "name": "fixture",
                "items": rows,
                "public_validation_accessed": False,
            }
            (root / "manifest.json").write_bytes(MODULE.json_bytes(manifest))
            _manifest_raw, items = MODULE.verify_screen_items(root, config)
            self.assertEqual(len(items), 4)
            self.assertTrue(all(Path(item["path"]).is_file() for item in items))

    def test_summary_admits_only_one_shared_exact_deterministic_variant(self) -> None:
        config = self.config()
        items = [
            {"id": item_id, "track": track, "source_bytes": 10_000}
            for track, split in config["splits"].items()
            for item_id in split["screen_items"]
        ]
        baseline_rows = [
            {
                "codec_id": "kanzi-max",
                "item_id": item["id"],
                "artifact_bytes": 1_000,
            }
            for item in items
        ]
        baseline = {"summary": {"item_codec_rows": baseline_rows}}
        size_by_variant = {
            "k1-lzp-prepend-level9": 950,
            "k2-lzp-text-utf": 995,
            "k3-lzp-only": 1_100,
        }
        trials = []
        for variant, artifact_bytes in size_by_variant.items():
            for item in items:
                for repetition in range(2):
                    trials.append(
                        {
                            "variant": variant,
                            "item_id": item["id"],
                            "repetition": repetition,
                            "artifact_bytes": artifact_bytes,
                            "artifact_sha256": hashlib.sha256(
                                f"{variant}/{item['id']}".encode()
                            ).hexdigest(),
                            "passed": True,
                            "compression": {
                                "wall_ns": 1_000 + repetition,
                                "peak_rss_bytes": 100,
                            },
                            "decompression": {
                                "wall_ns": 500 + repetition,
                                "peak_rss_bytes": 50,
                            },
                        }
                    )
        summary = MODULE.summarize(
            trials=trials, items=items, baseline=baseline, config=config
        )
        self.assertTrue(summary["axiom_prototype_admitted"])
        self.assertEqual(summary["selected_variant"], "k1-lzp-prepend-level9")
        self.assertEqual(
            summary["shared_passing_variants"], ["k1-lzp-prepend-level9"]
        )
        self.assertEqual(summary["axiom_wins"], 0)

        trials[1]["artifact_sha256"] = "f" * 64
        rejected = MODULE.summarize(
            trials=trials, items=items, baseline=baseline, config=config
        )
        self.assertFalse(rejected["axiom_prototype_admitted"])
        self.assertIsNone(rejected["selected_variant"])


if __name__ == "__main__":
    unittest.main()
