#!/usr/bin/env python3
"""Publish the frozen long-range decomposition screen beside every practical codec."""

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
DEFAULT_RUN = REPOSITORY / "runs" / "text-source-long-range-screen-v1"
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-long-range-screen-v1.json"
DEFAULT_BASELINE = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "results.json"
)
DEFAULT_BASELINE_PUBLICATION = (
    REPOSITORY / "runs" / "text-source-development-baseline-census-v1" / "publication"
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
VARIANT_LABELS = {
    "k1-lzp-prepend-level9": "K1 custom Kanzi: LZP + level-9 transforms + TPAQX",
    "k2-lzp-text-utf": "K2 custom Kanzi: LZP + TEXT + UTF + TPAQX",
    "k3-lzp-only": "K3 custom Kanzi: LZP + TPAQX",
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_script(
    "long_range_screen_runner_for_publication",
    REPOSITORY / "scripts" / "benchmark-text-source-long-range-screen.py",
)
RUN_VERIFY = load_script(
    "long_range_screen_verifier_for_publication",
    REPOSITORY / "scripts" / "verify-text-source-long-range-screen-run.py",
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
    manifest = {
        "trials": [
            {"path": row["path"], "sha256": row["sha256"]}
            for row in sorted(rows, key=lambda row: row["path"])
        ]
    }
    return sha256_bytes(json_bytes(manifest))


def validate_public_evidence(evidence: dict[str, Any]) -> None:
    if (
        evidence.get("name")
        != "text-source-long-range-kanzi-decomposition-public-evidence-v1"
        or evidence.get("schema_version") != 1
        or not isinstance(evidence.get("trials"), list)
        or len(evidence["trials"]) != 24
        or evidence.get("raw_trial_receipts_manifest_sha256")
        != receipt_manifest(evidence["trials"])
        or evidence.get("public_trial_receipts_manifest_sha256")
        != receipt_manifest(evidence["trials"])
    ):
        raise ValueError("long-range public evidence identity or manifest differs")
    paths: set[str] = set()
    for row in evidence["trials"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"path", "sha256", "receipt"}
            or not isinstance(row["path"], str)
            or not row["path"].startswith("trials/")
            or row["path"].startswith("/")
            or row["path"] in paths
            or row["sha256"] != sha256_bytes(json_bytes(row["receipt"]))
        ):
            raise ValueError("long-range public trial evidence differs")
        paths.add(row["path"])
    encoded = json.dumps(evidence, sort_keys=True)
    if str(REPOSITORY) in encoded or '"/Users/' in encoded:
        raise ValueError("long-range public evidence contains a local absolute path")


def aggregate_baseline_rows(
    baseline: dict[str, Any], track: str, item_ids: list[str]
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in baseline["summary"]["item_codec_rows"]
        if row["track"] == track and row["item_id"] in item_ids
    ]
    rows = []
    for codec_id, label in BASELINE_PUBLICATION.CODEC_LABELS.items():
        group = [row for row in selected if row["codec_id"] == codec_id]
        if len(group) != len(item_ids) or not all(row["passed"] for row in group):
            raise ValueError(f"long-range baseline subset is incomplete: {codec_id}")
        source_bytes = sum(row["source_bytes"] for row in group)
        complete_bytes = sum(row["artifact_bytes"] for row in group)
        compression_ns = sum(row["median_compression_ns"] for row in group)
        decompression_ns = sum(row["median_decompression_ns"] for row in group)
        rows.append(
            {
                "kind": "practical_baseline",
                "id": codec_id,
                "label": label,
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
                "axiom_beat": "no Axiom artifact",
                "decision": "tested practical standard",
            }
        )
    return rows


def derive(
    result: dict[str, Any],
    baseline: dict[str, Any],
    *,
    result_sha256: str,
    receipts_sha256: str,
    baseline_results_sha256: str,
    baseline_public_evidence_sha256: str,
    public_evidence_sha256: str,
) -> dict[str, Any]:
    summary = result.get("summary", {})
    if (
        result.get("name")
        != "text-source-long-range-kanzi-decomposition-screen-result-v1"
        or result.get("completed") is not True
        or result.get("trial_count") != 24
        or summary.get("axiom_prototype_admitted") is not False
        or summary.get("axiom_wins") != 0
        or summary.get("selected_variant") is not None
        or summary.get("decision")
        != "reject_shared_implicit_long_range_factorization_direction"
    ):
        raise ValueError("long-range result identity or decision differs")
    item_rows = summary["item_rows"]
    tracks = []
    for track_result in summary["tracks"]:
        track = track_result["track"]
        item_ids = track_result["screen_items"]
        rows = aggregate_baseline_rows(baseline, track, item_ids)
        source_bytes = sum(
            row["source_bytes"]
            for row in item_rows
            if row["track"] == track and row["variant"] == result["variants"][0]["id"]
        )
        for variant_result in track_result["variants"]:
            variant = variant_result["variant"]
            group = [
                row
                for row in item_rows
                if row["track"] == track and row["variant"] == variant
            ]
            if len(group) != len(item_ids) or not all(row["passed"] for row in group):
                raise ValueError(f"long-range diagnostic subset is incomplete: {variant}")
            compression_ns = sum(row["median_compression_ns"] for row in group)
            decompression_ns = sum(row["median_decompression_ns"] for row in group)
            complete_bytes = variant_result["artifact_bytes"]
            rows.append(
                {
                    "kind": "competitor_diagnostic",
                    "id": variant,
                    "label": VARIANT_LABELS[variant],
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
                    "portability": "custom Kanzi, same-host evidence only",
                    "axiom_beat": "not applicable: competitor diagnostic",
                    "decision": (
                        f"rejected: {variant_result['gain_vs_kanzi_percent']:.2f}% vs Kanzi max"
                    ),
                    "gain_vs_kanzi_percent": variant_result[
                        "gain_vs_kanzi_percent"
                    ],
                    "minimum_item_gain_vs_kanzi_percent": variant_result[
                        "minimum_item_gain_vs_kanzi_percent"
                    ],
                }
            )
        rows.append(
            {
                "kind": "axiom_unbuilt",
                "id": "axiom-long-range-prototype",
                "label": "Axiom long-range prototype (not built)",
                "source_bytes": source_bytes,
                "complete_bytes": None,
                "ratio": None,
                "size_percent": None,
                "compression_mbps": None,
                "decompression_mbps": None,
                "compression_peak_rss_mib": None,
                "decompression_peak_rss_mib": None,
                "exact": False,
                "deterministic": False,
                "portability": "no artifact",
                "axiom_beat": "no artifact; no win",
                "decision": "prototype not admitted; direction rejected",
            }
        )
        tracks.append(
            {
                "track_id": track,
                "track": TRACK_LABELS[track],
                "screen_items": item_ids,
                "baseline": "Kanzi max (level 9)",
                "best_diagnostic": max(
                    track_result["variants"],
                    key=lambda row: row["gain_vs_kanzi_percent"],
                )["variant"],
                "prototype_admitted": False,
                "rows": rows,
            }
        )
    return {
        "schema_version": 1,
        "name": "text-source-long-range-kanzi-decomposition-publication-v1",
        "stage": "training-only deterministic decomposition screen",
        "bindings": result["bindings"],
        "result_sha256": result_sha256,
        "trial_receipts_manifest_sha256": receipts_sha256,
        "baseline_results_sha256": baseline_results_sha256,
        "baseline_public_evidence_sha256": baseline_public_evidence_sha256,
        "public_evidence_sha256": public_evidence_sha256,
        "tracks": tracks,
        "integrity": {
            "trial_count": 24,
            "exact_deterministic_item_variant_count": 12,
            "all_15_practical_codecs_visible": True,
            "custom_kanzi_diagnostic_count": 3,
            "axiom_prototype_admitted": False,
            "axiom_wins": 0,
        },
        "runner_comparability": {
            "size": "All rows with bytes are complete decodable archives over the identical track subset. The Axiom row is intentionally empty because no prototype was admitted.",
            "speed_memory": "Practical and custom Kanzi rows retain measured same-host medians and peak RSS; cross-runner timings are directional, not controlled hardware-independent rankings.",
        },
        "decision": summary["decision"],
        "public_validation_status": "sealed and unaccessed",
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
        "# Long-range factorization screen: rejected",
        "",
        "![Long-range diagnostics and every practical standard](comparison.svg)",
        "",
        f"> **Claim ceiling:** {comparison['claim_ceiling']}",
        "",
        "The screen tested whether explicit single-reference LZP factorization improves Kanzi's TPAQX path. It did not. No Axiom codec was built, admitted, or credited with a win.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                "| Codec / diagnostic | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |",
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
            f"- Frozen result SHA-256: `{comparison['result_sha256']}`.",
            f"- Trial-receipt manifest SHA-256: `{comparison['trial_receipts_manifest_sha256']}`.",
            f"- Public evidence SHA-256: `{comparison['public_evidence_sha256']}`.",
            f"- Runner comparability (size): {comparison['runner_comparability']['size']}",
            f"- Runner comparability (speed/memory): {comparison['runner_comparability']['speed_memory']}",
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
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#172033}.title{font-size:25px;font-weight:700}.sub{font-size:13px;fill:#526078}.track{font-size:18px;font-weight:700}.head{font-size:11px;font-weight:700;fill:#526078}.row{font-size:11px}.diagnostic{font-size:11px;font-weight:700;fill:#8a4b16}.rejected{font-size:11px;font-weight:700;fill:#a13d2d}.num{font-size:11px;font-variant-numeric:tabular-nums}</style>",
        '<rect width="100%" height="100%" fill="#fbfcff"/>',
        '<text class="title" x="28" y="38">Axiom long-range factorization screen — rejected</text>',
        '<text class="sub" x="28" y="62">24/24 exact trials; all 15 practical standards visible; no Axiom artifact and no Axiom win.</text>',
    ]
    y = 100
    for track in comparison["tracks"]:
        parts.append(f'<text class="track" x="28" y="{y}">{escape(track["track"])}</text>')
        y += 24
        headers = [(28, "Codec / diagnostic", "start"), (650, "Bytes", "end"), (740, "Ratio", "end"), (830, "Size %", "end"), (940, "C MB/s", "end"), (1050, "D MB/s", "end"), (1170, "RSS C/D", "end"), (1290, "Exact/Det", "middle"), (1410, "Status", "middle")]
        for x, label, anchor in headers:
            parts.append(f'<text class="head" x="{x}" y="{y}" text-anchor="{anchor}">{label}</text>')
        y += 18
        for index, row in enumerate(track["rows"]):
            if index % 2 == 0:
                parts.append(f'<rect x="20" y="{y - 15}" width="1455" height="{row_height}" rx="3" fill="#f0f4fa"/>')
            css = {"competitor_diagnostic": "diagnostic", "axiom_unbuilt": "rejected"}.get(row["kind"], "row")
            integrity = "yes/yes" if row["exact"] else "—/—"
            status = "diagnostic" if row["kind"] == "competitor_diagnostic" else row["axiom_beat"]
            values = [
                (28, row["label"], "start", css),
                (650, display(row["complete_bytes"]), "end", "num"),
                (740, display(row["ratio"], "x"), "end", "num"),
                (830, display(row["size_percent"], "%"), "end", "num"),
                (940, display(row["compression_mbps"]), "end", "num"),
                (1050, display(row["decompression_mbps"]), "end", "num"),
                (1170, f"{display(row['compression_peak_rss_mib'])}/{display(row['decompression_peak_rss_mib'])}", "end", "num"),
                (1290, integrity, "middle", "num"),
                (1410, status, "middle", "num"),
            ]
            for x, value, anchor, klass in values:
                parts.append(f'<text class="{klass}" x="{x}" y="{y + 3}" text-anchor="{anchor}">{escape(str(value))}</text>')
            y += row_height
        y += 35
    parts.append(f'<text class="sub" x="28" y="{height - 25}">{escape(comparison["claim_ceiling"])}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def collect_trials(run: Path) -> list[dict[str, Any]]:
    trial_root = run / "trials"
    paths = sorted(trial_root.glob("*/*.json"))
    if len(paths) != 24 or any(path.is_symlink() for path in paths):
        raise ValueError("long-range trial receipt roster differs")
    rows = []
    for path in paths:
        raw, receipt = read_canonical(path)
        rows.append(
            {
                "path": path.relative_to(run).as_posix(),
                "sha256": sha256_bytes(raw),
                "receipt": receipt,
            }
        )
    return rows


def build_artifacts(
    run: Path,
    config_path: Path,
    baseline_path: Path,
    baseline_publication: Path,
) -> dict[str, bytes]:
    verification = RUN_VERIFY.verify(
        config_path=config_path,
        corpus=RUN_VERIFY.DEFAULT_CORPUS,
        baseline_path=baseline_path,
        predictor_result_path=RUN_VERIFY.DEFAULT_PREDICTOR_RESULT,
        kanzi=RUN_VERIFY.DEFAULT_KANZI,
        output=run,
    )
    result_raw, result = read_canonical(run / "results.json")
    config_raw, config = read_canonical(config_path)
    baseline_raw, baseline = read_canonical(baseline_path)
    baseline_evidence_raw, baseline_evidence = read_canonical(
        baseline_publication / "evidence.json"
    )
    if (
        baseline_evidence.get("raw_results_sha256") != sha256_bytes(baseline_raw)
        or baseline_evidence.get("results") != baseline
    ):
        raise ValueError("baseline publication does not bind the raw baseline")
    trials = collect_trials(run)
    manifest_sha256 = receipt_manifest(trials)
    evidence = {
        "schema_version": 1,
        "name": "text-source-long-range-kanzi-decomposition-public-evidence-v1",
        "result_sha256": sha256_bytes(result_raw),
        "config_sha256": sha256_bytes(config_raw),
        "baseline_results_sha256": sha256_bytes(baseline_raw),
        "baseline_public_evidence_sha256": sha256_bytes(baseline_evidence_raw),
        "raw_trial_receipts_manifest_sha256": manifest_sha256,
        "public_trial_receipts_manifest_sha256": manifest_sha256,
        "redaction_policy": "Commands retain only $REPOSITORY and $WORK placeholders; stdout and stderr are preserved because they contain no local paths.",
        "run_verification": verification,
        "config": config,
        "results": result,
        "trials": trials,
    }
    validate_public_evidence(evidence)
    evidence_raw = json_bytes(evidence)
    comparison = derive(
        result,
        baseline,
        result_sha256=evidence["result_sha256"],
        receipts_sha256=manifest_sha256,
        baseline_results_sha256=evidence["baseline_results_sha256"],
        baseline_public_evidence_sha256=evidence[
            "baseline_public_evidence_sha256"
        ],
        public_evidence_sha256=sha256_bytes(evidence_raw),
    )
    artifacts = {
        "evidence.json": evidence_raw,
        "comparison.json": json_bytes(comparison),
        "comparison.svg": render_svg(comparison).encode("utf-8"),
        "README.md": render_markdown(comparison).encode("utf-8"),
    }
    receipt = {
        "schema_version": 1,
        "name": "text-source-long-range-kanzi-decomposition-publication-receipt-v1",
        "result_sha256": comparison["result_sha256"],
        "trial_receipts_manifest_sha256": comparison[
            "trial_receipts_manifest_sha256"
        ],
        "baseline_results_sha256": comparison["baseline_results_sha256"],
        "baseline_public_evidence_sha256": comparison[
            "baseline_public_evidence_sha256"
        ],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "bindings": comparison["bindings"],
        "artifacts": {name: sha256_bytes(payload) for name, payload in artifacts.items()},
        "claim_ceiling": comparison["claim_ceiling"],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(
    run: Path,
    config: Path,
    baseline: Path,
    baseline_publication: Path,
    output: Path,
) -> Path:
    artifacts = build_artifacts(run, config, baseline, baseline_publication)
    if output.exists():
        if (
            output.is_symlink()
            or not output.is_dir()
            or {path.name for path in output.iterdir()} != set(artifacts)
        ):
            raise ValueError("long-range publication destination differs")
        for name, payload in artifacts.items():
            if (output / name).read_bytes() != payload:
                raise ValueError(f"long-range publication artifact differs: {name}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="long-range-publication-", dir=output.parent) as raw:
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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = publish(
            args.run,
            args.config,
            args.baseline,
            args.baseline_publication,
            args.output,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"long-range publication failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
