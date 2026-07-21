#!/usr/bin/env python3
"""Verify all E1 shards and publish complete-byte training summaries."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
E1_CONFIG = ROOT / "config" / "frontier-headroom-oracle-census-e1-v1.json"
E1_RECOVERY_RECEIPT = (
    ROOT / "config" / "frontier-headroom-e1-run-29846879040-recovery.json"
)


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_script(
    "e1_runner_for_verifier", ROOT / "scripts" / "benchmark-frontier-headroom-e1.py"
)
E1_VERIFIER = load_script(
    "e1_plan_for_run_verifier", ROOT / "scripts" / "verify-frontier-headroom-e1-plan.py"
)


def require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"E1 {label} schema differs: {sorted(set(value) ^ expected)}")


PROCESS_KEYS = {
    "command", "declared_command", "wall_ns", "cpu_user_ns", "cpu_system_ns",
    "peak_rss_bytes", "exit_status", "timed_out", "output_exceeded",
    "stdout_log_bytes", "stdout_log_path", "stdout_log_sha256",
    "stderr_log_bytes", "stderr_log_path", "stderr_log_sha256",
}
REPETITION_KEYS = {
    "repetition", "warmup", "source_bytes", "source_sha256", "artifact_path",
    "artifact_bytes", "artifact_sha256", "restored_bytes", "restored_sha256",
    "exact", "compress", "decompress",
}
TRIAL_KEYS = {
    "task_id", "phase", "codec_id", "item_id", "category", "repetitions",
    "deterministic", "exact",
}
GENERATED_KEYS = {"item_id", "path", "bytes", "sha256"}
CHOICE_KEYS = {
    "codec_id", "decoded_bytes", "decoded_sha256", "artifact_bytes",
    "artifact_sha256",
}
CONTAINER_KEYS = {"item_id", "path", "bytes", "sha256", "segment_count", "choices"}
SHARD_KEYS = {
    "schema_version", "name", "completed", "phase", "category", "codec_group",
    "schedule_sha256", "training_manifest_sha256", "tool_receipt_sha256",
    "repository_commit", "trials", "generated_inputs", "public_validation_accessed",
    "private_holdout_accessed", "claim_ceiling",
}
SEGMENT_KEYS = {
    "schema_version", "name", "completed", "phase", "category", "codec_group",
    "schedule_sha256", "training_manifest_sha256", "tool_receipt_sha256",
    "repository_commit", "triggered", "whole_item_winners", "trials", "containers",
    "public_validation_accessed", "private_holdout_accessed", "claim_ceiling",
}
RECOVERY_RUN_ID = 29846879040
SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


def sha256_file(path: Path) -> str:
    return RUNNER.sha256_file(path)


def ordinary(path: Path) -> None:
    RUNNER.ordinary(path)


def require_file(
    root: Path,
    relative: str,
    expected_bytes: int,
    expected_sha256: str,
    bound: set[str],
) -> Path:
    path = root / relative
    ordinary(path)
    if path.stat().st_size != expected_bytes or sha256_file(path) != expected_sha256:
        raise ValueError(f"E1 bound result file differs: {relative}")
    if relative in bound:
        raise ValueError(f"E1 result file is multiply bound: {relative}")
    bound.add(relative)
    return path


def verify_process(
    process: dict[str, Any], declared: list[str], root: Path, bound: set[str]
) -> None:
    require_keys(process, PROCESS_KEYS, "process")
    if process["declared_command"] != declared:
        raise ValueError("E1 declared process command differs")
    if (
        process["exit_status"] != 0
        or process["timed_out"]
        or process["output_exceeded"]
    ):
        raise ValueError("E1 process did not complete cleanly")
    if process["wall_ns"] <= 0 or process["peak_rss_bytes"] <= 0:
        raise ValueError("E1 process telemetry is absent")
    for stream in ("stdout", "stderr"):
        path = process[f"{stream}_log_path"]
        size = process[f"{stream}_log_bytes"]
        digest = process[f"{stream}_log_sha256"]
        if path is None:
            if size != 0 or digest is not None:
                raise ValueError("E1 absent process log has metadata")
        else:
            require_file(root, path, size, digest, bound)


def expected_task_map(schedule: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = schedule["whole_item_tasks"] + schedule["sample_tasks"]
    return {row["task_id"]: row for row in rows}


def verify_trial(
    trial: dict[str, Any],
    root: Path,
    schedule_tasks: dict[str, dict[str, Any]],
    bound: set[str],
    e1: dict[str, Any],
) -> None:
    require_keys(trial, TRIAL_KEYS, "trial")
    task_id = trial["task_id"]
    if trial["phase"] == "segment":
        _prefix, codec_id, item_id, _index = task_id.split("/")
        task = schedule_tasks[f"whole/{codec_id}/{item_id}"]
    else:
        task = schedule_tasks[task_id]
    if trial["codec_id"] != task["codec_id"] or trial["item_id"] != task["item_id"]:
        raise ValueError("E1 trial identity differs")
    expected_repetitions = (
        e1["measurement"]["measured_repetitions_zpaq"]
        if trial["codec_id"] == "zpaq-5-m510"
        else e1["measurement"]["measured_repetitions_practical"]
    )
    if (
        len(trial["repetitions"]) != expected_repetitions
        or not trial["exact"]
        or not trial["deterministic"]
    ):
        raise ValueError("E1 trial repetition or exactness differs")
    identities = set()
    for index, repetition in enumerate(trial["repetitions"]):
        require_keys(repetition, REPETITION_KEYS, "repetition")
        if repetition["repetition"] != index or repetition["warmup"]:
            raise ValueError("E1 measured repetition index differs")
        if (
            not repetition["exact"]
            or repetition["restored_bytes"] != repetition["source_bytes"]
            or repetition["restored_sha256"] != repetition["source_sha256"]
        ):
            raise ValueError("E1 repetition roundtrip differs")
        require_file(
            root,
            repetition["artifact_path"],
            repetition["artifact_bytes"],
            repetition["artifact_sha256"],
            bound,
        )
        verify_process(repetition["compress"], task["compress"], root, bound)
        verify_process(repetition["decompress"], task["decompress"], root, bound)
        identities.add((repetition["artifact_bytes"], repetition["artifact_sha256"]))
    if len(identities) != 1:
        raise ValueError("E1 measured artifacts are nondeterministic")


def bind_discarded_warmup_logs(
    document: dict[str, Any], root: Path, bound: set[str], e1: dict[str, Any]
) -> list[dict[str, Any]]:
    """Bind legacy E1 warmup logs that the runner retained but did not receipt.

    Run 29846879040 predates the runner cleanup that removes unscored warmup
    logs.  Its artifact ZIP digests preserve the original shards, so recovery
    must inventory the exact deterministic warmup-log roster rather than
    deleting or broadly ignoring those files.
    """
    records = []
    warmups = e1["measurement"]["warmups_practical"]
    for trial in document["trials"]:
        if trial["codec_id"] == "zpaq-5-m510":
            continue
        task_slug = trial["task_id"].replace("/", "__")
        for index in range(warmups):
            repetition = -1 - index
            for process in ("compress", "decompress"):
                streams = ["stderr"]
                if trial["codec_id"] != "xz-lzma2-9e":
                    streams.append("stdout")
                for stream in streams:
                    relative = (
                        f"logs/{task_slug}/{repetition}/{process}.{stream}"
                    )
                    path = root / relative
                    ordinary(path)
                    size = path.stat().st_size
                    if size > RUNNER.MAX_OUTPUT:
                        raise ValueError(
                            f"E1 discarded warmup log exceeds limit: {relative}"
                        )
                    digest = sha256_file(path)
                    require_file(root, relative, size, digest, bound)
                    records.append(
                        {"path": relative, "bytes": size, "sha256": digest}
                    )
    return records


def load_recovery_receipt(
    source_run_id: int | None, schedule: dict[str, Any]
) -> dict[str, Any] | None:
    if source_run_id is None:
        return None
    if source_run_id != RECOVERY_RUN_ID:
        raise ValueError("E1 recovery source run is not the pinned failed run")
    ordinary(E1_RECOVERY_RECEIPT)
    receipt = json.loads(E1_RECOVERY_RECEIPT.read_bytes())
    require_keys(
        receipt,
        {
            "schema_version", "name", "source_run_id", "source_run_attempt",
            "source_head_sha", "source_event", "source_conclusion", "source_url",
            "measurement_runner_sha256", "failed_publication_verifier_sha256",
            "artifacts",
        },
        "recovery receipt",
    )
    if (
        receipt["schema_version"] != 1
        or receipt["name"] != "frontier-headroom-e1-github-recovery-receipt-v1"
        or receipt["source_run_id"] != RECOVERY_RUN_ID
        or receipt["source_run_attempt"] != 1
        or receipt["source_head_sha"] != schedule["repository_commit"]
        or receipt["source_event"] != "workflow_dispatch"
        or receipt["source_conclusion"] != "failure"
        or receipt["measurement_runner_sha256"]
        != "d2dd2c1f07142bb8849d369688e0b20a30cb6b64881c01e3e3e3b805482527ea"
        or receipt["failed_publication_verifier_sha256"]
        != "4afdb9dd7ac7d2ab128fd590694814d11e55ad252a6f626fc55fc7113da0f145"
    ):
        raise ValueError("E1 recovery receipt identity differs")
    names = set()
    for artifact in receipt["artifacts"]:
        require_keys(
            artifact, {"id", "name", "size_in_bytes", "digest", "expired"},
            "recovery artifact",
        )
        if (
            not isinstance(artifact["id"], int)
            or artifact["id"] <= 0
            or not isinstance(artifact["name"], str)
            or not isinstance(artifact["size_in_bytes"], int)
            or artifact["size_in_bytes"] <= 0
            or SHA256_DIGEST.fullmatch(artifact["digest"]) is None
            or artifact["expired"] is not False
            or artifact["name"] in names
        ):
            raise ValueError("E1 recovery artifact receipt differs")
        names.add(artifact["name"])
    if len(receipt["artifacts"]) != 28:
        raise ValueError("E1 recovery artifact roster differs")
    return receipt


def source_artifact_for_shard(
    document: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    if document["phase"] == "segment":
        lane = "segment"
    else:
        group = (
            "zpaq" if document["codec_group"] == "zpaq-5-m510" else "practical"
        )
        lane = f"{document['phase']}-{group}"
    expected = (
        f"e1-{lane}-{document['category']}-{receipt['source_run_id']}"
    )
    matches = [row for row in receipt["artifacts"] if row["name"] == expected]
    if len(matches) != 1:
        raise ValueError(f"E1 recovery shard artifact is not pinned: {expected}")
    return matches[0]


def verify_shard(
    path: Path,
    schedule: dict[str, Any],
    schedule_sha: str,
    manifest_sha: str,
    receipt_sha: str,
    manifest: dict[str, Any],
    e1: dict[str, Any],
    recovery_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    root = path.parent
    document = json.loads(path.read_bytes())
    require_keys(
        document,
        SEGMENT_KEYS if document.get("phase") == "segment" else SHARD_KEYS,
        "result",
    )
    if document["schema_version"] != 1 or document["completed"] is not True:
        raise ValueError("E1 shard completion declaration differs")
    if (
        document["schedule_sha256"] != schedule_sha
        or document["training_manifest_sha256"] != manifest_sha
        or document["tool_receipt_sha256"] != receipt_sha
    ):
        raise ValueError("E1 shard provenance differs")
    if document["public_validation_accessed"] or document["private_holdout_accessed"]:
        raise ValueError("E1 shard crossed a sealed boundary")
    bound = {"result.json"}
    tasks = expected_task_map(schedule)
    for trial in document["trials"]:
        verify_trial(trial, root, tasks, bound, e1)
    for row in document.get("generated_inputs", []):
        require_keys(row, GENERATED_KEYS, "generated input")
        require_file(root, row["path"], row["bytes"], row["sha256"], bound)
    for row in document.get("containers", []):
        require_keys(row, CONTAINER_KEYS, "segment container")
        if row["segment_count"] != len(row["choices"]):
            raise ValueError("E1 segment count differs")
        for choice in row["choices"]:
            require_keys(choice, CHOICE_KEYS, "segment choice")
        container_path = require_file(
            root, row["path"], row["bytes"], row["sha256"], bound
        )
        item = next(value for value in manifest["items"] if value["id"] == row["item_id"])
        trial_map = {}
        for trial in document["trials"]:
            _phase, codec, item_id, index = trial["task_id"].split("/")
            trial_map[(item_id, int(index), codec)] = trial
        choices = []
        for index, choice in enumerate(row["choices"]):
            trial = trial_map[(row["item_id"], index, choice["codec_id"])]
            rep = trial["repetitions"][0]
            if any(
                choice[key] != rep[rep_key]
                for key, rep_key in (
                    ("decoded_bytes", "source_bytes"),
                    ("decoded_sha256", "source_sha256"),
                    ("artifact_bytes", "artifact_bytes"),
                    ("artifact_sha256", "artifact_sha256"),
                )
            ):
                raise ValueError("E1 segment choice differs from its measured artifact")
            choices.append({**choice, "artifact_path": str(root / rep["artifact_path"])})
        rebuilt = RUNNER.axe1g(item, e1["oracle_routing"]["segment_bytes"], choices)
        if rebuilt != container_path.read_bytes():
            raise ValueError("E1 AXE1G container bytes do not reconstruct")
    discarded_warmup_logs = []
    legacy_warmups_present = any("/-1/" in path for path in {
        candidate.relative_to(root).as_posix()
        for candidate in root.rglob("*")
        if candidate.is_file()
    })
    if legacy_warmups_present and recovery_receipt is None:
        raise ValueError("E1 legacy warmup logs require explicit pinned recovery")
    if legacy_warmups_present:
        discarded_warmup_logs = bind_discarded_warmup_logs(
            document, root, bound, e1
        )
    actual = {
        candidate.relative_to(root).as_posix()
        for candidate in root.rglob("*")
        if candidate.is_file()
    }
    if actual != bound:
        raise ValueError(
            f"E1 shard has missing or unbound files: {sorted(actual ^ bound)}"
        )
    source_artifact = (
        source_artifact_for_shard(document, recovery_receipt)
        if recovery_receipt is not None
        else None
    )
    return document | {
        "_root": root,
        "_result_path": path,
        "_discarded_warmup_logs": discarded_warmup_logs,
        "_source_artifact": source_artifact,
    }


def write_axe1o(
    path: Path, category: str, manifest_sha: str, choices: list[dict[str, Any]]
) -> dict[str, Any]:
    frame = bytearray(b"AXE1O" + bytes([1]))
    frame.extend(RUNNER.packed_string(category))
    frame.extend(bytes.fromhex(manifest_sha))
    frame.extend(struct.pack("<I", len(choices)))
    artifacts = []
    for row in sorted(choices, key=lambda value: value["item_id"]):
        artifact = row["artifact_path"]
        frame.extend(RUNNER.packed_string(row["item_id"]))
        frame.extend(RUNNER.packed_string(row["codec_id"]))
        frame.extend(struct.pack("<Q", row["decoded_bytes"]))
        frame.extend(bytes.fromhex(row["decoded_sha256"]))
        frame.extend(struct.pack("<Q", row["artifact_bytes"]))
        frame.extend(bytes.fromhex(row["artifact_sha256"]))
        artifacts.append(artifact.read_bytes())
    for artifact in artifacts:
        frame.extend(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frame)
    return {
        "path": path.name,
        "bytes": len(frame),
        "sha256": hashlib.sha256(frame).hexdigest(),
    }


def write_axe1g(
    path: Path, item: dict[str, Any], segment_bytes: int, choice: dict[str, Any]
) -> dict[str, Any]:
    frame = RUNNER.axe1g(item, segment_bytes, [choice])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frame)
    return {
        "item_id": item["id"],
        "path": path.name,
        "bytes": len(frame),
        "sha256": hashlib.sha256(frame).hexdigest(),
        "codec_id": choice["codec_id"],
    }


def wrapped_choice(
    item: dict[str, Any], codec_id: str, metadata: dict[str, Any], artifact: Path
) -> dict[str, Any]:
    return {
        "item_id": item["id"],
        "codec_id": codec_id,
        "decoded_bytes": item["bytes"],
        "decoded_sha256": item["sha256"],
        "artifact_bytes": metadata["bytes"],
        "artifact_sha256": metadata["sha256"],
        "artifact_path": artifact,
    }


def trial_choice(trial: dict[str, Any], root: Path) -> dict[str, Any]:
    rep = trial["repetitions"][0]
    return {
        "item_id": trial["item_id"],
        "codec_id": trial["codec_id"],
        "decoded_bytes": rep["source_bytes"],
        "decoded_sha256": rep["source_sha256"],
        "artifact_bytes": rep["artifact_bytes"],
        "artifact_sha256": rep["artifact_sha256"],
        "artifact_path": root / rep["artifact_path"],
    }


def performance_summary(
    trials: list[dict[str, Any]], codec_id: str, e1: dict[str, Any]
) -> dict[str, Any]:
    selected = [row for row in trials if row["codec_id"] == codec_id]
    count = len(selected[0]["repetitions"])
    repetitions = []
    for index in range(count):
        repetitions.append(
            {
                "repetition": index,
                "items": [
                    {
                        "item_id": row["item_id"],
                        "source_bytes": row["repetitions"][index]["source_bytes"],
                        "encode_wall_ns": row["repetitions"][index]["compress"][
                            "wall_ns"
                        ],
                        "decode_wall_ns": row["repetitions"][index]["decompress"][
                            "wall_ns"
                        ],
                        "peak_rss_bytes": max(
                            row["repetitions"][index]["compress"]["peak_rss_bytes"],
                            row["repetitions"][index]["decompress"]["peak_rss_bytes"],
                        ),
                    }
                    for row in selected
                ],
            }
        )
    metrics = E1_VERIFIER.aggregate_category_metrics(
        repetitions, expected_item_ids={row["item_id"] for row in selected}
    )
    return {
        **metrics,
        "attained_tiers": [],
        "tier_status": "unavailable_required_host_power_and_thermal_telemetry",
        "runner_comparability": "same hosted runner only within this category/codec shard; cross-shard speed comparisons are contextual",
    }


def aggregate(
    schedule_path: Path,
    manifest_path: Path,
    receipt_path: Path,
    shards_root: Path,
    output: Path,
    *,
    recover_source_run: int | None = None,
    verification_commit: str | None = None,
) -> dict[str, Any]:
    for path in (schedule_path, manifest_path, receipt_path):
        ordinary(path)
    schedule = json.loads(schedule_path.read_bytes())
    manifest = json.loads(manifest_path.read_bytes())
    manifest_items = {row["id"]: row for row in manifest["items"]}
    e1 = json.loads(E1_CONFIG.read_bytes())
    schedule_sha = sha256_file(schedule_path)
    manifest_sha = sha256_file(manifest_path)
    receipt_sha = sha256_file(receipt_path)
    recovery_receipt = load_recovery_receipt(recover_source_run, schedule)
    if recovery_receipt is not None and (
        verification_commit is None or COMMIT.fullmatch(verification_commit) is None
    ):
        raise ValueError("E1 recovery requires an exact verification commit")
    shard_paths = sorted(shards_root.rglob("result.json"))
    shards = [
        verify_shard(
            path, schedule, schedule_sha, manifest_sha, receipt_sha, manifest, e1,
            recovery_receipt,
        )
        for path in shard_paths
    ]
    categories = sorted({row["category"] for row in e1["items"]})
    for category in categories:
        if (
            sum(
                row["phase"] == "whole" and row["category"] == category
                for row in shards
            )
            != 2
        ):
            raise ValueError("E1 whole shard roster differs")
        if (
            sum(
                row["phase"] == "sample" and row["category"] == category
                for row in shards
            )
            != 2
        ):
            raise ValueError("E1 sample shard roster differs")
        if (
            sum(
                row["phase"] == "segment" and row["category"] == category
                for row in shards
            )
            != 1
        ):
            raise ValueError("E1 segment shard roster differs")
    if len(shards) != 25:
        raise ValueError("E1 total shard roster differs")
    if recovery_receipt is not None and len(
        {row["_source_artifact"]["name"] for row in shards}
    ) != 25:
        raise ValueError("E1 recovery source artifact use differs")
    if recovery_receipt is not None:
        for row in shards:
            relative_parts = row["_result_path"].relative_to(shards_root).parts
            if (
                not relative_parts
                or relative_parts[0] != row["_source_artifact"]["name"]
            ):
                raise ValueError(
                    "E1 recovery shard directory differs from pinned artifact"
                )
    if output.exists():
        raise ValueError("refusing to replace E1 aggregate")
    output.mkdir(parents=True)
    summaries = []
    codec_ids = [row["id"] for row in e1["codecs"]]
    for category in categories:
        whole_trials = [
            trial_choice(trial, shard["_root"])
            for shard in shards
            if shard["phase"] == "whole" and shard["category"] == category
            for trial in shard["trials"]
        ]
        item_ids = sorted({row["item_id"] for row in whole_trials})
        controls = {}
        for codec in codec_ids:
            choices = [row for row in whole_trials if row["codec_id"] == codec]
            controls[codec] = write_axe1o(
                output / "containers" / f"{category}-{codec}.axe1o",
                category,
                manifest_sha,
                choices,
            )
        oracle_choices = [
            min(
                (row for row in whole_trials if row["item_id"] == item),
                key=lambda row: (row["artifact_bytes"], row["codec_id"]),
            )
            for item in item_ids
        ]
        oracle = write_axe1o(
            output / "containers" / f"{category}-per-item-oracle.axe1o",
            category,
            manifest_sha,
            oracle_choices,
        )
        best_ratio = min(controls.values(), key=lambda row: row["bytes"])
        practical = {
            key: value for key, value in controls.items() if key != "zpaq-5-m510"
        }
        best_practical = min(practical.values(), key=lambda row: row["bytes"])
        practical_oracle_choices = [
            min(
                (
                    row for row in whole_trials
                    if row["item_id"] == item and row["codec_id"] != "zpaq-5-m510"
                ),
                key=lambda row: (row["artifact_bytes"], row["codec_id"]),
            )
            for item in item_ids
        ]
        practical_oracle = write_axe1o(
            output / "containers" / f"{category}-practical-per-item-oracle.axe1o",
            category,
            manifest_sha,
            practical_oracle_choices,
        )
        sample_trials = [
            trial_choice(trial, shard["_root"])
            for shard in shards
            if shard["phase"] == "sample" and shard["category"] == category
            for trial in shard["trials"]
        ]
        sample_totals = {
            codec: sum(
                row["artifact_bytes"]
                for row in sample_trials
                if row["codec_id"] == codec
            )
            for codec in codec_ids
        }
        best_practical_sample = min(sample_totals[codec] for codec in codec_ids[:-1])
        ceiling_sample = sample_totals["zpaq-5-m510"]
        segment = next(
            row
            for row in shards
            if row["phase"] == "segment" and row["category"] == category
        )
        segment_fallbacks = []
        for choice in oracle_choices:
            segment_fallbacks.append(
                write_axe1g(
                    output
                    / "containers"
                    / f"{category}-{choice['item_id']}-whole-fallback.axe1g",
                    manifest_items[choice["item_id"]],
                    manifest_items[choice["item_id"]]["bytes"],
                    choice,
                )
            )
        fallback_outer = write_axe1o(
            output / "containers" / f"{category}-whole-fallback.axe1o",
            category,
            manifest_sha,
            [
                wrapped_choice(
                    manifest_items[row["item_id"]],
                    f"axe1g-whole-{row['codec_id']}",
                    row,
                    output / "containers" / row["path"],
                )
                for row in segment_fallbacks
            ],
        )
        segment_outer = None
        if segment["triggered"]:
            segment_outer = write_axe1o(
                output / "containers" / f"{category}-segment-oracle.axe1o",
                category,
                manifest_sha,
                [
                    wrapped_choice(
                        manifest_items[row["item_id"]],
                        "axe1g-segment-oracle",
                        row,
                        segment["_root"] / row["path"],
                    )
                    for row in segment["containers"]
                ],
            )
        segment_bytes = segment_outer["bytes"] if segment_outer else None
        fallback_bytes = fallback_outer["bytes"]
        segment_gain_bp = (
            (fallback_bytes - segment_bytes) * 10_000 // fallback_bytes
            if segment_bytes is not None
            else None
        )
        category_whole_trials = [
            trial
            for shard in shards
            if shard["phase"] == "whole" and shard["category"] == category
            for trial in shard["trials"]
        ]
        summaries.append(
            {
                "category": category,
                "item_count": len(item_ids),
                "whole_controls": controls,
                "best_single_practical_bytes": best_practical["bytes"],
                "best_single_ratio_bytes": best_ratio["bytes"],
                "practical_per_item_oracle": practical_oracle,
                "practical_routing_gain_basis_points": (
                    best_practical["bytes"] - practical_oracle["bytes"]
                )
                * 10000
                // best_practical["bytes"],
                "per_item_oracle": oracle,
                "total_headroom_basis_points": (
                    best_practical["bytes"] - oracle["bytes"]
                )
                * 10000
                // best_practical["bytes"],
                "per_item_oracle_gain_basis_points": (
                    best_ratio["bytes"] - oracle["bytes"]
                )
                * 10000
                // best_ratio["bytes"],
                "sample_codec_payload_bytes": sample_totals,
                "sample_ceiling_gap_basis_points": (
                    best_practical_sample - ceiling_sample
                )
                * 10000
                // best_practical_sample,
                "segment_triggered": segment["triggered"],
                "segment_containers": [
                    {key: value for key, value in row.items() if key != "choices"}
                    for row in segment["containers"]
                ],
                "segment_whole_fallback_containers": segment_fallbacks,
                "segment_complete_category_container": segment_outer,
                "segment_whole_fallback_category_container": fallback_outer,
                "segment_complete_bytes": segment_bytes,
                "segment_whole_fallback_bytes": fallback_outer["bytes"],
                "segment_gain_basis_points": segment_gain_bp,
                "segment_safe_against_whole_fallback": (
                    segment_bytes <= fallback_bytes if segment_bytes is not None else None
                ),
                "segment_safe_upper_bound_bytes": (
                    min(segment_bytes, fallback_bytes)
                    if segment_bytes is not None
                    else fallback_bytes
                ),
                "performance": {
                    codec: performance_summary(category_whole_trials, codec, e1)
                    for codec in codec_ids
                },
            }
        )
    raw_shards = [
        {
            "path": row["_result_path"].relative_to(shards_root).as_posix(),
            "bytes": row["_result_path"].stat().st_size,
            "sha256": sha256_file(row["_result_path"]),
            "legacy_retained_warmup_logs": row["_discarded_warmup_logs"],
            "source_github_artifact": row["_source_artifact"],
        }
        for row in shards
    ]
    result = {
        "schema_version": 2,
        "name": "frontier-headroom-e1-training-result-v2",
        "completed": True,
        "schedule_sha256": schedule_sha,
        "training_manifest_sha256": manifest_sha,
        "tool_receipt_sha256": receipt_sha,
        "repository_commit": schedule["repository_commit"],
        "verification": {
            "repository_commit": verification_commit,
            "publication_verifier_sha256": sha256_file(Path(__file__)),
            "publication_runner_sha256": sha256_file(
                ROOT / "scripts" / "benchmark-frontier-headroom-e1.py"
            ),
            "measurement_runner_sha256": (
                recovery_receipt["measurement_runner_sha256"]
                if recovery_receipt is not None
                else None
            ),
            "failed_publication_verifier_sha256": (
                recovery_receipt["failed_publication_verifier_sha256"]
                if recovery_receipt is not None
                else None
            ),
            "config_sha256": sha256_file(E1_CONFIG),
            "recovery_receipt_sha256": (
                sha256_file(E1_RECOVERY_RECEIPT)
                if recovery_receipt is not None
                else None
            ),
            "source_run_id": recover_source_run,
            "source_run_attempt": (
                recovery_receipt["source_run_attempt"]
                if recovery_receipt is not None
                else None
            ),
        },
        "raw_shards": raw_shards,
        "category_summaries": summaries,
        "public_validation_accessed": False,
        "private_holdout_accessed": False,
        "measurements_exist": True,
        "claim_ceiling": e1["claim_ceiling"],
    }
    (output / "result.json").write_bytes(RUNNER.json_bytes(result))
    lines = [
        "# E1 frozen training frontier census",
        "",
        "> Training-only diagnostic; not an Axiom candidate, validation result, "
        "private-holdout result, or state-of-the-art claim.",
        "",
        "All sizes are complete framed bytes. Routing gain compares the best "
        "practical codec per item with the best single practical codec for the "
        "category. Total headroom additionally includes the ZPAQ research ceiling.",
        "",
        "| Category | Best single practical | Practical oracle | Full oracle | "
        "Routing gain | Total headroom |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['category']} | {row['best_single_practical_bytes']:,} | "
            f"{row['practical_per_item_oracle']['bytes']:,} | "
            f"{row['per_item_oracle']['bytes']:,} | "
            f"{row['practical_routing_gain_basis_points'] / 100:.2f}% | "
            f"{row['total_headroom_basis_points'] / 100:.2f}% |"
        )
    lines.extend(
        [
            "",
            "Speed and memory are same-hosted-runner contextual measurements, "
            "not dedicated-machine comparisons. Exact per-codec compression, "
            "decompression, peak RSS, integrity, and provenance fields are in "
            "`result.json`.",
            "",
        ]
    )
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")
    sums = []
    for path in sorted(
        candidate
        for candidate in output.rglob("*")
        if candidate.is_file() and candidate.name != "SHA256SUMS"
    ):
        sums.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}\n")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tool-receipt", type=Path, required=True)
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recover-source-run", type=int)
    parser.add_argument("--verification-commit")
    args = parser.parse_args()
    try:
        result = aggregate(
            args.schedule,
            args.manifest,
            args.tool_receipt,
            args.shards_root,
            args.output,
            recover_source_run=args.recover_source_run,
            verification_commit=args.verification_commit,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"E1 run verification failed: {error}") from error
    print(
        json.dumps(
            {
                "completed": result["completed"],
                "categories": len(result["category_summaries"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
