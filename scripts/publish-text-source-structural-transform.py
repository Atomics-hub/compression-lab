#!/usr/bin/env python3
"""Publish the completed text/source structural probe with all practical baselines."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import ModuleType
from typing import Any
from xml.sax.saxutils import escape


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = (
    REPOSITORY
    / "runs"
    / "text-source-structural-transform-development-v1"
    / "results.json"
)
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
EXPECTED_ITEMS = [
    ("cpython-3.14.6-source", "source-bundle-v1", "source_code_bundles"),
    ("typescript-6.0.3-source", "source-bundle-v1", "source_code_bundles"),
    ("rust-1.97.1-source", "source-bundle-v1", "source_code_bundles"),
    ("llvm-22.1.8-source", "source-bundle-v1", "source_code_bundles"),
    (
        "enwikibooks-20260701",
        "wikimedia-revision-text-v1",
        "english_wikimedia_wikitext",
    ),
    (
        "enwikinews-20260701",
        "wikimedia-revision-text-v1",
        "english_wikimedia_wikitext",
    ),
    (
        "enwikiversity-20260701",
        "wikimedia-revision-text-v1",
        "english_wikimedia_wikitext",
    ),
]
TRACK_LABELS = {
    "source_code_bundles": "Source-code bundles",
    "english_wikimedia_wikitext": "English Wikimedia wikitext",
}
VARIANT_LABELS = {
    "ts-h1-demux": "Axiom TS-H1 demux",
    "ts-h2-extension-lanes": "Axiom TS-H2 extension lanes",
}
CLAIM_CEILING = (
    "Development structural-representation evidence only. Public validation and "
    "private holdout remain sealed, research-ceiling codecs remain pending, and "
    "this result cannot support a category-win, market-leading, world-best, or "
    "state-of-the-art claim."
)


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STRUCTURAL = load_script(
    "text_source_structural_runner",
    REPOSITORY / "scripts" / "benchmark-text-source-structural-transform.py",
)
BASELINE_PUBLICATION = load_script(
    "text_source_baseline_publication",
    REPOSITORY / "scripts" / "publish-text-source-baseline-census.py",
)


def expected_process_commands(
    item: dict[str, Any], variant: str
) -> dict[str, list[list[str]]]:
    extension = {
        "source-bundle-v1": "axsrc",
        "wikimedia-revision-text-v1": "axwkt",
    }[item["format"]]
    runner_item = dict(item)
    runner_item["path"] = str(
        REPOSITORY
        / "corpora"
        / "text-source-development-v1"
        / f"{item['id']}.{extension}"
    )
    kanzi = REPOSITORY / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi"
    return STRUCTURAL.expected_process_commands(runner_item, variant, kanzi)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_process_record(process: object, destination: Path) -> None:
    if (
        not isinstance(process, dict)
        or type(process.get("returncode")) is not int
        or not isinstance(process.get("timed_out"), bool)
        or type(process.get("wall_ns")) is not int
        or process["wall_ns"] <= 0
        or type(process.get("cpu_ns")) is not int
        or process["cpu_ns"] < 0
        or type(process.get("peak_rss_bytes")) is not int
        or process["peak_rss_bytes"] < 0
        or not isinstance(process.get("command"), list)
        or not process["command"]
        or not all(isinstance(value, str) and value for value in process["command"])
        or not isinstance(process.get("stdout"), str)
        or not isinstance(process.get("stderr"), str)
    ):
        raise ValueError(f"structural process record is invalid: {destination}")


def validate_failed_trial(
    receipt: dict[str, Any],
    *,
    expected_commands: dict[str, list[list[str]]],
    destination: Path,
) -> None:
    admitted_errors = {
        "transform encode failed",
        "backend compression failed",
        "candidate envelope construction failed",
        "candidate envelope extraction failed",
        "backend decompression failed",
        "transform decode failed",
        "restored bytes differ from source",
    }
    if (
        receipt.get("passed") is not False
        or receipt.get("exact_roundtrip") is not False
        or receipt.get("error") not in admitted_errors
    ):
        raise ValueError(f"structural failed outcome is invalid: {destination}")
    processes = receipt.get("processes")
    if not isinstance(processes, dict) or set(processes) != {
        "compression",
        "decompression",
    }:
        raise ValueError(f"structural failed process map is invalid: {destination}")
    for phase in ("compression", "decompression"):
        records = processes[phase]
        if (
            not isinstance(records, list)
            or len(records) > 3
            or (phase == "compression" and not records)
        ):
            raise ValueError(
                f"structural failed {phase} process count is invalid: {destination}"
            )
        for index, process in enumerate(records):
            validate_process_record(process, destination)
            if process["command"] != expected_commands[phase][index]:
                raise ValueError(
                    f"structural failed {phase} command differs: {destination}"
                )
        expected_wall = (
            sum(process["wall_ns"] for process in records)
            if len(records) == 3
            else None
        )
        if receipt.get(f"{phase}_wall_ns") != expected_wall:
            raise ValueError(
                f"structural failed {phase} wall accounting is invalid: {destination}"
            )
        expected_rss = max(
            (process["peak_rss_bytes"] for process in records), default=0
        )
        if receipt.get(f"{phase}_peak_rss_bytes") != expected_rss:
            raise ValueError(
                f"structural failed {phase} RSS accounting is invalid: {destination}"
            )
    for key in ("transformed_bytes", "backend_payload_bytes", "candidate_bytes"):
        value = receipt.get(key)
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(
                f"structural failed artifact size is invalid: {destination}"
            )
    candidate_bytes = receipt.get("candidate_bytes")
    candidate_sha256 = receipt.get("candidate_sha256")
    payload_bytes = receipt.get("backend_payload_bytes")
    if candidate_bytes is None:
        if candidate_sha256 is not None:
            raise ValueError(
                f"structural failed artifact digest is invalid: {destination}"
            )
    elif (
        not STRUCTURAL.is_sha256(candidate_sha256)
        or type(payload_bytes) is not int
        or candidate_bytes != STRUCTURAL.FRAME_HEADER.size + payload_bytes
    ):
        raise ValueError(
            f"structural failed artifact accounting is invalid: {destination}"
        )


def validate_structural_receipts(
    results_path: Path, results: dict[str, Any]
) -> tuple[str, int]:
    if (
        type(results.get("schema_version")) is not int
        or results["schema_version"] != 1
        or results.get("name") != "text-source-structural-transform-development-v1"
        or results.get("completed") is not True
        or results.get("trial_count") != 33
        or results.get("backend") != "kanzi-max"
        or results.get("backend_setting")
        != ["--level=9", "--block=1g", "--jobs=1"]
        or results.get("repetitions") != 2
        or results.get("warmups") != 1
        or results.get("order_seed") != 20260718
    ):
        raise ValueError("structural result identity or completeness is invalid")
    items = results.get("items")
    if (
        not isinstance(items, list)
        or [(item.get("id"), item.get("format"), item.get("track")) for item in items]
        != EXPECTED_ITEMS
    ):
        raise ValueError("structural result item roster differs from protocol")
    if not all(
        type(item.get("source_bytes")) is int
        and item["source_bytes"] > 0
        and STRUCTURAL.is_sha256(item.get("source_sha256"))
        and type(item.get("baseline_bytes")) is int
        and item["baseline_bytes"] > 0
        and type(item.get("baseline_compression_peak_rss_bytes")) is int
        and item["baseline_compression_peak_rss_bytes"] >= 0
        and type(item.get("baseline_decompression_peak_rss_bytes")) is int
        and item["baseline_decompression_peak_rss_bytes"] >= 0
        for item in items
    ):
        raise ValueError("structural result item evidence is incomplete")

    expected_paths = {
        Path(variant) / f"{item['id']}.r{repetition}.json"
        for item in items
        for variant in STRUCTURAL.variants_for(item)
        for repetition in range(3)
    }
    trial_root = results_path.parent / "trials"
    observed_paths = (
        {path.relative_to(trial_root) for path in trial_root.glob("*/*.json")}
        if trial_root.is_dir()
        else set()
    )
    if observed_paths != expected_paths:
        raise ValueError(
            "structural receipt roster differs from frozen matrix: "
            f"{len(expected_paths - observed_paths)} missing, "
            f"{len(observed_paths - expected_paths)} extra"
        )

    item_map = {item["id"]: item for item in items}
    bindings = results.get("bindings")
    if not isinstance(bindings, dict) or set(bindings) != {
        "repository_commit",
        "baseline_results_sha256",
        "corpus_manifest_sha256",
        "kanzi_binary_sha256",
    }:
        raise ValueError("structural result bindings are invalid")
    if not BASELINE_PUBLICATION.is_lower_hex(
        bindings["repository_commit"], 40
    ) or not all(
        STRUCTURAL.is_sha256(bindings[key])
        for key in (
            "baseline_results_sha256",
            "corpus_manifest_sha256",
            "kanzi_binary_sha256",
        )
    ):
        raise ValueError("structural result bindings contain an invalid digest")
    trials = []
    receipt_hashes = []
    failed_trial_count = 0
    for relative in sorted(expected_paths, key=str):
        path = trial_root / relative
        raw = path.read_bytes()
        receipt_hashes.append(f"{sha256_bytes(raw)}  {relative.as_posix()}\n")
        receipt = json.loads(raw)
        if not isinstance(receipt, dict) or raw != json_bytes(receipt):
            raise ValueError(f"structural receipt is not canonical JSON: {path}")
        item_id, repetition_text = relative.stem.rsplit(".r", 1)
        item = item_map[item_id]
        repetition = int(repetition_text)
        expected_identity = {
            "schema_version": 1,
            "bindings": bindings,
            "variant": relative.parent.name,
            "item_id": item_id,
            "track": item["track"],
            "repetition": repetition,
            "warmup": repetition == 0,
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
            "baseline_codec": "kanzi-max",
            "baseline_bytes": item["baseline_bytes"],
        }
        commands = expected_process_commands(item, relative.parent.name)
        if (
            type(receipt.get("schema_version")) is not int
            or type(receipt.get("repetition")) is not int
            or not isinstance(receipt.get("warmup"), bool)
            or any(
                receipt.get(key) != value for key, value in expected_identity.items()
            )
        ):
            raise ValueError(f"structural receipt identity is invalid: {path}")
        if receipt.get("passed") is True:
            STRUCTURAL.validate_existing_trial(
                receipt,
                bindings=bindings,
                item=item,
                variant=relative.parent.name,
                repetition=repetition,
                expected_commands=commands,
                destination=path,
            )
        else:
            validate_failed_trial(
                receipt, expected_commands=commands, destination=path
            )
            failed_trial_count += 1
        trials.append(receipt)

    reconstructed = STRUCTURAL.summarize(trials, items)
    if results.get("summary") != reconstructed:
        raise ValueError("structural receipts do not reconstruct results summary")
    expected_completed = all(row["passed"] for row in reconstructed["item_rows"])
    if results.get("all_required_completed") is not expected_completed:
        raise ValueError("structural all-required decision is inconsistent")
    return (
        sha256_bytes("".join(receipt_hashes).encode("utf-8")),
        failed_trial_count,
    )


def build_public_evidence(
    results_path: Path,
    results: dict[str, Any],
    *,
    structural_results_sha256: str,
    raw_structural_receipts_manifest_sha256: str,
    baseline_results_sha256: str,
    baseline_public_evidence_sha256: str,
) -> bytes:
    items = results["items"]
    expected_paths = {
        Path(variant) / f"{item['id']}.r{repetition}.json"
        for item in items
        for variant in STRUCTURAL.variants_for(item)
        for repetition in range(3)
    }
    trials = []
    trial_root = results_path.parent / "trials"
    for relative in sorted(expected_paths, key=str):
        receipt = json.loads((trial_root / relative).read_bytes())
        public = dict(receipt)
        public_processes = {}
        for phase in ("compression", "decompression"):
            public_processes[phase] = []
            for raw_process in receipt["processes"][phase]:
                process = dict(raw_process)
                for stream in ("stdout", "stderr"):
                    process[f"{stream}_commitment"] = (
                        BASELINE_PUBLICATION.stream_commitment(process.pop(stream))
                    )
                public_processes[phase].append(process)
        public["processes"] = public_processes
        trials.append({"path": relative.as_posix(), "receipt": public})
    evidence = {
        "schema_version": 1,
        "name": "text-source-structural-transform-development-public-evidence-v1",
        "redaction_policy": (
            "Only process stdout/stderr content is removed. Each stream retains its "
            "UTF-8 byte count, SHA-256 commitment, and empty/artifact/redacted "
            "classification; every decision-bearing identity, command, timing, RSS, "
            "artifact, exactness, determinism, resource, and gate field remains present."
        ),
        "structural_results_sha256": structural_results_sha256,
        "raw_structural_trial_receipts_manifest_sha256": (
            raw_structural_receipts_manifest_sha256
        ),
        "public_structural_trial_receipts_manifest_sha256": (
            BASELINE_PUBLICATION.public_receipts_manifest_sha256(trials)
        ),
        "baseline_results_sha256": baseline_results_sha256,
        "baseline_public_evidence_sha256": baseline_public_evidence_sha256,
        "results": results,
        "trials": trials,
    }
    encoded = json_bytes(evidence)
    forbidden_path_markers = (
        b"/Users/",
        b"/private/var/",
        b"/var/folders/",
        b"/tmp/",
    )
    if any(marker in encoded for marker in forbidden_path_markers):
        raise ValueError("structural public evidence contains a local absolute path")
    validate_public_evidence(evidence)
    return encoded


def validate_public_evidence(evidence: dict[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "name",
        "redaction_policy",
        "structural_results_sha256",
        "raw_structural_trial_receipts_manifest_sha256",
        "public_structural_trial_receipts_manifest_sha256",
        "baseline_results_sha256",
        "baseline_public_evidence_sha256",
        "results",
        "trials",
    }
    digest_keys = {
        "structural_results_sha256",
        "raw_structural_trial_receipts_manifest_sha256",
        "public_structural_trial_receipts_manifest_sha256",
        "baseline_results_sha256",
        "baseline_public_evidence_sha256",
    }
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_keys
        or type(evidence.get("schema_version")) is not int
        or evidence["schema_version"] != 1
        or evidence.get("name")
        != "text-source-structural-transform-development-public-evidence-v1"
        or not isinstance(evidence.get("redaction_policy"), str)
        or not evidence["redaction_policy"]
        or not all(STRUCTURAL.is_sha256(evidence.get(key)) for key in digest_keys)
    ):
        raise ValueError("structural public evidence identity is invalid")
    results = evidence.get("results")
    if (
        not isinstance(results, dict)
        or sha256_bytes(json_bytes(results)) != evidence["structural_results_sha256"]
    ):
        raise ValueError("structural public evidence results digest is inconsistent")
    items = results.get("items")
    if not isinstance(items, list):
        raise ValueError("structural public evidence item roster is invalid")
    expected_paths = {
        Path(variant) / f"{item['id']}.r{repetition}.json"
        for item in items
        for variant in STRUCTURAL.variants_for(item)
        for repetition in range(3)
    }
    trials = evidence.get("trials")
    if (
        not isinstance(trials, list)
        or len(trials) != 33
        or [row.get("path") for row in trials]
        != [path.as_posix() for path in sorted(expected_paths, key=str)]
        or BASELINE_PUBLICATION.public_receipts_manifest_sha256(trials)
        != evidence["public_structural_trial_receipts_manifest_sha256"]
    ):
        raise ValueError("structural public trial manifest is inconsistent")
    receipt_keys = {
        "schema_version",
        "bindings",
        "variant",
        "item_id",
        "track",
        "repetition",
        "warmup",
        "source_bytes",
        "source_sha256",
        "baseline_codec",
        "baseline_bytes",
        "transformed_bytes",
        "backend_payload_bytes",
        "candidate_bytes",
        "candidate_sha256",
        "compression_wall_ns",
        "decompression_wall_ns",
        "compression_peak_rss_bytes",
        "decompression_peak_rss_bytes",
        "processes",
        "exact_roundtrip",
        "passed",
        "error",
    }
    public_process_keys = {
        "command",
        "returncode",
        "timed_out",
        "wall_ns",
        "cpu_ns",
        "peak_rss_bytes",
        "stdout_commitment",
        "stderr_commitment",
    }
    with tempfile.TemporaryDirectory(prefix="structural-public-evidence-") as raw:
        root = Path(raw)
        results_path = root / "results.json"
        results_path.write_bytes(json_bytes(results))
        for row in trials:
            public = row.get("receipt")
            if not isinstance(public, dict) or set(public) != receipt_keys:
                raise ValueError("structural public receipt field roster is invalid")
            receipt = dict(public)
            processes = public.get("processes")
            if not isinstance(processes, dict) or set(processes) != {
                "compression",
                "decompression",
            }:
                raise ValueError("structural public process map is invalid")
            rehydrated = {}
            for phase in ("compression", "decompression"):
                records = processes[phase]
                if not isinstance(records, list):
                    raise ValueError("structural public process list is invalid")
                rehydrated[phase] = []
                for public_process in records:
                    if (
                        not isinstance(public_process, dict)
                        or set(public_process) != public_process_keys
                    ):
                        raise ValueError("structural public process fields are invalid")
                    process = dict(public_process)
                    process["stdout"] = (
                        BASELINE_PUBLICATION.validate_stream_commitment(
                            process.pop("stdout_commitment")
                        )
                    )
                    process["stderr"] = (
                        BASELINE_PUBLICATION.validate_stream_commitment(
                            process.pop("stderr_commitment")
                        )
                    )
                    rehydrated[phase].append(process)
            receipt["processes"] = rehydrated
            destination = root / "trials" / row["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(json_bytes(receipt))
        validate_structural_receipts(results_path, results)


def candidate_row(
    track_id: str,
    track_summary: dict[str, Any],
    item_rows: list[dict[str, Any]],
    source_bytes: int,
) -> dict[str, Any]:
    variant = track_summary["variant"]
    selected = [
        row
        for row in item_rows
        if row["track"] == track_id and row["variant"] == variant
    ]
    complete = track_summary["complete"]
    candidate_bytes = track_summary["candidate_bytes"]
    compression_ns = (
        sum(row["median_compression_ns"] for row in selected) if complete else None
    )
    decompression_ns = (
        sum(row["median_decompression_ns"] for row in selected) if complete else None
    )
    if track_summary["final_specialist_admission_passed"]:
        decision = "development admission passed"
    elif track_summary["hypothesis_gate_passed"]:
        decision = "hypothesis passed; final admission missed"
    else:
        decision = "development hypothesis rejected"
    return {
        "kind": "axiom_candidate",
        "id": variant,
        "label": VARIANT_LABELS[variant],
        "source_bytes": source_bytes,
        "complete_bytes": candidate_bytes,
        "compression_ratio": (
            source_bytes / candidate_bytes if candidate_bytes else None
        ),
        "size_percent": (
            candidate_bytes / source_bytes * 100.0 if candidate_bytes else None
        ),
        "compression_mbps": (
            source_bytes / compression_ns * 1000.0 if compression_ns else None
        ),
        "decompression_mbps": (
            source_bytes / decompression_ns * 1000.0 if decompression_ns else None
        ),
        "compression_peak_rss_mib": max(
            (row["compression_peak_rss_bytes"] for row in selected), default=0
        )
        / (1024.0 * 1024.0),
        "decompression_peak_rss_mib": max(
            (row["decompression_peak_rss_bytes"] for row in selected), default=0
        )
        / (1024.0 * 1024.0),
        "exact_roundtrip": all(row["exact_roundtrip"] for row in selected),
        "deterministic_artifact": all(
            row["deterministic_artifact"] for row in selected
        ),
        "gain_vs_kanzi_percent": track_summary["gain_vs_kanzi_percent"],
        "minimum_item_gain_percent": track_summary["minimum_item_gain_percent"],
        "hypothesis_gate_passed": track_summary["hypothesis_gate_passed"],
        "final_specialist_admission_passed": track_summary[
            "final_specialist_admission_passed"
        ],
        "portability_status": "untested",
        "axiom_beaten_status": "candidate",
        "decision": decision,
    }


def derive(
    structural: dict[str, Any],
    baseline: dict[str, Any],
    *,
    structural_sha256: str,
    structural_receipts_sha256: str,
    baseline_sha256: str,
    baseline_receipts_sha256: str,
    public_evidence_sha256: str,
    baseline_public_evidence_sha256: str,
    public_receipts_sha256: str,
    failed_trial_count: int,
) -> dict[str, Any]:
    tracks = []
    item_rows = structural["summary"]["item_rows"]
    for track_id, label in TRACK_LABELS.items():
        baseline_track = baseline["summary"]["tracks"][track_id]
        source_bytes = baseline_track["source_bytes"]
        rows = []
        for row in baseline_track["codecs"]:
            rows.append(
                {
                    "kind": "practical_baseline",
                    "id": row["codec_id"],
                    "label": BASELINE_PUBLICATION.CODEC_LABELS[row["codec_id"]],
                    "source_bytes": source_bytes,
                    "complete_bytes": row["artifact_bytes"],
                    "compression_ratio": source_bytes / row["artifact_bytes"],
                    "size_percent": row["artifact_bytes"] / source_bytes * 100.0,
                    "compression_mbps": row["compression_mbps"],
                    "decompression_mbps": row["decompression_mbps"],
                    "compression_peak_rss_mib": row["compression_peak_rss_bytes"]
                    / (1024.0 * 1024.0),
                    "decompression_peak_rss_mib": row["decompression_peak_rss_bytes"]
                    / (1024.0 * 1024.0),
                    "exact_roundtrip": True,
                    "deterministic_artifact": True,
                    "portability_status": "same-host evidence only",
                    "ratio_leader": row["codec_id"]
                    == baseline_track["leader"]["codec_id"],
                    "decision": "tested practical baseline",
                }
            )
        candidates = [
            candidate_row(track_id, summary, item_rows, source_bytes)
            for summary in structural["summary"]["tracks"][track_id]
        ]
        admitted = [
            row
            for row in candidates
            if row["final_specialist_admission_passed"]
            and row["complete_bytes"] is not None
        ]
        for baseline_row in rows:
            baseline_row["beaten_by_admitted_axiom"] = bool(admitted) and any(
                candidate["complete_bytes"] < baseline_row["complete_bytes"]
                for candidate in admitted
            )
            baseline_row["axiom_beaten_status"] = (
                "yes" if baseline_row["beaten_by_admitted_axiom"] else "no"
            )
        tracks.append(
            {
                "track_id": track_id,
                "track": label,
                "source_bytes": source_bytes,
                "practical_leader": BASELINE_PUBLICATION.CODEC_LABELS[
                    baseline_track["leader"]["codec_id"]
                ],
                "rows": rows + candidates,
            }
        )
    return {
        "schema_version": 1,
        "name": "text-source-structural-transform-development-publication-v1",
        "stage": "development structural representation probe",
        "structural_results_sha256": structural_sha256,
        "structural_trial_receipts_manifest_sha256": structural_receipts_sha256,
        "baseline_results_sha256": baseline_sha256,
        "baseline_trial_receipts_manifest_sha256": baseline_receipts_sha256,
        "public_evidence_sha256": public_evidence_sha256,
        "baseline_public_evidence_sha256": baseline_public_evidence_sha256,
        "public_structural_trial_receipts_manifest_sha256": public_receipts_sha256,
        "bindings": structural["bindings"],
        "host": baseline["host"],
        "trial_count": structural["trial_count"],
        "tracks": tracks,
        "integrity": {
            "all_33_trials_present": True,
            "all_roundtrips_exact": failed_trial_count == 0,
            "failed_trial_count": failed_trial_count,
            "all_required_completed": structural["all_required_completed"],
            "complete_candidate_envelope_and_backend_bytes_counted": True,
            "axtp2_payload_sha256_verified_before_backend_decode": True,
            "axtp2_fixed_header_one_bit_mutations_rejected": STRUCTURAL.FRAME_HEADER.size
            * 8,
            "axtp2_truncated_header_lengths_rejected": STRUCTURAL.FRAME_HEADER.size,
            "axtp2_truncated_and_appended_payloads_rejected": True,
            "axtp2_transactional_extraction": True,
            "transform_output_bound_checked_before_reconstruction": True,
            "transform_record_count_bounded_before_iteration": True,
            "transform_encoder_decoder_format_bounds_symmetric": True,
            "transform_extension_lane_roster_canonical": True,
            "transform_front_coding_maximal_and_canonical": True,
            "candidate_determinism_reported": True,
            "same_practical_baseline_results_reverified": True,
            "all_33_public_receipts_decision_complete_and_stream_redacted": True,
        },
        "research_ceiling_pending": ["ZPAQ", "paq8px", "cmix", "NNCP"],
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "runner_comparability": {
            "size": "Fully comparable: identical declared source bytes and complete self-contained artifact bytes are used for every row.",
            "speed_memory": "Contextual rather than paired: all rows use the same host and one codec thread, but candidate subprocess-chain measurements occur in the later structural run while baseline measurements come from the separately checksummed census.",
        },
        "claim_ceiling": CLAIM_CEILING,
    }


def display_number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value:.2f}{suffix}"


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Text/source structural transform development result",
        "",
        "![Axiom structural variants compared with every practical standard](comparison.svg)",
        "",
        f"> **Claim ceiling:** {comparison['claim_ceiling']}",
        "",
        "Axiom rows are development hypotheses. A green ratio alone is not a category win.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                f"Practical ratio leader: **{track['practical_leader']}**.",
                "",
                "| Codec / candidate | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in track["rows"]:
            integrity = (
                "✅ / ✅"
                if row["exact_roundtrip"] and row["deterministic_artifact"]
                else "❌ / ❌"
            )
            lines.append(
                f"| {row['label']} | {display_number(row['complete_bytes'])} | "
                f"{display_number(row['compression_ratio'], 'x')} | "
                f"{display_number(row['size_percent'], '%')} | "
                f"{display_number(row['compression_mbps'])} | "
                f"{display_number(row['decompression_mbps'])} | "
                f"{display_number(row['compression_peak_rss_mib'])} / "
                f"{display_number(row['decompression_peak_rss_mib'])} | "
                f"{integrity} | {row['portability_status']} | "
                f"{row['axiom_beaten_status']} | {row['decision']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Evidence boundary",
            "",
            f"- Structural results SHA-256: `{comparison['structural_results_sha256']}`",
            "- Structural receipt-manifest SHA-256: "
            f"`{comparison['structural_trial_receipts_manifest_sha256']}`",
            f"- Baseline results SHA-256: `{comparison['baseline_results_sha256']}`",
            "- Baseline receipt-manifest SHA-256: "
            f"`{comparison['baseline_trial_receipts_manifest_sha256']}`",
            f"- Structural public recalculation evidence: [`evidence.json`](evidence.json), "
            f"SHA-256 `{comparison['public_evidence_sha256']}`.",
            "- Bound baseline public-evidence SHA-256: "
            f"`{comparison['baseline_public_evidence_sha256']}`.",
            "- Structural public trial-receipt manifest SHA-256: "
            f"`{comparison['public_structural_trial_receipts_manifest_sha256']}`.",
            "- Public evidence retains every decision-bearing field from all 33 structural "
            "trials; process streams are replaced by byte counts and SHA-256 commitments.",
            "- Failed structural trials: "
            f"**{comparison['integrity']['failed_trial_count']}**; "
            "all required item/variant gates complete: "
            f"**{str(comparison['integrity']['all_required_completed']).lower()}**.",
            "- Corruption preflight: AXTP2 authenticates the complete backend "
            "payload with SHA-256 before backend decoding and deletes a rejected "
            "extraction; all "
            f"{comparison['integrity']['axtp2_fixed_header_one_bit_mutations_rejected']} "
            "possible one-bit mutations and all "
            f"{comparison['integrity']['axtp2_truncated_header_lengths_rejected']} "
            "truncated lengths of its fixed header are rejected. Truncated or "
            "appended payloads are rejected without retaining stale/partial output.",
            "- Runner comparability (size): "
            f"{comparison['runner_comparability']['size']}",
            "- Runner comparability (speed/memory): "
            f"{comparison['runner_comparability']['speed_memory']}",
            "- Public validation and private holdout remain sealed.",
            "- Research-ceiling rows remain pending: ZPAQ, paq8px, cmix, and NNCP.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    width = 1620
    row_height = 27
    track_height = 76 + row_height * max(
        len(track["rows"]) for track in comparison["tracks"]
    )
    height = 138 + track_height * len(comparison["tracks"]) + 70
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Axiom text and source structural development comparison</title>',
        '<desc id="desc">Every practical standard and both applicable Axiom structural variants are compared by complete size, speed, memory, exactness, determinism, and development decision.</desc>',
        "<style>",
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#172033}",
        ".title{font-size:27px;font-weight:700}.sub{font-size:14px;fill:#526078}.track{font-size:20px;font-weight:700}.head{font-size:12px;font-weight:700;fill:#526078}.label{font-size:12px}.num{font-size:11px;font-variant-numeric:tabular-nums}.candidate{font-weight:700;fill:#0b6b57}.reject{fill:#a13d2d}",
        "</style>",
        '<rect width="100%" height="100%" fill="#fbfcff"/>',
        '<text class="title" x="32" y="42">Axiom text/source structural development probe</text>',
        '<text class="sub" x="32" y="68">All 15 practical standards remain visible; failed and rejected Axiom evidence remains visible.</text>',
    ]
    y = 112
    for track in comparison["tracks"]:
        parts.append(
            f'<text class="track" x="32" y="{y}">{escape(track["track"])}</text>'
        )
        y += 27
        headers = [
            (32, "Codec / candidate", "start"),
            (540, "Bytes", "end"),
            (635, "Ratio", "end"),
            (725, "Size %", "end"),
            (830, "C MB/s", "end"),
            (940, "D MB/s", "end"),
            (1035, "RSS C/D MiB", "end"),
            (1135, "Exact/Det", "middle"),
            (1270, "Portability", "middle"),
            (1385, "Axiom beat?", "middle"),
            (1590, "Decision", "end"),
        ]
        for x, label, anchor in headers:
            parts.append(
                f'<text class="head" x="{x}" y="{y}" text-anchor="{anchor}">{label}</text>'
            )
        y += 18
        for index, row in enumerate(track["rows"]):
            if index % 2 == 0:
                parts.append(
                    f'<rect x="24" y="{y - 15}" width="1572" height="{row_height}" rx="4" fill="#f0f4fa"/>'
                )
            candidate = row["kind"] == "axiom_candidate"
            css = "candidate" if candidate else "label"
            if candidate and not row["hypothesis_gate_passed"]:
                css = "candidate reject"
            integrity = (
                "yes/yes"
                if row["exact_roundtrip"] and row["deterministic_artifact"]
                else "no/no"
            )
            values = [
                (32, row["label"], "start", css),
                (540, display_number(row["complete_bytes"]), "end", "num"),
                (635, display_number(row["compression_ratio"], "x"), "end", "num"),
                (725, display_number(row["size_percent"], "%"), "end", "num"),
                (830, display_number(row["compression_mbps"]), "end", "num"),
                (940, display_number(row["decompression_mbps"]), "end", "num"),
                (
                    1035,
                    f"{display_number(row['compression_peak_rss_mib'])}/{display_number(row['decompression_peak_rss_mib'])}",
                    "end",
                    "num",
                ),
                (1135, integrity, "middle", "num"),
                (1270, row["portability_status"], "middle", "num"),
                (1385, row["axiom_beaten_status"], "middle", "num"),
                (1590, row["decision"], "end", "num"),
            ]
            for x, value, anchor, klass in values:
                parts.append(
                    f'<text class="{klass}" x="{x}" y="{y + 3}" text-anchor="{anchor}">{escape(str(value))}</text>'
                )
            y += row_height
        y += 31
    parts.append(
        f'<text class="sub" x="32" y="{height - 34}">{escape(CLAIM_CEILING)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_artifacts(results_path: Path, baseline_path: Path) -> dict[str, bytes]:
    structural_raw = results_path.read_bytes()
    structural = json.loads(structural_raw)
    baseline_raw = baseline_path.read_bytes()
    baseline = json.loads(baseline_raw)
    if not isinstance(structural, dict) or structural_raw != json_bytes(structural):
        raise ValueError("structural result is not canonical JSON")
    if not isinstance(baseline, dict) or baseline_raw != json_bytes(baseline):
        raise ValueError("baseline result is not canonical JSON")
    structural_receipts_sha256, failed_trial_count = validate_structural_receipts(
        results_path, structural
    )
    baseline_receipts_sha256 = BASELINE_PUBLICATION.validate_trial_receipts(
        baseline_path, baseline
    )
    baseline_sha256 = sha256_bytes(baseline_raw)
    baseline_public_evidence = BASELINE_PUBLICATION.build_public_evidence(
        baseline_path,
        baseline,
        raw_results_sha256=baseline_sha256,
        raw_receipts_manifest_sha256=baseline_receipts_sha256,
    )
    baseline_public_evidence_sha256 = sha256_bytes(baseline_public_evidence)
    if structural["bindings"].get("baseline_results_sha256") != baseline_sha256:
        raise ValueError("structural result is not bound to this baseline result")
    if structural.get("baseline_commit") != baseline["bindings"]["repository_commit"]:
        raise ValueError("structural result baseline commit is inconsistent")
    baseline_items = {item["id"]: item for item in baseline["items"]}
    baseline_kanzi = {
        row["item_id"]: row
        for row in baseline["summary"]["item_codec_rows"]
        if row["codec_id"] == "kanzi-max"
    }
    for item in structural["items"]:
        baseline_item = baseline_items.get(item["id"])
        baseline_row = baseline_kanzi.get(item["id"])
        if baseline_item is None or baseline_row is None:
            raise ValueError("structural item is absent from the bound baseline")
        expected = {
            "track": baseline_item["track"],
            "source_bytes": baseline_item["source_bytes"],
            "source_sha256": baseline_item["source_sha256"],
            "baseline_bytes": baseline_row["artifact_bytes"],
            "baseline_compression_peak_rss_bytes": baseline_row[
                "compression_peak_rss_bytes"
            ],
            "baseline_decompression_peak_rss_bytes": baseline_row[
                "decompression_peak_rss_bytes"
            ],
        }
        if any(item.get(key) != value for key, value in expected.items()):
            raise ValueError(
                f"structural item disagrees with bound baseline: {item['id']}"
            )
    structural_sha256 = sha256_bytes(structural_raw)
    public_evidence = build_public_evidence(
        results_path,
        structural,
        structural_results_sha256=structural_sha256,
        raw_structural_receipts_manifest_sha256=structural_receipts_sha256,
        baseline_results_sha256=baseline_sha256,
        baseline_public_evidence_sha256=baseline_public_evidence_sha256,
    )
    public_evidence_payload = json.loads(public_evidence)
    comparison = derive(
        structural,
        baseline,
        structural_sha256=structural_sha256,
        structural_receipts_sha256=structural_receipts_sha256,
        baseline_sha256=baseline_sha256,
        baseline_receipts_sha256=baseline_receipts_sha256,
        public_evidence_sha256=sha256_bytes(public_evidence),
        baseline_public_evidence_sha256=baseline_public_evidence_sha256,
        public_receipts_sha256=public_evidence_payload[
            "public_structural_trial_receipts_manifest_sha256"
        ],
        failed_trial_count=failed_trial_count,
    )
    artifacts = {
        "evidence.json": public_evidence,
        "comparison.json": json_bytes(comparison),
        "comparison.svg": render_svg(comparison).encode("utf-8"),
        "README.md": render_markdown(comparison).encode("utf-8"),
    }
    receipt = {
        "schema_version": 1,
        "name": "text-source-structural-transform-development-publication-receipt-v1",
        "structural_results_sha256": comparison["structural_results_sha256"],
        "structural_trial_receipts_manifest_sha256": comparison[
            "structural_trial_receipts_manifest_sha256"
        ],
        "baseline_results_sha256": comparison["baseline_results_sha256"],
        "baseline_trial_receipts_manifest_sha256": comparison[
            "baseline_trial_receipts_manifest_sha256"
        ],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "baseline_public_evidence_sha256": comparison[
            "baseline_public_evidence_sha256"
        ],
        "public_structural_trial_receipts_manifest_sha256": comparison[
            "public_structural_trial_receipts_manifest_sha256"
        ],
        "bindings": comparison["bindings"],
        "artifacts": {
            name: sha256_bytes(payload) for name, payload in artifacts.items()
        },
        "claim_ceiling": comparison["claim_ceiling"],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(results_path: Path, baseline_path: Path, output: Path) -> Path:
    artifacts = build_artifacts(results_path, baseline_path)
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ValueError("refusing non-directory publication destination")
        observed = {path.name for path in output.iterdir()}
        if observed != set(artifacts):
            raise ValueError("refusing publication directory with differing roster")
        for name, expected in artifacts.items():
            path = output / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise ValueError(
                    f"refusing to replace differing publication artifact: {name}"
                )
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="text-source-structural-publication-", dir=output.parent
    ) as raw:
        staging = Path(raw) / "publication"
        staging.mkdir()
        for name, payload in artifacts.items():
            (staging / name).write_bytes(payload)
        staging.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.results.parent / "publication"
    try:
        published = publish(args.results, args.baseline, output)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"structural publication refused: {error}") from error
    print(published)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
