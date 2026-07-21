#!/usr/bin/env python3
"""Import a verified hosted E2-A artifact into an immutable publication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "json-context-ceiling-e2-a-v1.json"
PROTOCOL = (
    ROOT / "docs" / "benchmarks" / "2026-07-21-json-context-ceiling-e2-a-protocol.md"
)
RUNNER = ROOT / "scripts" / "benchmark-json-context-ceiling-e2-a.py"
VERIFIER = ROOT / "scripts" / "verify-json-context-ceiling-e2-a.py"
RENDERER = ROOT / "scripts" / "render-json-context-ceiling-e2-a.py"
RUN_ID = re.compile(r"[1-9][0-9]*")
COMMIT = re.compile(r"[0-9a-f]{40}")
ARTIFACT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
GITHUB_REPOSITORY = "Atomics-hub/compression-lab"
WORKFLOW_NAME = "E2-A JSON context ceiling"
WORKFLOW_PATH = ".github/workflows/json-context-ceiling-e2-a.yml"
EXPECTED_HEAD_SHA = "45ca664d77e1a8a2f7ac057914e3ee034d683a30"
EXPECTED_RUN_ID = 29867575535
EXPECTED_WORKFLOW_ID = 317724122
REQUIRED_SOURCE_MEMBERS = {
    "measurement/result.json",
    "publication/README.md",
    "publication/comparison.svg",
    "run.log",
    "verification.log",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected ordinary file: {path}")


def read_json(path: Path) -> dict[str, Any]:
    ordinary(path)
    return json.loads(path.read_bytes())


def fetch_github_metadata(run_id: int) -> tuple[bytes, bytes]:
    if shutil.which("gh") is None:
        raise ValueError("GitHub CLI is required for live E2-A provenance")
    payloads = []
    for endpoint in (
        f"repos/{GITHUB_REPOSITORY}/actions/runs/{run_id}",
        f"repos/{GITHUB_REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100",
    ):
        completed = subprocess.run(
            ["gh", "api", endpoint],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        json.loads(completed.stdout)
        payloads.append(completed.stdout)
    return payloads[0], payloads[1]


def verify_checksum_manifest(root: Path) -> dict[str, str]:
    manifest = root / "SHA256SUMS"
    ordinary(manifest)
    rows: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](?:\./)?(.+)", line)
        if match is None:
            raise ValueError("E2-A SHA256SUMS syntax differs")
        digest, name = match.groups()
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name != path.as_posix():
            raise ValueError("E2-A SHA256SUMS contains an unsafe path")
        if name in rows:
            raise ValueError("E2-A SHA256SUMS contains a duplicate path")
        rows[name] = digest
    members = list(root.rglob("*"))
    if any(path.is_symlink() for path in members):
        raise ValueError("E2-A artifact contains a symlink")
    actual = {
        path.relative_to(root).as_posix()
        for path in members
        if path.is_file() and path != manifest
    }
    if set(rows) != actual:
        raise ValueError("E2-A artifact roster differs from SHA256SUMS")
    for name, digest in rows.items():
        if sha256_file(root / name) != digest:
            raise ValueError(f"E2-A artifact member digest differs: {name}")
    if not REQUIRED_SOURCE_MEMBERS.issubset(actual):
        raise ValueError("E2-A artifact is missing a publication member")
    return rows


def verify_zip_matches_tree(
    artifact_zip: Path, artifact_root: Path, size: int, digest: str
) -> None:
    ordinary(artifact_zip)
    if (
        artifact_zip.stat().st_size != size
        or f"sha256:{sha256_file(artifact_zip)}" != digest
    ):
        raise ValueError("E2-A artifact ZIP size or digest differs")
    tree = {
        path.relative_to(artifact_root).as_posix(): path
        for path in artifact_root.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(artifact_zip) as archive:
        all_infos = archive.infolist()
        normalized_names: list[str] = []
        for info in all_infos:
            normalized = info.filename[:-1] if info.is_dir() else info.filename
            path = Path(normalized)
            mode = (info.external_attr >> 16) & 0o170000
            allowed_modes = {0, 0o040000} if info.is_dir() else {0, 0o100000}
            if (
                not normalized
                or path.is_absolute()
                or ".." in path.parts
                or normalized != path.as_posix()
                or info.flag_bits & 1
                or mode not in allowed_modes
            ):
                raise ValueError("E2-A artifact ZIP contains an unsafe member")
            normalized_names.append(normalized)
        if len(normalized_names) != len(set(normalized_names)):
            raise ValueError("E2-A artifact ZIP contains a duplicate member")
        infos = [info for info in all_infos if not info.is_dir()]
        names = [info.filename for info in infos]
        if set(names) != set(tree):
            raise ValueError("E2-A artifact ZIP roster differs from extracted tree")
        for info in infos:
            digest_value = hashlib.sha256()
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest_value.update(chunk)
            if info.file_size != tree[
                info.filename
            ].stat().st_size or digest_value.hexdigest() != sha256_file(
                tree[info.filename]
            ):
                raise ValueError(f"E2-A artifact ZIP member differs: {info.filename}")


def verify_github_metadata(
    *,
    run: dict[str, Any],
    artifacts: dict[str, Any],
    run_id: int,
    run_url: str,
    run_head_sha: str,
    artifact_id: int,
    artifact_name: str,
    artifact_size: int,
    artifact_digest: str,
) -> None:
    expected_run = {
        "id": run_id,
        "head_sha": run_head_sha,
        "html_url": run_url,
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
        raise ValueError("live E2-A GitHub run metadata differs")
    if run.get("repository", {}).get("full_name") != GITHUB_REPOSITORY:
        raise ValueError("live E2-A GitHub repository identity differs")
    matches = [
        row for row in artifacts.get("artifacts", []) if row.get("id") == artifact_id
    ]
    if len(matches) != 1:
        raise ValueError("live E2-A GitHub artifact ID differs")
    row = matches[0]
    expected_artifact = {
        "name": artifact_name,
        "size_in_bytes": artifact_size,
        "digest": artifact_digest,
        "expired": False,
    }
    if any(row.get(key) != value for key, value in expected_artifact.items()):
        raise ValueError("live E2-A GitHub artifact metadata differs")
    if row.get("workflow_run", {}).get("id") != run_id:
        raise ValueError("live E2-A artifact belongs to another run")


def verify_rendered_publication(root: Path, result: dict[str, Any]) -> None:
    with tempfile.TemporaryDirectory(prefix="axiom-e2a-render-") as raw:
        rendered = Path(raw) / "publication"
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--result",
                str(root / "measurement" / "result.json"),
                "--output",
                str(rendered),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
        )
        for name in ("README.md", "comparison.svg"):
            if (rendered / name).read_bytes() != (
                root / "publication" / name
            ).read_bytes():
                raise ValueError(
                    f"E2-A hosted publication does not reconstruct: {name}"
                )


def derive_decision(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    method_ids = [row["id"] for row in config["methods"]]
    item_ids = [row["id"] for row in config["items"]]
    methods = {row["id"]: row for row in config["methods"]}
    items = {row["id"]: row for row in config["items"]}
    summaries = result["method_summaries"]
    if [row["method_id"] for row in summaries] != method_ids:
        raise ValueError("E2-A method-summary roster differs")
    baseline = config["e1_fixed_reference"]["kanzi_complete_bytes"]
    limits = config["measurement"]
    for method, summary in zip(config["methods"], summaries, strict=True):
        complete_bytes = summary["complete_container"]["bytes"]
        compression_rss = summary["maximum_compression_peak_rss_bytes"]
        decompression_rss = summary["maximum_decompression_peak_rss_bytes"]
        if (
            summary["complete_container"]["path"]
            != f"containers/{method['id']}-r1.axe2o"
            or summary["maximum_block_mib"] != method["maximum_block_mib"]
            or summary["gain_vs_e1_kanzi_basis_points"]
            != (baseline - complete_bytes) * 10000 // baseline
            or summary["eligible"]
            is not (
                compression_rss <= limits["maximum_compression_peak_rss_bytes"]
                and decompression_rss <= limits["maximum_decompression_peak_rss_bytes"]
            )
            or summary["fragile"]
            is not (
                max(compression_rss, decompression_rss)
                >= config["decision_gates"]["fragile_peak_rss_bytes"]
            )
            or summary["exact"] is not True
        ):
            raise ValueError("E2-A method summary does not rederive")
    eligible = sorted(
        (row for row in summaries if row["eligible"]),
        key=lambda row: (row["complete_container"]["bytes"], row["method_id"]),
    )
    best = eligible[0] if eligible else None
    selected = [] if best is None else [best["method_id"]]
    if "zpaq-5-m510" not in selected:
        selected.append("zpaq-5-m510")
    if result["selected_methods"] != selected:
        raise ValueError("E2-A confirmation selection does not rederive")
    stage_one = result["stage_one_trials"]
    confirmation = result["confirmation_trials"]
    for trial in stage_one + confirmation:
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
            raise ValueError("E2-A trial identity or exactness differs")
    stage_map = {
        (row["method_id"], row["item_id"]): row
        for row in stage_one
        if row["stage"] == "stage_one" and row["repetition"] == 1
    }
    confirmation_map = {
        (row["method_id"], row["item_id"]): row
        for row in confirmation
        if row["stage"] == "confirmation" and row["repetition"] == 2
    }
    if len(stage_one) != len(stage_map) or set(stage_map) != {
        (method, item) for method in method_ids for item in item_ids
    }:
        raise ValueError("E2-A stage-one schedule does not rederive")
    expected_confirmation = {(method, item) for method in selected for item in item_ids}
    if (
        len(confirmation) != len(confirmation_map)
        or set(confirmation_map) != expected_confirmation
    ):
        raise ValueError("E2-A confirmation schedule does not rederive")
    confirmation_passed = all(
        stage_map[key]["archive"]["bytes"] == confirmation_map[key]["archive"]["bytes"]
        and stage_map[key]["archive"]["sha256"]
        == confirmation_map[key]["archive"]["sha256"]
        for key in expected_confirmation
    )
    summary_by_method = {row["method_id"]: row for row in summaries}
    confirmation_passed &= set(result["confirmation_containers"]) == set(selected)
    if confirmation_passed:
        confirmation_passed &= all(
            result["confirmation_containers"][method]["path"]
            == f"containers/{method}-r2.axe2o"
            and result["confirmation_containers"][method]["bytes"]
            == summary_by_method[method]["complete_container"]["bytes"]
            and result["confirmation_containers"][method]["sha256"]
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
        row["item_id"]: row for row in result["e1_reference"]["zpaq_510_per_item"]
    }
    anchor_matched = set(e1_rows) == set(item_ids) and all(
        stage_map[("zpaq-5-m510", item)]["archive"]["bytes"]
        == e1_rows[item]["artifact_bytes"]
        and stage_map[("zpaq-5-m510", item)]["archive"]["sha256"]
        == e1_rows[item]["artifact_sha256"]
        for item in item_ids
    )
    if result["e1_reference"]["anchor_matched"] is not anchor_matched:
        raise ValueError("E2-A E1 anchor does not rederive")
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


def verify_result_identity(result: dict[str, Any], run_head_sha: str) -> dict[str, Any]:
    config = read_json(CONFIG)
    if set(result) != set(config["required_result_sections"]):
        raise ValueError("E2-A result section roster differs")
    if (
        result["schema_version"] != 1
        or result["name"] != config["name"]
        or result["completed"] is not True
        or result["repository_commit"] != run_head_sha
        or result["claim_ceiling"] != config["claim_ceiling"]
        or result["config_sha256"] != sha256_file(CONFIG)
        or result["protocol_sha256"] != sha256_file(PROTOCOL)
        or result["runner_sha256"] != sha256_file(RUNNER)
        or result["verifier_sha256"] != sha256_file(VERIFIER)
        or result["source_bindings"] != config["source_run"]
        or result["information_boundary"] != config["information_boundary"]
    ):
        raise ValueError("E2-A result identity or binding differs")
    expected_decision = derive_decision(result, config)
    if result["decision"] != expected_decision:
        raise ValueError("E2-A decision does not rederive")
    return expected_decision


def verify_result_file_manifest(result: dict[str, Any], measurement: Path) -> None:
    rows = result["file_manifest"]
    if len({row["path"] for row in rows}) != len(rows):
        raise ValueError("E2-A result file manifest contains a duplicate")
    actual = {
        path.relative_to(measurement).as_posix(): path
        for path in measurement.rglob("*")
        if path.is_file() and path.name != "result.json"
    }
    if set(actual) != {row["path"] for row in rows}:
        raise ValueError("E2-A result file manifest roster differs")
    for row in rows:
        path = actual[row["path"]]
        if path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
            raise ValueError(f"E2-A result file manifest differs: {row['path']}")


def publish(
    *,
    artifact_root: Path,
    artifact_zip: Path,
    output: Path,
    run_id: int,
    run_url: str,
    run_head_sha: str,
    artifact_id: int,
    artifact_name: str,
    artifact_size: int,
    artifact_digest: str,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("refusing to replace an E2-A publication")
    if (
        RUN_ID.fullmatch(str(run_id)) is None
        or RUN_ID.fullmatch(str(artifact_id)) is None
        or run_id != EXPECTED_RUN_ID
    ):
        raise ValueError("E2-A run or artifact ID is invalid")
    if run_url != (
        f"https://github.com/Atomics-hub/compression-lab/actions/runs/{run_id}"
    ):
        raise ValueError("E2-A run URL differs")
    if COMMIT.fullmatch(run_head_sha) is None or run_head_sha != EXPECTED_HEAD_SHA:
        raise ValueError("E2-A run commit is invalid")
    if ARTIFACT_DIGEST.fullmatch(artifact_digest) is None or artifact_size <= 0:
        raise ValueError("E2-A artifact metadata is invalid")
    if artifact_name != f"json-context-ceiling-e2-a-{run_id}":
        raise ValueError("E2-A artifact name differs")
    run_metadata_bytes, artifacts_metadata_bytes = fetch_github_metadata(run_id)
    verify_github_metadata(
        run=json.loads(run_metadata_bytes),
        artifacts=json.loads(artifacts_metadata_bytes),
        run_id=run_id,
        run_url=run_url,
        run_head_sha=run_head_sha,
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        artifact_size=artifact_size,
        artifact_digest=artifact_digest,
    )
    verify_zip_matches_tree(artifact_zip, artifact_root, artifact_size, artifact_digest)
    checksums = verify_checksum_manifest(artifact_root)
    result_path = artifact_root / "measurement" / "result.json"
    result = read_json(result_path)
    decision = verify_result_identity(result, run_head_sha)
    verify_result_file_manifest(result, artifact_root / "measurement")
    verify_rendered_publication(artifact_root, result)
    verification_lines = [
        line
        for line in (artifact_root / "verification.log")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(verification_lines) != 1 or json.loads(verification_lines[0]) != {
        "decision": decision,
        "verified": True,
    }:
        raise ValueError("E2-A hosted verification log differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".axiom-e2a-publish-", dir=output.parent
    ) as raw:
        stage = Path(raw) / "publication"
        stage.mkdir()
        shutil.copyfile(result_path, stage / "evidence.json")
        for name in ("README.md", "comparison.svg"):
            shutil.copyfile(artifact_root / "publication" / name, stage / name)
        for name in ("run.log", "verification.log"):
            shutil.copyfile(artifact_root / name, stage / name)
        (stage / "github-run.json").write_bytes(run_metadata_bytes)
        (stage / "github-artifacts.json").write_bytes(artifacts_metadata_bytes)
        shutil.copyfile(artifact_root / "SHA256SUMS", stage / "SHA256SUMS")
        shutil.copytree(
            artifact_root / "measurement" / "containers", stage / "containers"
        )
        source_members = {
            name: {
                "bytes": (artifact_root / name).stat().st_size,
                "sha256": checksums[name],
            }
            for name in sorted(
                set(REQUIRED_SOURCE_MEMBERS)
                | {
                    path
                    for path in checksums
                    if path.startswith("measurement/containers/")
                }
            )
        }
        published_members = {
            path.relative_to(stage).as_posix(): sha256_file(path)
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        receipt = {
            "schema_version": 1,
            "name": "axiom-json-context-ceiling-e2-a-publication-receipt-v1",
            "evidence_stage": "development_only_diagnostic",
            "source_run": {
                "id": run_id,
                "url": run_url,
                "head_sha": run_head_sha,
                "conclusion": "success",
            },
            "source_artifact": {
                "id": artifact_id,
                "name": artifact_name,
                "size_in_bytes": artifact_size,
                "digest": artifact_digest,
                "checksum_manifest_sha256": sha256_file(artifact_root / "SHA256SUMS"),
                "all_member_checksums_verified": True,
                "member_count": len(checksums),
                "zip_tree_verified": True,
                "github_metadata_verified": True,
            },
            "source_members": source_members,
            "published_members": published_members,
            "decision": result["decision"],
            "information_boundary": result["information_boundary"],
            "claim_ceiling": result["claim_ceiling"],
        }
        (stage / "receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stage.rename(output)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--run-head-sha", required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-size", type=int, required=True)
    parser.add_argument("--artifact-digest", required=True)
    args = parser.parse_args()
    try:
        receipt = publish(
            artifact_root=args.artifact_root,
            artifact_zip=args.artifact_zip,
            output=args.output,
            run_id=args.run_id,
            run_url=args.run_url,
            run_head_sha=args.run_head_sha,
            artifact_id=args.artifact_id,
            artifact_name=args.artifact_name,
            artifact_size=args.artifact_size,
            artifact_digest=args.artifact_digest,
        )
    except (
        KeyError,
        AttributeError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E2-A publication failed: {error}") from error
    print(json.dumps(receipt["decision"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
