#!/usr/bin/env python3
"""Publish the rejected record-neighborhood screen beside every practical codec."""

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
DEFAULT_RUN = REPOSITORY / "runs" / "text-source-record-neighborhood-screen-v1"
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-record-neighborhood-screen-v1.json"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
)
DEFAULT_STRUCTURAL_RESULT = (
    REPOSITORY / "runs" / "text-source-structural-transform-development-v1" / "results.json"
)
DEFAULT_OUTPUT = DEFAULT_RUN / "publication"
EXPECTED_FILES = {
    "README.md",
    "comparison.json",
    "comparison.svg",
    "evidence.json",
    "receipt.json",
}
TRACK_LABELS = {
    "source_code_bundles": "Source-code screen: CPython + TypeScript",
    "english_wikimedia_wikitext": "Wikimedia screen: English Wikibooks + Wikinews",
}


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


RUNNER = load_script(
    "record_neighborhood_runner_for_publication",
    REPOSITORY / "scripts" / "benchmark-text-source-record-neighborhood-screen.py",
)
RUN_VERIFY = load_script(
    "record_neighborhood_verifier_for_publication",
    REPOSITORY / "scripts" / "verify-text-source-record-neighborhood-run.py",
)
LONG_PUBLICATION = load_script(
    "long_range_publication_helpers_for_record_neighborhood",
    REPOSITORY / "scripts" / "publish-text-source-long-range-screen.py",
)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_canonical(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary JSON file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != json_bytes(value):
        raise ValueError(f"JSON is not canonical: {path}")
    return raw, value


def receipt_manifest(rows: list[dict[str, Any]]) -> str:
    return sha256_bytes(
        json_bytes(
            {
                "trials": [
                    {"path": row["path"], "sha256": row["sha256"]}
                    for row in sorted(rows, key=lambda row: row["path"])
                ]
            }
        )
    )


def collect_trials(run: Path) -> list[dict[str, Any]]:
    paths = sorted((run / "trials").glob("*/*.json"))
    if len(paths) != 8 or any(path.is_symlink() for path in paths):
        raise ValueError("record-neighborhood trial receipt roster differs")
    rows = []
    for path in paths:
        raw, receipt = read_canonical(path)
        rows.append(
            {
                "path": path.relative_to(run).as_posix(),
                "receipt": receipt,
                "sha256": sha256_bytes(raw),
            }
        )
    return rows


def validate_public_evidence(evidence: dict[str, Any]) -> None:
    trials = evidence.get("trials")
    if (
        evidence.get("name")
        != "text-source-record-neighborhood-public-evidence-v1"
        or evidence.get("schema_version") != 1
        or not isinstance(trials, list)
        or len(trials) != 8
        or evidence.get("raw_trial_receipts_manifest_sha256")
        != receipt_manifest(trials)
        or evidence.get("public_trial_receipts_manifest_sha256")
        != receipt_manifest(trials)
        or not isinstance(evidence.get("structural_control_rows"), list)
        or len(evidence["structural_control_rows"]) != 4
    ):
        raise ValueError("record-neighborhood public evidence identity differs")
    paths: set[str] = set()
    for row in trials:
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "receipt", "sha256"}
            or not isinstance(row["path"], str)
            or not row["path"].startswith("trials/")
            or row["path"].startswith("/")
            or row["path"] in paths
            or row["sha256"] != sha256_bytes(json_bytes(row["receipt"]))
        ):
            raise ValueError("record-neighborhood public trial evidence differs")
        paths.add(row["path"])
    encoded = json.dumps(evidence, sort_keys=True)
    if str(REPOSITORY) in encoded or '"/Users/' in encoded:
        raise ValueError("record-neighborhood public evidence contains a local path")


def speed(source_bytes: int, nanoseconds: int) -> float:
    return source_bytes / (1024 * 1024) / (nanoseconds / 1e9)


