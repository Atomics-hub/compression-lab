#!/usr/bin/env python3
"""Verify the compact immutable E2-A publication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-context-ceiling-e2-a-v1.json"
PROTOCOL = (
    ROOT / "docs" / "benchmarks" / "2026-07-21-json-context-ceiling-e2-a-protocol.md"
)
RUNNER = ROOT / "scripts" / "benchmark-json-context-ceiling-e2-a.py"
FULL_VERIFIER = ROOT / "scripts" / "verify-json-context-ceiling-e2-a.py"
RENDERER = ROOT / "scripts" / "render-json-context-ceiling-e2-a.py"
ROOT_MEMBERS = {
    "README.md",
    "comparison.svg",
    "evidence.json",
    "run.log",
    "verification.log",
    "github-run.json",
    "github-artifacts.json",
    "SHA256SUMS",
    "containers",
    "receipt.json",
}
SHA256 = re.compile(r"[0-9a-f]{64}")
GITHUB_REPOSITORY = "Atomics-hub/compression-lab"
WORKFLOW_NAME = "E2-A JSON context ceiling"
WORKFLOW_PATH = ".github/workflows/json-context-ceiling-e2-a.yml"
EXPECTED_HEAD_SHA = "45ca664d77e1a8a2f7ac057914e3ee034d683a30"
EXPECTED_RUN_ID = 29867575535
EXPECTED_WORKFLOW_ID = 317724122


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary JSON file: {path}")
    return json.loads(path.read_bytes())


def verify_github_receipts(publication: Path, receipt: dict[str, Any]) -> None:
    run = read_json(publication / "github-run.json")
    artifacts = read_json(publication / "github-artifacts.json")
    source_run = receipt["source_run"]
    expected_run = {
        "id": source_run["id"],
        "head_sha": source_run["head_sha"],
        "html_url": source_run["url"],
        "conclusion": "success",
        "status": "completed",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "name": WORKFLOW_NAME,
        "path": WORKFLOW_PATH,
        "workflow_id": EXPECTED_WORKFLOW_ID,
        "run_attempt": 1,
    }
    if any(run.get(key) != value for key, value in expected_run.items()):
        raise ValueError("E2-A retained GitHub run metadata differs")
    if run.get("repository", {}).get("full_name") != GITHUB_REPOSITORY:
        raise ValueError("E2-A retained GitHub repository identity differs")
    source_artifact = receipt["source_artifact"]
    matches = [
        row
        for row in artifacts.get("artifacts", [])
        if row.get("id") == source_artifact["id"]
    ]
    if len(matches) != 1:
        raise ValueError("E2-A retained GitHub artifact ID differs")
    row = matches[0]
    expected_artifact = {
        "name": source_artifact["name"],
        "size_in_bytes": source_artifact["size_in_bytes"],
        "digest": source_artifact["digest"],
        "expired": False,
    }
    if any(row.get(key) != value for key, value in expected_artifact.items()):
        raise ValueError("E2-A retained GitHub artifact metadata differs")
    if row.get("workflow_run", {}).get("id") != source_run["id"]:
        raise ValueError("E2-A retained artifact belongs to another run")


def derive_decision(evidence: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    method_ids = [row["id"] for row in config["methods"]]
    item_ids = [row["id"] for row in config["items"]]
    methods = {row["id"]: row for row in config["methods"]}
    items = {row["id"]: row for row in config["items"]}
    summaries = evidence["method_summaries"]
    if [row["method_id"] for row in summaries] != method_ids:
        raise ValueError("E2-A compact method-summary roster differs")
    baseline = config["e1_fixed_reference"]["kanzi_complete_bytes"]
    limits = config["measurement"]
    for method, summary in zip(config["methods"], summaries, strict=True):
        size = summary["complete_container"]["bytes"]
        compress_rss = summary["maximum_compression_peak_rss_bytes"]
        decode_rss = summary["maximum_decompression_peak_rss_bytes"]
        if (
            summary["complete_container"]["path"]
            != f"containers/{method['id']}-r1.axe2o"
            or summary["maximum_block_mib"] != method["maximum_block_mib"]
            or summary["gain_vs_e1_kanzi_basis_points"]
            != (baseline - size) * 10000 // baseline
            or summary["eligible"]
            is not (
                compress_rss <= limits["maximum_compression_peak_rss_bytes"]
                and decode_rss <= limits["maximum_decompression_peak_rss_bytes"]
            )
            or summary["fragile"]
            is not (
                max(compress_rss, decode_rss)
                >= config["decision_gates"]["fragile_peak_rss_bytes"]
            )
            or summary["exact"] is not True
        ):
            raise ValueError("E2-A compact method summary does not rederive")
    eligible = sorted(
        (row for row in summaries if row["eligible"]),
        key=lambda row: (row["complete_container"]["bytes"], row["method_id"]),
    )
    best = eligible[0] if eligible else None
    selected = [] if best is None else [best["method_id"]]
    if "zpaq-5-m510" not in selected:
        selected.append("zpaq-5-m510")
    if evidence["selected_methods"] != selected:
        raise ValueError("E2-A compact confirmation selection differs")
    all_trials = evidence["stage_one_trials"] + evidence["confirmation_trials"]
    for trial in all_trials:
        item = items.get(trial["item_id"])
        method = methods.get(trial["method_id"])
        if (
            item is None
            or method is None
            or trial["method"] != method["method"]
            or trial["source_bytes"] != item["bytes"]
            or trial["source_sha256"] != item["sha256"]
            or trial["restored_bytes"] != item["bytes"]
            or trial["restored_sha256"] != item["sha256"]
            or trial["exact"] is not True
        ):
            raise ValueError("E2-A compact trial identity or exactness differs")
    stage_map = {
        (row["method_id"], row["item_id"]): row
        for row in evidence["stage_one_trials"]
        if row["stage"] == "stage_one" and row["repetition"] == 1
    }
    confirmation_map = {
        (row["method_id"], row["item_id"]): row
        for row in evidence["confirmation_trials"]
        if row["stage"] == "confirmation" and row["repetition"] == 2
    }
    if len(evidence["stage_one_trials"]) != len(stage_map) or set(stage_map) != {
        (method, item) for method in method_ids for item in item_ids
    }:
        raise ValueError("E2-A compact stage-one schedule differs")
    expected_confirmation = {(method, item) for method in selected for item in item_ids}
    if (
        len(evidence["confirmation_trials"]) != len(confirmation_map)
        or set(confirmation_map) != expected_confirmation
    ):
        raise ValueError("E2-A compact confirmation schedule differs")
    confirmation_passed = all(
        stage_map[key]["archive"]["bytes"] == confirmation_map[key]["archive"]["bytes"]
        and stage_map[key]["archive"]["sha256"]
        == confirmation_map[key]["archive"]["sha256"]
        for key in expected_confirmation
    )
    summary_by_method = {row["method_id"]: row for row in summaries}
    confirmation_passed &= set(evidence["confirmation_containers"]) == set(selected)
    if confirmation_passed:
        confirmation_passed &= all(
            evidence["confirmation_containers"][method]["path"]
            == f"containers/{method}-r2.axe2o"
            and evidence["confirmation_containers"][method]["bytes"]
            == summary_by_method[method]["complete_container"]["bytes"]
            and evidence["confirmation_containers"][method]["sha256"]
            == summary_by_method[method]["complete_container"]["sha256"]
            for method in selected
        )
    if best is not None:
        bounded = [confirmation_map[(best["method_id"], item)] for item in item_ids]
        confirmation_passed &= (
            max(row["compress"]["peak_rss_bytes"] for row in bounded)
            <= limits["maximum_compression_peak_rss_bytes"]
        )
        confirmation_passed &= (
            max(row["decompress"]["peak_rss_bytes"] for row in bounded)
            <= limits["maximum_decompression_peak_rss_bytes"]
        )
    e1_rows = {
        row["item_id"]: row for row in evidence["e1_reference"]["zpaq_510_per_item"]
    }
    anchor_matched = set(e1_rows) == set(item_ids) and all(
        stage_map[("zpaq-5-m510", item)]["archive"]["bytes"]
        == e1_rows[item]["artifact_bytes"]
        and stage_map[("zpaq-5-m510", item)]["archive"]["sha256"]
        == e1_rows[item]["artifact_sha256"]
        for item in item_ids
    )
    if evidence["e1_reference"]["anchor_matched"] is not anchor_matched:
        raise ValueError("E2-A compact E1 anchor differs")
    gates = config["decision_gates"]
    if not anchor_matched:
        outcome = "refuse_e1_anchor_mismatch"
    elif not confirmation_passed:
        outcome = "fail_confirmation"
    elif (
        best is None
        or best["complete_container"]["bytes"]
        >= gates["kill_when_complete_bytes_at_least"]
    ):
        outcome = "kill_bounded_level5_lane"
    elif best["complete_container"]["bytes"] <= gates["advance_maximum_complete_bytes"]:
        outcome = "advance_component_attribution"
    else:
        outcome = "permit_one_frozen_refinement"
    return {
        "outcome": outcome,
        "best_eligible_method": None if best is None else best["method_id"],
        "best_eligible_complete_bytes": None
        if best is None
        else best["complete_container"]["bytes"],
        "best_eligible_gain_basis_points": None
        if best is None
        else best["gain_vs_e1_kanzi_basis_points"],
        "confirmation_passed": confirmation_passed,
    }


def verify(publication: Path, expected_receipt_sha256: str) -> dict[str, Any]:
    paths = list(publication.iterdir())
    if (
        any(path.is_symlink() for path in publication.rglob("*"))
        or {path.name for path in paths} != ROOT_MEMBERS
    ):
        raise ValueError("E2-A compact publication roster differs")
    if SHA256.fullmatch(expected_receipt_sha256) is None:
        raise ValueError("E2-A expected receipt digest is invalid")
    receipt = read_json(publication / "receipt.json")
    evidence = read_json(publication / "evidence.json")
    config = read_json(CONFIG)
    if sha256_file(publication / "receipt.json") != expected_receipt_sha256:
        raise ValueError("E2-A external receipt digest differs")
    if (
        receipt["schema_version"] != 1
        or receipt["name"] != "axiom-json-context-ceiling-e2-a-publication-receipt-v1"
        or receipt["evidence_stage"] != "development_only_diagnostic"
        or receipt["source_artifact"]["all_member_checksums_verified"] is not True
        or receipt["source_artifact"]["zip_tree_verified"] is not True
        or receipt["source_artifact"]["github_metadata_verified"] is not True
        or evidence.get("schema_version") != 1
        or set(evidence) != set(config["required_result_sections"])
        or evidence.get("name") != config["name"]
        or evidence.get("completed") is not True
        or evidence["repository_commit"] != EXPECTED_HEAD_SHA
        or receipt["source_run"]["id"] != EXPECTED_RUN_ID
        or evidence["config_sha256"] != sha256_file(CONFIG)
        or evidence["protocol_sha256"] != sha256_file(PROTOCOL)
        or evidence["runner_sha256"] != sha256_file(RUNNER)
        or evidence["verifier_sha256"] != sha256_file(FULL_VERIFIER)
        or evidence["source_bindings"] != config["source_run"]
        or evidence["information_boundary"] != config["information_boundary"]
        or evidence["claim_ceiling"] != config["claim_ceiling"]
        or evidence["decision"] != receipt["decision"]
        or evidence["information_boundary"] != receipt["information_boundary"]
        or evidence["claim_ceiling"] != receipt["claim_ceiling"]
        or evidence["repository_commit"] != receipt["source_run"]["head_sha"]
        or receipt["source_members"]["measurement/result.json"]["sha256"]
        != receipt["published_members"]["evidence.json"]
        or receipt["source_artifact"]["checksum_manifest_sha256"]
        != receipt["published_members"]["SHA256SUMS"]
    ):
        raise ValueError("E2-A compact publication identity differs")
    if derive_decision(evidence, config) != evidence["decision"]:
        raise ValueError("E2-A compact decision does not rederive")
    verify_github_receipts(publication, receipt)
    verification_lines = [
        line
        for line in (publication / "verification.log")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(verification_lines) != 1 or json.loads(verification_lines[0]) != {
        "decision": evidence["decision"],
        "verified": True,
    }:
        raise ValueError("E2-A retained verification log differs")
    expected_containers = {
        f"containers/{row['method_id']}-r1.axe2o"
        for row in evidence["method_summaries"]
    } | {f"containers/{method}-r2.axe2o" for method in evidence["selected_methods"]}
    actual_containers = {
        path.relative_to(publication).as_posix()
        for path in (publication / "containers").iterdir()
        if path.is_file()
    }
    if actual_containers != expected_containers:
        raise ValueError("E2-A retained container roster differs")
    container_rows = {
        f"containers/{row['method_id']}-r1.axe2o": row["complete_container"]
        for row in evidence["method_summaries"]
    } | {
        f"containers/{method}-r2.axe2o": evidence["confirmation_containers"][method]
        for method in evidence["selected_methods"]
    }
    for name, row in container_rows.items():
        path = publication / name
        source_name = f"measurement/{name}"
        if (
            path.stat().st_size != row["bytes"]
            or sha256_file(path) != row["sha256"]
            or receipt["source_members"][source_name]
            != {"bytes": row["bytes"], "sha256": row["sha256"]}
        ):
            raise ValueError(f"E2-A retained container differs: {name}")
    expected_members = {
        path.relative_to(publication).as_posix(): sha256_file(path)
        for path in publication.rglob("*")
        if path.is_file() and path.name != "receipt.json"
    }
    if receipt["published_members"] != expected_members:
        raise ValueError("E2-A compact publication digest differs")
    with tempfile.TemporaryDirectory(prefix="axiom-e2a-publication-verify-") as raw:
        output = Path(raw) / "publication"
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--result",
                str(publication / "evidence.json"),
                "--output",
                str(output),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
        )
        for name in ("README.md", "comparison.svg"):
            if (output / name).read_bytes() != (publication / name).read_bytes():
                raise ValueError(
                    f"E2-A compact publication does not reconstruct: {name}"
                )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    args = parser.parse_args()
    try:
        receipt = verify(args.publication, args.expected_receipt_sha256)
    except (
        KeyError,
        AttributeError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E2-A publication verification failed: {error}") from error
    print(
        json.dumps({"verified": True, "decision": receipt["decision"]}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
