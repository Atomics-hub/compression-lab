import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-text-source-bwt-screen.py"
VERIFIER_SCRIPT = REPOSITORY / "scripts" / "verify-text-source-bwt-screen-run.py"
CONFIG = REPOSITORY / "config" / "text-source-bwt-screen-v1.json"
PROTOCOL = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-18-text-source-bwt-screen-protocol.md"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load_module("text_source_bwt_screen", SCRIPT)
VERIFIER = load_module("text_source_bwt_screen_verifier", VERIFIER_SCRIPT)


class TextSourceBwtScreenTests(unittest.TestCase):
    def config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def items(self, config: dict) -> list[dict]:
        return [
            {"id": item_id, "track": track, "source_bytes": 10_000}
            for track, split in config["splits"].items()
            for item_id in split["screen_items"]
        ]

    def baseline(self) -> dict:
        baseline_bytes = {
            "cpython-3.14.6-source": 4_511_714,
            "typescript-6.0.3-source": 1_709_772,
            "enwikibooks-20260701": 12_622_786,
            "enwikinews-20260701": 11_534_002,
        }
        return {
            "summary": {
                "item_codec_rows": [
                    {
                        "codec_id": "kanzi-max",
                        "item_id": item_id,
                        "artifact_bytes": artifact_bytes,
                    }
                    for item_id, artifact_bytes in baseline_bytes.items()
                ]
            }
        }

    def trials(
        self,
        config: dict,
        items: list[dict],
        sizes: dict[tuple[str, str], int],
    ) -> list[dict]:
        rows = []
        for variant in MODULE.VARIANTS:
            for item in items:
                artifact_bytes = sizes[(variant, item["id"])]
                digest = hashlib.sha256(f"{variant}/{item['id']}".encode()).hexdigest()
                for repetition in range(2):
                    rows.append(
                        {
                            "variant": variant,
                            "item_id": item["id"],
                            "repetition": repetition,
                            "artifact_bytes": artifact_bytes,
                            "artifact_sha256": digest,
                            "exact_roundtrip": True,
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
        return rows

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
        self.assertIn("No BWT screen result existed", protocol)
        self.assertIn("32", protocol)
        self.assertIn("complete artifact", protocol)
        self.assertIn("at least 5%", protocol)
        self.assertIn("`axiom_wins` is always\nzero", protocol)

    def test_commands_are_the_exact_four_explicit_single_job_chains(self) -> None:
        config = self.config()
        expected = [
            ("TEXT+UTF+BWT", "TPAQX"),
            ("TEXT+UTF+BWT+SRT+ZRLT", "TPAQX"),
            ("TEXT+UTF+BWT+SRT+ZRLT", "FPAQ"),
            ("BWT+SRT+ZRLT", "TPAQX"),
        ]
        self.assertEqual(
            [(row["transform"], row["entropy"]) for row in config["variants"]],
            expected,
        )
        for variant in config["variants"]:
            compression, decompression = MODULE.commands(
                kanzi=Path("/tool/kanzi"),
                variant=variant,
                source=Path("/data/source"),
                artifact=Path("/work/artifact.knz"),
                restored=Path("/work/restored"),
            )
            self.assertEqual(compression[5], f"--transform={variant['transform']}")
            self.assertEqual(compression[6], f"--entropy={variant['entropy']}")
            self.assertIn("--block=1g", compression)
            self.assertIn("--jobs=1", compression)
            self.assertIn("--jobs=1", decompression)
            self.assertFalse(
                any(
                    argument.startswith(("--level", "--skip", "--checksum"))
                    for argument in compression
                )
            )

    def test_manifest_verification_never_opens_reserved_evaluation_bytes(self) -> None:
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

    def test_tracks_select_independently_using_integer_byte_gates(self) -> None:
        config = self.config()
        items = self.items(config)
        baseline_rows = {
            row["item_id"]: row["artifact_bytes"]
            for row in self.baseline()["summary"]["item_codec_rows"]
        }
        sizes = {
            (variant, item["id"]): baseline_rows[item["id"]]
            for variant in MODULE.VARIANTS
            for item in items
        }
        sizes[(MODULE.VARIANTS[0], "cpython-3.14.6-source")] = 4_420_000
        sizes[(MODULE.VARIANTS[0], "typescript-6.0.3-source")] = 1_670_000
        sizes[(MODULE.VARIANTS[1], "enwikibooks-20260701")] = 12_500_000
        sizes[(MODULE.VARIANTS[1], "enwikinews-20260701")] = 11_410_000
        trials = self.trials(config, items, sizes)
        summary = MODULE.summarize(
            trials=trials,
            items=items,
            baseline=self.baseline(),
            config=config,
        )
        tracks = {row["track"]: row for row in summary["tracks"]}
        source = tracks["source_code_bundles"]
        wiki = tracks["english_wikimedia_wikitext"]
        self.assertEqual(source["selected_variant"], MODULE.VARIANTS[0])
        self.assertTrue(source["selected_strong_signal"])
        self.assertEqual(
            source["decision"], "admit_token_bwt_representation_prototype_for_track"
        )
        self.assertEqual(wiki["selected_variant"], MODULE.VARIANTS[1])
        self.assertFalse(wiki["selected_strong_signal"])
        self.assertEqual(wiki["decision"], "retain_diagnostic_bwt_signal_only_for_track")
        self.assertEqual(summary["shared_signal_variants"], [])
        self.assertEqual(summary["axiom_wins"], 0)

    def test_resource_rejected_ratio_signal_and_nondeterminism_admit_nothing(self) -> None:
        config = self.config()
        items = self.items(config)
        baseline_rows = {
            row["item_id"]: row["artifact_bytes"]
            for row in self.baseline()["summary"]["item_codec_rows"]
        }
        sizes = {
            (variant, item["id"]): baseline_rows[item["id"]]
            for variant in MODULE.VARIANTS
            for item in items
        }
        sizes[(MODULE.VARIANTS[1], "enwikibooks-20260701")] = 12_500_000
        sizes[(MODULE.VARIANTS[1], "enwikinews-20260701")] = 11_410_000
        trials = self.trials(config, items, sizes)
        for row in trials:
            if (
                row["variant"] == MODULE.VARIANTS[1]
                and row["item_id"] == "enwikibooks-20260701"
            ):
                row["compression"]["peak_rss_bytes"] = 4 * 1024**3 + 1
        summary = MODULE.summarize(
            trials=trials,
            items=items,
            baseline=self.baseline(),
            config=config,
        )
        wiki = next(
            row for row in summary["tracks"] if row["track"] == "english_wikimedia_wikitext"
        )
        variant = next(row for row in wiki["variants"] if row["variant"] == MODULE.VARIANTS[1])
        self.assertTrue(variant["ratio_signal"])
        self.assertTrue(variant["resource_rejected_ratio_signal"])
        self.assertFalse(variant["track_signal"])
        self.assertIsNone(wiki["selected_variant"])

        for row in trials:
            if (
                row["variant"] == MODULE.VARIANTS[1]
                and row["item_id"] == "enwikinews-20260701"
                and row["repetition"] == 1
            ):
                row["artifact_sha256"] = "f" * 64
        rejected = MODULE.summarize(
            trials=trials,
            items=items,
            baseline=self.baseline(),
            config=config,
        )
        item_row = next(
            row
            for row in rejected["item_rows"]
            if row["variant"] == MODULE.VARIANTS[1]
            and row["item_id"] == "enwikinews-20260701"
        )
        self.assertFalse(item_row["passed"])

    def test_preflight_verifier_requires_exact_four_variant_roster(self) -> None:
        config = self.config()
        rows = [
            {
                "variant": variant["id"],
                "source_bytes": 364_544,
                "artifact_bytes": 1,
                "artifact_sha256": hashlib.sha256(variant["id"].encode()).hexdigest(),
                "exact_roundtrip": True,
            }
            for variant in config["variants"]
        ]
        VERIFIER.validate_preflight(rows, config)
        with self.assertRaisesRegex(ValueError, "roster differs"):
            VERIFIER.validate_preflight(rows[:-1], config)


if __name__ == "__main__":
    unittest.main()
