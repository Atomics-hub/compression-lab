import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


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

    def test_real_executor_launches_both_three_process_chains_and_binds_physical_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.axwkt"
            source.write_bytes(b"prefix {{T|a=one|nested={{U|x=y}}}} suffix")
            fake_kanzi = root / "fake-kanzi"
            fake_kanzi.write_text(
                "#!/usr/bin/env python3\n"
                "import shutil, sys\n"
                "source = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--input='))\n"
                "destination = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--output='))\n"
                "shutil.copyfile(source, destination)\n",
                encoding="utf-8",
            )
            os.chmod(fake_kanzi, 0o755)
            item = {
                "id": MODULE.SCREEN_ITEMS[0],
                "track": "english_wikimedia_wikitext",
                "path": str(source),
                "source_bytes": source.stat().st_size,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            bindings = {"fixture": "a" * 64}
            receipt = MODULE.run_trial(
                output=root / "run",
                bindings=bindings,
                item=item,
                variant=MODULE.VARIANTS[0],
                repetition=0,
                transform=MODULE.DEFAULT_TRANSFORM,
                kanzi=fake_kanzi,
                timeout_seconds=30,
            )
            self.assertTrue(receipt["passed"])
            self.assertEqual(len(receipt["encode_processes"]), 3)
            self.assertEqual(len(receipt["decode_processes"]), 3)
            self.assertEqual(
                receipt["encode_totals"]["peak_rss_bytes"],
                max(row["peak_rss_bytes"] for row in receipt["encode_processes"]),
            )
            self.assertEqual(
                receipt["decode_totals"]["peak_rss_bytes"],
                max(row["peak_rss_bytes"] for row in receipt["decode_processes"]),
            )
            self.assertEqual(
                receipt["artifact_bytes"],
                receipt["artifact_file_evidence"]["size_bytes"],
            )
            self.assertEqual(
                receipt["artifact_sha256"],
                receipt["artifact_file_evidence"]["sha256"],
            )
            MODULE.validate_trial_receipt(
                receipt,
                bindings=bindings,
                variant=MODULE.VARIANTS[0],
                item=item,
                repetition=0,
            )
            VERIFIER.validate_receipt(
                receipt,
                bindings=bindings,
                variant=MODULE.VARIANTS[0],
                item_id=item["id"],
                repetition=0,
            )
            tampered = copy.deepcopy(receipt)
            tampered["encode_totals"]["peak_rss_bytes"] += 1
            with self.assertRaisesRegex(ValueError, "aggregate encode metrics"):
                MODULE.validate_trial_receipt(
                    tampered,
                    bindings=bindings,
                    variant=MODULE.VARIANTS[0],
                    item=item,
                    repetition=0,
                )
            tampered = copy.deepcopy(receipt)
            tampered["artifact_bytes"] += 1
            with self.assertRaisesRegex(ValueError, "successful retained trial"):
                VERIFIER.validate_receipt(
                    tampered,
                    bindings=bindings,
                    variant=MODULE.VARIANTS[0],
                    item_id=item["id"],
                    repetition=0,
                )

    def test_resource_smoke_is_authorized_only_and_fails_closed_above_four_gib(self) -> None:
        config = self.config()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            items = []
            for item_id in MODULE.SCREEN_ITEMS:
                path = root / item_id
                path.write_bytes(b"{{T|a=one|nested={{U|x=y}}}}")
                items.append(
                    {
                        "id": item_id,
                        "path": str(path),
                        "source_bytes": path.stat().st_size,
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
            rows = MODULE.resource_smoke(
                items=items,
                config=config,
                transform=MODULE.DEFAULT_TRANSFORM,
            )
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row["passed"] for row in rows))
            VERIFIER.validate_resource_smoke(rows, config)

            oversized = {
                "command": ["python"],
                "returncode": 0,
                "timed_out": False,
                "wall_ns": 1,
                "cpu_ns": 1,
                "peak_rss_bytes": 4 * 1024**3 + 1,
                "stdout": "",
                "stderr": "",
            }
            with mock.patch.object(MODULE, "run_process", return_value=oversized):
                with self.assertRaisesRegex(ValueError, "exceeded 4 GiB"):
                    MODULE.resource_smoke(
                        items=items,
                        config=config,
                        transform=MODULE.DEFAULT_TRANSFORM,
                    )

    def test_census_provenance_reconstructs_controls_and_rejects_rebound_edit(self) -> None:
        config = self.config()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            def write_json(name: str, value: dict) -> Path:
                path = root / name
                path.write_bytes(MODULE.json_bytes(value))
                return path

            baseline_result = {
                "completed": True,
                "all_required_completed": True,
                "summary": {
                    "item_codec_rows": [
                        {
                            "codec_id": "kanzi-max",
                            "item_id": "enwikibooks-20260701",
                            "artifact_bytes": 12622786,
                            "passed": True,
                            "exact_roundtrip": True,
                            "deterministic_artifact": True,
                        },
                        {
                            "codec_id": "kanzi-max",
                            "item_id": "enwikinews-20260701",
                            "artifact_bytes": 11534002,
                            "passed": True,
                            "exact_roundtrip": True,
                            "deterministic_artifact": True,
                        },
                    ]
                },
            }
            baseline = write_json("baseline.json", baseline_result)
            baseline_evidence = write_json(
                "baseline-evidence.json",
                {
                    "raw_results_sha256": MODULE.sha256_file(baseline),
                    "results": baseline_result,
                },
            )
            structural_result = write_json("structural.json", {})
            structural_evidence = write_json(
                "structural-evidence.json",
                {
                    "structural_results_sha256": MODULE.sha256_file(structural_result),
                    "results": {
                        "summary": {
                            "item_rows": [
                                {
                                    "variant": "ts-h1-demux",
                                    "item_id": item_id,
                                    "candidate_bytes": size,
                                }
                                for item_id, size in config["ts_h1_controls"].items()
                            ]
                        }
                    },
                },
            )
            successor = write_json(
                "successor.json",
                {
                    "name": "text-source-structural-successor-decision-v1",
                    "decisions": [{"axiom_win": False}, {"axiom_win": False}],
                },
            )
            routing = write_json("routing.json", {})
            bwt_result = write_json("bwt.json", {})
            bwt_evidence = write_json(
                "bwt-evidence.json",
                {
                    "result_sha256": MODULE.sha256_file(bwt_result),
                    "results": {
                        "summary": {
                            "axiom_wins": 0,
                            "tracks": [
                                {"decision": "reject_raw_bwt_direction_for_track"},
                                {"decision": "reject_raw_bwt_direction_for_track"},
                            ],
                        }
                    },
                },
            )
            bwt_receipt = write_json("bwt-receipt.json", {})
            kanzi = root / "kanzi"
            kanzi.write_bytes(b"pinned binary fixture")
            paths = {
                "baseline_results_sha256": baseline,
                "baseline_public_evidence_sha256": baseline_evidence,
                "kanzi_binary_sha256": kanzi,
                "structural_results_sha256": structural_result,
                "structural_public_evidence_sha256": structural_evidence,
                "successor_decision_sha256": successor,
                "successor_routing_config_sha256": routing,
                "bwt_result_sha256": bwt_result,
                "bwt_public_evidence_sha256": bwt_evidence,
                "bwt_publication_receipt_sha256": bwt_receipt,
            }
            fixture_config = copy.deepcopy(config)
            fixture_config["bindings"].update(
                {key: MODULE.sha256_file(path) for key, path in paths.items()}
            )
            arguments = {
                "config": fixture_config,
                "baseline": baseline,
                "baseline_evidence": baseline_evidence,
                "kanzi": kanzi,
                "structural_result": structural_result,
                "structural_evidence": structural_evidence,
                "successor_decision": successor,
                "successor_routing": routing,
                "bwt_result": bwt_result,
                "bwt_evidence": bwt_evidence,
                "bwt_receipt": bwt_receipt,
            }
            MODULE.verify_dependencies(**arguments)
            edited_gate = copy.deepcopy(fixture_config)
            edited_gate["decision"]["track_gate"]["item_maximum_complete_bytes"][
                "enwikibooks-20260701"
            ] += 1
            with self.assertRaisesRegex(ValueError, "Kanzi-max control"):
                MODULE.verify_dependencies(**{**arguments, "config": edited_gate})
            edited = json.loads(baseline_evidence.read_bytes())
            edited["results"]["summary"]["item_codec_rows"][0]["artifact_bytes"] += 1
            baseline_evidence.write_bytes(MODULE.json_bytes(edited))
            fixture_config["bindings"]["baseline_public_evidence_sha256"] = (
                MODULE.sha256_file(baseline_evidence)
            )
            with self.assertRaisesRegex(ValueError, "raw census|Kanzi-max control"):
                MODULE.verify_dependencies(**arguments)


if __name__ == "__main__":
    unittest.main()
