#!/usr/bin/env python3
"""Publish the completed BWT screen from retained JSON evidence only."""

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
DEFAULT_RUN = REPOSITORY / "runs" / "text-source-bwt-screen-v1"
DEFAULT_CONFIG = REPOSITORY / "config" / "text-source-bwt-screen-v1.json"
DEFAULT_OUTPUT = DEFAULT_RUN / "publication"
EXPECTED_FILES = {
    "README.md",
    "comparison.json",
    "comparison.svg",
    "evidence.json",
    "receipt.json",
}
TRACK_LABELS = {
    "source_code_bundles": "Source code: CPython + TypeScript",
    "english_wikimedia_wikitext": "English Wikimedia: Wikibooks + Wikinews",
}
VARIANT_LABELS = {
    "tb1-text-bwt-tpaqx-direct": "TB1 TEXT + UTF + BWT / TPAQX",
    "tb2-text-bwt-srt-zrlt-tpaqx": "TB2 TEXT + UTF + BWT + SRT + ZRLT / TPAQX",
    "tb3-text-bwt-srt-zrlt-fpaq-control": "TB3 level-6 control / FPAQ",
    "tb4-raw-bwt-srt-zrlt-tpaqx": "TB4 raw BWT + SRT + ZRLT / TPAQX",
}


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


RUNNER = load_script(
    "bwt_runner_for_offline_publication",
    REPOSITORY / "scripts" / "benchmark-text-source-bwt-screen.py",
)
RUN_VERIFY = load_script(
    "bwt_run_verifier_helpers_for_offline_publication",
    REPOSITORY / "scripts" / "verify-text-source-bwt-screen-run.py",
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


def validate_process(process: object, *, compression: bool) -> None:
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
        or process.get("returncode") != 0
        or process.get("timed_out") is not False
        or type(process.get("wall_ns")) is not int
        or process["wall_ns"] <= 0
        or type(process.get("cpu_ns")) is not int
        or process["cpu_ns"] < 0
        or type(process.get("peak_rss_bytes")) is not int
        or process["peak_rss_bytes"] < 0
        or not isinstance(process.get("stdout"), str)
        or not isinstance(process.get("stderr"), str)
        or not isinstance(process.get("command"), list)
    ):
        raise ValueError("BWT public process evidence differs")
    command = process["command"]
    if compression:
        forbidden = ("--level", "--skip", "--checksum")
        if (
            "--compress" not in command
            or "--block=1g" not in command
            or "--jobs=1" not in command
            or any(argument.startswith(forbidden) for argument in command)
        ):
            raise ValueError("BWT public compression command differs")
    elif "--decompress" not in command or "--jobs=1" not in command:
        raise ValueError("BWT public decompression command differs")


