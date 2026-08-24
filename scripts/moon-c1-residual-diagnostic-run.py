#!/usr/bin/env python3
"""Authorized, non-scoring C1 residual-diagnostic driver.

The CLI refuses unless the exact owner literal names the checked-out readiness
commit. It validates every frozen code/metadata binding before opening either
retained snapshot, then durably charges the shared Moon development budget
before each subprocess dispatch. A dispatched failure remains charged.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import Callable, Optional


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "moon-c1-residual-diagnostic-readiness-v1"
SUMMARY_SCHEMA = "moon-c1-residual-diagnostic-sweep-v1"
BUDGET_SCHEMA = "moon-prescreen-budget-v1"
BUDGET_CAP = 160
CONFIG_RELATIVE = Path("config/moon-c1-residual-diagnostic-readiness-v1.json")
READINESS_FILES = {
    "config/moon-c1-residual-diagnostic-readiness-v1.json",
    "docs/benchmarks/2026-08-23-moon-c1-residual-diagnostic-readiness-v1.md",
    "scripts/moon-c1-residual-diagnostic-run.py",
    "tests/test_moon_c1_residual_diagnostic_readiness.py",
    "tests/test_moon_c1_residual_diagnostic_run.py",
}
TOP_LEVEL_KEYS = {
    "schema",
    "kernel_version",
    "evidence_stage",
    "claim_ceiling",
    "arm",
    "item_index",
    "sse_bucket_bits",
    "q24_scale",
    "source_bytes",
    "source_sha256",
    "tape_bytes",
    "tape_sha256",
    "charged_event_digest_sha256",
    "identity_guard",
    "state_accounting",
    "ledger",
    "loss",
    "primary_partition",
    "overlays",
    "live_match_partition",
    "match_bits",
    "match_lifecycle",
    "match_length_buckets",
    "match_distance_buckets",
    "shadow_oracle",
}
STATE_SEMANTICS = (
    "checked peak-phase logical payload accounting; Vec capacity, allocator "
    "overhead, stack, and RSS are not claimed"
)
REPEAT_SIGNAL = (
    "canonical live_match_partition is the bounded causal repeat signal; no "
    "separate unbounded repeat overlay is retained"
)
SHADOW_SELECTION = (
    "at each position, any retained verified candidate may supply the current "
    "byte; candidates may change every byte, so all fields are non-causal "
    "hindsight upper bounds prohibited as direct funding evidence"
)
SHADOW_OPPORTUNITY = "per-position verified-candidate opportunity count, not span mass"
SHADOW_SELF_OVERLAP = (
    "legal because every candidate byte is strictly earlier than the current position"
)


class Refused(SystemExit):
    """Fail-closed readiness or lifecycle refusal."""


class DuplicateJsonKey(ValueError):
    """An inbound JSON object repeated a member name."""


class InvalidJsonConstant(ValueError):
    """Inbound JSON used a non-standard NaN or infinity token."""


def strict_json_loads(data: bytes, what: str) -> object:
    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
        value = {}
        for key, member in pairs:
            if key in value:
                raise DuplicateJsonKey(key)
            value[key] = member
        return value

    def reject_constant(token: str) -> object:
        raise InvalidJsonConstant(token)

    try:
        return json.loads(
            data,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, DuplicateJsonKey, InvalidJsonConstant) as error:
        raise Refused(f"cannot load {what}: duplicate key or invalid JSON") from error


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, what: str) -> dict:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Refused(f"cannot load {what}: {error}") from error
    value = strict_json_loads(data, what)
    if not isinstance(value, dict):
        raise Refused(f"{what} must be a JSON object")
    return value


def git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": "/var/empty",
        "XDG_CONFIG_HOME": "/var/empty",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "LC_ALL": "C",
        "TMPDIR": "/private/tmp",
    }


def git(*arguments: str) -> str:
    try:
        return subprocess.check_output(
            ["/usr/bin/git", *arguments],
            cwd=ROOT,
            text=True,
            stderr=subprocess.STDOUT,
            env=git_environment(),
        ).strip()
    except subprocess.CalledProcessError as error:
        raise Refused(
            f"git {' '.join(arguments)} refused: {error.output.strip()}"
        ) from error


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def durable_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.{os.getpid()}.pending")
    if lexists(pending):
        raise Refused(f"budget staging path already exists: {pending}")
    with pending.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_budget(path: Path) -> int:
    if not path.is_file() or path.is_symlink():
        raise Refused("exact Moon budget is missing, non-regular, or symlinked")
    if path.stat().st_nlink != 1:
        raise Refused("exact Moon budget must have one hard link")
    value = load_object(path, "Moon budget")
    if set(value) != {"schema", "runs_consumed", "cap"}:
        raise Refused("Moon budget keys differ")
    if value.get("schema") != BUDGET_SCHEMA or value.get("cap") != BUDGET_CAP:
        raise Refused("Moon budget schema or cap differs")
    if type(value.get("cap")) is not int:
        raise Refused("Moon budget cap type differs")
    consumed = value.get("runs_consumed")
    if type(consumed) is not int or not 0 <= consumed <= BUDGET_CAP:
        raise Refused("Moon budget consumed value is invalid")
    return consumed


def charge_budget(path: Path, consumed: int) -> None:
    durable_replace(
        path,
        canonical_json(
            {"schema": BUDGET_SCHEMA, "runs_consumed": consumed, "cap": BUDGET_CAP}
        ),
    )


def validate_bindings(config: dict, authorized_commit: str, owner_literal: str) -> None:
    if config.get("schema") != SCHEMA:
        raise Refused("readiness schema differs")
    verify_git_identity(config)
    if not re.fullmatch(r"[0-9a-f]{40}", authorized_commit):
        raise Refused("authorized readiness commit must be full lowercase 40-hex")
    expected_literal = config["authority"]["exact_owner_literal_template"].replace(
        "{FINAL_READINESS_COMMIT}", authorized_commit
    )
    if owner_literal != expected_literal:
        raise Refused("owner literal differs")
    if git("rev-parse", "HEAD") != authorized_commit:
        raise Refused("HEAD differs from authorized readiness commit")
    if git("status", "--porcelain"):
        raise Refused("working tree is not clean")
    identity = config["identity"]
    implementation = identity["implementation_commit"]
    if git("rev-parse", f"{implementation}^") != identity["implementation_base_commit"]:
        raise Refused("implementation parent differs")
    if (
        git("rev-parse", f"{implementation}^{{tree}}")
        != identity["implementation_tree"]
    ):
        raise Refused("implementation tree differs")
    changed = set(
        filter(None, git("diff", "--name-only", f"{implementation}..HEAD").splitlines())
    )
    configured_roster = identity.get("readiness_diff_roster")
    if (
        not isinstance(configured_roster, list)
        or set(configured_roster) != READINESS_FILES
        or len(configured_roster) != len(READINESS_FILES)
        or changed != READINESS_FILES
    ):
        raise Refused("readiness commit diff roster differs")
    try:
        subprocess.run(
            ["/usr/bin/git", "merge-base", "--is-ancestor", implementation, "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            env=git_environment(),
        )
    except subprocess.CalledProcessError as error:
        raise Refused("implementation is not an ancestor of readiness HEAD") from error
    for group in ("source_sha256", "build_inputs_sha256"):
        for relative, expected in identity[group].items():
            if sha256_file(ROOT / relative) != expected:
                raise Refused(f"bound file differs: {relative}")
    for metadata in config["retained_snapshot_identity"]["metadata_sources"]:
        path = ROOT / metadata["path"]
        if sha256_file(path) != metadata["sha256"]:
            raise Refused(f"metadata source differs: {metadata['path']}")
        if (
            git("rev-parse", f"{implementation}:{metadata['path']}")
            != metadata["git_blob"]
        ):
            raise Refused(f"metadata git blob differs: {metadata['path']}")
    for relative, expected in config["package_bindings"].items():
        if sha256_file(ROOT / relative) != expected:
            raise Refused(f"readiness package file differs: {relative}")
    runtime = config["runtime"]
    if (
        runtime["shared_budget_path"]
        != "/Users/guts/Documents/axiom-moonshot-corpora/run-budget.json"
        or runtime["shared_budget_schema"] != BUDGET_SCHEMA
        or type(runtime["shared_budget_cap"]) is not int
        or runtime["shared_budget_cap"] != BUDGET_CAP
        or type(runtime["expected_consumed_before"]) is not int
        or runtime["expected_consumed_before"] != 52
        or type(runtime["expected_consumed_after"]) is not int
        or runtime["expected_consumed_after"] != 54
    ):
        raise Refused("frozen shared budget identity differs")
    authority = config["authority"]
    authority_keys = {
        "attempts_authorized",
        "execution_currently_authorized",
        "retained_snapshot_read_authorized",
        "candidate_execution_authorized",
        "scoring_authorized",
        "corpus_advancement_authorized",
        "run_budget_advancement_authorized",
        "ledger_advancement_authorized",
        "exact_owner_literal_template",
        "binding_rule",
    }
    if set(authority) != authority_keys:
        raise Refused("authority key set differs")
    if (
        type(authority["attempts_authorized"]) is not int
        or authority["attempts_authorized"] != 0
        or any(
            value is not False
            for key, value in authority.items()
            if key.endswith("_authorized") and key != "attempts_authorized"
        )
    ):
        raise Refused("readiness record already carries authority")


def inspect_snapshot(path: Path) -> tuple[int, str, int]:
    digest = hashlib.sha256()
    size = 0
    records = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                size += len(chunk)
                records += chunk.count(b"\n")
                digest.update(chunk)
    except OSError as error:
        raise Refused(f"cannot inspect snapshot: {path}: {error}") from error
    return size, digest.hexdigest(), records


def validate_snapshots(config: dict, paths: list[Path]) -> list[int]:
    snapshots = config["retained_snapshot_identity"]["snapshots"]
    if len(snapshots) != len(paths):
        raise Refused("snapshot path count differs")
    references_path = ROOT / config["runtime"]["references"]
    references = load_object(references_path, "local references")["snapshots"]
    record_counts = []
    for snapshot, path in zip(snapshots, paths):
        if not path.is_file() or path.is_symlink():
            raise Refused(f"snapshot is missing, non-regular, or symlinked: {path}")
        size, actual, records = inspect_snapshot(path)
        if size != snapshot["source_bytes"]:
            raise Refused(f"snapshot size differs: {snapshot['name']}")
        if actual != snapshot["source_sha256"]:
            raise Refused(f"snapshot SHA-256 differs: {snapshot['name']}")
        reference = references.get(snapshot["name"])
        if not isinstance(reference, dict) or any(
            reference.get(key) != snapshot[key]
            for key in ("source_bytes", "source_sha256")
        ):
            raise Refused(f"snapshot references differ: {snapshot['name']}")
        record_counts.append(records)
    return record_counts


def prepare_output_roster(
    config: dict,
) -> tuple[list[Path], int, tuple[int, int], Path]:
    outputs: list[Path] = []
    for raw in config["output_roster"]:
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise Refused("output roster must remain beneath repository root")
        path = ROOT / relative
        current = ROOT
        for component in relative.parent.parts:
            current = current / component
            if lexists(current):
                if current.is_symlink() or not current.is_dir():
                    raise Refused(f"output ancestor is not a real directory: {current}")
            else:
                current.mkdir()
        # Recheck after creation so a replaced ancestor does not pass silently.
        current = ROOT
        for component in relative.parent.parts:
            current = current / component
            if current.is_symlink() or not current.is_dir():
                raise Refused(f"output ancestor changed during preflight: {current}")
        if lexists(path):
            raise Refused(f"an output-roster path already exists: {path}")
        outputs.append(path)
    parents = {path.parent for path in outputs}
    if len(parents) != 1:
        raise Refused("all output-roster files must share one held directory")
    parent = parents.pop()
    required = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise Refused("platform lacks required POSIX directory safety flags")
    try:
        directory_fd = os.open(parent, required)
    except OSError as error:
        raise Refused(f"cannot hold output directory: {error}") from error
    held = os.fstat(directory_fd)
    lexical = os.stat(parent, follow_symlinks=False)
    if not stat.S_ISDIR(held.st_mode) or (held.st_dev, held.st_ino) != (
        lexical.st_dev,
        lexical.st_ino,
    ):
        os.close(directory_fd)
        raise Refused("output directory identity differs")
    return outputs, directory_fd, (held.st_dev, held.st_ino), parent


def verify_held_directory(path: Path, expected: tuple[int, int]) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise Refused(f"output directory disappeared: {error}") from error
    if (
        not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != expected
    ):
        raise Refused("output directory path no longer names held directory")


def read_report_once(directory_fd: int, name: str) -> tuple[bytes, dict, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as error:
        raise Refused(f"cannot open staged report: {error}") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Refused("staged report must be a singly-linked regular file")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    value = strict_json_loads(data, "staged report")
    if not isinstance(value, dict):
        raise Refused("staged report must be a JSON object")
    return data, value, hashlib.sha256(data).hexdigest()


def hash_fd(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1 << 20)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def publish_validated_bytes(
    output_fd: int,
    output_name: str,
    data: bytes,
    expected_sha256: str,
    output_parent: Path,
    output_identity: tuple[int, int],
) -> None:
    verify_held_directory(output_parent, output_identity)
    pending = f".moon-c1-{os.getpid()}-{secrets.token_hex(16)}.pending"
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    created_pending = False
    try:
        descriptor = os.open(pending, flags, 0o600, dir_fd=output_fd)
        created_pending = True
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise Refused(f"short write staging {output_name}")
                view = view[written:]
            os.fsync(descriptor)
            if hash_fd(descriptor) != expected_sha256:
                raise Refused("staged publication digest differs from validated bytes")
            staged = os.fstat(descriptor)
            os.link(
                pending,
                output_name,
                src_dir_fd=output_fd,
                dst_dir_fd=output_fd,
                follow_symlinks=False,
            )
            published_fd = os.open(
                output_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=output_fd
            )
            try:
                published = os.fstat(published_fd)
                if (published.st_dev, published.st_ino) != (
                    staged.st_dev,
                    staged.st_ino,
                ):
                    raise Refused(
                        "published inode differs from validated staging inode"
                    )
                if hash_fd(published_fd) != expected_sha256:
                    raise Refused("published digest differs from validated bytes")
            finally:
                os.close(published_fd)
        finally:
            os.close(descriptor)
        os.fsync(output_fd)
        os.unlink(pending, dir_fd=output_fd)
        os.fsync(output_fd)
    except FileExistsError as error:
        raise Refused(f"refusing preexisting publication: {output_name}") from error
    except OSError as error:
        raise Refused(f"cannot publish retained validated bytes: {error}") from error
    finally:
        if created_pending:
            try:
                os.unlink(pending, dir_fd=output_fd)
            except FileNotFoundError:
                pass
    verify_held_directory(output_parent, output_identity)


def paths_alias(left: Path, right: Path) -> bool:
    if left.resolve(strict=False) == right.resolve(strict=False):
        return True
    if lexists(left) and lexists(right):
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False
    return False


def validate_budget_path(
    config: dict, budget_path: Path, snapshot_paths: list[Path], outputs: list[Path]
) -> None:
    expected = Path(config["runtime"]["shared_budget_path"])
    if budget_path != expected or budget_path.resolve(strict=False) != expected:
        raise Refused("Moon budget path differs from the exact bound path")
    if lexists(budget_path) and budget_path.is_symlink():
        raise Refused("Moon budget path must not be a symlink")
    for other in [*snapshot_paths, *outputs]:
        if paths_alias(budget_path, other):
            raise Refused("Moon budget aliases a snapshot or output-roster path")


def exact_uint(value: object, what: str) -> int:
    if type(value) is not int or value < 0:
        raise Refused(f"report {what} must be a non-negative integer")
    return value


def exact_digest(value: object, what: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Refused(f"report {what} must be lowercase 64-hex")
    return value


def require_keys(value: object, expected: set[str], what: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise Refused(f"report {what} keys differ")
    return value


def partition_closure(
    report: dict,
    key: str,
    labels: tuple[str, ...],
    source_bytes: int,
    modeled: int,
) -> None:
    rows = report.get(key)
    if not isinstance(rows, list) or len(rows) != len(labels):
        raise Refused(f"report partition missing: {key}")
    byte_total = 0
    loss_total = 0
    for index, row in enumerate(rows):
        row = require_keys(row, {"label", "bytes", "loss_q24"}, f"{key}[{index}]")
        if row["label"] != labels[index]:
            raise Refused(f"report partition label differs: {key}[{index}]")
        byte_total += exact_uint(row.get("bytes"), f"{key}[{index}].bytes")
        loss_total += exact_uint(row.get("loss_q24"), f"{key}[{index}].loss_q24")
    if byte_total != source_bytes:
        raise Refused(f"report byte closure differs: {key}")
    if loss_total != modeled:
        raise Refused(f"report loss closure differs: {key}")


def validate_report(
    config: dict, snapshot: dict, expected_records: int, report: dict
) -> None:
    require_keys(report, TOP_LEVEL_KEYS, "top-level")
    if report.get("schema") != config["instrument"]["report_schema"]:
        raise Refused("report schema differs")
    if report.get("evidence_stage") != config["instrument"]["evidence_stage"]:
        raise Refused("report evidence stage differs")
    if report.get("claim_ceiling") != config["instrument"]["report_claim_ceiling"]:
        raise Refused("report claim ceiling differs")
    if report.get("arm") != "c1-match-mixer":
        raise Refused("report arm differs")
    if report.get("kernel_version") != config["instrument"]["kernel_version"]:
        raise Refused("report kernel version differs")
    if exact_uint(report.get("q24_scale"), "Q24 scale") != 1 << 24:
        raise Refused("report Q24 scale differs")
    if report.get("source_sha256") != snapshot["source_sha256"]:
        raise Refused("report source identity differs")
    exact_digest(report.get("source_sha256"), "source_sha256")
    exact_digest(report.get("tape_sha256"), "tape_sha256")
    exact_digest(
        report.get("charged_event_digest_sha256"), "charged_event_digest_sha256"
    )
    source_bytes = exact_uint(report.get("source_bytes"), "source_bytes")
    if source_bytes != snapshot["source_bytes"]:
        raise Refused("report source byte count differs")
    if exact_uint(report.get("item_index"), "item index") != snapshot["item_index"]:
        raise Refused("report item index differs")
    if (
        exact_uint(report.get("sse_bucket_bits"), "SSE width")
        != config["instrument"]["sse_bucket_bits"]
    ):
        raise Refused("report SSE width differs")
    guard = report.get("identity_guard")
    guard_keys = {
        "shared_canonical_event_generator",
        "canonical_tape_equal",
        "canonical_ledger_equal",
    }
    if (
        not isinstance(guard, dict)
        or set(guard) != guard_keys
        or any(value is not True for value in guard.values())
    ):
        raise Refused("report identity guard differs")
    state = report.get("state_accounting")
    state_components = (
        "canonical_c1_declared_bytes",
        "c1_derived_stretch_tables_bytes",
        "shared_loss_table_bytes",
        "shadow_table_bytes",
        "source_input_bytes",
        "classification_bytes",
        "overlay_bit_payload_bytes",
        "aggregation_struct_bytes",
        "retained_observed_tape_payload_bytes",
        "comparison_tape_payload_bytes",
    )
    state = require_keys(
        state,
        {"semantics", "accounted_concurrent_logical_bytes", *state_components},
        "state accounting",
    )
    if state["semantics"] != STATE_SEMANTICS:
        raise Refused("report state semantics differ")
    ceiling = config["memory_and_claim_ceiling"][
        "accounted_concurrent_logical_bytes_max"
    ]
    accounted = exact_uint(
        state.get("accounted_concurrent_logical_bytes"),
        "state accounted_concurrent_logical_bytes",
    )
    reconstructed = sum(
        exact_uint(state.get(key), f"state {key}") for key in state_components
    )
    events_for_payload = 9 * source_bytes + 1
    exact_state = {
        "canonical_c1_declared_bytes": 136_773_760,
        "c1_derived_stretch_tables_bytes": 786_432,
        "shared_loss_table_bytes": 262_144,
        "shadow_table_bytes": 67_108_864,
        "source_input_bytes": source_bytes,
        "classification_bytes": source_bytes,
        "overlay_bit_payload_bytes": 3 * ((source_bytes + 7) // 8),
        "retained_observed_tape_payload_bytes": (events_for_payload + 7) // 8,
        "comparison_tape_payload_bytes": (events_for_payload + 7) // 8,
        "aggregation_struct_bytes": config["memory_and_claim_ceiling"][
            "aggregation_struct_bytes_frozen_target"
        ],
    }
    if any(state.get(key) != value for key, value in exact_state.items()):
        raise Refused("report formulaic state component differs")
    if accounted != reconstructed:
        raise Refused("report state accounting does not reconstruct")
    if accounted > ceiling:
        raise Refused("report logical accounting exceeds ceiling")
    ledger = require_keys(
        report.get("ledger"),
        {"records", "modeled_binary_events", "modeled_loss_q24", "raw_literal_bytes"},
        "ledger",
    )
    loss = require_keys(
        report.get("loss"),
        {"modeled_bits_q24", "framing_q24_including_terminal", "terminal_q24"},
        "loss",
    )
    if exact_uint(ledger.get("records"), "ledger records") != expected_records:
        raise Refused("report ledger record count differs")
    events = exact_uint(ledger.get("modeled_binary_events"), "ledger events")
    if events != 9 * source_bytes + 1:
        raise Refused("report modeled-event formula differs")
    if exact_uint(ledger.get("raw_literal_bytes"), "raw literals") != 0:
        raise Refused("report carries raw literals")
    ledger_loss = exact_uint(ledger.get("modeled_loss_q24"), "ledger loss")
    modeled = exact_uint(loss.get("modeled_bits_q24"), "modeled loss")
    framing = exact_uint(loss.get("framing_q24_including_terminal"), "framing loss")
    terminal_loss = exact_uint(loss.get("terminal_q24"), "terminal loss")
    if terminal_loss > framing:
        raise Refused("report terminal loss exceeds framing loss")
    if modeled + framing != ledger_loss:
        raise Refused("report modeled plus framing loss differs from ledger")
    if source_bytes and (modeled == 0 or framing == 0 or ledger_loss == 0):
        raise Refused("nonempty report carries zero charged loss")
    tape_bytes = exact_uint(report.get("tape_bytes"), "tape_bytes")
    if tape_bytes != 54 + (events + 7) // 8:
        raise Refused("report tape byte formula differs")
    partition_closure(
        report,
        "primary_partition",
        (
            "structural",
            "field_name",
            "string_value",
            "number_value",
            "literal_value",
            "whitespace",
            "unclassified",
        ),
        source_bytes,
        modeled,
    )
    partition_closure(
        report, "live_match_partition", ("live", "not_live"), source_bytes, modeled
    )
    partition_closure(
        report,
        "match_length_buckets",
        ("0-5", "6-7", "8-15", "16-31", "32-63", "64+"),
        source_bytes,
        modeled,
    )
    partition_closure(
        report,
        "match_distance_buckets",
        (
            "none",
            "1-64",
            "65-256",
            "257-1024",
            "1025-4096",
            "4097-65536",
            "65537-1048576",
            "1048577+",
        ),
        source_bytes,
        modeled,
    )

    overlays = require_keys(
        report.get("overlays"), {"partition", "rows", "repeat_signal"}, "overlays"
    )
    overlay_rows = overlays["rows"]
    if (
        overlays["partition"] is not False
        or overlays["repeat_signal"] != REPEAT_SIGNAL
        or not isinstance(overlay_rows, list)
        or len(overlay_rows) != 3
    ):
        raise Refused("report overlays differ")
    for index, (row, label) in enumerate(
        zip(overlay_rows, ("digits", "timestamp", "hex_id"))
    ):
        row = require_keys(row, {"label", "bytes", "loss_q24"}, f"overlay[{index}]")
        if row["label"] != label:
            raise Refused("report overlay label differs")
        if exact_uint(row.get("bytes"), f"overlay[{index}].bytes") > source_bytes:
            raise Refused("report overlay byte bound differs")
        if exact_uint(row.get("loss_q24"), f"overlay[{index}].loss") > modeled:
            raise Refused("report overlay loss bound differs")

    match_bits = require_keys(
        report.get("match_bits"), {"valid", "correct"}, "match bits"
    )
    valid_bits = exact_uint(match_bits.get("valid"), "valid match bits")
    correct_bits = exact_uint(match_bits.get("correct"), "correct match bits")
    if correct_bits > valid_bits or valid_bits > 8 * source_bytes:
        raise Refused("report match-bit bound differs")

    lifecycle = require_keys(
        report.get("match_lifecycle"),
        {
            "breaks",
            "total_acquisitions",
            "initial_acquisitions",
            "post_break_reacquisitions",
            "unresolved_breaks",
            "terminal_censored_lag",
            "acquisition_disposition",
            "reacquisition_lag_buckets",
        },
        "match lifecycle",
    )
    breaks = exact_uint(lifecycle.get("breaks"), "lifecycle breaks")
    total = exact_uint(
        lifecycle.get("total_acquisitions"), "lifecycle total acquisitions"
    )
    initial = exact_uint(
        lifecycle.get("initial_acquisitions"), "lifecycle initial acquisitions"
    )
    post = exact_uint(
        lifecycle.get("post_break_reacquisitions"),
        "lifecycle post-break reacquisitions",
    )
    unresolved = exact_uint(
        lifecycle.get("unresolved_breaks"), "lifecycle unresolved breaks"
    )
    if unresolved not in (0, 1) or initial > 1:
        raise Refused("report lifecycle cardinality differs")
    if initial + post != total or post + unresolved != breaks:
        raise Refused("report lifecycle arithmetic differs")
    disposition = lifecycle.get("acquisition_disposition")
    disposition_keys = {
        "empty_slot",
        "prefix_verification_failed",
        "window_expired",
        "live_match_suppressed",
    }
    if not isinstance(disposition, dict) or set(disposition) != disposition_keys:
        raise Refused("report acquisition disposition differs")
    disposition_total = sum(
        exact_uint(value, f"acquisition disposition {key}")
        for key, value in disposition.items()
    )
    if total + disposition_total != max(source_bytes - 5, 0):
        raise Refused("report acquisition disposition event formula differs")
    lag = lifecycle.get("reacquisition_lag_buckets")
    if not isinstance(lag, list) or len(lag) != 6:
        raise Refused("report reacquisition lag buckets differ")
    if sum(exact_uint(value, "lifecycle lag bucket") for value in lag) != post:
        raise Refused("report reacquisition lag closure differs")
    terminal_lag = lifecycle.get("terminal_censored_lag")
    if unresolved == 0:
        if terminal_lag is not None:
            raise Refused("report has terminal censor without unresolved break")
    elif terminal_lag is None:
        raise Refused("report omits terminal censor for unresolved break")
    else:
        exact_uint(terminal_lag, "terminal censored lag")

    shadow = require_keys(
        report.get("shadow_oracle"),
        {
            "selection_semantics",
            "candidate_opportunity_semantics",
            "self_overlap",
            "raw_overlapping_matched_bytes_reported",
            "rows",
        },
        "shadow oracle",
    )
    if (
        shadow["selection_semantics"] != SHADOW_SELECTION
        or shadow["candidate_opportunity_semantics"] != SHADOW_OPPORTUNITY
        or shadow["self_overlap"] != SHADOW_SELF_OVERLAP
        or shadow["raw_overlapping_matched_bytes_reported"] is not False
    ):
        raise Refused("report shadow semantics differ")
    rows = shadow["rows"]
    if not isinstance(rows, list) or len(rows) != 3:
        raise Refused("report shadow rows differ")
    previous_correct = 0
    previous_loss = 0
    previous_opportunities = 0
    for index, (row, depth) in enumerate(zip(rows, (1, 2, 4))):
        row = require_keys(
            row,
            {
                "depth",
                "candidate_opportunities_upper_bound",
                "any_correct_bytes_upper_bound",
                "any_correct_loss_q24_upper_bound",
                "incremental_any_correct_bytes_upper_bound",
                "incremental_any_correct_loss_q24_upper_bound",
            },
            f"shadow[{index}]",
        )
        if row.get("depth") != depth:
            raise Refused("report shadow depths differ")
        opportunities = exact_uint(
            row.get("candidate_opportunities_upper_bound"),
            f"shadow[{index}] opportunities",
        )
        correct = exact_uint(
            row.get("any_correct_bytes_upper_bound"), f"shadow[{index}] correct"
        )
        correct_loss = exact_uint(
            row.get("any_correct_loss_q24_upper_bound"), f"shadow[{index}] loss"
        )
        incremental = exact_uint(
            row.get("incremental_any_correct_bytes_upper_bound"),
            f"shadow[{index}] incremental correct",
        )
        incremental_loss = exact_uint(
            row.get("incremental_any_correct_loss_q24_upper_bound"),
            f"shadow[{index}] incremental loss",
        )
        if (
            opportunities < previous_opportunities
            or correct < previous_correct
            or correct_loss < previous_loss
            or opportunities > source_bytes
            or correct > opportunities
            or correct_loss > modeled
            or incremental != correct - previous_correct
            or incremental_loss != correct_loss - previous_loss
        ):
            raise Refused("report shadow monotonicity or increment differs")
        previous_opportunities = opportunities
        previous_correct = correct
        previous_loss = correct_loss


def kernel_command(
    config: dict, kernel: list[str], snapshot: dict, source: Path, output: Path
) -> list[str]:
    return kernel + [
        "diagnose-c1",
        "--item-index",
        str(snapshot["item_index"]),
        "--input",
        str(source),
        "--report-out",
        str(output),
        "--sse-bucket-bits",
        str(config["instrument"]["sse_bucket_bits"]),
    ]


def controlled_environment(config: dict, scratch: Path) -> dict[str, str]:
    allowed = config["runtime"]["build_environment_allowlist"]
    if allowed != []:
        raise Refused("build environment allowlist differs")
    toolchain = config["runtime"]["toolchain"]
    temporary = scratch / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    cargo_home = Path(toolchain["cargo_source_home"])
    if not cargo_home.is_dir() or cargo_home.is_symlink():
        raise Refused("bound Cargo source home differs")
    return {
        "PATH": toolchain["fixed_path"],
        "TMPDIR": str(temporary),
        "CARGO_HOME": str(cargo_home),
        "RUSTUP_HOME": toolchain["rustup_home"],
        "RUSTC": toolchain["rustc_path"],
        "CC": toolchain["clang_path"],
        "CXX": toolchain["clang_path"],
        "CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER": toolchain["clang_path"],
        "RUSTFLAGS": (
            f"--remap-path-prefix={scratch.resolve()}={toolchain['remap_path_prefix']}"
        ),
        "DEVELOPER_DIR": toolchain["developer_dir"],
        "SDKROOT": toolchain["sdkroot"],
        "CARGO_NET_OFFLINE": "true",
        "CARGO_INCREMENTAL": "0",
    }


def kernel_environment(config: dict, scratch: Path) -> dict[str, str]:
    expected_names = config["runtime"]["kernel_runtime_environment_names"]
    if expected_names != ["LC_ALL", "PATH", "TMPDIR"]:
        raise Refused("kernel runtime environment roster differs")
    temporary = scratch / "kernel-tmp"
    temporary.mkdir(mode=0o700, parents=True)
    return {
        "LC_ALL": "C",
        "PATH": config["runtime"]["toolchain"]["fixed_path"],
        "TMPDIR": str(temporary),
    }


def verify_toolchain(config: dict, scratch: Path) -> tuple[dict[str, str], dict]:
    toolchain = config["runtime"]["toolchain"]
    tools = (
        ("cargo", "cargo_path", "cargo_sha256", "cargo_version"),
        ("rustc", "rustc_path", "rustc_sha256", "rustc_version"),
        ("clang", "clang_path", "clang_sha256", "clang_version"),
    )
    environment = controlled_environment(config, scratch)
    identity = {}
    for name, path_key, sha_key, version_key in tools:
        path = Path(toolchain[path_key])
        expected_sha = toolchain[sha_key]
        if (
            not path.is_file()
            or path.is_symlink()
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None
            or sha256_file(path) != expected_sha
        ):
            raise Refused(f"bound {name} executable identity differs")
        try:
            output = subprocess.check_output(
                [str(path), "--version"], text=True, env=environment
            ).splitlines()[0]
        except (OSError, subprocess.CalledProcessError, IndexError) as error:
            raise Refused(f"cannot identify bound tool: {name}") from error
        if output != toolchain[version_key]:
            raise Refused(f"bound {name} version differs")
        identity[name] = {"path": str(path), "sha256": expected_sha, "version": output}
    return environment, identity


def verify_git_identity(config: dict) -> None:
    toolchain = config["runtime"]["toolchain"]
    path = Path(toolchain["git_path"])
    expected_sha = toolchain["git_sha256"]
    if (
        path != Path("/usr/bin/git")
        or not path.is_file()
        or path.is_symlink()
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None
        or sha256_file(path) != expected_sha
    ):
        raise Refused("bound git executable identity differs")
    try:
        version = subprocess.check_output(
            [str(path), "--version"], text=True, env=git_environment()
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise Refused("cannot identify bound git") from error
    if version != toolchain["git_version"]:
        raise Refused("bound git version differs")


def require_release_digest(actual: str, expected: object) -> str:
    if (
        not isinstance(expected, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        or actual != expected
    ):
        raise Refused("built release binary digest differs")
    return expected


def refuse_cargo_source_configs(cargo_home: Path, build_cwd: Path) -> None:
    candidates = [cargo_home / "config", cargo_home / "config.toml"]
    current = build_cwd.resolve()
    while True:
        candidates.extend((current / ".cargo/config", current / ".cargo/config.toml"))
        if current.parent == current:
            break
        current = current.parent
    if any(lexists(path) for path in candidates):
        raise Refused("ambient Cargo source/config substitution is present")


def materialize_and_build(
    config: dict,
    scratch: Path,
    *,
    after_verify_hook: Optional[Callable[[Path], None]] = None,
) -> tuple[list[str], dict, Optional[int]]:
    toolchain = config["runtime"]["toolchain"]
    build_root = Path(toolchain["fixed_build_root"])
    if not build_root.is_absolute() or lexists(build_root):
        raise Refused("fixed exclusive build root is unavailable")
    parent = build_root.parent
    if not parent.is_dir() or parent.is_symlink():
        raise Refused("fixed build-root parent differs")
    try:
        build_root.mkdir(mode=0o700)
    except OSError as error:
        raise Refused("cannot create fixed exclusive build root") from error
    build_info = build_root.lstat()
    implementation = config["identity"]["implementation_commit"]
    try:
        try:
            archive = subprocess.check_output(
                ["/usr/bin/git", "archive", "--format=tar", implementation, "native"],
                cwd=ROOT,
                env=git_environment(),
            )
        except subprocess.CalledProcessError as error:
            raise Refused(
                "cannot materialize exact implementation native tree"
            ) from error
        materialized = build_root / "materialized"
        materialized.mkdir()
        materialized_identity = materialized.resolve()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle.getmembers():
                target_path = materialized / member.name
                if not target_path.resolve(strict=False).is_relative_to(
                    materialized_identity
                ) or not (member.isdir() or member.isfile()):
                    raise Refused("implementation archive contains unsafe member")
                if member.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise Refused("implementation archive file cannot be read")
                with source, target_path.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
                target_path.chmod(member.mode & 0o777)
        environment, tool_identity = verify_toolchain(config, build_root)
        refuse_cargo_source_configs(
            Path(toolchain["cargo_source_home"]), materialized / "native"
        )
        target = build_root / "target"
        completed = subprocess.run(
            [
                toolchain["cargo_path"],
                "build",
                "--offline",
                "--locked",
                "--release",
                "--target-dir",
                str(target),
                "--bin",
                "clab-moon-kernel",
            ],
            cwd=materialized / "native",
            env=environment,
        )
        if completed.returncode:
            raise Refused(
                "exact materialized kernel build failed before retained-data read"
            )
        binary = target / "release/clab-moon-kernel"
        if not binary.is_file() or binary.is_symlink():
            raise Refused("exact built kernel is missing or symlinked")
        binary_sha = sha256_file(binary)
        require_release_digest(
            binary_sha, toolchain.get("expected_release_binary_sha256")
        )
        verified_copy = scratch / "verified-clab-moon-kernel"
        shutil.copyfile(binary, verified_copy)
        verified_copy.chmod(0o500)
        if sha256_file(verified_copy) != binary_sha:
            raise Refused("held executable digest differs")
        if after_verify_hook:
            after_verify_hook(binary)
        return (
            [str(verified_copy)],
            {
                "implementation_commit": implementation,
                "binary_sha256": binary_sha,
                "tools": tool_identity,
                "environment_names": sorted(environment),
                "fixed_build_root": str(build_root),
                "remap_path_prefix": toolchain["remap_path_prefix"],
            },
            None,
        )
    finally:
        current = build_root.lstat()
        if (
            not stat.S_ISDIR(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or (current.st_dev, current.st_ino)
            != (build_info.st_dev, build_info.st_ino)
        ):
            raise Refused("fixed build root identity changed; refusing cleanup")
        shutil.rmtree(build_root)


def verify_kernel_before_dispatch(path: Path, expected_sha256: str) -> None:
    if (
        not path.is_file()
        or path.is_symlink()
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or sha256_file(path) != expected_sha256
    ):
        raise Refused("private executable changed before dispatch")


def attempt_ref_exists(ref: str) -> bool:
    return (
        subprocess.run(
            ["/usr/bin/git", "show-ref", "--verify", "--quiet", ref],
            cwd=ROOT,
            env=git_environment(),
        ).returncode
        == 0
    )


def create_attempt_ref(config: dict, authorized_commit: str) -> str:
    ref = config["runtime"]["durable_attempt_ref"]
    if attempt_ref_exists(ref):
        raise Refused("durable C1 diagnostic attempt ref already exists")
    payload = canonical_json(
        {
            "schema": "moon-c1-residual-diagnostic-attempt-v1",
            "readiness_commit": authorized_commit,
            "expected_budget_before": config["runtime"]["expected_consumed_before"],
            "snapshots": config["retained_snapshot_identity"]["snapshots"],
            "status": "reserved-before-first-snapshot-read",
        }
    )
    try:
        blob = (
            subprocess.check_output(
                ["/usr/bin/git", "hash-object", "-w", "--stdin"],
                cwd=ROOT,
                input=payload,
                env=git_environment(),
            )
            .decode()
            .strip()
        )
        subprocess.run(
            ["/usr/bin/git", "update-ref", ref, blob, "0" * 40],
            cwd=ROOT,
            check=True,
            env=git_environment(),
        )
    except subprocess.CalledProcessError as error:
        raise Refused("cannot durably create attempt ref") from error
    if not attempt_ref_exists(ref):
        raise Refused("durable attempt ref did not persist")
    return blob


def run(
    config_path: Path,
    authorized_commit: str,
    owner_literal: str,
    budget_path: Path,
    snapshot_paths: list[Path],
    *,
    kernel_override: Optional[list[str]] = None,
    dispatch: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    boundary_hook: Optional[Callable[[str, int], None]] = None,
    attempt_create: Callable[[dict, str], str] = create_attempt_ref,
    attempt_check: Callable[[str], bool] = attempt_ref_exists,
) -> dict:
    if config_path.resolve() != (ROOT / CONFIG_RELATIVE).resolve():
        raise Refused("runner accepts only the committed readiness config path")
    config = load_object(config_path, "readiness config")
    validate_bindings(config, authorized_commit, owner_literal)
    outputs, output_fd, output_identity, output_parent = prepare_output_roster(config)
    try:
        validate_budget_path(config, budget_path, snapshot_paths, outputs)
        already_attempted = attempt_check(config["runtime"]["durable_attempt_ref"])
    except BaseException:
        os.close(output_fd)
        raise
    if already_attempted:
        os.close(output_fd)
        raise Refused("durable C1 diagnostic attempt ref already exists")
    lock = budget_path.with_name(f"{budget_path.name}.c1-diagnostic.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        os.close(output_fd)
        raise Refused("Moon budget is locked") from error
    except OSError as error:
        os.close(output_fd)
        raise Refused(f"cannot create Moon budget lock: {error}") from error
    os.close(descriptor)
    try:
        before = read_budget(budget_path)
        if before != config["runtime"]["expected_consumed_before"]:
            raise Refused("Moon budget does not equal the frozen pre-run value")
        if before + len(snapshot_paths) > BUDGET_CAP:
            raise Refused("insufficient Moon run budget for both diagnostics")
        with (
            tempfile.TemporaryDirectory(prefix=".moon-c1-private-", dir=ROOT) as tmp,
            tempfile.TemporaryDirectory(prefix="moon-c1-build-") as build_tmp,
        ):
            scratch = Path(tmp)
            runtime_environment = kernel_environment(config, scratch)
            if kernel_override is not None:
                for test_name in ("TEST_BUDGET", "TEST_OBSERVED", "FAIL_ITEM"):
                    if test_name in os.environ:
                        runtime_environment[test_name] = os.environ[test_name]
            stage = scratch / "stage"
            stage.mkdir(mode=0o700)
            stage_fd = os.open(
                stage,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            kernel_fd: Optional[int] = None
            verified_kernel_sha: Optional[str] = None
            try:
                if kernel_override is None:
                    kernel, runtime_identity, kernel_fd = materialize_and_build(
                        config, Path(build_tmp)
                    )
                    verified_kernel_sha = runtime_identity["binary_sha256"]
                else:
                    kernel = kernel_override
                    runtime_identity = {
                        "implementation_commit": config["identity"][
                            "implementation_commit"
                        ],
                        "binary_sha256": sha256_file(Path(kernel[0])),
                        "tools": "test-override",
                        "environment_names": [],
                    }
                runtime_identity["kernel_environment_names"] = sorted(
                    runtime_environment
                )
                attempt_blob = attempt_create(config, authorized_commit)
                expected_records = validate_snapshots(config, snapshot_paths)
                runs = []
                retained: list[tuple[str, bytes, str]] = []
                consumed = before
                for index, (snapshot, source, records) in enumerate(
                    zip(
                        config["retained_snapshot_identity"]["snapshots"],
                        snapshot_paths,
                        expected_records,
                    )
                ):
                    stage_name = f"report-{index}.json"
                    report_path = stage / stage_name
                    if boundary_hook:
                        boundary_hook("before_dispatch", index)
                    verify_held_directory(output_parent, output_identity)
                    if verified_kernel_sha is not None:
                        verify_kernel_before_dispatch(
                            Path(kernel[0]), verified_kernel_sha
                        )
                    if read_budget(budget_path) != consumed:
                        raise Refused("Moon budget changed while held")
                    consumed += 1
                    charge_budget(budget_path, consumed)
                    if read_budget(budget_path) != consumed:
                        raise Refused("Moon budget charge did not persist exactly")
                    try:
                        dispatch_arguments = {"env": runtime_environment}
                        if kernel_fd is not None:
                            dispatch_arguments["pass_fds"] = (kernel_fd,)
                        completed = dispatch(
                            kernel_command(
                                config, kernel, snapshot, source, report_path
                            ),
                            **dispatch_arguments,
                        )
                    except OSError:
                        runs.append(
                            {
                                "snapshot": snapshot["name"],
                                "item_index": snapshot["item_index"],
                                "status": "dispatch_error",
                                "exit_code": None,
                                "report": outputs[index].relative_to(ROOT).as_posix(),
                            }
                        )
                        break
                    entry = {
                        "snapshot": snapshot["name"],
                        "item_index": snapshot["item_index"],
                        "status": "failed" if completed.returncode else "measured",
                        "exit_code": completed.returncode,
                        "report": outputs[index].relative_to(ROOT).as_posix(),
                    }
                    runs.append(entry)
                    if completed.returncode:
                        break
                    try:
                        report_bytes, report, report_sha = read_report_once(
                            stage_fd, stage_name
                        )
                        validate_report(config, snapshot, records, report)
                    except Refused:
                        entry["status"] = "invalid_report"
                        break
                    entry["report_sha256"] = report_sha
                    retained.append((outputs[index].name, report_bytes, report_sha))
                summary = {
                    "schema": SUMMARY_SCHEMA,
                    "evidence_stage": "mechanism_local_diagnostic",
                    "authorized_readiness_commit": authorized_commit,
                    "attempt_ref": config["runtime"]["durable_attempt_ref"],
                    "attempt_blob": attempt_blob,
                    "runtime_identity": runtime_identity,
                    "scoring": False,
                    "candidate_execution": False,
                    "corpus_advancement": False,
                    "budget": {
                        "consumed_before": before,
                        "consumed_after": consumed,
                        "cap": BUDGET_CAP,
                    },
                    "runs": runs,
                }
                summary_bytes = canonical_json(summary)
                summary_sha = hashlib.sha256(summary_bytes).hexdigest()
                if boundary_hook:
                    boundary_hook("before_publish", -1)
                for output_name, retained_bytes, digest in retained:
                    publish_validated_bytes(
                        output_fd,
                        output_name,
                        retained_bytes,
                        digest,
                        output_parent,
                        output_identity,
                    )
                publish_validated_bytes(
                    output_fd,
                    outputs[2].name,
                    summary_bytes,
                    summary_sha,
                    output_parent,
                    output_identity,
                )
                complete = len(runs) == 2 and all(
                    row["status"] == "measured" for row in runs
                )
                if complete:
                    lines = [f"{digest}  {name}\n" for name, _, digest in retained]
                    lines.append(f"{summary_sha}  {outputs[2].name}\n")
                    manifest_bytes = "".join(lines).encode()
                    publish_validated_bytes(
                        output_fd,
                        outputs[3].name,
                        manifest_bytes,
                        hashlib.sha256(manifest_bytes).hexdigest(),
                        output_parent,
                        output_identity,
                    )
                return summary
            finally:
                if kernel_fd is not None:
                    os.close(kernel_fd)
                os.close(stage_fd)
    finally:
        if lexists(lock):
            lock.unlink()
        os.close(output_fd)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--authorized-readiness-commit", required=True)
    parser.add_argument("--owner-literal", required=True)
    parser.add_argument("--budget-state", required=True, type=Path)
    parser.add_argument("--snapshot-a", required=True, type=Path)
    parser.add_argument("--snapshot-b", required=True, type=Path)
    arguments = parser.parse_args(argv)
    summary = run(
        arguments.config,
        arguments.authorized_readiness_commit,
        arguments.owner_literal,
        arguments.budget_state,
        [arguments.snapshot_a, arguments.snapshot_b],
    )
    return (
        0
        if len(summary["runs"]) == 2
        and all(row["status"] == "measured" for row in summary["runs"])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
