import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPOSITORY / "scripts" / "benchmark-text-source-record-neighborhood-screen.py"
)
CONFIG = REPOSITORY / "config" / "text-source-record-neighborhood-screen-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-18-text-source-record-neighborhood-screen-protocol.md"
)
TRANSFORM = REPOSITORY / "scripts" / "text-source-record-neighborhood-transform.py"
SPEC = importlib.util.spec_from_file_location("record_neighborhood_screen", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import {SCRIPT}")
screen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screen)


class RecordNeighborhoodScreenTests(unittest.TestCase):
    def config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_protocol_is_frozen_canonical_and_binds_exact_transform(self) -> None:
        raw = CONFIG.read_bytes()
        config = json.loads(raw)
        self.assertEqual(raw, screen.json_bytes(config))
        screen.validate_config(config)
        self.assertEqual(
            config["bindings"]["transform_script_sha256"],
            screen.sha256_file(TRANSFORM),
        )
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("No record-neighborhood screen result\nexisted", protocol)
        self.assertIn("at least 2% smaller", protocol)
        self.assertIn("at least 1% smaller", protocol)
        self.assertIn("at least 5% smaller", protocol)
        self.assertIn("not accessed by this screen", protocol)

    def test_manifest_verification_does_not_open_reserved_paths(self) -> None:
        config = self.config()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            rows = []
            for split in config["splits"].values():
                for item_id in split["screen_items"]:
                    payload = (item_id + "\n").encode()
                    path = root / f"{item_id}.bin"
                    path.write_bytes(payload)
                    rows.append(
                        {
                            "bundle_path": path.name,
                            "bundle_sha256": hashlib.sha256(payload).hexdigest(),
                            "bundle_size_bytes": len(payload),
                            "format": "fixture",
                            "source_id": item_id,
                        }
                    )
                for item_id in split["reserved_evaluation_not_accessed_by_screen"]:
                    rows.append(
                        {
                            "bundle_path": f"missing-{item_id}.bin",
                            "bundle_sha256": "a" * 64,
                            "bundle_size_bytes": 1,
                            "format": "reserved",
                            "source_id": item_id,
                        }
                    )
            manifest = {
                "items": rows,
                "name": "fixture",
                "public_validation_accessed": False,
                "schema_version": 1,
            }
            (root / "manifest.json").write_bytes(screen.json_bytes(manifest))
            _manifest_raw, items = screen.verify_screen_items(root, config)
            self.assertEqual(len(items), 4)
            self.assertTrue(all(Path(item["path"]).is_file() for item in items))

    def test_commands_are_the_exact_frozen_six_process_chain(self) -> None:
        item = {
            "id": "fixture",
            "path": "/data/source.axsrc",
            "source_bytes": 123,
            "source_sha256": "ab" * 32,
        }
        commands = screen.process_commands(
            item,
            Path("/tool/kanzi"),
            Path("/repo/record-transform.py"),
            Path("/work"),
        )
        self.assertEqual(len(commands["compression"]), 3)
        self.assertEqual(len(commands["decompression"]), 3)
        backend = commands["compression"][1]
        self.assertEqual(
            backend[1:7],
            [
                "--compress",
                "--level=9",
                "--block=1g",
                "--jobs=1",
                "--verbose=0",
                "--force",
            ],
        )
        self.assertEqual(commands["compression"][0][2], "encode")
        self.assertEqual(commands["decompression"][2][2], "decode")
        self.assertIn("--max-output-size", commands["decompression"][2])
        self.assertFalse(any("--transform=" in value for value in backend))
        self.assertFalse(any("--entropy=" in value for value in backend))

    def test_summary_requires_both_controls_both_tracks_and_determinism(self) -> None:
        config = self.config()
        items = [
            {
                "baseline_bytes": 1_000,
                "id": item_id,
                "source_bytes": 10_000,
                "structural_control_bytes": 990,
                "track": track,
            }
            for track, split in config["splits"].items()
            for item_id in split["screen_items"]
        ]

        def trials(candidate_bytes: int) -> list[dict]:
            return [
                {
                    "candidate_bytes": candidate_bytes,
                    "candidate_sha256": hashlib.sha256(item["id"].encode()).hexdigest(),
                    "compression_peak_rss_bytes": 100,
                    "compression_wall_ns": 1_000 + repetition,
                    "decompression_peak_rss_bytes": 50,
                    "decompression_wall_ns": 500 + repetition,
                    "item_id": item["id"],
                    "passed": True,
                    "repetition": repetition,
                }
                for item in items
                for repetition in range(2)
            ]

        admitted = screen.summarize(
            trials=trials(970), items=items, config=config
        )
        self.assertTrue(admitted["axiom_prototype_admitted"])
        self.assertEqual(admitted["selected_variant"], screen.VARIANT)
        self.assertEqual(admitted["axiom_wins"], 0)

        control_failure = screen.summarize(
            trials=trials(985), items=items, config=config
        )
        self.assertFalse(control_failure["axiom_prototype_admitted"])

        nondeterministic = trials(970)
        nondeterministic[1]["candidate_sha256"] = "f" * 64
        rejected = screen.summarize(
            trials=nondeterministic, items=items, config=config
        )
        self.assertFalse(rejected["axiom_prototype_admitted"])
        self.assertIsNone(rejected["selected_variant"])

    def test_frame_roundtrip_and_corruption_rejection(self) -> None:
        payload_bytes = b"kanzi payload bytes"
        source_sha256 = hashlib.sha256(b"source").hexdigest()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "payload.knz"
            frame = root / "candidate.axrq"
            extracted = root / "extracted.knz"
            payload.write_bytes(payload_bytes)
            screen.build_frame(
                frame,
                source_bytes=6,
                source_sha256=source_sha256,
                payload=payload,
            )
            screen.extract_frame(
                frame,
                extracted,
                expected_source_bytes=6,
                expected_source_sha256=source_sha256,
            )
            self.assertEqual(extracted.read_bytes(), payload_bytes)
            corrupted = bytearray(frame.read_bytes())
            corrupted[-1] ^= 1
            frame.write_bytes(corrupted)
            with self.assertRaisesRegex(ValueError, "payload digest differs"):
                screen.extract_frame(
                    frame,
                    extracted,
                    expected_source_bytes=6,
                    expected_source_sha256=source_sha256,
                )
            self.assertFalse(extracted.exists())


if __name__ == "__main__":
    unittest.main()
