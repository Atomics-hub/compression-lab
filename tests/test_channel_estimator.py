import importlib.util
from pathlib import Path
import unittest

from compresslab.native import (
    structured_text_encode,
    structured_text_split_channels,
)
from compresslab.structured_text import DICTIONARY_SAMPLE_BYTES, _dictionary_limit


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train-token-channel-estimator.py"
SPEC = importlib.util.spec_from_file_location("token_channel_estimator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ESTIMATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ESTIMATOR)

SAMPLED_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "train-sampled-channel-probe.py"
)
SAMPLED_SPEC = importlib.util.spec_from_file_location(
    "sampled_channel_probe", SAMPLED_SCRIPT
)
assert SAMPLED_SPEC is not None and SAMPLED_SPEC.loader is not None
SAMPLED = importlib.util.module_from_spec(SAMPLED_SPEC)
SAMPLED_SPEC.loader.exec_module(SAMPLED)


def row(side_density, top1_share, wins, savings=0, false_positive_cost=1000.0):
    features = {feature: 0.0 for feature in ESTIMATOR.FEATURES}
    features["side_density"] = side_density
    features["top1_share"] = top1_share
    return {
        "features": features,
        "channel_wins": wins,
        "available_savings_bytes": savings,
        "false_positive_cost_bytes": false_positive_cost,
        "interleaved_bytes": 10_000,
    }


class ChannelEstimatorResearchTests(unittest.TestCase):
    def test_bounded_fit_separates_simple_winner(self):
        rows = [
            row(0.8, 0.8, True, savings=500),
            row(0.1, 0.1, False),
            row(0.2, 0.1, False),
        ]
        model = ESTIMATOR.fit(rows)
        decisions = [ESTIMATOR.predicts(model, item) for item in rows]
        self.assertEqual(decisions, [True, False, False])
        measured = ESTIMATOR.metrics(rows, decisions)
        self.assertEqual(measured["captured_savings_bytes"], 500)
        self.assertEqual(measured["avoided_losing_attempts"], 2)

    def test_channel_features_are_bounded_and_deterministic(self):
        source = (
            b'{"shared_identifier":"alpha","other_identifier":"beta"}\n'
            * 200
        )
        transformed = structured_text_encode(
            source,
            _dictionary_limit(source),
            DICTIONARY_SAMPLE_BYTES,
        )
        first = ESTIMATOR.channel_features(transformed)
        second = ESTIMATOR.channel_features(transformed)
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(ESTIMATOR.FEATURES))
        for value in first.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_representative_sample_is_bounded_valid_and_deterministic(self):
        source = (
            b'{"shared_identifier":"alpha","other_identifier":"beta"}\n'
            * 5_000
        )
        transformed = structured_text_encode(
            source,
            _dictionary_limit(source),
            DICTIONARY_SAMPLE_BYTES,
        )
        budget = 24 * 1024
        first = SAMPLED.sampled_transform(transformed, budget)
        second = SAMPLED.sampled_transform(transformed, budget)
        dictionary_end = SAMPLED.dictionary_end(transformed)
        self.assertEqual(first, second)
        self.assertEqual(first[:dictionary_end], transformed[:dictionary_end])
        self.assertLessEqual(len(first) - dictionary_end, budget)
        skeleton, side = structured_text_split_channels(first)
        self.assertGreater(len(skeleton), 0)
        self.assertGreater(len(side), 0)


if __name__ == "__main__":
    unittest.main()
