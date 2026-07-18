#!/usr/bin/env python3
"""Run the frozen sampled TS-P1/WK-P1 predictor entropy-ceiling probe."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time
from typing import Any, Iterator


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-predictor-probe-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-v1.json"
)
TRACK_ORDER = ["source_code_bundles", "english_wikimedia_wikitext"]
VARIANTS = [
    "p0-adaptive-byte-unigram",
    "p1-adaptive-byte-previous-class",
    "p2-adaptive-mixed-token-previous-class",
]
SOURCE_TOKEN = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,63}")
WIKI_WORD = re.compile(rb"[A-Za-z][A-Za-z0-9_'\-]{2,63}")
PUNCTUATION = frozenset(range(33, 48)) | frozenset(range(58, 65)) | frozenset(
    range(91, 97)
) | frozenset(range(123, 127))
MAGIC = b"AXPD1"
HALF = 0.5


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return value


def write_immutable(path: Path, payload: dict[str, Any]) -> Path:
    encoded = json_bytes(payload)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != encoded:
            raise ValueError(f"refusing to replace differing predictor result: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return path


def put_varint(output: bytearray, value: int) -> None:
    if value < 0:
        raise ValueError("predictor varint is negative")
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)


def varint_size(value: int) -> int:
    output = bytearray()
    put_varint(output, value)
    return len(output)


def sample_offsets(size: int, chunk_size: int, maximum_chunks: int) -> list[int]:
    if size <= 0 or chunk_size <= 0 or maximum_chunks <= 0:
        raise ValueError("sample dimensions must be positive")
    if size <= chunk_size:
        return [0]
    count = min(maximum_chunks, size // chunk_size)
    if count <= 1:
        return [0]
    span = size - chunk_size
    offsets = [(index * span) // (count - 1) for index in range(count)]
    if any(
        right - left < chunk_size for left, right in zip(offsets, offsets[1:])
    ):
        raise ValueError("sample offset policy produced overlapping chunks")
    return offsets


def read_chunks(path: Path, offsets: list[int], chunk_size: int) -> Iterator[bytes]:
    with path.open("rb") as source:
        size = path.stat().st_size
        for offset in offsets:
            source.seek(offset)
            chunk = source.read(min(chunk_size, size - offset))
            if not chunk:
                raise ValueError(f"sample chunk is empty: {path}")
            yield chunk


def token_matches(track: str, data: bytes) -> Iterator[bytes]:
    pattern = SOURCE_TOKEN if track == "source_code_bundles" else WIKI_WORD
    for match in pattern.finditer(data):
        yield match.group(0)


def fixed_markup(config: dict[str, Any], track: str) -> list[bytes]:
    if track != "english_wikimedia_wikitext":
        return []
    return [
        value.encode("ascii")
        for value in config["tokenization"][track]["fixed_markup_tokens"]
    ]


def train_dictionary(
    *,
    config: dict[str, Any],
    track: str,
    paths: list[Path],
) -> tuple[list[bytes], list[int], list[int], bytes, dict[str, int]]:
    sampling = config["sampling"]
    policy = config["dictionary_policy"]
    counts: Counter[bytes] = Counter()
    byte_counts = [0] * 256
    sampled_bytes = 0
    for path in paths:
        offsets = sample_offsets(
            path.stat().st_size,
            sampling["training_chunk_bytes"],
            sampling["training_maximum_chunks_per_item"],
        )
        for chunk in read_chunks(path, offsets, sampling["training_chunk_bytes"]):
            sampled_bytes += len(chunk)
            for value, count in Counter(chunk).items():
                byte_counts[value] += count
            counts.update(token_matches(track, chunk))

    forced = fixed_markup(config, track)
    forced_set = set(forced)
    candidates: list[tuple[bool, int, int, bytes, int]] = []
    for token, count in counts.items():
        if not policy["minimum_token_bytes"] <= len(token) <= policy["maximum_token_bytes"]:
            continue
        if count < policy["minimum_occurrences"] and token not in forced_set:
            continue
        serialized_cost = len(token) + varint_size(len(token))
        savings = count * max(0, len(token) - 2) - serialized_cost
        if savings > 0 or token in forced_set:
            candidates.append(
                (token in forced_set, savings, count, token, 1 + math.isqrt(count))
            )
    for token in forced:
        if token not in counts:
            candidates.append((True, 0, 0, token, 1))
    candidates.sort(key=lambda row: (-int(row[0]), -row[1], -row[2], row[3]))

    raw_weights = [1 + math.isqrt(count) for count in byte_counts]
    tokens: list[bytes] = []
    token_weights: list[int] = []
    seen: set[bytes] = set()
    track_byte = 1 if track == "source_code_bundles" else 2
    base_size = len(MAGIC) + 1 + sum(varint_size(weight) for weight in raw_weights)
    entries_size = 0
    for _is_forced, _savings, _count, token, weight in candidates:
        if token in seen or len(tokens) >= policy["maximum_entries"]:
            continue
        entry_size = varint_size(len(token)) + len(token) + varint_size(weight)
        proposed_size = (
            base_size + varint_size(len(tokens) + 1) + entries_size + entry_size
        )
        if proposed_size > policy["maximum_serialized_bytes"]:
            continue
        tokens.append(token)
        token_weights.append(weight)
        entries_size += entry_size
        seen.add(token)
    payload = serialize_dictionary(
        track_byte, tokens, raw_weights=raw_weights, token_weights=token_weights
    )
    if any(token not in seen for token in forced):
        raise ValueError("fixed Wikimedia markup token did not fit the dictionary")
    return tokens, raw_weights, token_weights, payload, {
        "training_sample_bytes": sampled_bytes,
        "observed_candidate_tokens": len(counts),
    }


def serialize_dictionary(
    track_byte: int,
    tokens: list[bytes],
    *,
    raw_weights: list[int],
    token_weights: list[int],
) -> bytes:
    if (
        track_byte not in {1, 2}
        or len(tokens) != len(set(tokens))
        or len(raw_weights) != 256
        or len(token_weights) != len(tokens)
        or any(type(weight) is not int or weight <= 0 for weight in raw_weights)
        or any(type(weight) is not int or weight <= 0 for weight in token_weights)
    ):
        raise ValueError("dictionary identity is invalid")
    output = bytearray(MAGIC)
    output.append(track_byte)
    for weight in raw_weights:
        put_varint(output, weight)
    put_varint(output, len(tokens))
    for token, weight in zip(tokens, token_weights):
        put_varint(output, len(token))
        output.extend(token)
        put_varint(output, weight)
    return bytes(output)


def raw_class(track: str, value: int) -> int:
    if track == "source_code_bundles":
        if value == 95 or 65 <= value <= 90 or 97 <= value <= 122:
            return 2
        if 48 <= value <= 57:
            return 3
        if value in {9, 32}:
            return 4
        if value in {10, 13}:
            return 5
        if value in PUNCTUATION:
            return 6
        return 7
    if 65 <= value <= 90 or 97 <= value <= 122:
        return 3
    if 48 <= value <= 57:
        return 4
    if value in {9, 32}:
        return 5
    if value in {10, 13}:
        return 6
    if value in PUNCTUATION:
        return 7
    return 8


def dictionary_class(track: str, token: bytes, markup: set[bytes]) -> int:
    if track == "source_code_bundles":
        return 1
    return 2 if token in markup else 1


def mixed_symbols(
    track: str,
    data: bytes,
    token_ids: dict[bytes, int],
    markup_tokens: list[bytes],
) -> Iterator[tuple[int, int]]:
    if track == "source_code_bundles":
        scanner = SOURCE_TOKEN
    else:
        alternatives = [re.escape(token) for token in sorted(markup_tokens, key=lambda value: (-len(value), value))]
        alternatives.append(WIKI_WORD.pattern)
        scanner = re.compile(b"(?:" + b"|".join(alternatives) + b")")
    markup_set = set(markup_tokens)
    offset = 0
    for match in scanner.finditer(data):
        for value in data[offset : match.start()]:
            yield value, raw_class(track, value)
        token = match.group(0)
        token_id = token_ids.get(token)
        if token_id is None:
            for value in token:
                yield value, raw_class(track, value)
        else:
            yield 256 + token_id, dictionary_class(track, token, markup_set)
        offset = match.end()
    for value in data[offset:]:
        yield value, raw_class(track, value)


def estimate_raw(track: str, data: bytes) -> tuple[float, float]:
    alphabet = 256
    class_count = 8 if track == "source_code_bundles" else 9
    global_counts = [0] * alphabet
    contexts = [[0] * alphabet for _ in range(class_count)]
    context_totals = [0] * class_count
    total = 0
    previous_class = 0
    p0_bits = 0.0
    p1_bits = 0.0
    prior = HALF * alphabet
    for value in data:
        global_probability = (global_counts[value] + HALF) / (total + prior)
        context_probability = (contexts[previous_class][value] + HALF) / (
            context_totals[previous_class] + prior
        )
        p0_bits -= math.log2(global_probability)
        p1_bits -= math.log2(0.25 * global_probability + 0.75 * context_probability)
        global_counts[value] += 1
        contexts[previous_class][value] += 1
        total += 1
        context_totals[previous_class] += 1
        previous_class = raw_class(track, value)
    return p0_bits, p1_bits


def estimate_mixed(
    *,
    track: str,
    data: bytes,
    tokens: list[bytes],
    raw_weights: list[int],
    token_weights: list[int],
    markup_tokens: list[bytes],
) -> float:
    alphabet = 256 + len(tokens)
    class_count = 8 if track == "source_code_bundles" else 9
    if len(raw_weights) != 256 or len(token_weights) != len(tokens):
        raise ValueError("mixed predictor prior roster differs")
    global_counts = [*raw_weights, *token_weights]
    contexts = [[0] * alphabet for _ in range(class_count)]
    context_totals = [0] * class_count
    total = sum(global_counts)
    previous_class = 0
    bits = 0.0
    prior = HALF * alphabet
    token_ids = {token: index for index, token in enumerate(tokens)}
    for symbol, next_class in mixed_symbols(
        track, data, token_ids, markup_tokens
    ):
        global_probability = (global_counts[symbol] + HALF) / (total + prior)
        context_probability = (contexts[previous_class][symbol] + HALF) / (
            context_totals[previous_class] + prior
        )
        bits -= math.log2(0.25 * global_probability + 0.75 * context_probability)
        global_counts[symbol] += 1
        contexts[previous_class][symbol] += 1
        total += 1
        context_totals[previous_class] += 1
        previous_class = next_class
    return bits


def upper_bpb(values: list[float]) -> tuple[float, float, float]:
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("sample bits-per-byte values are invalid")
    mean = statistics.fmean(values)
    standard_error = (
        statistics.pstdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    )
    return mean, standard_error, mean + 2.0 * standard_error


def repository_commit() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("predictor probe requires a clean committed worktree")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_config(config: dict[str, Any]) -> None:
    if (
        config.get("schema_version") != 1
        or config.get("name") != "text-source-predictor-entropy-ceiling-probe-v1"
        or config.get("frozen_before_probe_results") is not True
        or list(config.get("splits", {}))
        != ["english_wikimedia_wikitext", "source_code_bundles"]
        or config.get("estimator", {}).get("variants") != VARIANTS
    ):
        raise ValueError("predictor probe config identity is invalid")
    training: set[str] = set()
    evaluation: set[str] = set()
    for track in TRACK_ORDER:
        split = config["splits"][track]
        if not split["training"] or not split["evaluation"]:
            raise ValueError(f"predictor split is empty: {track}")
        if set(split["training"]) & set(split["evaluation"]):
            raise ValueError(f"predictor training/evaluation overlap: {track}")
        training.update(split["training"])
        evaluation.update(split["evaluation"])
    if training & evaluation:
        raise ValueError("predictor tracks share training/evaluation identities")
    gate = config["gates"]["full_codec_build_admission"]
    if (
        gate["required_variant"] != VARIANTS[2]
        or gate["minimum_conservative_aggregate_gain_vs_kanzi_percent"] != 10.0
        or gate["minimum_conservative_item_gain_vs_kanzi_percent"] != 5.0
        or gate["dictionary_gain_over_byte_previous_class_percent"] != 3.0
    ):
        raise ValueError("predictor admission gate differs from protocol")


def load_inputs(
    config_path: Path, corpus: Path, baseline_path: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, int]]:
    config = read_canonical_json(config_path)
    validate_config(config)
    bindings = config["bindings"]
    bound_files = {
        "corpus_manifest_sha256": corpus / "manifest.json",
        "baseline_results_sha256": baseline_path,
        "structural_successor_decision_sha256": REPOSITORY
        / "runs"
        / "text-source-structural-successor-decision-v1.json",
        "successor_routing_config_sha256": REPOSITORY
        / "config"
        / "text-source-successor-routing-v1.json",
    }
    for key, path in bound_files.items():
        if sha256_file(path) != bindings[key]:
            raise ValueError(f"predictor binding differs: {key}")
    manifest = read_canonical_json(corpus / "manifest.json")
    baseline = read_canonical_json(baseline_path)
    if baseline.get("trial_count") != 630 or baseline.get("completed") is not True:
        raise ValueError("complete practical baseline is required")
    tracks = {item["id"]: item["track"] for item in baseline["items"]}
    rows: dict[str, dict[str, Any]] = {}
    for item in manifest["items"]:
        item_id = item["source_id"]
        path = corpus / item["bundle_path"]
        if (
            path.stat().st_size != item["bundle_size_bytes"]
            or sha256_file(path) != item["bundle_sha256"]
        ):
            raise ValueError(f"predictor corpus item differs: {item_id}")
        rows[item_id] = {
            "id": item_id,
            "track": tracks[item_id],
            "path": path,
            "source_bytes": item["bundle_size_bytes"],
            "source_sha256": item["bundle_sha256"],
        }
    kanzi = {
        row["item_id"]: row["artifact_bytes"]
        for row in baseline["summary"]["item_codec_rows"]
        if row["codec_id"] == "kanzi-max"
    }
    if set(rows) != set(kanzi):
        raise ValueError("predictor corpus and Kanzi roster differ")
    return config, rows, kanzi


def project_variant(
    *,
    variant: str,
    source_bytes: int,
    sample_bpbs: list[float],
    dictionary_bytes: int,
    startup_bytes: int,
) -> dict[str, Any]:
    mean, standard_error, conservative = upper_bpb(sample_bpbs)
    core = math.ceil(conservative * source_bytes / 8.0) + startup_bytes
    complete = core + (dictionary_bytes if variant == VARIANTS[2] else 0)
    return {
        "variant": variant,
        "sample_chunk_count": len(sample_bpbs),
        "sample_mean_bits_per_byte": mean,
        "sample_standard_error_bits_per_byte": standard_error,
        "conservative_bits_per_byte": conservative,
        "projected_core_bytes": core,
        "projected_complete_item_bytes": complete,
    }


def run_track(
    *,
    config: dict[str, Any],
    track: str,
    items: dict[str, dict[str, Any]],
    kanzi: dict[str, int],
) -> dict[str, Any]:
    split = config["splits"][track]
    tokens, raw_weights, token_weights, dictionary, training = train_dictionary(
        config=config,
        track=track,
        paths=[items[item_id]["path"] for item_id in split["training"]],
    )
    markup = fixed_markup(config, track)
    sampling = config["sampling"]
    startup = config["estimator"]["projection_startup_allowance_bytes_per_item"]
    item_results = []
    for item_id in split["evaluation"]:
        item = items[item_id]
        offsets = sample_offsets(
            item["source_bytes"],
            sampling["evaluation_chunk_bytes"],
            sampling["evaluation_chunks_per_item"],
        )
        values: dict[str, list[float]] = {variant: [] for variant in VARIANTS}
        sampled_bytes = 0
        for chunk in read_chunks(
            item["path"], offsets, sampling["evaluation_chunk_bytes"]
        ):
            sampled_bytes += len(chunk)
            p0_bits, p1_bits = estimate_raw(track, chunk)
            p2_bits = estimate_mixed(
                track=track,
                data=chunk,
                tokens=tokens,
                raw_weights=raw_weights,
                token_weights=token_weights,
                markup_tokens=markup,
            )
            values[VARIANTS[0]].append(p0_bits / len(chunk))
            values[VARIANTS[1]].append(p1_bits / len(chunk))
            values[VARIANTS[2]].append(p2_bits / len(chunk))
        projections = [
            project_variant(
                variant=variant,
                source_bytes=item["source_bytes"],
                sample_bpbs=values[variant],
                dictionary_bytes=len(dictionary),
                startup_bytes=startup,
            )
            for variant in VARIANTS
        ]
        for projection in projections:
            projection["gain_vs_kanzi_percent"] = (
                (kanzi[item_id] - projection["projected_complete_item_bytes"])
                / kanzi[item_id]
                * 100.0
            )
        item_results.append(
            {
                "item_id": item_id,
                "source_bytes": item["source_bytes"],
                "source_sha256": item["source_sha256"],
                "kanzi_bytes": kanzi[item_id],
                "sampled_bytes": sampled_bytes,
                "sample_offsets": offsets,
                "variants": projections,
            }
        )

    aggregates = []
    for variant in VARIANTS:
        selected = [
            next(row for row in item["variants"] if row["variant"] == variant)
            for item in item_results
        ]
        baseline_bytes = sum(item["kanzi_bytes"] for item in item_results)
        projected_bytes = sum(row["projected_core_bytes"] for row in selected)
        if variant == VARIANTS[2]:
            projected_bytes += len(dictionary)
        gain = (baseline_bytes - projected_bytes) / baseline_bytes * 100.0
        aggregates.append(
            {
                "variant": variant,
                "kanzi_bytes": baseline_bytes,
                "projected_complete_aggregate_bytes": projected_bytes,
                "gain_vs_kanzi_percent": gain,
                "minimum_item_gain_vs_kanzi_percent": min(
                    row["gain_vs_kanzi_percent"] for row in selected
                ),
            }
        )
    p1 = next(row for row in aggregates if row["variant"] == VARIANTS[1])
    p2 = next(row for row in aggregates if row["variant"] == VARIANTS[2])
    dictionary_gain = (
        (p1["projected_complete_aggregate_bytes"] - p2["projected_complete_aggregate_bytes"])
        / p1["projected_complete_aggregate_bytes"]
        * 100.0
    )
    gate = config["gates"]["full_codec_build_admission"]
    admitted = (
        p2["gain_vs_kanzi_percent"]
        >= gate["minimum_conservative_aggregate_gain_vs_kanzi_percent"]
        and p2["minimum_item_gain_vs_kanzi_percent"]
        >= gate["minimum_conservative_item_gain_vs_kanzi_percent"]
        and dictionary_gain >= gate["dictionary_gain_over_byte_previous_class_percent"]
        and len(dictionary) <= gate["maximum_dictionary_bytes"]
    )
    return {
        "track": track,
        "hypothesis_id": split["hypothesis_id"],
        "training_items": split["training"],
        "evaluation_items": split["evaluation"],
        "dictionary": {
            "bytes": len(dictionary),
            "sha256": hashlib.sha256(dictionary).hexdigest(),
            "entry_count": len(tokens),
            **training,
        },
        "items": item_results,
        "aggregates": aggregates,
        "dictionary_gain_over_byte_previous_class_percent": dictionary_gain,
        "full_codec_build_admitted": admitted,
        "decision": (
            "advance_to_exact_entropy_coder"
            if admitted
            else "reject_predictor_family_below_entropy_headroom_gate"
        ),
        "axiom_win": False,
    }


def benchmark(
    *, config_path: Path, corpus: Path, baseline_path: Path, output: Path
) -> Path:
    commit = repository_commit()
    config, items, kanzi = load_inputs(config_path, corpus, baseline_path)
    started = time.perf_counter_ns()
    tracks = [
        run_track(config=config, track=track, items=items, kanzi=kanzi)
        for track in TRACK_ORDER
    ]
    result = {
        "schema_version": 1,
        "name": "text-source-predictor-entropy-ceiling-result-v1",
        "completed": True,
        "bindings": {
            "config_sha256": sha256_file(config_path),
            "repository_commit": commit,
            **config["bindings"],
        },
        "sampling": config["sampling"],
        "dictionary_policy": config["dictionary_policy"],
        "estimator": config["estimator"],
        "gates": config["gates"],
        "tracks": tracks,
        "full_codec_build_admissions": sum(
            int(track["full_codec_build_admitted"]) for track in tracks
        ),
        "wall_ns": time.perf_counter_ns() - started,
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "axiom_wins": 0,
        "claim_ceiling": config["claim_ceiling"],
    }
    return write_immutable(output, result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = benchmark(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            output=args.output,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"predictor entropy-ceiling probe failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
