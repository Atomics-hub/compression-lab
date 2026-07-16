"""Validation for controlling public-release benchmark artifacts."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Optional, Sequence


EXPECTED_CODECS = (
    "adaptive-v3",
    "gzip-9",
    "zstd-3",
    "zstd-9",
    "brotli-6",
    "brotli-11",
    "lzma-9",
    "7zip-9",
)
MINIMUM_REPETITIONS = 7
MINIMUM_CORPUS_ITEMS = 8
MINIMUM_CORPUS_CATEGORIES = 5
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def verify_release_evidence(
    payload: dict[str, Any], *, expected_commit: Optional[str] = None
) -> str:
    """Reject incomplete, untraceable, or incorrect release benchmark results."""

    if payload.get("schema_version") != 4:
        raise ValueError("release benchmark must use results schema version 4")

    config = payload.get("config")
    if not isinstance(config, dict):
        raise ValueError("release benchmark config is missing")
    repetitions = config.get("repetitions")
    if not isinstance(repetitions, int) or repetitions < MINIMUM_REPETITIONS:
        raise ValueError(
            f"release benchmark requires at least {MINIMUM_REPETITIONS} repetitions"
        )
    if config.get("warmups", 0) < 1:
        raise ValueError("release benchmark requires at least one warmup")
    if config.get("splits") != ["validation"]:
        raise ValueError("release benchmark must use only the public validation split")
    if config.get("execution_mode") != "persistent-worker":
        raise ValueError("release benchmark must use persistent workers")

    codec_rows = payload.get("codecs")
    if not isinstance(codec_rows, list):
        raise ValueError("release benchmark codec provenance is missing")
    codec_ids = tuple(row.get("id") for row in codec_rows if isinstance(row, dict))
    if codec_ids != EXPECTED_CODECS:
        raise ValueError(
            "release benchmark codec set or order differs from the frozen protocol"
        )
    for row in codec_rows:
        if not row.get("available"):
            raise ValueError(f"release benchmark codec is unavailable: {row.get('id')}")
        if row.get("implementation", "").startswith("external-") and not row.get(
            "version"
        ):
            raise ValueError(f"external codec version is missing: {row.get('id')}")

    corpus = payload.get("corpus")
    if not isinstance(corpus, list) or len(corpus) < MINIMUM_CORPUS_ITEMS:
        raise ValueError(
            f"release corpus requires at least {MINIMUM_CORPUS_ITEMS} items"
        )
    categories = set()
    item_ids = set()
    for row in corpus:
        if not isinstance(row, dict):
            raise ValueError("release corpus contains invalid metadata")
        item_id = row.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in item_ids:
            raise ValueError("release corpus item identifiers must be unique")
        item_ids.add(item_id)
        category = row.get("category")
        if not isinstance(category, str) or not category:
            raise ValueError(f"corpus category is missing: {item_id}")
        categories.add(category)
        if row.get("split") != "validation":
            raise ValueError(f"non-validation corpus item found: {item_id}")
        if not row.get("license_spdx"):
            raise ValueError(f"corpus license is missing: {item_id}")
        if not str(row.get("source_url", "")).startswith("https://"):
            raise ValueError(f"corpus source URL is invalid: {item_id}")
        if not _SHA256.fullmatch(str(row.get("sha256", ""))):
            raise ValueError(f"corpus SHA-256 is invalid: {item_id}")
    if len(categories) < MINIMUM_CORPUS_CATEGORIES:
        raise ValueError(
            f"release corpus requires at least {MINIMUM_CORPUS_CATEGORIES} categories"
        )

    failures = payload.get("failures")
    if failures != []:
        raise ValueError("release benchmark contains round-trip failures")

    git = payload.get("system", {}).get("git", {})
    commit = git.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("release benchmark commit provenance is invalid")
    if git.get("dirty") is not False:
        raise ValueError("release benchmark was not run from a clean worktree")
    if expected_commit is not None and commit != expected_commit:
        raise ValueError(
            f"release benchmark commit mismatch: expected {expected_commit}, got {commit}"
        )

    pair_counts: Counter[tuple[str, str]] = Counter()
    for trial in payload.get("trials", []):
        if not isinstance(trial, dict):
            raise ValueError("release benchmark contains an invalid trial")
        item_id = trial.get("item_id")
        codec_id = trial.get("codec_id")
        if not isinstance(item_id, str) or not isinstance(codec_id, str):
            raise ValueError("release benchmark trial identity is invalid")
        if not trial.get("roundtrip_ok"):
            raise ValueError("release benchmark contains an unsuccessful trial")
        if trial.get("source_sha256") != trial.get("restored_sha256"):
            raise ValueError("release benchmark trial restored the wrong bytes")
        pair_counts[(item_id, codec_id)] += 1
    expected_pairs = {
        (item_id, codec_id) for item_id in item_ids for codec_id in EXPECTED_CODECS
    }
    if set(pair_counts) != expected_pairs:
        raise ValueError("release benchmark trial matrix is incomplete or contains extras")
    if any(count != repetitions for count in pair_counts.values()):
        raise ValueError("release benchmark trial repetitions are incomplete")

    summaries = payload.get("summary")
    if not isinstance(summaries, list) or len(summaries) != len(EXPECTED_CODECS):
        raise ValueError("release benchmark aggregate summary is incomplete")
    summary_by_codec = {row.get("codec_id"): row for row in summaries}
    if set(summary_by_codec) != set(EXPECTED_CODECS):
        raise ValueError("release benchmark summary codec set is incorrect")
    for codec_id, row in summary_by_codec.items():
        if row.get("items") != len(corpus) or row.get("roundtrip_failures") != 0:
            raise ValueError(f"release benchmark summary is incomplete: {codec_id}")
        if row.get("original_bytes", 0) <= 0 or row.get("compressed_bytes", 0) <= 0:
            raise ValueError(f"release benchmark summary sizes are invalid: {codec_id}")

    return (
        f"verified {len(corpus)} public items across {len(EXPECTED_CODECS)} codecs, "
        f"{repetitions} repetitions, commit {commit}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a controlling Compression Lab release benchmark"
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-commit")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(args.results.read_text(encoding="utf-8"))
    print(
        verify_release_evidence(payload, expected_commit=args.expected_commit),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
