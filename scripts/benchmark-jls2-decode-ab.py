#!/usr/bin/env python3
"""Run an alternating, byte-exact JLS2 decode-kernel A/B benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "native/src/lib.rs",
    "src/compresslab/json_columnar.py",
    "src/compresslab/json_log_codec.py",
    "src/compresslab/native.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def native_library(root: Path) -> Path:
    if sys.platform == "darwin":
        filename = "libcompression_lab_native.dylib"
    elif sys.platform == "win32":
        filename = "compression_lab_native.dll"
    else:
        filename = "libcompression_lab_native.so"
    path = root / "native" / "target" / "release" / filename
    if not path.is_file():
        raise ValueError(f"native release library is missing: {path}")
    return path


def git_state(root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    sources = {}
    for relative in SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"bound source is missing: {path}")
        sources[relative] = sha256_file(path)
    library = native_library(root)
    return {
        "root": str(root),
        "commit": commit,
        "dirty": dirty,
        "source_sha256": sources,
        "native_library_sha256": sha256_file(library),
    }


def resolve_source(root: Path, item: dict[str, Any]) -> Path:
    path = Path(item["path"])
    return path if path.is_absolute() else root / path


def load_manifest(root: Path, path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    families = set()
    for item in manifest["items"]:
        family = item["family"]
        if family in families:
            raise ValueError(f"duplicate family: {family}")
        families.add(family)
        source = resolve_source(root, item)
        if source.stat().st_size != item["size_bytes"]:
            raise ValueError(f"corpus size mismatch: {source}")
        if sha256_file(source) != item["sha256"]:
            raise ValueError(f"corpus digest mismatch: {source}")
    return manifest


def worker_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["COMPRESSION_LAB_NATIVE_LIB"] = str(native_library(root))
    return environment


def run_worker(
    root: Path,
    corpus_root: Path,
    manifest: Path,
    fixtures: Path,
    output: Path,
    iterations: int,
) -> dict[str, Any]:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--manifest",
            str(manifest),
            "--corpus-root",
            str(corpus_root),
            "--fixtures",
            str(fixtures),
            "--output",
            str(output),
            "--iterations",
            str(iterations),
        ],
        cwd=root,
        env=worker_environment(root),
        check=True,
    )
    return json.loads(output.read_text(encoding="utf-8"))


def prepare_fixtures(
    root: Path, corpus_root: Path, manifest: Path, fixtures: Path
) -> None:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--prepare-fixtures",
            "--manifest",
            str(manifest),
            "--corpus-root",
            str(corpus_root),
            "--fixtures",
            str(fixtures),
        ],
        cwd=root,
        env=worker_environment(root),
        check=True,
    )


def worker(args: argparse.Namespace) -> int:
    from compresslab.json_log_codec import compress, decompress

    manifest = load_manifest(args.corpus_root, args.manifest)
    args.fixtures.mkdir(parents=True, exist_ok=True)
    if args.prepare_fixtures:
        for item in manifest["items"]:
            source = resolve_source(args.corpus_root, item).read_bytes()
            encoded, _telemetry = compress(source)
            restored = decompress(encoded, max_output_size=item["size_bytes"])
            if hashlib.sha256(restored).hexdigest() != item["sha256"]:
                raise RuntimeError(f"fixture round trip failed: {item['family']}")
            (args.fixtures / f"{item['family']}.jls2").write_bytes(encoded)
        return 0

    rows = []
    for item in manifest["items"]:
        encoded_path = args.fixtures / f"{item['family']}.jls2"
        encoded = encoded_path.read_bytes()
        encoded_sha256 = hashlib.sha256(encoded).hexdigest()
        restored = decompress(encoded, max_output_size=item["size_bytes"])
        if hashlib.sha256(restored).hexdigest() != item["sha256"]:
            raise RuntimeError(f"warm round trip failed: {item['family']}")
        samples_ns = []
        for _ in range(args.iterations):
            started = time.perf_counter_ns()
            restored = decompress(encoded, max_output_size=item["size_bytes"])
            elapsed = time.perf_counter_ns() - started
            if len(restored) != item["size_bytes"]:
                raise RuntimeError(f"size mismatch: {item['family']}")
            if hashlib.sha256(restored).hexdigest() != item["sha256"]:
                raise RuntimeError(f"digest mismatch: {item['family']}")
            samples_ns.append(elapsed)
        median_ns = int(statistics.median(samples_ns))
        rows.append(
            {
                "family": item["family"],
                "source_bytes": item["size_bytes"],
                "source_sha256": item["sha256"],
                "encoded_bytes": len(encoded),
                "encoded_sha256": encoded_sha256,
                "median_ns": median_ns,
                "samples_ns": samples_ns,
                "mbps": item["size_bytes"] / median_ns * 1_000,
                "exact": True,
            }
        )
    result = {
        "iterations": args.iterations,
        "rows": rows,
        "aggregate_mbps": (
            sum(row["source_bytes"] for row in rows)
            / sum(row["median_ns"] for row in rows)
            * 1_000
        ),
    }
    write_json(args.output, result)
    return 0


def summarize(
    baseline_rounds: list[dict[str, Any]],
    candidate_rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    aggregate_pairs = []
    for index, (baseline, candidate) in enumerate(
        zip(baseline_rounds, candidate_rounds), start=1
    ):
        improvement = (
            candidate["aggregate_mbps"] / baseline["aggregate_mbps"] - 1
        ) * 100
        aggregate_pairs.append(
            {
                "round": index,
                "baseline_mbps": baseline["aggregate_mbps"],
                "candidate_mbps": candidate["aggregate_mbps"],
                "candidate_improvement_percent": improvement,
            }
        )

    family_rows = []
    family_names = [row["family"] for row in baseline_rounds[0]["rows"]]
    for family in family_names:
        pairs = []
        fixture_identity = None
        for baseline, candidate in zip(baseline_rounds, candidate_rounds):
            baseline_row = next(row for row in baseline["rows"] if row["family"] == family)
            candidate_row = next(row for row in candidate["rows"] if row["family"] == family)
            identity = (
                baseline_row["source_bytes"],
                baseline_row["source_sha256"],
                baseline_row["encoded_bytes"],
                baseline_row["encoded_sha256"],
            )
            candidate_identity = (
                candidate_row["source_bytes"],
                candidate_row["source_sha256"],
                candidate_row["encoded_bytes"],
                candidate_row["encoded_sha256"],
            )
            if identity != candidate_identity:
                raise ValueError(f"A/B fixture identity mismatch: {family}")
            if fixture_identity is not None and fixture_identity != identity:
                raise ValueError(f"fixture drift between rounds: {family}")
            fixture_identity = identity
            pairs.append(
                {
                    "baseline_mbps": baseline_row["mbps"],
                    "candidate_mbps": candidate_row["mbps"],
                    "candidate_improvement_percent": (
                        candidate_row["mbps"] / baseline_row["mbps"] - 1
                    )
                    * 100,
                }
            )
        improvements = [row["candidate_improvement_percent"] for row in pairs]
        if fixture_identity is None:
            raise AssertionError(f"family has no measured rounds: {family}")
        family_rows.append(
            {
                "family": family,
                "source_bytes": fixture_identity[0],
                "source_sha256": fixture_identity[1],
                "encoded_bytes": fixture_identity[2],
                "encoded_sha256": fixture_identity[3],
                "median_baseline_mbps": statistics.median(
                    row["baseline_mbps"] for row in pairs
                ),
                "median_candidate_mbps": statistics.median(
                    row["candidate_mbps"] for row in pairs
                ),
                "median_paired_improvement_percent": statistics.median(improvements),
                "minimum_paired_improvement_percent": min(improvements),
                "maximum_paired_improvement_percent": max(improvements),
                "rounds": pairs,
                "exact": True,
            }
        )

    improvements = [row["candidate_improvement_percent"] for row in aggregate_pairs]
    return {
        "aggregate": {
            "median_baseline_mbps": statistics.median(
                row["baseline_mbps"] for row in aggregate_pairs
            ),
            "median_candidate_mbps": statistics.median(
                row["candidate_mbps"] for row in aggregate_pairs
            ),
            "median_paired_improvement_percent": statistics.median(improvements),
            "minimum_paired_improvement_percent": min(improvements),
            "maximum_paired_improvement_percent": max(improvements),
            "candidate_rounds_at_or_above_250_mbps": sum(
                row["candidate_mbps"] >= 250 for row in aggregate_pairs
            ),
            "pairs": aggregate_pairs,
        },
        "families": family_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-root", type=Path)
    parser.add_argument("--candidate-root", type=Path, default=REPOSITORY)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--prepare-fixtures", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.manifest = args.manifest.resolve()
    args.fixtures = args.fixtures.resolve()
    if args.worker or args.prepare_fixtures:
        if args.corpus_root is None:
            raise ValueError("--corpus-root is required for worker modes")
        args.corpus_root = args.corpus_root.resolve()
        return worker(args)
    if args.base_root is None or args.output is None:
        raise ValueError("--base-root and --output are required")
    if args.rounds < 1 or args.iterations < 1:
        raise ValueError("rounds and iterations must be positive")

    base_root = args.base_root.resolve()
    candidate_root = args.candidate_root.resolve()
    base_state = git_state(base_root)
    candidate_state = git_state(candidate_root)
    if base_state["dirty"] or candidate_state["dirty"]:
        raise SystemExit("A/B benchmark requires clean base and candidate commits")
    manifest = load_manifest(candidate_root, args.manifest)
    prepare_fixtures(
        candidate_root, candidate_root, args.manifest, args.fixtures
    )

    baseline_rounds = []
    candidate_rounds = []
    raw_directory = args.output.resolve().parent / ".jls2-decode-ab-raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    for round_index in range(1, args.rounds + 1):
        order = (
            (("baseline", base_root), ("candidate", candidate_root))
            if round_index % 2
            else (("candidate", candidate_root), ("baseline", base_root))
        )
        round_results = {}
        for label, root in order:
            output = raw_directory / f"{label}-{round_index}.json"
            round_results[label] = run_worker(
                root,
                candidate_root,
                args.manifest,
                args.fixtures,
                output,
                args.iterations,
            )
        baseline_rounds.append(round_results["baseline"])
        candidate_rounds.append(round_results["candidate"])
        print(
            f"round {round_index}: base "
            f"{round_results['baseline']['aggregate_mbps']:.2f} MB/s, candidate "
            f"{round_results['candidate']['aggregate_mbps']:.2f} MB/s",
            flush=True,
        )

    summary = summarize(baseline_rounds, candidate_rounds)
    payload = {
        "schema_version": 1,
        "benchmark": "jls2-decode-kernel-development-v1",
        "claim_ceiling": (
            "alternating byte-API decode-kernel evidence on consumed development "
            "families only; not fresh unseen, public-validation, independent-corpus, "
            "market-leading, world-best, or state-of-the-art evidence"
        ),
        "manifest": {
            "path": str(args.manifest),
            "sha256": sha256_file(args.manifest),
            "families": [item["family"] for item in manifest["items"]],
            "source_bytes": sum(item["size_bytes"] for item in manifest["items"]),
        },
        "settings": {
            "rounds": args.rounds,
            "iterations_per_family_per_round": args.iterations,
            "alternating_first_position": True,
            "warmup_per_family_per_process": 1,
            "exact_sha256_after_every_decode": True,
            "timing_scope": "in-memory JLS2 byte API; SHA-256 verification included",
        },
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "base": base_state,
        "candidate": candidate_state,
        "summary": summary,
        "raw_rounds": {
            "baseline": baseline_rounds,
            "candidate": candidate_rounds,
        },
        "passed": (
            all(row["exact"] for row in summary["families"])
            and summary["aggregate"]["candidate_rounds_at_or_above_250_mbps"]
            == args.rounds
            and summary["aggregate"]["median_paired_improvement_percent"] > 0
        ),
    }
    write_json(args.output.resolve(), payload)
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
