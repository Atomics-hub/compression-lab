#!/usr/bin/env python3
"""Publish the TS-P1/WK-P1 entropy-ceiling result beside every practical codec."""

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
DEFAULT_RESULT = REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-v1.json"
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-predictor-probe-v1.json"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY / "runs" / "text-source-predictor-entropy-ceiling-publication-v1"
)
TRACK_LABELS = {
    "source_code_bundles": "Source-code evaluation: Rust + LLVM",
    "english_wikimedia_wikitext": "Wikimedia evaluation: English Wikiversity",
}
VARIANT_LABELS = {
    "p0-adaptive-byte-unigram": "Axiom P0 byte unigram estimate",
    "p1-adaptive-byte-previous-class": "Axiom P1 byte/class estimate",
    "p2-adaptive-mixed-token-previous-class": "Axiom P2 mixed token/class estimate",
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_script(
    "predictor_ceiling_runner_for_publication",
    REPOSITORY / "scripts" / "benchmark-text-source-predictor-ceiling.py",
)
BASELINE_PUBLICATION = load_script(
    "baseline_publication_for_predictor_ceiling",
    REPOSITORY / "scripts" / "publish-text-source-baseline-census.py",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return raw, value


def aggregate_baseline_rows(
    baseline: dict[str, Any], track: str, item_ids: list[str]
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in baseline["summary"]["item_codec_rows"]
        if row["track"] == track and row["item_id"] in item_ids
    ]
    codec_ids = list(BASELINE_PUBLICATION.CODEC_LABELS)
    rows = []
    for codec_id in codec_ids:
        group = [row for row in selected if row["codec_id"] == codec_id]
        if len(group) != len(item_ids) or not all(row["passed"] for row in group):
            raise ValueError(f"predictor baseline subset is incomplete: {codec_id}")
        source_bytes = sum(row["source_bytes"] for row in group)
        complete_bytes = sum(row["artifact_bytes"] for row in group)
        compression_ns = sum(row["median_compression_ns"] for row in group)
        decompression_ns = sum(row["median_decompression_ns"] for row in group)
        rows.append(
            {
                "kind": "practical_baseline",
                "id": codec_id,
                "label": BASELINE_PUBLICATION.CODEC_LABELS[codec_id],
                "source_bytes": source_bytes,
                "complete_bytes": complete_bytes,
                "ratio": source_bytes / complete_bytes,
                "size_percent": complete_bytes / source_bytes * 100.0,
                "compression_mbps": source_bytes / (1024 * 1024) / (compression_ns / 1e9),
                "decompression_mbps": source_bytes / (1024 * 1024) / (decompression_ns / 1e9),
                "compression_peak_rss_mib": max(
                    row["compression_peak_rss_bytes"] for row in group
                )
                / (1024 * 1024),
                "decompression_peak_rss_mib": max(
                    row["decompression_peak_rss_bytes"] for row in group
                )
                / (1024 * 1024),
                "exact": True,
                "deterministic": True,
                "portability": "same-host evidence only",
                "axiom_beat": "not established",
                "decision": "tested practical baseline",
            }
        )
    return rows


def derive(result: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    if (
        result.get("name") != "text-source-predictor-entropy-ceiling-result-v1"
        or result.get("completed") is not True
        or result.get("full_codec_build_admissions") != 0
        or result.get("axiom_wins") != 0
        or [row.get("track") for row in result.get("tracks", [])]
        != list(TRACK_LABELS)
    ):
        raise ValueError("predictor result identity or decision differs")
    tracks = []
    for track_result in result["tracks"]:
        track = track_result["track"]
        evaluation_ids = track_result["evaluation_items"]
        source_bytes = sum(item["source_bytes"] for item in track_result["items"])
        rows = aggregate_baseline_rows(baseline, track, evaluation_ids)
        for aggregate in track_result["aggregates"]:
            variant = aggregate["variant"]
            complete_bytes = aggregate["projected_complete_aggregate_bytes"]
            rows.append(
                {
                    "kind": "axiom_entropy_estimate",
                    "id": variant,
                    "label": VARIANT_LABELS[variant],
                    "source_bytes": source_bytes,
                    "complete_bytes": complete_bytes,
                    "ratio": source_bytes / complete_bytes,
                    "size_percent": complete_bytes / source_bytes * 100.0,
                    "compression_mbps": None,
                    "decompression_mbps": None,
                    "compression_peak_rss_mib": None,
                    "decompression_peak_rss_mib": None,
                    "exact": False,
                    "deterministic": False,
                    "portability": "not an artifact",
                    "axiom_beat": "ineligible estimate",
                    "decision": (
                        track_result["decision"]
                        if variant == RUNNER.VARIANTS[2]
                        else "diagnostic ablation only"
                    ),
                }
            )
        tracks.append(
            {
                "track_id": track,
                "track": TRACK_LABELS[track],
                "evaluation_items": evaluation_ids,
                "training_items": track_result["training_items"],
                "dictionary": track_result["dictionary"],
                "dictionary_gain_over_byte_previous_class_percent": track_result[
                    "dictionary_gain_over_byte_previous_class_percent"
                ],
                "full_codec_build_admitted": False,
                "rows": rows,
            }
        )
    return {
        "schema_version": 1,
        "name": "text-source-predictor-entropy-ceiling-publication-v1",
        "stage": "sampled development entropy-ceiling probe",
        "bindings": result["bindings"],
        "tracks": tracks,
        "integrity": {
            "result_recomputed_from_frozen_samples": True,
            "all_15_practical_codecs_visible": True,
            "estimated_rows_are_not_artifacts": True,
            "full_codec_build_admissions": 0,
            "axiom_wins": 0,
        },
        "runner_comparability": {
            "size": "Predictor rows are conservative sampled ideal-code projections and are not comparable as complete decodable artifacts; practical rows are exact complete bytes on the identical evaluation items.",
            "speed_memory": "No predictor speed or memory claim exists; practical rows retain measured same-host values.",
        },
        "validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "claim_ceiling": result["claim_ceiling"],
    }


def display(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value:.2f}{suffix}"


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# TS-P1 / WK-P1 predictor entropy-ceiling result",
        "",
        "![Predictor estimates and every practical standard](comparison.svg)",
        "",
        f"> **Claim ceiling:** {comparison['claim_ceiling']}",
        "",
        "The predictor rows are conservative ideal-code estimates, not decodable archives. They cannot beat a standard or support a codec claim.",
        "",
        "Every tested practical standard remains visible on the identical evaluation subset.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                f"Dictionary: **{track['dictionary']['bytes']:,} bytes**, **{track['dictionary']['entry_count']:,} entries**. "
                f"P2 improvement over P1: **{track['dictionary_gain_over_byte_previous_class_percent']:.2f}%**. "
                "Full-codec admission: **no**.",
                "",
                "| Codec / estimate | Complete or projected bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in track["rows"]:
            integrity = "✅ / ✅" if row["exact"] and row["deterministic"] else "— / —"
            lines.append(
                f"| {row['label']} | {display(row['complete_bytes'])} | "
                f"{display(row['ratio'], 'x')} | {display(row['size_percent'], '%')} | "
                f"{display(row['compression_mbps'])} | {display(row['decompression_mbps'])} | "
                f"{display(row['compression_peak_rss_mib'])} / {display(row['decompression_peak_rss_mib'])} | "
                f"{integrity} | {row['portability']} | {row['axiom_beat']} | {row['decision']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Evidence boundary",
            "",
            f"- Result SHA-256: `{comparison['result_sha256']}`.",
            f"- Public evidence SHA-256: `{comparison['public_evidence_sha256']}`.",
            f"- Runner comparability (size): {comparison['runner_comparability']['size']}",
            f"- Runner comparability (speed/memory): {comparison['runner_comparability']['speed_memory']}",
            "- Public validation and private holdout remain sealed and unaccessed.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    width = 1450
    row_height = 25
    height = 130 + sum(85 + len(track["rows"]) * row_height for track in comparison["tracks"])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#172033}.title{font-size:25px;font-weight:700}.sub{font-size:13px;fill:#526078}.track{font-size:18px;font-weight:700}.head{font-size:11px;font-weight:700;fill:#526078}.row{font-size:11px}.estimate{font-size:11px;font-weight:700;fill:#a13d2d}.num{font-size:11px;font-variant-numeric:tabular-nums}</style>",
        '<rect width="100%" height="100%" fill="#fbfcff"/>',
        '<text class="title" x="28" y="38">Axiom TS-P1 / WK-P1 entropy-ceiling probe</text>',
        '<text class="sub" x="28" y="62">All practical standards remain visible; predictor rows are ineligible estimates and both successors are rejected.</text>',
    ]
    y = 100
    for track in comparison["tracks"]:
        parts.append(f'<text class="track" x="28" y="{y}">{escape(track["track"])}</text>')
        y += 24
        headers = [(28, "Codec / estimate", "start"), (560, "Bytes", "end"), (650, "Ratio", "end"), (740, "Size %", "end"), (850, "C MB/s", "end"), (960, "D MB/s", "end"), (1080, "RSS C/D", "end"), (1190, "Exact/Det", "middle"), (1320, "Status", "middle")]
        for x, label, anchor in headers:
            parts.append(f'<text class="head" x="{x}" y="{y}" text-anchor="{anchor}">{label}</text>')
        y += 18
        for index, row in enumerate(track["rows"]):
            if index % 2 == 0:
                parts.append(f'<rect x="20" y="{y - 15}" width="1405" height="{row_height}" rx="3" fill="#f0f4fa"/>')
            css = "estimate" if row["kind"] == "axiom_entropy_estimate" else "row"
            integrity = "yes/yes" if row["exact"] else "—/—"
            values = [
                (28, row["label"], "start", css),
                (560, display(row["complete_bytes"]), "end", "num"),
                (650, display(row["ratio"], "x"), "end", "num"),
                (740, display(row["size_percent"], "%"), "end", "num"),
                (850, display(row["compression_mbps"]), "end", "num"),
                (960, display(row["decompression_mbps"]), "end", "num"),
                (1080, f"{display(row['compression_peak_rss_mib'])}/{display(row['decompression_peak_rss_mib'])}", "end", "num"),
                (1190, integrity, "middle", "num"),
                (1320, row["axiom_beat"], "middle", "num"),
            ]
            for x, value, anchor, klass in values:
                parts.append(f'<text class="{klass}" x="{x}" y="{y + 3}" text-anchor="{anchor}">{escape(str(value))}</text>')
            y += row_height
        y += 35
    parts.append(f'<text class="sub" x="28" y="{height - 25}">{escape(comparison["claim_ceiling"])}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_artifacts(
    result_path: Path, config_path: Path, baseline_path: Path
) -> dict[str, bytes]:
    verification = RUNNER.verify(
        config_path=config_path,
        corpus=RUNNER.DEFAULT_CORPUS,
        baseline_path=baseline_path,
        output=result_path,
    )
    result_raw, result = read_canonical(result_path)
    config_raw, config = read_canonical(config_path)
    baseline_raw, baseline = read_canonical(baseline_path)
    BASELINE_PUBLICATION.validate_trial_receipts(baseline_path, baseline)
    evidence = {
        "schema_version": 1,
        "name": "text-source-predictor-entropy-ceiling-public-evidence-v1",
        "result_sha256": sha256_bytes(result_raw),
        "config_sha256": sha256_bytes(config_raw),
        "baseline_results_sha256": sha256_bytes(baseline_raw),
        "result_verification": verification,
        "config": config,
        "result": result,
    }
    evidence_raw = json_bytes(evidence)
    comparison = derive(result, baseline)
    comparison["result_sha256"] = evidence["result_sha256"]
    comparison["public_evidence_sha256"] = sha256_bytes(evidence_raw)
    artifacts = {
        "evidence.json": evidence_raw,
        "comparison.json": json_bytes(comparison),
        "comparison.svg": render_svg(comparison).encode("utf-8"),
        "README.md": render_markdown(comparison).encode("utf-8"),
    }
    receipt = {
        "schema_version": 1,
        "name": "text-source-predictor-entropy-ceiling-publication-receipt-v1",
        "result_sha256": comparison["result_sha256"],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "artifacts": {name: sha256_bytes(payload) for name, payload in artifacts.items()},
        "claim_ceiling": comparison["claim_ceiling"],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(result: Path, config: Path, baseline: Path, output: Path) -> Path:
    artifacts = build_artifacts(result, config, baseline)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or {path.name for path in output.iterdir()} != set(artifacts):
            raise ValueError("predictor publication destination differs")
        for name, payload in artifacts.items():
            if (output / name).read_bytes() != payload:
                raise ValueError(f"predictor publication artifact differs: {name}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="predictor-publication-", dir=output.parent) as raw:
        staging = Path(raw) / "publication"
        staging.mkdir()
        for name, payload in artifacts.items():
            (staging / name).write_bytes(payload)
        staging.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = publish(args.result, args.config, args.baseline, args.output)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"predictor publication failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
