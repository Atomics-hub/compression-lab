import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-text-source-wk-c1-screen.py"
VERIFIER_SCRIPT = REPOSITORY / "scripts" / "verify-text-source-wk-c1-screen-run.py"
CONFIG = REPOSITORY / "config" / "text-source-wk-c1-screen-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-18-text-source-wk-c1-protocol.md"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


MODULE = load_module("text_source_wk_c1_screen", SCRIPT)
VERIFIER = load_module("text_source_wk_c1_screen_verifier", VERIFIER_SCRIPT)


class TextSourceWkC1ScreenTests(unittest.TestCase):
    def config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def trials(self, full: tuple[int, int], structure: tuple[int, int]) -> list[dict]:
        sizes = {
            MODULE.VARIANTS[0]: dict(zip(MODULE.SCREEN_ITEMS, full)),
            MODULE.VARIANTS[1]: dict(zip(MODULE.SCREEN_ITEMS, structure)),
        }
        rows = []
        for variant in MODULE.VARIANTS:
            for item_id in MODULE.SCREEN_ITEMS:
                for repetition in range(2):
                    rows.append(
                        {
                            "variant": variant,
                            "item_id": item_id,
                            "repetition": repetition,
                            "artifact_bytes": sizes[variant][item_id],
                            "artifact_sha256": hashlib.sha256(
                                f"{variant}/{item_id}".encode()
                            ).hexdigest(),
                            "exact_roundtrip": True,
                            "passed": True,
                            "encode_peak_rss_bytes": 100,
                            "decode_peak_rss_bytes": 200,
                        }
                    )
        return rows

    def test_protocol_and_config_are_frozen_before_measurement(self) -> None:
        raw = CONFIG.read_bytes()
        config = json.loads(raw)
        self.assertEqual(raw, MODULE.json_bytes(config))
        MODULE.validate_config(config)
        self.assertEqual(len(MODULE.schedule(config)), 8)
        self.assertEqual(len(set(MODULE.schedule(config))), 8)
        splits = config["splits"]
        self.assertFalse(
            set(splits["screen_items"])
            & set(splits["reserved_evaluation_not_accessed"])
        )
        protocol = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("No WK-C1 corpus measurement or result", protocol)
        self.assertIn("not an ideal-bits estimate", protocol)
        self.assertIn("full * 10000 <= structure-only * 9950", protocol)
        self.assertIn("22,948,948", protocol)
        self.assertIn("`axiom_wins` remains zero", protocol)

    def test_manifest_verifier_never_opens_reserved_or_out_of_scope_paths(self) -> None:
        config = self.config()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            rows = []
            for item_id in config["splits"]["screen_items"]:
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
            for key in (
                "out_of_scope_training_not_accessed",
                "reserved_evaluation_not_accessed",
            ):
                for item_id in config["splits"][key]:
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
                "items": rows,
                "public_validation_accessed": False,
            }
            (root / "manifest.json").write_bytes(MODULE.json_bytes(manifest))
            _raw, items = MODULE.verify_screen_items(root, config)
            self.assertEqual([row["id"] for row in items], list(MODULE.SCREEN_ITEMS))

    def test_commands_are_exact_transform_kanzi_wrap_inverse_chain(self) -> None:
        encode, decode = MODULE.commands(
            python="python",
            runner=Path("/repo/runner.py"),
            transform=Path("/repo/transform.py"),
            kanzi=Path("/tool/kanzi"),
            variant=MODULE.VARIANTS[0],
            source=Path("/data/source"),
            transformed=Path("/work/transformed"),
            payload=Path("/work/payload"),
            artifact=Path("/work/artifact"),
            extracted=Path("/work/extracted"),
            decoded_transform=Path("/work/decoded"),
            restored=Path("/work/restored"),
            source_bytes=123,
            source_sha256="a" * 64,
        )
        self.assertEqual(len(encode), 3)
        self.assertEqual(len(decode), 3)
        self.assertIn("encode", encode[0])
        self.assertIn("--level=9", encode[1])
        self.assertIn("--block=1g", encode[1])
        self.assertIn("--jobs=1", encode[1])
        self.assertIn("wrap", encode[2])
        self.assertIn("unwrap", decode[0])
        self.assertIn("--decompress", decode[1])
        self.assertIn("decode", decode[2])

    def test_complete_axwk2_frame_counts_and_authenticates_backend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            payload = root / "payload"
            artifact = root / "artifact"
            restored_payload = root / "restored-payload"
            source.write_bytes(b"source {{T|x=y}}")
            payload.write_bytes(b"complete pinned backend payload")
            MODULE.wrap_payload(MODULE.VARIANTS[0], source, payload, artifact)
            self.assertEqual(
                artifact.stat().st_size,
                MODULE.FRAME_HEADER.size + payload.stat().st_size,
            )
            MODULE.unwrap_payload(
                MODULE.VARIANTS[0],
                artifact,
                restored_payload,
                source_bytes=source.stat().st_size,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(restored_payload.read_bytes(), payload.read_bytes())
            corrupted = bytearray(artifact.read_bytes())
            corrupted[-1] ^= 1
            artifact.write_bytes(corrupted)
            with self.assertRaisesRegex(ValueError, "payload digest differs"):
                MODULE.unwrap_payload(
                    MODULE.VARIANTS[0],
                    artifact,
                    restored_payload,
                    source_bytes=source.stat().st_size,
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )
            self.assertFalse(restored_payload.exists())

    def test_integer_gates_require_ts_h1_attribution_and_strong_for_admission(self) -> None:
        config = self.config()
        strong = MODULE.summarize(
            self.trials(
                full=(12_300_000, 11_300_000),
                structure=(12_400_000, 11_400_000),
            ),
            config,
        )
        self.assertTrue(strong["full_signal"])
        self.assertTrue(strong["full_strong_signal"])
        self.assertTrue(strong["full_beats_structure_only_by_half_percent"])
        self.assertEqual(
            strong["decision"], "admit_separately_frozen_wk_c1_codec_prototype"
        )
        self.assertEqual(strong["axiom_wins"], 0)

        diagnostic = MODULE.summarize(
            self.trials(
                full=(12_450_000, 11_460_000),
                structure=(12_550_000, 11_500_000),
            ),
            config,
        )
        self.assertTrue(diagnostic["full_signal"])
        self.assertFalse(diagnostic["full_strong_signal"])
        self.assertEqual(diagnostic["decision"], "retain_wk_c1_diagnostic_signal_only")

        unattributed = MODULE.summarize(
            self.trials(
                full=(12_450_000, 11_460_000),
                structure=(12_455_000, 11_465_000),
            ),
            config,
        )
        self.assertFalse(unattributed["full_beats_structure_only_by_half_percent"])
        self.assertFalse(unattributed["full_signal"])
        self.assertEqual(
            unattributed["decision"], "reject_wk_c1_recursive_template_columnarization"
        )

    def test_synthetic_preflight_and_verifier_shape(self) -> None:
        rows = MODULE.preflight()
        VERIFIER.validate_preflight(rows)
        self.assertEqual([row["variant"] for row in rows], list(MODULE.VARIANTS))
        self.assertTrue(all(row["exact_roundtrip"] for row in rows))
        with self.assertRaisesRegex(ValueError, "roster differs"):
            VERIFIER.validate_preflight(rows[:-1])


if __name__ == "__main__":
    unittest.main()