def derive(
    result: dict[str, Any],
    baseline: dict[str, Any],
    structural_control_rows: list[dict[str, Any]],
    *,
    result_sha256: str,
    receipts_sha256: str,
    baseline_results_sha256: str,
    baseline_public_evidence_sha256: str,
    public_evidence_sha256: str,
) -> dict[str, Any]:
    summary = result.get("summary", {})
    if (
        result.get("name") != "text-source-record-neighborhood-screen-result-v1"
        or result.get("completed") is not True
        or result.get("trial_count") != 8
        or summary.get("axiom_prototype_admitted") is not False
        or summary.get("axiom_wins") != 0
        or summary.get("selected_variant") is not None
        or summary.get("decision")
        != "reject_bounded_record_neighborhood_shared_successor"
    ):
        raise ValueError("record-neighborhood result identity or decision differs")
    controls = {row["item_id"]: row for row in structural_control_rows}
    if len(controls) != 4 or any(row.get("variant") != "ts-h1-demux" for row in controls.values()):
        raise ValueError("record-neighborhood structural control roster differs")
    tracks = []
    for track_result in summary["tracks"]:
        track = track_result["track"]
        item_ids = track_result["screen_items"]
        rows = LONG_PUBLICATION.aggregate_baseline_rows(baseline, track, item_ids)
        candidate_items = [
            row
            for row in summary["item_rows"]
            if row["track"] == track and row["variant"] == RUNNER.VARIANT
        ]
        if len(candidate_items) != len(item_ids) or not all(
            row["passed"] for row in candidate_items
        ):
            raise ValueError("record-neighborhood candidate subset differs")
        source_bytes = sum(row["source_bytes"] for row in candidate_items)
        candidate_bytes = track_result["candidate_bytes"]
        for row in rows:
            gain = (row["complete_bytes"] - candidate_bytes) / row["complete_bytes"] * 100.0
            row["gain_for_axiom_percent"] = gain
            row["axiom_beat"] = "yes" if gain > 0 else "no"
            row["decision"] = f"Q1 {abs(gain):.2f}% {'smaller' if gain > 0 else 'larger'}"
        control_group = [controls[item_id] for item_id in item_ids]
        control_bytes = sum(row["candidate_bytes"] for row in control_group)
        control_compression_ns = sum(row["median_compression_ns"] for row in control_group)
        control_decompression_ns = sum(row["median_decompression_ns"] for row in control_group)
        control_gain = (control_bytes - candidate_bytes) / control_bytes * 100.0
        rows.append(
            {
                "axiom_beat": "yes" if control_gain > 0 else "no",
                "complete_bytes": control_bytes,
                "compression_mbps": speed(source_bytes, control_compression_ns),
                "compression_peak_rss_mib": max(
                    row["compression_peak_rss_bytes"] for row in control_group
                )
                / (1024 * 1024),
                "decision": f"Q1 {abs(control_gain):.2f}% {'smaller' if control_gain > 0 else 'larger'}",
                "decompression_mbps": speed(source_bytes, control_decompression_ns),
                "decompression_peak_rss_mib": max(
                    row["decompression_peak_rss_bytes"] for row in control_group
                )
                / (1024 * 1024),
                "deterministic": True,
                "exact": True,
                "gain_for_axiom_percent": control_gain,
                "id": "ts-h1-demux-control",
                "kind": "attribution_control",
                "label": "TS-H1 exact demux control",
                "portability": "experimental Python transform + Kanzi; same-host evidence",
                "ratio": source_bytes / control_bytes,
                "size_percent": control_bytes / source_bytes * 100.0,
                "source_bytes": source_bytes,
            }
        )
        candidate_compression_ns = sum(
            row["median_compression_ns"] for row in candidate_items
        )
        candidate_decompression_ns = sum(
            row["median_decompression_ns"] for row in candidate_items
        )
        rows.append(
            {
                "axiom_beat": "candidate",
                "complete_bytes": candidate_bytes,
                "compression_mbps": speed(source_bytes, candidate_compression_ns),
                "compression_peak_rss_mib": max(
                    row["compression_peak_rss_bytes"] for row in candidate_items
                )
                / (1024 * 1024),
                "decision": (
                    f"rejected: {track_result['gain_vs_kanzi_percent']:.2f}% vs Kanzi max; "
                    f"{track_result['gain_vs_structural_control_percent']:.2f}% vs TS-H1"
                ),
                "decompression_mbps": speed(source_bytes, candidate_decompression_ns),
                "decompression_peak_rss_mib": max(
                    row["decompression_peak_rss_bytes"] for row in candidate_items
                )
                / (1024 * 1024),
                "deterministic": True,
                "exact": True,
                "gain_vs_kanzi_percent": track_result["gain_vs_kanzi_percent"],
                "gain_vs_structural_control_percent": track_result[
                    "gain_vs_structural_control_percent"
                ],
                "id": RUNNER.VARIANT,
                "kind": "axiom_experimental_candidate",
                "label": "Axiom Q1 bounded record-neighborhood",
                "portability": "experimental Python transform + Kanzi; same-host evidence",
                "ratio": source_bytes / candidate_bytes,
                "size_percent": candidate_bytes / source_bytes * 100.0,
                "source_bytes": source_bytes,
            }
        )
        tracks.append(
            {
                "baseline": "Kanzi max (level 9)",
                "candidate_admitted": False,
                "rows": rows,
                "screen_items": item_ids,
                "track": TRACK_LABELS[track],
                "track_id": track,
            }
        )
    return {
        "baseline_public_evidence_sha256": baseline_public_evidence_sha256,
        "baseline_results_sha256": baseline_results_sha256,
        "bindings": result["bindings"],
        "claim_ceiling": result["claim_ceiling"],
        "decision": summary["decision"],
        "integrity": {
            "all_15_practical_codecs_visible": True,
            "axiom_prototype_admitted": False,
            "axiom_wins": 0,
            "exact_deterministic_candidate_item_count": 4,
            "structural_attribution_control_count": 1,
            "trial_count": 8,
        },
        "name": "text-source-record-neighborhood-publication-v1",
        "private_holdout_status": "sealed and unaccessed",
        "public_evidence_sha256": public_evidence_sha256,
        "public_validation_status": "sealed and unaccessed",
        "result_sha256": result_sha256,
        "runner_comparability": {
            "size": "Every byte row is a complete decodable artifact over the identical two-item track subset. Q1 includes transform metadata, permutation, backend payload, and outer frame.",
            "speed_memory": "Practical, TS-H1, and Q1 rows retain measured same-host medians and peak RSS. Cross-run timings are directional because background load and runner overhead differ.",
        },
        "schema_version": 1,
        "stage": "training-only deterministic Axiom representation screen",
        "tracks": tracks,
        "trial_receipts_manifest_sha256": receipts_sha256,
    }


