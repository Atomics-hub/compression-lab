#!/usr/bin/env python3
"""Run the frozen training-split Kanzi long-range decomposition screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import statistics
import subprocess
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-long-range-screen-v1.json"
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_PREDICTOR_RESULT = (
    REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-v1.json"
)
DEFAULT_KANZI = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-long-range-screen-v1"
TRACKS = ("source_code_bundles", "english_wikimedia_wikitext")
VARIANTS = (
    "k1-lzp-prepend-level9",
    "k2-lzp-text-utf",
    "k3-lzp-only",
)


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BASELINE_RUNNER = load_script(
    "baseline_runner_for_long_range_screen",
    REPOSITORY / "scripts" / "benchmark-text-source-baselines.py",
)
BASELINE_PUBLICATION = load_script(
    "baseline_publication_for_long_range_screen",
    REPOSITORY / "scripts" / "publish-text-source-baseline-census.py",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return raw, value


def validate_config(config: dict[str, Any]) -> None:
    expected_splits = {
        "source_code_bundles": {
            "screen_items": [
                "cpython-3.14.6-source",
                "typescript-6.0.3-source",
            ],
            "reserved_evaluation_not_accessed_by_screen": [
                "rust-1.97.1-source",
                "llvm-22.1.8-source",
            ],
        },
        "english_wikimedia_wikitext": {
            "screen_items": [
                "enwikibooks-20260701",
                "enwikinews-20260701",
            ],
            "reserved_evaluation_not_accessed_by_screen": [
                "enwikiversity-20260701"
            ],
        },
    }
    expected_variants = [
        ("k1-lzp-prepend-level9", "LZP+EXE+RLT+TEXT+UTF+DNA", "TPAQX"),
        ("k2-lzp-text-utf", "LZP+TEXT+UTF", "TPAQX"),
        ("k3-lzp-only", "LZP", "TPAQX"),
    ]
    observed_variants = [
        (row.get("id"), row.get("transform"), row.get("entropy"))
        for row in config.get("variants", [])
    ]
    measurement = config.get("measurement", {})
    gate = config.get("decision", {}).get("axiom_prototype_admission", {})
    if (
        type(config.get("schema_version")) is not int
        or config["schema_version"] != 1
        or config.get("name")
        != "text-source-long-range-kanzi-decomposition-screen-v1"
        or config.get("frozen_before_screen_results") is not True
        or config.get("splits") != expected_splits
        or observed_variants != expected_variants
        or measurement.get("measured_repetitions") != 2
        or measurement.get("warmups") != 0
        or measurement.get("jobs") != 1
        or measurement.get("block_bytes") != 1024**3
        or gate.get("minimum_aggregate_gain_percent_each_track") != 2.0
        or gate.get("maximum_item_regression_percent") != 0.5
        or gate.get("required_same_variant_across_tracks") is not True
        or gate.get("required_identical_artifacts") != 2
        or "not Axiom artifacts" not in config.get("claim_ceiling", "")
    ):
        raise ValueError("long-range screen config differs from the frozen contract")
    for split in expected_splits.values():
        if set(split["screen_items"]) & set(
            split["reserved_evaluation_not_accessed_by_screen"]
        ):
            raise ValueError("long-range screen split overlaps reserved evaluation")


def repository_commit() -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked:
        raise ValueError("long-range screen requires a clean tracked commit")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("repository commit identity is invalid")
    return commit


def verify_screen_items(
    corpus: Path, config: dict[str, Any]
) -> tuple[bytes, list[dict[str, Any]]]:
    manifest_path = corpus / "manifest.json"
    manifest_raw, manifest = read_canonical(manifest_path)
    expected_ids = {
        item_id
        for split in config["splits"].values()
        for key in ("screen_items", "reserved_evaluation_not_accessed_by_screen")
        for item_id in split[key]
    }
    manifest_rows = {row.get("source_id"): row for row in manifest.get("items", [])}
    if set(manifest_rows) != expected_ids or manifest.get("public_validation_accessed") is not False:
        raise ValueError("development manifest roster or seal differs")
    track_by_id = {
        item_id: track
        for track, split in config["splits"].items()
        for item_id in split["screen_items"]
    }
    items = []
    for track in TRACKS:
        for item_id in config["splits"][track]["screen_items"]:
            row = manifest_rows[item_id]
            path = corpus / row["bundle_path"]
            if path.stat().st_size != row["bundle_size_bytes"]:
                raise ValueError(f"screen item size differs: {item_id}")
            if sha256_file(path) != row["bundle_sha256"]:
                raise ValueError(f"screen item digest differs: {item_id}")
            items.append(
                {
                    "id": item_id,
                    "track": track_by_id[item_id],
                    "path": str(path.resolve()),
                    "source_bytes": row["bundle_size_bytes"],
                    "source_sha256": row["bundle_sha256"],
                }
            )
    return manifest_raw, items


def verify_dependencies(
    *,
    config: dict[str, Any],
    corpus: Path,
    baseline_path: Path,
    predictor_result_path: Path,
    kanzi: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_raw, items = verify_screen_items(corpus, config)
    _baseline_raw, baseline = read_canonical(baseline_path)
    _predictor_raw, predictor = read_canonical(predictor_result_path)
    bindings = config["bindings"]
    if (
        sha256_bytes(manifest_raw) != bindings["corpus_manifest_sha256"]
        or sha256_file(baseline_path) != bindings["baseline_results_sha256"]
        or sha256_file(predictor_result_path) != bindings["predictor_result_sha256"]
        or sha256_file(kanzi) != bindings["kanzi_binary_sha256"]
        or baseline.get("completed") is not True
        or baseline.get("all_required_completed") is not True
        or baseline.get("tools", {}).get("kanzi", {}).get("binary_sha256")
        != bindings["kanzi_binary_sha256"]
        or predictor.get("full_codec_build_admissions") != 0
        or predictor.get("axiom_wins") != 0
    ):
        raise ValueError("long-range screen dependency binding differs")
    BASELINE_PUBLICATION.validate_trial_receipts(baseline_path, baseline)
    baseline_rows = {
        (row["item_id"], row["codec_id"]): row
        for row in baseline["summary"]["item_codec_rows"]
    }
    for item in items:
        row = baseline_rows.get((item["id"], "kanzi-max"))
        if (
            row is None
            or row.get("passed") is not True
            or row.get("exact_roundtrip") is not True
            or row.get("deterministic_artifact") is not True
            or row.get("source_bytes") != item["source_bytes"]
        ):
            raise ValueError(f"screen baseline row differs: {item['id']}")
    return items, baseline


def variant_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in config["variants"]}


def commands(
    *,
    kanzi: Path,
    variant: dict[str, Any],
    source: Path,
    artifact: Path,
    restored: Path,
) -> tuple[list[str], list[str]]:
    compression = [
        str(kanzi),
        "--compress",
        f"--input={source}",
        f"--output={artifact}",
        "--force",
        f"--transform={variant['transform']}",
        f"--entropy={variant['entropy']}",
        "--block=1g",
        "--jobs=1",
        "--verbose=0",
    ]
    decompression = [
        str(kanzi),
        "--decompress",
        f"--input={artifact}",
        f"--output={restored}",
        "--force",
        "--jobs=1",
        "--verbose=0",
    ]
    return compression, decompression


def sanitize_process(record: dict[str, Any], work: Path) -> dict[str, Any]:
    return BASELINE_RUNNER.sanitize_process_record(record, work)


def validate_process(
    process: object, expected_command: list[str], destination: Path
) -> None:
    if (
        not isinstance(process, dict)
        or set(process)
        != {
            "command",
            "returncode",
            "timed_out",
            "wall_ns",
            "cpu_ns",
            "peak_rss_bytes",
            "stdout",
            "stderr",
        }
        or process.get("command") != expected_command
        or type(process.get("returncode")) is not int
        or not isinstance(process.get("timed_out"), bool)
        or type(process.get("wall_ns")) is not int
        or process["wall_ns"] <= 0
        or type(process.get("cpu_ns")) is not int
        or process["cpu_ns"] < 0
        or type(process.get("peak_rss_bytes")) is not int
        or process["peak_rss_bytes"] < 0
        or not isinstance(process.get("stdout"), str)
        or not isinstance(process.get("stderr"), str)
    ):
        raise ValueError(f"resumed process record differs: {destination}")


def trial_path(output: Path, variant: str, item: str, repetition: int) -> Path:
    return output / "trials" / variant / f"{item}.r{repetition}.json"


def validate_existing_trial(
    receipt: dict[str, Any],
    *,
    destination: Path,
    bindings: dict[str, str],
    item: dict[str, Any],
    variant: dict[str, Any],
    repetition: int,
    kanzi: Path,
) -> None:
    expected_identity = {
        "schema_version": 1,
        "bindings": bindings,
        "variant": variant["id"],
        "item_id": item["id"],
        "track": item["track"],
        "repetition": repetition,
        "source_bytes": item["source_bytes"],
        "source_sha256": item["source_sha256"],
    }
    if (
        set(receipt)
        != {
            *expected_identity,
            "artifact_bytes",
            "artifact_sha256",
            "compression",
            "decompression",
            "exact_roundtrip",
            "passed",
            "error",
        }
        or any(receipt.get(key) != value for key, value in expected_identity.items())
    ):
        raise ValueError(f"resumed trial identity differs: {destination}")
    work = Path("$WORK")
    compression, decompression = commands(
        kanzi=kanzi,
        variant=variant,
        source=Path(item["path"]),
        artifact=work / "artifact.knz",
        restored=work / "restored.bin",
    )
    validate_process(
        receipt.get("compression"),
        sanitize_process({"command": compression}, work)["command"],
        destination,
    )
    if receipt.get("decompression") is not None:
        validate_process(
            receipt["decompression"],
            sanitize_process({"command": decompression}, work)["command"],
            destination,
        )
    passed = receipt.get("passed") is True
    artifact_valid = (
        type(receipt.get("artifact_bytes")) is int
        and receipt["artifact_bytes"] > 0
        and isinstance(receipt.get("artifact_sha256"), str)
        and len(receipt["artifact_sha256"]) == 64
    )
    if passed:
        if (
            receipt.get("exact_roundtrip") is not True
            or receipt.get("error") is not None
            or not artifact_valid
            or receipt.get("decompression") is None
            or receipt["compression"]["returncode"] != 0
            or receipt["decompression"]["returncode"] != 0
        ):
            raise ValueError(f"resumed successful trial differs: {destination}")
    elif (
        receipt.get("passed") is not False
        or receipt.get("exact_roundtrip") is not False
        or not isinstance(receipt.get("error"), str)
        or not receipt["error"]
    ):
        raise ValueError(f"resumed failed trial differs: {destination}")


def run_trial(
    *,
    output: Path,
    bindings: dict[str, str],
    item: dict[str, Any],
    variant: dict[str, Any],
    repetition: int,
    kanzi: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    destination = trial_path(output, variant["id"], item["id"], repetition)
    if destination.exists():
        receipt_raw, receipt = read_canonical(destination)
        if receipt_raw != json_bytes(receipt):
            raise ValueError(f"resumed trial is not canonical: {destination}")
        validate_existing_trial(
            receipt,
            destination=destination,
            bindings=bindings,
            item=item,
            variant=variant,
            repetition=repetition,
            kanzi=kanzi,
        )
        return receipt
    with tempfile.TemporaryDirectory(prefix="long-range-screen-") as temporary:
        work = Path(temporary)
        artifact = work / "artifact.knz"
        restored = work / "restored.bin"
        compression_command, decompression_command = commands(
            kanzi=kanzi,
            variant=variant,
            source=Path(item["path"]),
            artifact=artifact,
            restored=restored,
        )
        compression = BASELINE_RUNNER.run_process(
            compression_command,
            stdout_path=None,
            timeout_seconds=timeout_seconds,
        )
        decompression: dict[str, Any] | None = None
        artifact_bytes: int | None = None
        artifact_sha256: str | None = None
        error = ""
        if compression["timed_out"]:
            error = "compression timed out"
        elif compression["returncode"] != 0:
            error = f"compression exited {compression['returncode']}"
        elif not artifact.is_file():
            error = "compression produced no artifact"
        else:
            artifact_bytes = artifact.stat().st_size
            artifact_sha256 = sha256_file(artifact)
            decompression = BASELINE_RUNNER.run_process(
                decompression_command,
                stdout_path=None,
                timeout_seconds=timeout_seconds,
            )
            if decompression["timed_out"]:
                error = "decompression timed out"
            elif decompression["returncode"] != 0:
                error = f"decompression exited {decompression['returncode']}"
            elif not restored.is_file():
                error = "decompression produced no output"
            elif restored.stat().st_size != item["source_bytes"]:
                error = "restored size differs"
            elif sha256_file(restored) != item["source_sha256"]:
                error = "restored digest differs"
        receipt = {
            "schema_version": 1,
            "bindings": bindings,
            "variant": variant["id"],
            "item_id": item["id"],
            "track": item["track"],
            "repetition": repetition,
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
            "artifact_bytes": artifact_bytes,
            "artifact_sha256": artifact_sha256,
            "compression": sanitize_process(compression, work),
            "decompression": (
                sanitize_process(decompression, work)
                if decompression is not None
                else None
            ),
            "exact_roundtrip": not error,
            "passed": not error,
            "error": error or None,
        }
        BASELINE_RUNNER.write_json_atomic(destination, receipt)
        return receipt


def preflight(config: dict[str, Any], kanzi: Path) -> list[dict[str, Any]]:
    fixture = (
        b"template<typename T> T repeat(T value) { return value; }\n" * 4096
        + bytes(range(256)) * 512
    )
    rows = []
    with tempfile.TemporaryDirectory(prefix="long-range-preflight-") as raw:
        root = Path(raw)
        source = root / "fixture.bin"
        source.write_bytes(fixture)
        for variant in config["variants"]:
            work = root / variant["id"]
            work.mkdir()
            artifact = work / "artifact.knz"
            restored = work / "restored.bin"
            compression, decompression = commands(
                kanzi=kanzi,
                variant=variant,
                source=source,
                artifact=artifact,
                restored=restored,
            )
            encoded = BASELINE_RUNNER.run_process(
                compression, stdout_path=None, timeout_seconds=300.0
            )
            decoded = BASELINE_RUNNER.run_process(
                decompression, stdout_path=None, timeout_seconds=300.0
            )
            if (
                encoded["returncode"] != 0
                or encoded["timed_out"]
                or decoded["returncode"] != 0
                or decoded["timed_out"]
                or not artifact.is_file()
                or not restored.is_file()
                or restored.read_bytes() != fixture
            ):
                raise ValueError(f"long-range preflight failed: {variant['id']}")
            rows.append(
                {
                    "variant": variant["id"],
                    "source_bytes": len(fixture),
                    "artifact_bytes": artifact.stat().st_size,
                    "artifact_sha256": sha256_file(artifact),
                    "exact_roundtrip": True,
                }
            )
    return rows


def summarize(
    *,
    trials: list[dict[str, Any]],
    items: list[dict[str, Any]],
    baseline: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    baseline_map = {
        row["item_id"]: row
        for row in baseline["summary"]["item_codec_rows"]
        if row["codec_id"] == "kanzi-max"
    }
    repetitions = config["measurement"]["measured_repetitions"]
    item_rows = []
    for variant in VARIANTS:
        for item in items:
            group = [
                row
                for row in trials
                if row["variant"] == variant and row["item_id"] == item["id"]
            ]
            sizes = {row["artifact_bytes"] for row in group if row["passed"]}
            digests = {row["artifact_sha256"] for row in group if row["passed"]}
            passed = (
                len(group) == repetitions
                and all(row["passed"] for row in group)
                and len(sizes) == 1
                and len(digests) == 1
            )
            baseline_bytes = baseline_map[item["id"]]["artifact_bytes"]
            artifact_bytes = next(iter(sizes)) if passed else None
            item_rows.append(
                {
                    "variant": variant,
                    "item_id": item["id"],
                    "track": item["track"],
                    "source_bytes": item["source_bytes"],
                    "baseline_bytes": baseline_bytes,
                    "artifact_bytes": artifact_bytes,
                    "artifact_sha256": next(iter(digests)) if passed else None,
                    "gain_vs_kanzi_percent": (
                        (baseline_bytes - artifact_bytes) / baseline_bytes * 100.0
                        if passed
                        else None
                    ),
                    "median_compression_ns": (
                        int(
                            statistics.median(
                                row["compression"]["wall_ns"] for row in group
                            )
                        )
                        if passed
                        else None
                    ),
                    "median_decompression_ns": (
                        int(
                            statistics.median(
                                row["decompression"]["wall_ns"] for row in group
                            )
                        )
                        if passed
                        else None
                    ),
                    "compression_peak_rss_bytes": max(
                        (row["compression"]["peak_rss_bytes"] for row in group),
                        default=0,
                    ),
                    "decompression_peak_rss_bytes": max(
                        (
                            row["decompression"]["peak_rss_bytes"]
                            for row in group
                            if row["decompression"] is not None
                        ),
                        default=0,
                    ),
                    "exact_roundtrip": passed,
                    "deterministic_artifact": passed,
                    "passed": passed,
                }
            )
    gate = config["decision"]["axiom_prototype_admission"]
    track_rows = []
    passing_by_track: dict[str, set[str]] = {}
    for track in TRACKS:
        baseline_bytes = sum(
            baseline_map[item["id"]]["artifact_bytes"]
            for item in items
            if item["track"] == track
        )
        variants = []
        for variant in VARIANTS:
            selected_item_rows = [
                row
                for row in item_rows
                if row["track"] == track and row["variant"] == variant
            ]
            complete = len(selected_item_rows) == 2 and all(
                row["passed"] for row in selected_item_rows
            )
            artifact_bytes = (
                sum(row["artifact_bytes"] for row in selected_item_rows)
                if complete
                else None
            )
            gain = (
                (baseline_bytes - artifact_bytes) / baseline_bytes * 100.0
                if complete
                else None
            )
            worst_item_gain = (
                min(row["gain_vs_kanzi_percent"] for row in selected_item_rows)
                if complete
                else None
            )
            admitted = bool(
                complete
                and gain >= gate["minimum_aggregate_gain_percent_each_track"]
                and worst_item_gain >= -gate["maximum_item_regression_percent"]
            )
            variants.append(
                {
                    "variant": variant,
                    "baseline_bytes": baseline_bytes,
                    "artifact_bytes": artifact_bytes,
                    "gain_vs_kanzi_percent": gain,
                    "minimum_item_gain_vs_kanzi_percent": worst_item_gain,
                    "complete": complete,
                    "track_admitted": admitted,
                }
            )
        passing_by_track[track] = {
            row["variant"] for row in variants if row["track_admitted"]
        }
        track_rows.append(
            {
                "track": track,
                "baseline": "kanzi-max",
                "screen_items": config["splits"][track]["screen_items"],
                "variants": variants,
            }
        )
    shared = set.intersection(*(passing_by_track[track] for track in TRACKS))
    selected_variant: str | None = None
    if shared:
        selected_variant = max(
            shared,
            key=lambda variant: min(
                row["gain_vs_kanzi_percent"]
                for track in track_rows
                for row in track["variants"]
                if row["variant"] == variant
            ),
        )
    return {
        "item_rows": item_rows,
        "tracks": track_rows,
        "shared_passing_variants": sorted(shared),
        "selected_variant": selected_variant,
        "axiom_prototype_admitted": selected_variant is not None,
        "axiom_wins": 0,
        "decision": (
            "admit_bounded_multi_reference_implicit_long_range_prototype"
            if selected_variant is not None
            else "reject_shared_implicit_long_range_factorization_direction"
        ),
    }


def benchmark(
    *,
    config_path: Path,
    corpus: Path,
    baseline_path: Path,
    predictor_result_path: Path,
    kanzi: Path,
    output: Path,
) -> Path:
    config_raw, config = read_canonical(config_path)
    validate_config(config)
    commit = repository_commit()
    items, baseline = verify_dependencies(
        config=config,
        corpus=corpus,
        baseline_path=baseline_path,
        predictor_result_path=predictor_result_path,
        kanzi=kanzi,
    )
    preflight_rows = preflight(config, kanzi)
    bindings = {
        "repository_commit": commit,
        "config_sha256": sha256_bytes(config_raw),
        **config["bindings"],
    }
    repetitions = config["measurement"]["measured_repetitions"]
    schedule = [
        (variant["id"], item["id"], repetition)
        for variant in config["variants"]
        for item in items
        for repetition in range(repetitions)
    ]
    random.Random(config["measurement"]["order_seed"]).shuffle(schedule)
    items_by_id = {item["id"]: item for item in items}
    variants_by_id = variant_map(config)
    trials = []
    for index, (variant_id, item_id, repetition) in enumerate(schedule, start=1):
        print(
            f"[{index}/{len(schedule)}] r{repetition} {item_id} × {variant_id}",
            flush=True,
        )
        trials.append(
            run_trial(
                output=output,
                bindings=bindings,
                item=items_by_id[item_id],
                variant=variants_by_id[variant_id],
                repetition=repetition,
                kanzi=kanzi,
                timeout_seconds=config["measurement"]["timeout_seconds_per_process"],
            )
        )
    summary = summarize(trials=trials, items=items, baseline=baseline, config=config)
    result = {
        "schema_version": 1,
        "name": "text-source-long-range-kanzi-decomposition-screen-result-v1",
        "completed": True,
        "all_required_completed": all(row["passed"] for row in summary["item_rows"]),
        "trial_count": len(trials),
        "bindings": bindings,
        "screen_boundary": {
            track: config["splits"][track] for track in TRACKS
        },
        "measurement": config["measurement"],
        "preflight": preflight_rows,
        "variants": config["variants"],
        "summary": summary,
        "claim_ceiling": config["claim_ceiling"],
        "public_validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
    }
    destination = output / "results.json"
    if destination.exists():
        raw, existing = read_canonical(destination)
        if raw != json_bytes(existing) or existing != result:
            raise ValueError("long-range screen result differs from retained result")
    else:
        BASELINE_RUNNER.write_json_atomic(destination, result)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--predictor-result", type=Path, default=DEFAULT_PREDICTOR_RESULT
    )
    parser.add_argument("--kanzi", type=Path, default=DEFAULT_KANZI)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = benchmark(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            predictor_result_path=args.predictor_result,
            kanzi=args.kanzi,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"long-range screen failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