def reconstruct_run_verification(evidence: dict[str, Any]) -> dict[str, Any]:
    config = evidence["config"]
    result = evidence["results"]
    summary = result["summary"]
    RUNNER.validate_config(config)
    RUN_VERIFY.validate_preflight(result.get("preflight"), config)
    if (
        result.get("schema_version") != 1
        or result.get("name") != "text-source-bwt-kanzi-decomposition-screen-result-v1"
        or result.get("completed") is not True
        or result.get("all_required_completed") is not True
        or result.get("trial_count") != 32
        or result.get("measurement") != config["measurement"]
        or result.get("variants") != config["variants"]
        or result.get("screen_boundary")
        != {track: config["splits"][track] for track in RUNNER.TRACKS}
        or result.get("claim_ceiling") != config["claim_ceiling"]
        or result.get("public_validation_status") != "sealed and unaccessed"
        or result.get("private_holdout_status") != "sealed and unaccessed"
        or result["bindings"].get("config_sha256") != evidence["config_sha256"]
        or any(
            result["bindings"].get(key) != value
            for key, value in config["bindings"].items()
        )
        or summary.get("decision") != "track_specific_bwt_screen_complete"
        or summary.get("shared_signal_variants") != []
        or summary.get("axiom_wins") != 0
    ):
        raise ValueError("BWT public result identity or decision differs")

    receipts = [row["receipt"] for row in evidence["trials"]]
    expected_pairs = {
        (variant["id"], item_id, repetition)
        for variant in config["variants"]
        for track in RUNNER.TRACKS
        for item_id in config["splits"][track]["screen_items"]
        for repetition in range(config["measurement"]["measured_repetitions"])
    }
    observed_pairs = {
        (row.get("variant"), row.get("item_id"), row.get("repetition"))
        for row in receipts
    }
    if len(receipts) != 32 or observed_pairs != expected_pairs:
        raise ValueError("BWT public trial roster differs")
    variants = {row["id"]: row for row in config["variants"]}
    for row in receipts:
        variant = variants[row["variant"]]
        if (
            row.get("bindings") != result["bindings"]
            or row.get("passed") is not True
            or row.get("exact_roundtrip") is not True
            or row.get("error") is not None
            or type(row.get("artifact_bytes")) is not int
            or row["artifact_bytes"] <= 0
            or not isinstance(row.get("artifact_sha256"), str)
            or len(row["artifact_sha256"]) != 64
            or row.get("track") not in RUNNER.TRACKS
        ):
            raise ValueError("BWT public successful trial differs")
        validate_process(row.get("compression"), compression=True)
        validate_process(row.get("decompression"), compression=False)
        compression = row["compression"]["command"]
        if (
            f"--transform={variant['transform']}" not in compression
            or f"--entropy={variant['entropy']}" not in compression
        ):
            raise ValueError("BWT public variant command differs")

    item_metadata: dict[str, dict[str, Any]] = {}
    baseline_map: dict[str, int] = {}
    for row in summary["item_rows"]:
        item_id = row["item_id"]
        metadata = {
            "id": item_id,
            "track": row["track"],
            "source_bytes": row["source_bytes"],
        }
        if item_id in item_metadata and item_metadata[item_id] != metadata:
            raise ValueError("BWT public item metadata differs")
        item_metadata[item_id] = metadata
        if item_id in baseline_map and baseline_map[item_id] != row["baseline_bytes"]:
            raise ValueError("BWT public baseline bytes differ")
        baseline_map[item_id] = row["baseline_bytes"]
    expected_item_ids = {
        item_id
        for track in RUNNER.TRACKS
        for item_id in config["splits"][track]["screen_items"]
    }
    if set(item_metadata) != expected_item_ids or set(baseline_map) != expected_item_ids:
        raise ValueError("BWT public item roster differs")
    pseudo_baseline = {
        "summary": {
            "item_codec_rows": [
                {
                    "codec_id": "kanzi-max",
                    "item_id": item_id,
                    "artifact_bytes": baseline_map[item_id],
                }
                for item_id in sorted(item_metadata)
            ]
        }
    }
    ordered_items = [
        item_metadata[item_id]
        for track in RUNNER.TRACKS
        for item_id in config["splits"][track]["screen_items"]
    ]
    expected_summary = RUNNER.summarize(
        trials=receipts,
        items=ordered_items,
        baseline=pseudo_baseline,
        config=config,
    )
    if summary != expected_summary:
        raise ValueError("BWT public decision does not reconstruct")
    if any(
        track["decision"] != "reject_raw_bwt_direction_for_track"
        or track["selected_variant"] is not None
        for track in expected_summary["tracks"]
    ):
        raise ValueError("BWT public track rejection differs")
    return {
        "verified": True,
        "offline": True,
        "trial_count": len(receipts),
        "exact_deterministic_item_variant_count": sum(
            row["passed"] for row in expected_summary["item_rows"]
        ),
        "track_decisions": {
            row["track"]: row["decision"] for row in expected_summary["tracks"]
        },
        "selected_variants": {
            row["track"]: row["selected_variant"] for row in expected_summary["tracks"]
        },
        "shared_signal_variants": [],
        "axiom_wins": 0,
        "decision": expected_summary["decision"],
        "result_sha256": evidence["result_sha256"],
        "claim_ceiling": result["claim_ceiling"],
    }


def validate_public_evidence(evidence: dict[str, Any]) -> None:
    if (
        evidence.get("schema_version") != 1
        or evidence.get("name")
        != "text-source-bwt-kanzi-decomposition-public-evidence-v1"
        or not isinstance(evidence.get("trials"), list)
        or len(evidence["trials"]) != 32
        or evidence.get("raw_trial_receipts_manifest_sha256")
        != receipt_manifest(evidence["trials"])
        or evidence.get("public_trial_receipts_manifest_sha256")
        != receipt_manifest(evidence["trials"])
    ):
        raise ValueError("BWT public evidence identity or manifest differs")
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
            raise ValueError("BWT public trial evidence differs")
        paths.add(row["path"])
    encoded = json.dumps(evidence, sort_keys=True)
    if str(REPOSITORY) in encoded or '"/Users/' in encoded:
        raise ValueError("BWT public evidence contains a local absolute path")


