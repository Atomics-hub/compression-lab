import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "benchmark-text-source-predictor-ceiling.py"
CONFIG = REPOSITORY / "config" / "text-source-predictor-probe-v1.json"
SPEC = importlib.util.spec_from_file_location("text_source_predictor_ceiling", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load text/source predictor ceiling module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TextSourcePredictorCeilingTests(unittest.TestCase):
    def config(self) -> dict:
        return json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_checked_config_is_canonical_frozen_and_split(self) -> None:
        raw = CONFIG.read_bytes()
        config = json.loads(raw)
        self.assertEqual(raw, MODULE.json_bytes(config))
        MODULE.validate_config(config)
        for split in config["splits"].values():
            self.assertFalse(set(split["training"]) & set(split["evaluation"]))
        self.assertIn("not a decodable artifact", config["claim_ceiling"])

    def test_sample_offsets_are_deterministic_nonoverlapping_and_bounded(self) -> None:
        offsets = MODULE.sample_offsets(1000, 100, 5)
        self.assertEqual(offsets, [0, 225, 450, 675, 900])
        self.assertEqual(MODULE.sample_offsets(99, 100, 12), [0])
        dense = MODULE.sample_offsets(250, 100, 12)
        self.assertEqual(dense, [0, 150])
        self.assertTrue(
            all(right - left >= 100 for left, right in zip(dense, dense[1:]))
        )

    def test_dictionary_is_deterministic_bounded_and_counts_priors(self) -> None:
        config = self.config()
        data = (
            b"alpha identifier alpha identifier beta identifier\n" * 4096
            + b"raw bytes 1234\n"
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "training.bin"
            path.write_bytes(data)
            first = MODULE.train_dictionary(
                config=config, track="source_code_bundles", paths=[path]
            )
            second = MODULE.train_dictionary(
                config=config, track="source_code_bundles", paths=[path]
            )
        self.assertEqual(first, second)
        tokens, raw_weights, token_weights, payload, metadata = first
        self.assertIn(b"identifier", tokens)
        self.assertEqual(len(raw_weights), 256)
        self.assertEqual(len(token_weights), len(tokens))
        self.assertTrue(all(weight > 0 for weight in raw_weights + token_weights))
        self.assertLessEqual(
            len(payload), config["dictionary_policy"]["maximum_serialized_bytes"]
        )
        self.assertEqual(payload[:5], MODULE.MAGIC)
        self.assertEqual(metadata["training_sample_bytes"], len(data))

    def test_wikimedia_dictionary_always_contains_fixed_markup(self) -> None:
        config = self.config()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "training.bin"
            path.write_bytes(b"plain words only " * 1024)
            tokens, _raw, _weights, _payload, _metadata = MODULE.train_dictionary(
                config=config,
                track="english_wikimedia_wikitext",
                paths=[path],
            )
        fixed = set(MODULE.fixed_markup(config, "english_wikimedia_wikitext"))
        self.assertTrue(fixed.issubset(tokens))

    def test_mixed_symbol_stream_reconstructs_every_input_byte(self) -> None:
        data = b"alpha += beta\nalpha"
        tokens = [b"alpha", b"beta"]
        symbols = list(
            MODULE.mixed_symbols(
                "source_code_bundles",
                data,
                {token: index for index, token in enumerate(tokens)},
                [],
            )
        )
        restored = bytearray()
        for symbol, _class_id in symbols:
            if symbol < 256:
                restored.append(symbol)
            else:
                restored.extend(tokens[symbol - 256])
        self.assertEqual(bytes(restored), data)

    def test_trained_token_model_has_finite_attributable_estimate(self) -> None:
        data = b"alpha beta alpha beta alpha beta\n" * 4096
        tokens = [b"alpha", b"beta"]
        raw_weights = [1] * 256
        token_weights = [100, 100]
        p0, p1 = MODULE.estimate_raw("source_code_bundles", data)
        p2 = MODULE.estimate_mixed(
            track="source_code_bundles",
            data=data,
            tokens=tokens,
            raw_weights=raw_weights,
            token_weights=token_weights,
            markup_tokens=[],
        )
        self.assertTrue(all(math.isfinite(value) and value > 0 for value in (p0, p1, p2)))
        self.assertLess(p2, p1)

    def test_projection_charges_dictionary_to_each_item(self) -> None:
        row = MODULE.project_variant(
            variant=MODULE.VARIANTS[2],
            source_bytes=1_000_000,
            sample_bpbs=[1.0, 1.0, 1.0],
            dictionary_bytes=1234,
            startup_bytes=100,
        )
        self.assertEqual(row["projected_core_bytes"], 125100)
        self.assertEqual(row["projected_complete_item_bytes"], 126334)
        self.assertEqual(row["conservative_bits_per_byte"], 1.0)

    def test_invalid_dictionary_weight_rosters_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dictionary identity"):
            MODULE.serialize_dictionary(
                1, [b"token"], raw_weights=[1] * 255, token_weights=[1]
            )
        with self.assertRaisesRegex(ValueError, "prior roster"):
            MODULE.estimate_mixed(
                track="source_code_bundles",
                data=b"token",
                tokens=[b"token"],
                raw_weights=[1] * 256,
                token_weights=[],
                markup_tokens=[],
            )

    def test_calculation_rejects_an_invalid_repository_binding_first(self) -> None:
        with self.assertRaisesRegex(ValueError, "repository commit"):
            MODULE.calculate(
                config_path=CONFIG,
                corpus=REPOSITORY / "corpora" / "text-source-development-v1",
                baseline_path=REPOSITORY
                / "runs"
                / "text-source-development-baseline-census-v1"
                / "results.json",
                commit="not-a-commit",
            )


if __name__ == "__main__":
    unittest.main()
