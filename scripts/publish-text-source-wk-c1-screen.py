#!/usr/bin/env python3
"""Publish a retained WK-C1 training screen from offline evidence only."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "text-source-wk-c1-screen-v1.json"
RUNNER_PATH = ROOT / "scripts" / "benchmark-text-source-wk-c1-screen.py"
TRANSFORM_PATH = ROOT / "scripts" / "text-source-wk-c1-transform.py"
RUN_VERIFIER_PATH = ROOT / "scripts" / "verify-text-source-wk-c1-screen-run.py"
PROTOCOL_PATH = (
    ROOT / "docs" / "benchmarks" / "2026-07-18-text-source-wk-c1-protocol.md"
)
DEFAULT_RUN = ROOT / "runs" / "text-source-wk-c1-screen-v1"
DEFAULT_OUTPUT = DEFAULT_RUN / "publication"
FROZEN_DEPENDENCIES = {
    "config/text-source-wk-c1-screen-v1.json": "af334f5528df39535e484ba28b36c8363443305f90d8fac35f5943a7a94d3270",
    "docs/benchmarks/2026-07-18-text-source-wk-c1-protocol.md": "febfd22003021654269a66f24fa06de3b9c97c6c3a0370b9884adbdc6978b278",
    "scripts/benchmark-text-source-wk-c1-screen.py": "f434fe9e1e244166a729435d33af4d20534747bfdfd085156de568d31ed71f4b",
    "scripts/text-source-wk-c1-transform.py": "dcee5264690befb493360d28dbc4465a587471741788fdabc3aae2137d0408e7",
    "scripts/verify-text-source-wk-c1-screen-run.py": "2bb331666c1e55546a1bcbc9c94b192071a3ce7a33fb8d2df6ffdb79b060f580",
}
EXPECTED_FILES = {
    "README.md",
    "benchmark.log",
    "comparison.json",
    "comparison.svg",
    "evidence.json",
    "provenance.txt",
    "receipt.json",
    "results.json",
}
RESULT_KEYS = {
    "schema_version", "name", "completed", "all_required_completed", "trial_count",
    "trial_receipts_manifest_sha256", "bindings", "screen_boundary", "measurement",
    "preflight", "premeasurement_resource_smoke", "variants", "summary",
    "claim_ceiling", "public_validation_status", "private_holdout_status",
}
TRIAL_KEYS = {
    "schema_version", "bindings", "variant", "item_id", "track", "repetition",
    "source_bytes", "source_sha256", "transform_file_evidence",
    "artifact_file_evidence", "artifact_bytes", "artifact_sha256", "encode_processes",
    "decode_processes", "encode_totals", "decode_totals", "encode_peak_rss_bytes",
    "decode_peak_rss_bytes", "exact_roundtrip", "passed", "error",
}
PROCESS_KEYS = {
    "command", "returncode", "timed_out", "wall_ns", "cpu_ns", "peak_rss_bytes",
    "stdout", "stderr",
}
SMOKE_KEYS = {
    "variant", "item_id", "source_bytes", "source_sha256", "transform_file_evidence",
    "encode", "backend_encode", "backend_decode", "decode", "maximum_peak_rss_bytes",
    "exact_roundtrip", "passed", "error",
}
TRANSFORM_EVIDENCE_KEYS = {
    "magic", "version", "variant", "source_bytes", "source_sha256", "header_bytes",
    "metadata_bytes", "value_stream_bytes", "complete_transform_bytes",
    "template_count", "field_count", "sha256",
}


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected an ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return raw, value


def require_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has unexpected fields")
    return value


def require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} is not a lowercase SHA-256")
    return value


def validate_dependencies() -> None:
    for relative, expected in FROZEN_DEPENDENCIES.items():
        path = ROOT / relative
        if sha256_file(path) != expected:
            raise RuntimeError(f"frozen WK-C1 dependency drifted: {relative}")


validate_dependencies()
RUNNER = load_script("wk_c1_runner_for_publication", RUNNER_PATH)
RUN_VERIFY = load_script("wk_c1_run_verifier_for_publication", RUN_VERIFIER_PATH)


def validate_process(value: object, label: str) -> dict[str, Any]:
    process = require_keys(value, PROCESS_KEYS, label)
    RUNNER.validate_process_record(process)
    if (
        process["returncode"] != 0
        or process["timed_out"] is not False
        or not process["command"]
    ):
        raise ValueError(f"{label} is not a successful bounded process")
    return process


def validate_transform_evidence(value: object, *, variant: str, label: str) -> None:
    row = require_keys(value, TRANSFORM_EVIDENCE_KEYS, label)
    if (
        row["magic"] != "WKC1"
        or row["version"] != 1
        or row["variant"] != variant
        or type(row["source_bytes"]) is not int
        or row["source_bytes"] <= 0
        or row["header_bytes"] != RUNNER.TRANSFORM.HEADER.size
        or any(
            type(row[key]) is not int or row[key] < 0
            for key in (
                "metadata_bytes", "value_stream_bytes", "template_count", "field_count"
            )
        )
        or row["complete_transform_bytes"]
        != row["header_bytes"] + row["metadata_bytes"] + row["value_stream_bytes"]
    ):
        raise ValueError(f"{label} accounting differs")
    require_sha256(row["source_sha256"], f"{label} source digest")
    require_sha256(row["sha256"], f"{label} transform digest")


def validate_strict_result(
    result: dict[str, Any], config: dict[str, Any], trials: list[dict[str, Any]]
) -> None:
    RUNNER.validate_config(config)
    require_keys(result, RESULT_KEYS, "WK-C1 result")
    expected_binding_keys = {"repository_commit", "config_sha256", "transform_sha256"} | set(
        config["bindings"]
    )
    bindings = require_keys(result["bindings"], expected_binding_keys, "WK-C1 bindings")
    if (
        not isinstance(bindings["repository_commit"], str)
        or len(bindings["repository_commit"]) != 40
        or any(
            character not in "0123456789abcdef"
            for character in bindings["repository_commit"]
        )
    ):
        raise ValueError("repository commit is not a lowercase 40-character Git hash")
    for key in expected_binding_keys - {"repository_commit"}:
        require_sha256(bindings[key], f"binding {key}")
    if (
        result["schema_version"] != 1
        or result["name"]
        != "text-source-wk-c1-recursive-template-columnarization-screen-result-v1"
        or result["screen_boundary"] != config["splits"]
        or result["measurement"] != config["measurement"]
        or result["variants"] != config["variants"]
        or result["claim_ceiling"] != config["claim_ceiling"]
        or any(bindings[key] != value for key, value in config["bindings"].items())
    ):
        raise ValueError("WK-C1 result identity or frozen contract differs")
    for row in result["preflight"]:
        require_keys(
            row,
            {"variant", "source_bytes", "transform_bytes", "transform_sha256", "exact_roundtrip", "deterministic_transform"},
            "WK-C1 preflight row",
        )
    RUN_VERIFY.validate_preflight(result["preflight"])
    if not isinstance(result["premeasurement_resource_smoke"], list):
        raise ValueError("WK-C1 resource smoke is not a list")
    for row in result["premeasurement_resource_smoke"]:
        smoke = require_keys(row, SMOKE_KEYS, "WK-C1 resource smoke row")
        variant = smoke["variant"]
        require_keys(smoke["transform_file_evidence"], {"size_bytes", "sha256"}, "smoke transform evidence")
        require_sha256(smoke["transform_file_evidence"]["sha256"], "smoke transform digest")
        for key in ("encode", "backend_encode", "backend_decode", "decode"):
            validate_process(smoke[key], f"smoke {key}")
        if smoke["passed"] is not True or smoke["exact_roundtrip"] is not True or smoke["error"] is not None:
            raise ValueError("WK-C1 resource smoke did not pass exactly")
        if variant not in RUNNER.VARIANTS:
            raise ValueError("WK-C1 resource smoke variant differs")
    RUN_VERIFY.validate_resource_smoke(result["premeasurement_resource_smoke"], config)
    if len(trials) != 8:
        raise ValueError("WK-C1 must contain exactly eight retained trials")
    expected = set(RUNNER.schedule(config))
    observed: set[tuple[str, str, int]] = set()
    for receipt in trials:
        require_keys(receipt, TRIAL_KEYS, "WK-C1 trial receipt")
        key = (receipt["variant"], receipt["item_id"], receipt["repetition"])
        if key in observed:
            raise ValueError("WK-C1 trial schedule contains a duplicate")
        observed.add(key)
        require_keys(receipt["artifact_file_evidence"], {"size_bytes", "sha256"}, "artifact evidence")
        require_sha256(receipt["artifact_file_evidence"]["sha256"], "artifact digest")
        validate_transform_evidence(receipt["transform_file_evidence"], variant=receipt["variant"], label="trial transform evidence")
        for group in ("encode_processes", "decode_processes"):
            if not isinstance(receipt[group], list) or len(receipt[group]) != 3:
                raise ValueError(f"WK-C1 {group} must contain three processes")
            for index, process in enumerate(receipt[group]):
                validate_process(process, f"{group}[{index}]")
        for totals_key, processes_key in (
            ("encode_totals", "encode_processes"), ("decode_totals", "decode_processes")
        ):
            require_keys(receipt[totals_key], {"wall_ns", "cpu_ns", "peak_rss_bytes"}, totals_key)
            if receipt[totals_key] != RUNNER.aggregate_processes(receipt[processes_key]):
                raise ValueError(f"WK-C1 {totals_key} does not reconstruct")
        if receipt["passed"] is not True or receipt["exact_roundtrip"] is not True or receipt["error"] is not None:
            raise ValueError("WK-C1 trial is not an exact successful decode")
        RUN_VERIFY.validate_receipt(
            receipt,
            bindings=bindings,
            variant=receipt["variant"],
            item_id=receipt["item_id"],
            repetition=receipt["repetition"],
        )
    if observed != expected:
        raise ValueError("WK-C1 trial schedule differs from the frozen eight trials")
    expected_summary = RUNNER.summarize(trials, config)
    if result["summary"] != expected_summary:
        raise ValueError("WK-C1 summary differs from receipt recomputation")
    if result["all_required_completed"] is not True or result["completed"] is not True:
        raise ValueError("WK-C1 result is incomplete")
    if result["trial_count"] != 8 or result["summary"].get("axiom_wins") != 0:
        raise ValueError("WK-C1 result count or claim differs")
    if result["public_validation_status"] != "sealed and unaccessed" or result["private_holdout_status"] != "sealed and unaccessed":
        raise ValueError("WK-C1 sealed split status differs")


def trial_manifest(rows: list[dict[str, Any]]) -> str:
    return sha256_bytes(json_bytes({"trials": [{"path": row["path"], "sha256": row["sha256"]} for row in rows]}))


def collect_run(run: Path) -> tuple[bytes, dict[str, Any], bytes, dict[str, Any], list[dict[str, Any]]]:
    if run.is_symlink() or not run.is_dir():
        raise ValueError("WK-C1 run must be an ordinary directory")
    config_raw, config = read_canonical(CONFIG)
    result_raw, result = read_canonical(run / "results.json")
    expected_paths = {
        run / "trials" / variant / f"{item}.r{repetition}.json"
        for variant, item, repetition in RUNNER.schedule(config)
    }
    observed_paths = set((run / "trials").glob("*/*.json"))
    if observed_paths != expected_paths or any(path.is_symlink() for path in observed_paths):
        raise ValueError("WK-C1 retained trial file roster differs")
    rows: list[dict[str, Any]] = []
    trials: list[dict[str, Any]] = []
    for path in sorted(expected_paths):
        raw, receipt = read_canonical(path)
        rows.append({"path": path.relative_to(run).as_posix(), "sha256": sha256_bytes(raw), "receipt": receipt})
        trials.append(receipt)
    validate_strict_result(result, config, trials)
    if result["bindings"]["config_sha256"] != sha256_bytes(config_raw):
        raise ValueError("WK-C1 config binding differs")
    if result["bindings"]["transform_sha256"] != FROZEN_DEPENDENCIES["scripts/text-source-wk-c1-transform.py"]:
        raise ValueError("WK-C1 transform binding differs")
    if result["trial_receipts_manifest_sha256"] != trial_manifest(rows):
        raise ValueError("WK-C1 retained receipt manifest differs")
    return config_raw, config, result_raw, result, rows


def _median_two(values: list[int]) -> float:
    if len(values) != 2:
        raise ValueError("WK-C1 metric requires two repetitions")
    return (values[0] + values[1]) / 2.0


def derive(config: dict[str, Any], result: dict[str, Any], trials: list[dict[str, Any]], *, result_sha256: str, evidence_sha256: str) -> dict[str, Any]:
    gate = config["decision"]["track_gate"]
    summary = result["summary"]
    summary_variants = {row["variant"]: row for row in summary["variants"]}
    item_summary = {(row["variant"], row["item_id"]): row for row in summary["item_rows"]}
    source_by_item: dict[str, int] = {}
    for row in trials:
        source_by_item.setdefault(row["item_id"], row["source_bytes"])
        if source_by_item[row["item_id"]] != row["source_bytes"]:
            raise ValueError("WK-C1 source byte identity differs across receipts")
    total_source = sum(source_by_item.values())
    controls = [
        {"id": "kanzi-max", "label": "Kanzi-max", "complete_bytes": gate["kanzi_max_complete_bytes"], "gain_vs_kanzi_percent": 0.0, "measurement": "immutable census control", "exact": True, "deterministic": True, "peak_rss_bytes": None, "compression_mbps": None, "decompression_mbps": None},
        {"id": "ts-h1", "label": "TS-H1", "complete_bytes": gate["ts_h1_complete_bytes"], "gain_vs_kanzi_percent": (gate["kanzi_max_complete_bytes"] - gate["ts_h1_complete_bytes"]) / gate["kanzi_max_complete_bytes"] * 100.0, "measurement": "immutable two-item control", "exact": True, "deterministic": True, "peak_rss_bytes": None, "compression_mbps": None, "decompression_mbps": None},
    ]
    candidates = []
    for variant in RUNNER.VARIANTS:
        selected = [row for row in trials if row["variant"] == variant]
        encode_by_rep = [sum(row["encode_totals"]["wall_ns"] for row in selected if row["repetition"] == repetition) for repetition in range(2)]
        decode_by_rep = [sum(row["decode_totals"]["wall_ns"] for row in selected if row["repetition"] == repetition) for repetition in range(2)]
        complete_bytes = summary_variants[variant]["artifact_bytes"]
        candidates.append({
            "id": variant,
            "label": "WK-C1 full schema columns" if variant == RUNNER.VARIANTS[0] else "WK-C1 structure-only",
            "complete_bytes": complete_bytes,
            "gain_vs_kanzi_percent": (gate["kanzi_max_complete_bytes"] - complete_bytes) / gate["kanzi_max_complete_bytes"] * 100.0,
            "gain_vs_ts_h1_percent": (gate["ts_h1_complete_bytes"] - complete_bytes) / gate["ts_h1_complete_bytes"] * 100.0,
            "compression_mbps": total_source / _median_two(encode_by_rep) * 1000.0,
            "decompression_mbps": total_source / _median_two(decode_by_rep) * 1000.0,
            "peak_rss_bytes": max(max(row["encode_peak_rss_bytes"], row["decode_peak_rss_bytes"]) for row in selected),
            "measurement": "WK-C1 training screen, two exact repetitions",
            "exact": all(row["exact_roundtrip"] for row in selected),
            "deterministic": all(item_summary[(variant, item)]["deterministic_artifact"] for item in RUNNER.SCREEN_ITEMS),
            "item_rows": [item_summary[(variant, item)] for item in RUNNER.SCREEN_ITEMS],
        })
    full = candidates[0]
    structure = candidates[1]
    gates = {
        "complete_bytes_recomputed": full["complete_bytes"],
        "signal_1_percent_vs_kanzi": full["complete_bytes"] <= gate["signal_maximum_complete_bytes"],
        "strong_2_percent_vs_kanzi": full["complete_bytes"] <= gate["strong_maximum_complete_bytes"],
        "one_percent_vs_ts_h1": full["complete_bytes"] <= gate["full_maximum_complete_bytes_to_beat_ts_h1_by_one_percent"],
        "attribution_half_percent_vs_structure_only": full["complete_bytes"] * 10000 <= structure["complete_bytes"] * 9950,
        "all_item_guards": all(row["item_guard_passed"] for row in full["item_rows"]),
        "all_resource_guards": all(row["resource_limit_passed"] for row in full["item_rows"]),
        "exact_and_deterministic": full["exact"] and full["deterministic"],
        "full_signal": summary["full_signal"],
        "full_strong_signal": summary["full_strong_signal"],
    }
    return {
        "schema_version": 1,
        "name": "text-source-wk-c1-public-comparison-v1",
        "result_sha256": result_sha256,
        "public_evidence_sha256": evidence_sha256,
        "frozen_dependencies": FROZEN_DEPENDENCIES,
        "source_bytes": total_source,
        "schedule": [{"ordinal": index, "variant": variant, "item_id": item, "repetition": repetition} for index, (variant, item, repetition) in enumerate(RUNNER.schedule(config), start=1)],
        "controls": controls,
        "candidates": candidates,
        "gates": gates,
        "decision": summary["decision"],
        "rejected": summary["decision"] == "reject_wk_c1_recursive_template_columnarization",
        "axiom_wins": 0,
        "screen_scope": "training-only English Wikibooks + Wikinews",
        "sealed_splits": {"public_validation": result["public_validation_status"], "private_holdout": result["private_holdout_status"], "reserved_evaluation": "sealed and unaccessed"},
        "claim_ceiling": result["claim_ceiling"],
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    rows = [*comparison["controls"], *comparison["candidates"]]
    def metric(value: object, suffix: str = "") -> str:
        return "not measured in this screen" if value is None else f"{float(value):.2f}{suffix}"
    decision = comparison["decision"].replace("_", " ")
    rejection = " **WK-C1 is rejected on this training split.**" if comparison["rejected"] else ""
    lines = [
        "# WK-C1 recursive template/schema columnarization screen",
        "",
        f"Decision: **{decision}**.{rejection}",
        "",
        "This is an offline publication of a frozen, training-only screen. `axiom_wins = 0`. Public validation, private holdout, and reserved evaluation remained sealed and unaccessed.",
        "",
        "![Complete-byte comparison](comparison.svg)",
        "",
        "| Candidate/control | Complete bytes | Gain vs Kanzi-max | Compress MB/s | Decompress MB/s | Peak RSS MiB | Exact / deterministic |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        rss = None if row["peak_rss_bytes"] is None else row["peak_rss_bytes"] / 1024**2
        lines.append(f"| {row['label']} | {row['complete_bytes']:,} | {row['gain_vs_kanzi_percent']:+.3f}% | {metric(row['compression_mbps'])} | {metric(row['decompression_mbps'])} | {metric(rss)} | {'yes' if row['exact'] and row['deterministic'] else 'no'} |")
    lines.extend([
        "",
        "The candidate byte counts are physical complete AXWK2 artifacts: the WKC1 frame, every data-derived table/permutation/stream, Kanzi payload, integrity metadata, and wrapper are counted. Candidate speeds sum all three encode/decode subprocesses; control speeds and memory are not remeasured here and are shown as unavailable.",
        "",
        "## Frozen gates",
        "",
    ])
    for key, value in sorted(comparison["gates"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Claim ceiling",
        "",
        comparison["claim_ceiling"],
        "",
        f"Evidence SHA-256: `{comparison['public_evidence_sha256']}`. Result SHA-256: `{comparison['result_sha256']}`.",
        "",
    ])
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    rows = [*comparison["controls"], *comparison["candidates"]]
    maximum = max(row["complete_bytes"] for row in rows)
    width, height = 980, 380
    bars = []
    for index, row in enumerate(rows):
        y = 98 + index * 54
        bar_width = 560 * row["complete_bytes"] / maximum
        color = "#64748b" if index < 2 else ("#2563eb" if index == 2 else "#7c3aed")
        bars.append(f'<text x="24" y="{y + 18}" font-size="14">{html.escape(row["label"])}</text><rect x="300" y="{y}" width="{bar_width:.2f}" height="25" rx="4" fill="{color}"/><text x="{310 + bar_width:.2f}" y="{y + 18}" font-size="13">{row["complete_bytes"]:,}</text>')
    decision = html.escape(comparison["decision"].replace("_", " "))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        '<text x="24" y="34" font-size="22" font-weight="700">WK-C1 complete-byte comparison</text>'
        '<text x="24" y="60" font-size="14">Training-only screen · exact complete artifacts · Axiom wins = 0</text>'
        + "".join(bars)
        + f'<text x="24" y="330" font-size="13">Decision: {decision}; validation and holdout sealed.</text>'
        + '<text x="24" y="354" font-size="13">Claim ceiling: training-only diagnostic; not a product, validation, holdout, independent, or SOTA result.</text></svg>\n'
    )


def build_evidence(config: dict[str, Any], result: dict[str, Any], trial_rows: list[dict[str, Any]]) -> dict[str, Any]:
    trials = [row["receipt"] for row in trial_rows]
    verification = {
        "verified": True,
        "offline": True,
        "trial_count": 8,
        "schedule": [{"variant": a, "item_id": b, "repetition": c} for a, b, c in RUNNER.schedule(config)],
        "complete_bytes_recomputed": {row["variant"]: row["artifact_bytes"] for row in RUNNER.summarize(trials, config)["variants"]},
        "decision": result["summary"]["decision"],
        "axiom_wins": 0,
    }
    return {
        "schema_version": 1,
        "name": "text-source-wk-c1-public-evidence-v1",
        "frozen_dependencies": FROZEN_DEPENDENCIES,
        "config": config,
        "config_sha256": sha256_bytes(json_bytes(config)),
        "results": result,
        "result_sha256": sha256_bytes(json_bytes(result)),
        "trials": trial_rows,
        "trial_receipts_manifest_sha256": trial_manifest(trial_rows),
        "run_verification": verification,
    }


def validate_evidence(evidence: dict[str, Any]) -> None:
    require_keys(evidence, {"schema_version", "name", "frozen_dependencies", "config", "config_sha256", "results", "result_sha256", "trials", "trial_receipts_manifest_sha256", "run_verification"}, "WK-C1 public evidence")
    if evidence["schema_version"] != 1 or evidence["name"] != "text-source-wk-c1-public-evidence-v1" or evidence["frozen_dependencies"] != FROZEN_DEPENDENCIES:
        raise ValueError("WK-C1 public evidence identity differs")
    if evidence["config_sha256"] != sha256_bytes(json_bytes(evidence["config"])) or evidence["result_sha256"] != sha256_bytes(json_bytes(evidence["results"])):
        raise ValueError("WK-C1 public evidence content hashes differ")
    if not isinstance(evidence["trials"], list) or len(evidence["trials"]) != 8:
        raise ValueError("WK-C1 public trial evidence count differs")
    paths = set()
    receipts = []
    for row in evidence["trials"]:
        require_keys(row, {"path", "sha256", "receipt"}, "WK-C1 public trial row")
        if not isinstance(row["path"], str) or not row["path"].startswith("trials/") or row["path"] in paths:
            raise ValueError("WK-C1 public trial path differs")
        paths.add(row["path"])
        if row["sha256"] != sha256_bytes(json_bytes(row["receipt"])):
            raise ValueError("WK-C1 public trial hash differs")
        receipts.append(row["receipt"])
    if evidence["trial_receipts_manifest_sha256"] != trial_manifest(evidence["trials"]):
        raise ValueError("WK-C1 public trial manifest differs")
    RUNNER.validate_config(evidence["config"])
    validate_strict_result(evidence["results"], evidence["config"], receipts)
    expected = build_evidence(evidence["config"], evidence["results"], evidence["trials"])
    if evidence != expected:
        raise ValueError("WK-C1 public evidence does not reconstruct")


def publish(*, run: Path, provenance: Path, benchmark_log: Path, output: Path) -> dict[str, Any]:
    validate_dependencies()
    for path, label in ((provenance, "provenance"), (benchmark_log, "benchmark log")):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"WK-C1 {label} must be an ordinary file")
    config_raw, config, result_raw, result, trial_rows = collect_run(run)
    evidence = build_evidence(config, result, trial_rows)
    validate_evidence(evidence)
    evidence_raw = json_bytes(evidence)
    comparison = derive(config, result, [row["receipt"] for row in trial_rows], result_sha256=sha256_bytes(result_raw), evidence_sha256=sha256_bytes(evidence_raw))
    receipt = {
        "schema_version": 1,
        "name": "text-source-wk-c1-publication-receipt-v1",
        "result_sha256": comparison["result_sha256"],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "trial_receipts_manifest_sha256": evidence["trial_receipts_manifest_sha256"],
        "frozen_dependencies": FROZEN_DEPENDENCIES,
        "decision": comparison["decision"],
        "axiom_wins": 0,
        "claim_ceiling": comparison["claim_ceiling"],
        "artifacts": {},
    }
    if output.exists():
        raise ValueError("refusing to overwrite an existing WK-C1 publication")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wk-c1-publication-", dir=output.parent) as raw:
        stage = Path(raw) / "publication"
        stage.mkdir()
        (stage / "README.md").write_text(render_markdown(comparison), encoding="utf-8")
        (stage / "comparison.json").write_bytes(json_bytes(comparison))
        (stage / "comparison.svg").write_text(render_svg(comparison), encoding="utf-8")
        (stage / "evidence.json").write_bytes(evidence_raw)
        (stage / "results.json").write_bytes(result_raw)
        shutil.copyfile(provenance, stage / "provenance.txt")
        shutil.copyfile(benchmark_log, stage / "benchmark.log")
        receipt["artifacts"] = {name: sha256_file(stage / name) for name in EXPECTED_FILES - {"receipt.json"}}
        (stage / "receipt.json").write_bytes(json_bytes(receipt))
        os.replace(stage, output)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--benchmark-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        receipt = publish(run=args.run, provenance=args.provenance, benchmark_log=args.benchmark_log, output=args.output)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"WK-C1 publication failed: {error}") from error
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