def display(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value:.2f}{suffix}"


def render_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Axiom Q1 record-neighborhood screen: rejected",
        "",
        "![Axiom Q1 compared with every practical standard](comparison.svg)",
        "",
        f"> **Claim ceiling:** {comparison['claim_ceiling']}",
        "",
        "Q1 was exact and deterministic, but every measured item became larger than the strongest control. It is rejected and earns no category win. The tables retain all 15 practical standards and the prior TS-H1 attribution control.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                "| Codec / candidate | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Q1 beat it? | Decision |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for row in track["rows"]:
            integrity = "✅ / ✅" if row["exact"] and row["deterministic"] else "❌ / ❌"
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
            f"- Frozen result SHA-256: `{comparison['result_sha256']}`.",
            f"- Trial-receipt manifest SHA-256: `{comparison['trial_receipts_manifest_sha256']}`.",
            f"- Public evidence SHA-256: `{comparison['public_evidence_sha256']}`.",
            f"- Size comparability: {comparison['runner_comparability']['size']}",
            f"- Speed/memory comparability: {comparison['runner_comparability']['speed_memory']}",
            "- Public validation and private holdout were not opened.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    width = 1500
    row_height = 25
    height = 130 + sum(85 + len(track["rows"]) * row_height for track in comparison["tracks"])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#172033}.title{font-size:25px;font-weight:700}.sub{font-size:13px;fill:#526078}.track{font-size:18px;font-weight:700}.head{font-size:11px;font-weight:700;fill:#526078}.row{font-size:11px}.control{font-size:11px;font-weight:700;fill:#725a13}.candidate{font-size:11px;font-weight:700;fill:#a13d2d}.num{font-size:11px;font-variant-numeric:tabular-nums}</style>",
        '<rect width="100%" height="100%" fill="#fbfcff"/>',
        '<text class="title" x="28" y="38">Axiom Q1 record-neighborhood screen — rejected</text>',
        '<text class="sub" x="28" y="62">8/8 exact trials; 4/4 deterministic item artifacts; all 15 practical standards visible; Q1 lost both tracks.</text>',
    ]
    y = 100
    for track in comparison["tracks"]:
        parts.append(f'<text class="track" x="28" y="{y}">{escape(track["track"])}</text>')
        y += 24
        headers = [(28, "Codec / candidate", "start"), (650, "Bytes", "end"), (740, "Ratio", "end"), (830, "Size %", "end"), (940, "C MB/s", "end"), (1050, "D MB/s", "end"), (1170, "RSS C/D", "end"), (1290, "Exact/Det", "middle"), (1410, "Q1 beat?", "middle")]
        for x, label, anchor in headers:
            parts.append(f'<text class="head" x="{x}" y="{y}" text-anchor="{anchor}">{label}</text>')
        y += 18
        for index, row in enumerate(track["rows"]):
            if index % 2 == 0:
                parts.append(f'<rect x="20" y="{y - 15}" width="1455" height="{row_height}" rx="3" fill="#f0f4fa"/>')
            css = {"attribution_control": "control", "axiom_experimental_candidate": "candidate"}.get(row["kind"], "row")
            values = [
                (28, row["label"], "start", css),
                (650, display(row["complete_bytes"]), "end", "num"),
                (740, display(row["ratio"], "x"), "end", "num"),
                (830, display(row["size_percent"], "%"), "end", "num"),
                (940, display(row["compression_mbps"]), "end", "num"),
                (1050, display(row["decompression_mbps"]), "end", "num"),
                (1170, f"{display(row['compression_peak_rss_mib'])}/{display(row['decompression_peak_rss_mib'])}", "end", "num"),
                (1290, "yes/yes", "middle", "num"),
                (1410, row["axiom_beat"], "middle", css),
            ]
            for x, value, anchor, klass in values:
                parts.append(f'<text class="{klass}" x="{x}" y="{y + 3}" text-anchor="{anchor}">{escape(str(value))}</text>')
            y += row_height
        y += 35
    parts.append(f'<text class="sub" x="28" y="{height - 25}">{escape(comparison["claim_ceiling"])}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_artifacts(
    run: Path,
    config_path: Path,
    baseline_path: Path,
    baseline_publication: Path,
    structural_result_path: Path,
) -> dict[str, bytes]:
    verification = RUN_VERIFY.verify(
        config_path=config_path,
        corpus=RUNNER.DEFAULT_CORPUS,
        baseline_path=baseline_path,
        structural_result_path=structural_result_path,
        structural_evidence_path=RUNNER.DEFAULT_STRUCTURAL_EVIDENCE,
        long_range_result_path=RUNNER.DEFAULT_LONG_RANGE_RESULT,
        transform=RUNNER.DEFAULT_TRANSFORM,
        kanzi=RUNNER.DEFAULT_KANZI,
        output=run,
    )
    result_raw, result = read_canonical(run / "results.json")
    config_raw, config = read_canonical(config_path)
    baseline_raw, baseline = read_canonical(baseline_path)
    baseline_evidence_raw, baseline_evidence = read_canonical(
        baseline_publication / "evidence.json"
    )
    structural_raw, structural = read_canonical(structural_result_path)
    if (
        baseline_evidence.get("raw_results_sha256") != sha256_bytes(baseline_raw)
        or baseline_evidence.get("results") != baseline
        or sha256_bytes(structural_raw)
        != config["bindings"]["structural_results_sha256"]
    ):
        raise ValueError("record-neighborhood predecessor publication differs")
    structural_control_rows = [
        row for row in structural["summary"]["item_rows"] if row["variant"] == "ts-h1-demux"
    ]
    selected_ids = {
        item_id
        for split in config["splits"].values()
        for item_id in split["screen_items"]
    }
    structural_control_rows = [
        row for row in structural_control_rows if row["item_id"] in selected_ids
    ]
    trials = collect_trials(run)
    manifest_sha256 = receipt_manifest(trials)
    evidence = {
        "baseline_public_evidence_sha256": sha256_bytes(baseline_evidence_raw),
        "baseline_results_sha256": sha256_bytes(baseline_raw),
        "config": config,
        "config_sha256": sha256_bytes(config_raw),
        "name": "text-source-record-neighborhood-public-evidence-v1",
        "public_trial_receipts_manifest_sha256": manifest_sha256,
        "raw_trial_receipts_manifest_sha256": manifest_sha256,
        "redaction_policy": "Commands retain only $REPOSITORY and $WORK placeholders; stdout and stderr contain no local absolute paths.",
        "result_sha256": sha256_bytes(result_raw),
        "results": result,
        "run_verification": verification,
        "schema_version": 1,
        "structural_control_rows": structural_control_rows,
        "structural_results_sha256": sha256_bytes(structural_raw),
        "trials": trials,
    }
    validate_public_evidence(evidence)
    evidence_raw = json_bytes(evidence)
    comparison = derive(
        result,
        baseline,
        structural_control_rows,
        result_sha256=evidence["result_sha256"],
        receipts_sha256=manifest_sha256,
        baseline_results_sha256=evidence["baseline_results_sha256"],
        baseline_public_evidence_sha256=evidence[
            "baseline_public_evidence_sha256"
        ],
        public_evidence_sha256=sha256_bytes(evidence_raw),
    )
    artifacts = {
        "README.md": render_markdown(comparison).encode("utf-8"),
        "comparison.json": json_bytes(comparison),
        "comparison.svg": render_svg(comparison).encode("utf-8"),
        "evidence.json": evidence_raw,
    }
    receipt = {
        "artifacts": {name: sha256_bytes(payload) for name, payload in artifacts.items()},
        "baseline_public_evidence_sha256": comparison[
            "baseline_public_evidence_sha256"
        ],
        "baseline_results_sha256": comparison["baseline_results_sha256"],
        "bindings": comparison["bindings"],
        "claim_ceiling": comparison["claim_ceiling"],
        "name": "text-source-record-neighborhood-publication-receipt-v1",
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "result_sha256": comparison["result_sha256"],
        "schema_version": 1,
        "trial_receipts_manifest_sha256": comparison[
            "trial_receipts_manifest_sha256"
        ],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(
    run: Path,
    config: Path,
    baseline: Path,
    baseline_publication: Path,
    structural_result: Path,
    output: Path,
) -> Path:
    artifacts = build_artifacts(
        run, config, baseline, baseline_publication, structural_result
    )
    if output.exists():
        if (
            output.is_symlink()
            or not output.is_dir()
            or {path.name for path in output.iterdir()} != set(artifacts)
        ):
            raise ValueError("record-neighborhood publication destination differs")
        for name, payload in artifacts.items():
            if (output / name).read_bytes() != payload:
                raise ValueError(f"record-neighborhood publication differs: {name}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="record-neighborhood-publication-", dir=output.parent
    ) as raw:
        staging = Path(raw) / "publication"
        staging.mkdir()
        for name, payload in artifacts.items():
            (staging / name).write_bytes(payload)
        staging.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--baseline-publication", type=Path, default=DEFAULT_BASELINE_PUBLICATION
    )
    parser.add_argument(
        "--structural-result", type=Path, default=DEFAULT_STRUCTURAL_RESULT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = publish(
            args.run,
            args.config,
            args.baseline,
            args.baseline_publication,
            args.structural_result,
            args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"record-neighborhood publication failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