def collect_trials(run: Path) -> list[dict[str, Any]]:
    paths = sorted((run / "trials").glob("*/*.json"))
    if len(paths) != 32 or any(path.is_symlink() for path in paths):
        raise ValueError("BWT trial receipt roster differs")
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


def throughput_mbps(source_bytes: int, elapsed_ns: int) -> float:
    return source_bytes / (1024 * 1024) / (elapsed_ns / 1e9)


def derive(
    result: dict[str, Any],
    *,
    result_sha256: str,
    receipts_sha256: str,
    public_evidence_sha256: str,
) -> dict[str, Any]:
    summary = result["summary"]
    item_rows = summary["item_rows"]
    tracks = []
    for track_result in summary["tracks"]:
        track = track_result["track"]
        item_ids = track_result["screen_items"]
        source_bytes = sum(
            row["source_bytes"]
            for row in item_rows
            if row["track"] == track and row["variant"] == RUNNER.VARIANTS[0]
        )
        baseline_bytes = track_result["variants"][0]["baseline_bytes"]
        rows = [
            {
                "kind": "practical_baseline",
                "id": "kanzi-max",
                "label": "Kanzi max (level 9)",
                "source_bytes": source_bytes,
                "complete_bytes": baseline_bytes,
                "ratio": source_bytes / baseline_bytes,
                "size_percent": baseline_bytes / source_bytes * 100.0,
                "gain_vs_kanzi_percent": 0.0,
                "compression_mbps": None,
                "decompression_mbps": None,
                "compression_peak_rss_mib": None,
                "decompression_peak_rss_mib": None,
                "speed_memory_availability": "not copied into this diagnostic result",
                "exact": True,
                "deterministic": True,
                "resource_limit_passed": True,
                "decision": "immutable practical comparison baseline",
            }
        ]
        for variant_result in track_result["variants"]:
            variant = variant_result["variant"]
            group = [
                row
                for row in item_rows
                if row["track"] == track and row["variant"] == variant
            ]
            if len(group) != 2 or not all(
                row["passed"]
                and row["exact_roundtrip"]
                and row["deterministic_artifact"]
                for row in group
            ):
                raise ValueError(f"BWT diagnostic subset is incomplete: {variant}")
            complete_bytes = variant_result["artifact_bytes"]
            gain = variant_result["gain_vs_kanzi_percent"]
            if gain >= 0 or variant_result["track_signal"]:
                raise ValueError(f"BWT published rejection differs: {variant}")
            compression_ns = sum(row["median_compression_ns"] for row in group)
            decompression_ns = sum(row["median_decompression_ns"] for row in group)
            rows.append(
                {
                    "kind": "competitor_diagnostic",
                    "id": variant,
                    "label": VARIANT_LABELS[variant],
                    "source_bytes": source_bytes,
                    "complete_bytes": complete_bytes,
                    "ratio": source_bytes / complete_bytes,
                    "size_percent": complete_bytes / source_bytes * 100.0,
                    "gain_vs_kanzi_percent": gain,
                    "compression_mbps": throughput_mbps(source_bytes, compression_ns),
                    "decompression_mbps": throughput_mbps(source_bytes, decompression_ns),
                    "compression_peak_rss_mib": max(
                        row["compression_peak_rss_bytes"] for row in group
                    )
                    / (1024 * 1024),
                    "decompression_peak_rss_mib": max(
                        row["decompression_peak_rss_bytes"] for row in group
                    )
                    / (1024 * 1024),
                    "speed_memory_availability": "measured same-host medians and peaks",
                    "exact": True,
                    "deterministic": True,
                    "resource_limit_passed": variant_result["resource_limit_passed"],
                    "item_gains_vs_kanzi_percent": {
                        row["item_id"]: row["gain_vs_kanzi_percent"] for row in group
                    },
                    "decision": (
                        f"rejected: {-gain:.2f}% larger than Kanzi-max; no signal"
                    ),
                }
            )
        tracks.append(
            {
                "track_id": track,
                "track": TRACK_LABELS[track],
                "screen_items": item_ids,
                "baseline": "Kanzi max (level 9)",
                "selected_variant": None,
                "track_decision": track_result["decision"],
                "rows": rows,
            }
        )
    return {
        "schema_version": 1,
        "name": "text-source-bwt-kanzi-decomposition-publication-v1",
        "stage": "training-only custom Kanzi decomposition screen",
        "bindings": result["bindings"],
        "result_sha256": result_sha256,
        "trial_receipts_manifest_sha256": receipts_sha256,
        "public_evidence_sha256": public_evidence_sha256,
        "tracks": tracks,
        "integrity": {
            "trial_count": 32,
            "exact_deterministic_item_variant_count": 16,
            "comparison_rows_per_track": 5,
            "custom_kanzi_diagnostic_count_per_track": 4,
            "all_diagnostic_gains_negative": True,
            "axiom_artifact_count": 0,
            "axiom_wins": 0,
        },
        "runner_comparability": {
            "size": "Every byte value is one complete decodable .knz archive per item, aggregated once over the identical two-item track.",
            "speed_memory": "BWT rows show same-host medians and peak RSS from the retained trials. Baseline speed/RSS was not copied into this diagnostic result and is intentionally blank.",
        },
        "decision": summary["decision"],
        "track_decisions": {
            row["track"]: row["decision"] for row in summary["tracks"]
        },
        "public_validation_status": "sealed and unaccessed",
        "private_holdout_status": "sealed and unaccessed",
        "axiom_wins": 0,
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
        "# BWT decomposition screen: rejected on both tracks",
        "",
        "![All four BWT diagnostics against Kanzi-max](comparison.svg)",
        "",
        f"> **Claim ceiling:** {comparison['claim_ceiling']}",
        "",
        "All 32 retained trials decoded exactly and produced byte-identical repeats. Every custom BWT chain was larger than Kanzi-max on both training tracks, so neither track admitted a token-BWT prototype. No Axiom artifact was built and `axiom_wins` remains 0.",
        "",
    ]
    for track in comparison["tracks"]:
        lines.extend(
            [
                f"## {track['track']}",
                "",
                f"Decision: `{track['track_decision']}`.",
                "",
                "| Baseline / diagnostic | Complete bytes | Gain vs Kanzi-max | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Decision |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for row in track["rows"]:
            integrity = "✅ / ✅" if row["exact"] and row["deterministic"] else "— / —"
            lines.append(
                f"| {row['label']} | {display(row['complete_bytes'])} | "
                f"{display(row['gain_vs_kanzi_percent'], '%')} | "
                f"{display(row['ratio'], 'x')} | {display(row['size_percent'], '%')} | "
                f"{display(row['compression_mbps'])} | {display(row['decompression_mbps'])} | "
                f"{display(row['compression_peak_rss_mib'])} / "
                f"{display(row['decompression_peak_rss_mib'])} | {integrity} | "
                f"{row['decision']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Evidence boundary",
            "",
            f"- Frozen result SHA-256: `{comparison['result_sha256']}`.",
            f"- Trial-receipt manifest SHA-256: `{comparison['trial_receipts_manifest_sha256']}`.",
            f"- Public evidence SHA-256: `{comparison['public_evidence_sha256']}`.",
            f"- Size accounting: {comparison['runner_comparability']['size']}",
            f"- Speed and memory: {comparison['runner_comparability']['speed_memory']}",
            "- Publication and verification are offline: no corpus, reserved evaluation, public validation, or private holdout bytes are required or accessed.",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(comparison: dict[str, Any]) -> str:
    width = 1540
    row_height = 30
    height = 150 + sum(100 + len(track["rows"]) * row_height for track in comparison["tracks"])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;fill:#172033}.title{font-size:26px;font-weight:700}.sub{font-size:13px;fill:#526078}.track{font-size:18px;font-weight:700}.head{font-size:11px;font-weight:700;fill:#526078}.row{font-size:11px}.base{font-size:11px;font-weight:700;fill:#315b8a}.bad{font-size:11px;font-weight:700;fill:#a13d2d}.num{font-size:11px;font-variant-numeric:tabular-nums}</style>",
        '<text class="title" x="28" y="38">BWT decomposition screen — rejected on both tracks</text>',
        '<text class="sub" x="28" y="64">32/32 exact trials; four deterministic BWT diagnostics versus complete Kanzi-max archives; no Axiom artifact or win.</text>',
    ]
    y = 108
    for track in comparison["tracks"]:
        parts.append(f'<text class="track" x="28" y="{y}">{escape(track["track"])}</text>')
        parts.append(
            f'<text class="bad" x="1510" y="{y}" text-anchor="end">{escape(track["track_decision"])}</text>'
        )
        y += 28
        headers = [
            (28, "Baseline / diagnostic", "start"),
            (690, "Complete bytes", "end"),
            (810, "Gain vs K-max", "end"),
            (900, "Ratio", "end"),
            (1010, "C MB/s", "end"),
            (1120, "D MB/s", "end"),
            (1250, "RSS C/D MiB", "end"),
            (1375, "Exact/Det", "middle"),
            (1510, "Decision", "end"),
        ]
        for x, label, anchor in headers:
            parts.append(
                f'<text class="head" x="{x}" y="{y}" text-anchor="{anchor}">{label}</text>'
            )
        y += 20
        for index, row in enumerate(track["rows"]):
            if index % 2 == 0:
                parts.append(
                    f'<rect x="20" y="{y - 17}" width="1500" height="{row_height}" rx="3" fill="#eaf0f7" fill-opacity="0.62"/>'
                )
            css = "base" if row["kind"] == "practical_baseline" else "bad"
            status = "baseline" if row["kind"] == "practical_baseline" else "rejected"
            values = [
                (28, row["label"], "start", css),
                (690, display(row["complete_bytes"]), "end", "num"),
                (810, display(row["gain_vs_kanzi_percent"], "%"), "end", "num"),
                (900, display(row["ratio"], "x"), "end", "num"),
                (1010, display(row["compression_mbps"]), "end", "num"),
                (1120, display(row["decompression_mbps"]), "end", "num"),
                (
                    1250,
                    f"{display(row['compression_peak_rss_mib'])}/{display(row['decompression_peak_rss_mib'])}",
                    "end",
                    "num",
                ),
                (1375, "yes/yes", "middle", "num"),
                (1510, status, "end", css),
            ]
            for x, value, anchor, klass in values:
                parts.append(
                    f'<text class="{klass}" x="{x}" y="{y + 4}" text-anchor="{anchor}">{escape(str(value))}</text>'
                )
            y += row_height
        y += 42
    parts.append(
        f'<text class="sub" x="28" y="{height - 24}">{escape(comparison["claim_ceiling"])}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def build_artifacts(run: Path, config_path: Path) -> dict[str, bytes]:
    result_raw, result = read_canonical(run / "results.json")
    config_raw, config = read_canonical(config_path)
    trials = collect_trials(run)
    manifest_sha256 = receipt_manifest(trials)
    evidence = {
        "schema_version": 1,
        "name": "text-source-bwt-kanzi-decomposition-public-evidence-v1",
        "result_sha256": sha256_bytes(result_raw),
        "config_sha256": sha256_bytes(config_raw),
        "raw_trial_receipts_manifest_sha256": manifest_sha256,
        "public_trial_receipts_manifest_sha256": manifest_sha256,
        "redaction_policy": "Commands retain only $REPOSITORY and $WORK placeholders; no local absolute path is published.",
        "offline_verification_policy": "Reconstruct the frozen summary and decisions from the copied config, result, and 32 receipts without opening corpus or evaluation bytes or executing Kanzi.",
        "config": config,
        "results": result,
        "trials": trials,
    }
    verification = reconstruct_run_verification(evidence)
    evidence["run_verification"] = verification
    validate_public_evidence(evidence)
    evidence_raw = json_bytes(evidence)
    comparison = derive(
        result,
        result_sha256=evidence["result_sha256"],
        receipts_sha256=manifest_sha256,
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
        "name": "text-source-bwt-kanzi-decomposition-publication-receipt-v1",
        "result_sha256": comparison["result_sha256"],
        "trial_receipts_manifest_sha256": comparison[
            "trial_receipts_manifest_sha256"
        ],
        "public_evidence_sha256": comparison["public_evidence_sha256"],
        "bindings": comparison["bindings"],
        "artifacts": {name: sha256_bytes(payload) for name, payload in artifacts.items()},
        "axiom_wins": 0,
        "claim_ceiling": comparison["claim_ceiling"],
    }
    artifacts["receipt.json"] = json_bytes(receipt)
    return artifacts


def publish(run: Path, config: Path, output: Path) -> Path:
    artifacts = build_artifacts(run, config)
    if output.exists():
        if (
            output.is_symlink()
            or not output.is_dir()
            or {path.name for path in output.iterdir()} != set(artifacts)
        ):
            raise ValueError("BWT publication destination differs")
        for name, payload in artifacts.items():
            if (output / name).read_bytes() != payload:
                raise ValueError(f"BWT publication artifact differs: {name}")
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bwt-publication-", dir=output.parent) as raw:
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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = publish(args.run, args.config, args.output)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"BWT publication failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
