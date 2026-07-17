import copy
import unittest

from compresslab.release_evidence import EXPECTED_CODECS, verify_release_evidence


COMMIT = "a" * 40


def valid_payload():
    corpus = [
        {
            "id": f"item-{index}",
            "category": f"category-{index % 5}",
            "split": "validation",
            "license_spdx": "MIT",
            "source_url": f"https://example.com/item-{index}",
            "sha256": f"{index:064x}",
        }
        for index in range(8)
    ]
    codecs = [
        {
            "id": codec_id,
            "available": True,
            "implementation": (
                "adaptive-v3"
                if codec_id == "adaptive-v3"
                else (
                    codec_id.split("-")[0]
                    if codec_id in {"gzip-9", "lzma-9"}
                    else f"external-{codec_id.rsplit('-', 1)[0]}"
                )
            ),
            "version": "test-version",
        }
        for codec_id in EXPECTED_CODECS
    ]
    trials = []
    for repetition in range(1, 8):
        for item in corpus:
            for codec_id in EXPECTED_CODECS:
                trials.append(
                    {
                        "item_id": item["id"],
                        "codec_id": codec_id,
                        "roundtrip_ok": True,
                        "source_sha256": item["sha256"],
                        "restored_sha256": item["sha256"],
                        "repetition": repetition,
                    }
                )
    return {
        "schema_version": 5,
        "config": {
            "runner": {
                "api_version": 2,
                "source_sha256": "b" * 64,
                "legacy_runner_source_sha256": "e" * 64,
                "corpus_loader_source_sha256": "c" * 64,
            },
            "corpus_manifest": {
                "path": "/corpora/public-validation/scoring-manifest.json",
                "sha256": "d" * 64,
                "selected_item_count": len(corpus),
                "selected_item_ids": [row["id"] for row in corpus],
            },
            "repetitions": 7,
            "warmups": 1,
            "splits": ["validation"],
            "execution_mode": "persistent-worker",
        },
        "codecs": codecs,
        "corpus": corpus,
        "failures": [],
        "system": {"git": {"commit": COMMIT, "dirty": False}},
        "trials": trials,
        "summary": [
            {
                "codec_id": codec_id,
                "items": len(corpus),
                "roundtrip_failures": 0,
                "original_bytes": 8_000,
                "compressed_bytes": 4_000,
            }
            for codec_id in EXPECTED_CODECS
        ],
    }


class ReleaseEvidenceTests(unittest.TestCase):
    def test_complete_release_evidence_is_accepted(self):
        message = verify_release_evidence(valid_payload(), expected_commit=COMMIT)
        self.assertIn("verified 8 public items", message)

    def test_missing_trial_is_rejected(self):
        payload = valid_payload()
        payload["trials"].pop()
        with self.assertRaisesRegex(ValueError, "repetitions are incomplete"):
            verify_release_evidence(payload)

    def test_wrong_commit_and_roundtrip_failure_are_rejected(self):
        payload = valid_payload()
        with self.assertRaisesRegex(ValueError, "commit mismatch"):
            verify_release_evidence(payload, expected_commit="b" * 40)

        payload = copy.deepcopy(payload)
        payload["trials"][0]["roundtrip_ok"] = False
        with self.assertRaisesRegex(ValueError, "unsuccessful trial"):
            verify_release_evidence(payload)

    def test_manifest_identity_must_match_result_corpus(self):
        payload = valid_payload()
        payload["config"]["corpus_manifest"]["selected_item_ids"].pop()
        with self.assertRaisesRegex(ValueError, "item identities differ"):
            verify_release_evidence(payload)


if __name__ == "__main__":
    unittest.main()
