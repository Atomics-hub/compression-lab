#!/usr/bin/env python3
"""Run the frozen training-only record-neighborhood representation screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import statistics
import struct
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    REPOSITORY / "config" / "text-source-record-neighborhood-screen-v1.json"
)
DEFAULT_CORPUS = REPOSITORY / "corpora" / "text-source-development-v1"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_STRUCTURAL_RESULT = (
    REPOSITORY / "runs" / "text-source-structural-transform-development-v1" / "results.json"
)
DEFAULT_STRUCTURAL_EVIDENCE = (
    REPOSITORY
    / "runs"
    / "text-source-structural-transform-development-v1"
    / "publication"
    / "evidence.json"
)
DEFAULT_LONG_RANGE_RESULT = (
    REPOSITORY / "runs" / "text-source-long-range-screen-v1" / "results.json"
)
DEFAULT_TRANSFORM = (
    REPOSITORY / "scripts" / "text-source-record-neighborhood-transform.py"
)
DEFAULT_KANZI = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
DEFAULT_OUTPUT = REPOSITORY / "runs" / "text-source-record-neighborhood-screen-v1"
TRACKS = ("source_code_bundles", "english_wikimedia_wikitext")
VARIANT = "q1-bounded-minhash-record-neighborhood"
FRAME_MAGIC = b"AXRQ1\0"
FRAME_HEADER = struct.Struct("<6sQQ32s32s")


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


STRUCTURAL_RUNNER = load_script(
    "structural_runner_for_record_neighborhood",
    REPOSITORY / "scripts" / "benchmark-text-source-structural-transform.py",
)
BASELINE_PUBLICATION = load_script(
    "baseline_publication_for_record_neighborhood",
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


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(json_bytes(payload))
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


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
    measurement = config.get("measurement", {})
    gate = config.get("decision", {}).get("axiom_prototype_admission", {})
    variants = config.get("variants", [])
    if (
        type(config.get("schema_version")) is not int
        or config["schema_version"] != 1
        or config.get("name") != "text-source-record-neighborhood-screen-v1"
        or config.get("frozen_before_screen_results") is not True
        or config.get("splits") != expected_splits
        or len(variants) != 1
        or variants[0].get("id") != VARIANT
        or variants[0].get("backend") != "kanzi-max"
        or measurement.get("measured_repetitions") != 2
        or measurement.get("warmups") != 0
        or measurement.get("order_seed") != 20260718
        or measurement.get("backend_arguments")
        != ["--level=9", "--block=1g", "--jobs=1", "--verbose=0", "--force"]
        or gate.get("minimum_aggregate_gain_percent_each_track_vs_kanzi_max")
        != 2.0
        or gate.get(
            "minimum_aggregate_gain_percent_each_track_vs_structural_control"
        )
        != 1.0
        or gate.get("maximum_item_regression_percent") != 0.5
        or gate.get("required_identical_artifacts") != 2
        or gate.get("required_same_variant_across_tracks") is not True
        or "not validation" not in config.get("claim_ceiling", "")
    ):
        raise ValueError("record-neighborhood config differs from frozen contract")
    for split in expected_splits.values():
        if set(split["screen_items"]) & set(
            split["reserved_evaluation_not_accessed_by_screen"]
        ):
            raise ValueError("record-neighborhood split overlaps reserved evaluation")


def repository_commit() -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise ValueError("record-neighborhood screen requires a clean committed tree")
    if len(commit) != 40 or any(value not in "0123456789abcdef" for value in commit):
        raise ValueError("repository commit identity is invalid")
    return commit


def verify_screen_items(
    corpus: Path, config: dict[str, Any]
) -> tuple[bytes, list[dict[str, Any]]]:
    manifest_raw, manifest = read_canonical(corpus / "manifest.json")
    expected_ids = {
        item_id
        for split in config["splits"].values()
        for boundary in ("screen_items", "reserved_evaluation_not_accessed_by_screen")
        for item_id in split[boundary]
    }
    rows = {row.get("source_id"): row for row in manifest.get("items", [])}
    if set(rows) != expected_ids or manifest.get("public_validation_accessed") is not False:
        raise ValueError("development manifest roster or seal differs")
    items = []
    for track in TRACKS:
        for item_id in config["splits"][track]["screen_items"]:
            row = rows[item_id]
            path = corpus / row["bundle_path"]
            if path.stat().st_size != row["bundle_size_bytes"]:
                raise ValueError(f"screen item size differs: {item_id}")
            if sha256_file(path) != row["bundle_sha256"]:
                raise ValueError(f"screen item digest differs: {item_id}")
            items.append(
                {
                    "format": row["format"],
                    "id": item_id,
                    "path": str(path.resolve()),
                    "source_bytes": row["bundle_size_bytes"],
                    "source_sha256": row["bundle_sha256"],
                    "track": track,
                }
            )
    return manifest_raw, items


def verify_dependencies(
    *,
    config: dict[str, Any],
    corpus: Path,
    baseline_path: Path,
    structural_result_path: Path,
    structural_evidence_path: Path,
    long_range_result_path: Path,
    transform: Path,
    kanzi: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_raw, items = verify_screen_items(corpus, config)
    _baseline_raw, baseline = read_canonical(baseline_path)
    _structural_raw, structural = read_canonical(structural_result_path)
    _evidence_raw, evidence = read_canonical(structural_evidence_path)
    _long_range_raw, long_range = read_canonical(long_range_result_path)
    bindings = config["bindings"]
    observed = {
        "baseline_results_sha256": sha256_file(baseline_path),
        "corpus_manifest_sha256": sha256_bytes(manifest_raw),
        "kanzi_binary_sha256": sha256_file(kanzi),
        "long_range_result_sha256": sha256_file(long_range_result_path),
        "structural_public_evidence_sha256": sha256_file(structural_evidence_path),
        "structural_results_sha256": sha256_file(structural_result_path),
        "transform_script_sha256": sha256_file(transform),
    }
    if observed != bindings:
        raise ValueError("record-neighborhood dependency binding differs")
    if (
        baseline.get("completed") is not True
        or baseline.get("all_required_completed") is not True
        or structural.get("completed") is not True
        or structural.get("all_required_completed") is not True
        or evidence.get("results") != structural
        or long_range.get("completed") is not True
        or long_range.get("summary", {}).get("axiom_prototype_admitted") is not False
    ):
        raise ValueError("record-neighborhood predecessor evidence differs")
    BASELINE_PUBLICATION.validate_trial_receipts(baseline_path, baseline)
    baseline_rows = {
        (row["item_id"], row["codec_id"]): row
        for row in baseline["summary"]["item_codec_rows"]
    }
    control_rows = {
        row["item_id"]: row
        for row in structural["summary"]["item_rows"]
        if row["variant"] == "ts-h1-demux"
    }
    for item in items:
        baseline_row = baseline_rows.get((item["id"], "kanzi-max"))
        control_row = control_rows.get(item["id"])
        if (
            baseline_row is None
            or baseline_row.get("passed") is not True
            or baseline_row.get("exact_roundtrip") is not True
            or baseline_row.get("deterministic_artifact") is not True
            or control_row is None
            or control_row.get("passed") is not True
            or control_row.get("exact_roundtrip") is not True
            or control_row.get("deterministic_artifact") is not True
            or baseline_row.get("source_bytes") != item["source_bytes"]
            or control_row.get("source_bytes") != item["source_bytes"]
        ):
            raise ValueError(f"record-neighborhood control row differs: {item['id']}")
        item["baseline_bytes"] = baseline_row["artifact_bytes"]
        item["structural_control_bytes"] = control_row["candidate_bytes"]
    return items, baseline


def build_frame(
    destination: Path,
    *,
    source_bytes: int,
    source_sha256: str,
    payload: Path,
) -> None:
    payload_size = payload.stat().st_size
    header = FRAME_HEADER.pack(
        FRAME_MAGIC,
        source_bytes,
        payload_size,
        bytes.fromhex(source_sha256),
        bytes.fromhex(sha256_file(payload)),
    )
    with destination.open("wb") as output, payload.open("rb") as source:
        output.write(header)
        while chunk := source.read(1024 * 1024):
            output.write(chunk)


def extract_frame(
    frame: Path,
    payload: Path,
    *,
    expected_source_bytes: int,
    expected_source_sha256: str,
) -> None:
    payload.unlink(missing_ok=True)
    try:
        with frame.open("rb") as source:
            header = source.read(FRAME_HEADER.size)
            if len(header) != FRAME_HEADER.size:
                raise ValueError("record-neighborhood frame header is truncated")
            magic, source_bytes, payload_bytes, source_digest, payload_digest = (
                FRAME_HEADER.unpack(header)
            )
            if (
                magic != FRAME_MAGIC
                or source_bytes != expected_source_bytes
                or source_digest.hex() != expected_source_sha256
                or payload_bytes != frame.stat().st_size - FRAME_HEADER.size
            ):
                raise ValueError("record-neighborhood frame identity differs")
            observed = hashlib.sha256()
            with payload.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    observed.update(chunk)
            if observed.digest() != payload_digest:
                raise ValueError("record-neighborhood frame payload digest differs")
    except BaseException:
        payload.unlink(missing_ok=True)
        raise


def process_commands(
    item: dict[str, Any], kanzi: Path, transform: Path, work: Path
) -> dict[str, list[list[str]]]:
    python = str(Path(sys.executable).resolve())
    script = str(Path(__file__).resolve())
    source_bytes = str(item["source_bytes"])
    source_sha256 = item["source_sha256"]
    return {
        "compression": [
            [
                python,
                str(transform.resolve()),
                "encode",
                item["path"],
                str(work / "transformed.bin"),
            ],
            [
                str(kanzi.resolve()),
                "--compress",
                "--level=9",
                "--block=1g",
                "--jobs=1",
                "--verbose=0",
                "--force",
                f"--input={work / 'transformed.bin'}",
                f"--output={work / 'payload.knz'}",
            ],
            [
                python,
                script,
                "--worker-wrap",
                source_bytes,
                source_sha256,
                str(work / "payload.knz"),
                str(work / "candidate.axrq"),
            ],
        ],
        "decompression": [
            [
                python,
                script,
                "--worker-unwrap",
                source_bytes,
                source_sha256,
                str(work / "candidate.axrq"),
                str(work / "extracted.knz"),
            ],
            [
                str(kanzi.resolve()),
                "--decompress",
                "--jobs=1",
                "--verbose=0",
                "--force",
                f"--input={work / 'extracted.knz'}",
                f"--output={work / 'decoded-transform.bin'}",
            ],
            [
                python,
                str(transform.resolve()),
                "decode",
                "--max-output-size",
                source_bytes,
                str(work / "decoded-transform.bin"),
                str(work / "restored.bin"),
            ],
        ],
    }


def sanitize_process(record: dict[str, Any], work: Path) -> dict[str, Any]:
    return STRUCTURAL_RUNNER.sanitize_process_record(record, work)


def expected_process_commands(
    item: dict[str, Any], kanzi: Path, transform: Path
) -> dict[str, list[list[str]]]:
    work = Path("$WORK")
    return {
        phase: [
            sanitize_process({"command": command, "stdout": "", "stderr": ""}, work)[
                "command"
            ]
            for command in commands
        ]
        for phase, commands in process_commands(item, kanzi, transform, work).items()
    }


def trial_path(output: Path, item_id: str, repetition: int) -> Path:
    return output / "trials" / VARIANT / f"{item_id}.r{repetition}.json"


def run_trial(
    *,
    output: Path,
    bindings: dict[str, str],
    item: dict[str, Any],
    repetition: int,
    kanzi: Path,
    transform: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    destination = trial_path(output, item["id"], repetition)
    expected_identity = {
        "baseline_bytes": item["baseline_bytes"],
        "bindings": bindings,
        "item_id": item["id"],
        "repetition": repetition,
        "schema_version": 1,
        "source_bytes": item["source_bytes"],
        "source_sha256": item["source_sha256"],
        "structural_control_bytes": item["structural_control_bytes"],
        "track": item["track"],
        "variant": VARIANT,
    }
    if destination.exists():
        _raw, existing = read_canonical(destination)
        if any(existing.get(key) != value for key, value in expected_identity.items()):
            raise ValueError(f"resumed trial identity differs: {destination}")
        if existing.get("passed") is not True or existing.get("exact_roundtrip") is not True:
            raise ValueError(f"resumed trial is not successful: {destination}")
        return existing
    with tempfile.TemporaryDirectory(prefix="record-neighborhood-screen-") as raw:
        work = Path(raw)
        commands = process_commands(item, kanzi, transform, work)
        compression_processes = []
        decompression_processes = []
        error: str | None = None

        def run(command: list[str]) -> dict[str, Any]:
            return STRUCTURAL_RUNNER.run_process(
                command, timeout_seconds=timeout_seconds
            )

        for command in commands["compression"]:
            process = run(command)
            compression_processes.append(process)
            if process["timed_out"] or process["returncode"] != 0:
                error = "candidate compression pipeline failed"
                break
        frame = work / "candidate.axrq"
        payload = work / "payload.knz"
        transformed = work / "transformed.bin"
        restored = work / "restored.bin"
        if error is None and not frame.is_file():
            error = "candidate compression pipeline produced no frame"
        if error is None:
            for command in commands["decompression"]:
                process = run(command)
                decompression_processes.append(process)
                if process["timed_out"] or process["returncode"] != 0:
                    error = "candidate decompression pipeline failed"
                    break
        exact = bool(
            error is None
            and restored.is_file()
            and restored.stat().st_size == item["source_bytes"]
            and sha256_file(restored) == item["source_sha256"]
        )
        if not exact and error is None:
            error = "restored bytes differ from source"
        row = {
            **expected_identity,
            "backend_payload_bytes": payload.stat().st_size if payload.is_file() else None,
            "candidate_bytes": frame.stat().st_size if frame.is_file() else None,
            "candidate_sha256": sha256_file(frame) if frame.is_file() else None,
            "compression_peak_rss_bytes": max(
                (process["peak_rss_bytes"] for process in compression_processes),
                default=0,
            ),
            "compression_wall_ns": (
                sum(process["wall_ns"] for process in compression_processes)
                if len(compression_processes) == 3
                else None
            ),
            "decompression_peak_rss_bytes": max(
                (process["peak_rss_bytes"] for process in decompression_processes),
                default=0,
            ),
            "decompression_wall_ns": (
                sum(process["wall_ns"] for process in decompression_processes)
                if len(decompression_processes) == 3
                else None
            ),
            "error": error,
            "exact_roundtrip": exact,
            "passed": exact,
            "processes": {
                "compression": [sanitize_process(row, work) for row in compression_processes],
                "decompression": [
                    sanitize_process(row, work) for row in decompression_processes
                ],
            },
            "transformed_bytes": (
                transformed.stat().st_size if transformed.is_file() else None
            ),
        }
        write_json_atomic(destination, row)
        return row


def summarize(
    *, trials: list[dict[str, Any]], items: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    repetitions = config["measurement"]["measured_repetitions"]
    item_rows = []
    for item in items:
        group = [row for row in trials if row["item_id"] == item["id"]]
        sizes = {row["candidate_bytes"] for row in group if row["passed"]}
        digests = {row["candidate_sha256"] for row in group if row["passed"]}
        passed = bool(
            len(group) == repetitions
            and all(row["passed"] for row in group)
            and len(sizes) == 1
            and len(digests) == 1
        )
        candidate_bytes = next(iter(sizes)) if passed else None
        item_rows.append(
            {
                "baseline_bytes": item["baseline_bytes"],
                "candidate_bytes": candidate_bytes,
                "candidate_sha256": next(iter(digests)) if passed else None,
                "compression_peak_rss_bytes": max(
                    (row["compression_peak_rss_bytes"] for row in group), default=0
                ),
                "decompression_peak_rss_bytes": max(
                    (row["decompression_peak_rss_bytes"] for row in group), default=0
                ),
                "deterministic_artifact": passed,
                "exact_roundtrip": passed,
                "gain_vs_kanzi_percent": (
                    (item["baseline_bytes"] - candidate_bytes)
                    / item["baseline_bytes"]
                    * 100.0
                    if passed
                    else None
                ),
                "gain_vs_structural_control_percent": (
                    (item["structural_control_bytes"] - candidate_bytes)
                    / item["structural_control_bytes"]
                    * 100.0
                    if passed
                    else None
                ),
                "item_id": item["id"],
                "median_compression_ns": (
                    int(statistics.median(row["compression_wall_ns"] for row in group))
                    if passed
                    else None
                ),
                "median_decompression_ns": (
                    int(statistics.median(row["decompression_wall_ns"] for row in group))
                    if passed
                    else None
                ),
                "passed": passed,
                "source_bytes": item["source_bytes"],
                "structural_control_bytes": item["structural_control_bytes"],
                "track": item["track"],
                "variant": VARIANT,
            }
        )
    gate = config["decision"]["axiom_prototype_admission"]
    track_rows = []
    for track in TRACKS:
        selected = [row for row in item_rows if row["track"] == track]
        complete = len(selected) == 2 and all(row["passed"] for row in selected)
        baseline_bytes = sum(row["baseline_bytes"] for row in selected)
        control_bytes = sum(row["structural_control_bytes"] for row in selected)
        candidate_bytes = sum(row["candidate_bytes"] for row in selected) if complete else None
        gain_vs_kanzi = (
            (baseline_bytes - candidate_bytes) / baseline_bytes * 100.0
            if complete
            else None
        )
        gain_vs_control = (
            (control_bytes - candidate_bytes) / control_bytes * 100.0
            if complete
            else None
        )
        minimum_item_gain = (
            min(row["gain_vs_kanzi_percent"] for row in selected) if complete else None
        )
        admitted = bool(
            complete
            and gain_vs_kanzi
            >= gate["minimum_aggregate_gain_percent_each_track_vs_kanzi_max"]
            and gain_vs_control
            >= gate[
                "minimum_aggregate_gain_percent_each_track_vs_structural_control"
            ]
            and minimum_item_gain >= -gate["maximum_item_regression_percent"]
        )
        track_rows.append(
            {
                "baseline_bytes": baseline_bytes,
                "candidate_bytes": candidate_bytes,
                "complete": complete,
                "gain_vs_kanzi_percent": gain_vs_kanzi,
                "gain_vs_structural_control_percent": gain_vs_control,
                "minimum_item_gain_vs_kanzi_percent": minimum_item_gain,
                "screen_items": config["splits"][track]["screen_items"],
                "structural_control_bytes": control_bytes,
                "track": track,
                "track_admitted": admitted,
            }
        )
    admitted = all(row["track_admitted"] for row in track_rows)
    return {
        "axiom_prototype_admitted": admitted,
        "axiom_wins": 0,
        "decision": (
            "admit_bounded_record_neighborhood_specialist"
            if admitted
            else "reject_bounded_record_neighborhood_shared_successor"
        ),
        "item_rows": item_rows,
        "selected_variant": VARIANT if admitted else None,
        "tracks": track_rows,
    }


def benchmark(
    *,
    config_path: Path,
    corpus: Path,
    baseline_path: Path,
    structural_result_path: Path,
    structural_evidence_path: Path,
    long_range_result_path: Path,
    transform: Path,
    kanzi: Path,
    output: Path,
) -> Path:
    config_raw, config = read_canonical(config_path)
    validate_config(config)
    commit = repository_commit()
    items, _baseline = verify_dependencies(
        config=config,
        corpus=corpus,
        baseline_path=baseline_path,
        structural_result_path=structural_result_path,
        structural_evidence_path=structural_evidence_path,
        long_range_result_path=long_range_result_path,
        transform=transform,
        kanzi=kanzi,
    )
    bindings = {
        **config["bindings"],
        "config_sha256": sha256_bytes(config_raw),
        "repository_commit": commit,
    }
    repetitions = config["measurement"]["measured_repetitions"]
    schedule = [
        (item["id"], repetition) for item in items for repetition in range(repetitions)
    ]
    random.Random(config["measurement"]["order_seed"]).shuffle(schedule)
    by_id = {item["id"]: item for item in items}
    trials = []
    for index, (item_id, repetition) in enumerate(schedule, start=1):
        print(f"[{index}/{len(schedule)}] r{repetition} {item_id} x {VARIANT}", flush=True)
        trials.append(
            run_trial(
                output=output,
                bindings=bindings,
                item=by_id[item_id],
                repetition=repetition,
                kanzi=kanzi,
                transform=transform,
                timeout_seconds=config["measurement"]["timeout_seconds_per_process"],
            )
        )
    summary = summarize(trials=trials, items=items, config=config)
    result = {
        "all_required_completed": all(row["passed"] for row in summary["item_rows"]),
        "bindings": bindings,
        "claim_ceiling": config["claim_ceiling"],
        "completed": True,
        "measurement": config["measurement"],
        "name": "text-source-record-neighborhood-screen-result-v1",
        "private_holdout_status": "sealed and unaccessed",
        "public_validation_status": "sealed and unaccessed",
        "schema_version": 1,
        "screen_boundary": {track: config["splits"][track] for track in TRACKS},
        "summary": summary,
        "trial_count": len(trials),
        "variants": config["variants"],
    }
    destination = output / "results.json"
    if destination.exists():
        _raw, existing = read_canonical(destination)
        if existing != result:
            raise ValueError("record-neighborhood result differs from retained result")
    else:
        write_json_atomic(destination, result)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--structural-result", type=Path, default=DEFAULT_STRUCTURAL_RESULT
    )
    parser.add_argument(
        "--structural-evidence", type=Path, default=DEFAULT_STRUCTURAL_EVIDENCE
    )
    parser.add_argument("--long-range-result", type=Path, default=DEFAULT_LONG_RANGE_RESULT)
    parser.add_argument("--transform", type=Path, default=DEFAULT_TRANSFORM)
    parser.add_argument("--kanzi", type=Path, default=DEFAULT_KANZI)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--worker-wrap", nargs=4)
    parser.add_argument("--worker-unwrap", nargs=4)
    args = parser.parse_args()
    try:
        if args.worker_wrap:
            source_bytes, source_sha256, payload, destination = args.worker_wrap
            build_frame(
                Path(destination),
                source_bytes=int(source_bytes),
                source_sha256=source_sha256,
                payload=Path(payload),
            )
            return 0
        if args.worker_unwrap:
            source_bytes, source_sha256, frame, payload = args.worker_unwrap
            extract_frame(
                Path(frame),
                Path(payload),
                expected_source_bytes=int(source_bytes),
                expected_source_sha256=source_sha256,
            )
            return 0
        result = benchmark(
            config_path=args.config,
            corpus=args.corpus,
            baseline_path=args.baseline,
            structural_result_path=args.structural_result,
            structural_evidence_path=args.structural_evidence,
            long_range_result_path=args.long_range_result,
            transform=args.transform,
            kanzi=args.kanzi,
            output=args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"record-neighborhood screen failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
