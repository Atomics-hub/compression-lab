#!/usr/bin/env python3
"""Independent dedicated-machine reproduction bundle for the JLS2 v2 pass.

One entry point that, on a clean checkout at a pinned commit, rebuilds the
frozen v2 environment, re-acquires only the two authorized public CLUE-LDS
ranges, re-runs the frozen benchmark/evaluator without forking their logic,
re-verifies exact output byte-identity, measures clean wall time and
clean-child peak RSS, and writes a self-bound reproduction receipt whose
byte counts and gate decisions are compared against the immutable hosted
result under runs/clue-jls2-public-validation-v2/.

This tool never mints a new score. It reproduces the SAME frozen result:
byte counts must match the hosted decision exactly, while speed and peak RSS
are machine-dependent and reported as measured with the frozen gates applied.
A GitHub rerun of the same workflow is not independent reproduction, and a run
on the primary development machine is not independent either; see
docs/benchmarks/2026-07-24-jls2-v2-reproduction-protocol.md.

The full pipeline reproduces the frozen ubuntu-22.04 environment and therefore
requires Linux. On any platform the --smoke mode exercises the candidate build,
the frozen compress driver, the standalone native decode, the clean-child
instrument, and the frozen-hash verification end to end on a tiny synthetic
input, without touching CLUE-LDS or the Linux-only baselines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional


REPOSITORY = Path(__file__).resolve().parents[1]

GATES_PATH = REPOSITORY / "config" / "clue-jls2-public-validation-v2-gates.json"
LOCK_PATH = REPOSITORY / "config" / "clue-jls2-public-validation-v2-lock.json"
CORPUS_CONFIG_PATH = REPOSITORY / "config" / "clue-json-log-corpus-v2.json"
HOSTED_RUN_DIR = REPOSITORY / "runs" / "clue-jls2-public-validation-v2"
HOSTED_DECISION_PATH = HOSTED_RUN_DIR / "decision.json"

MEASURE_CLEAN_RSS = REPOSITORY / "scripts" / "measure-clean-rss.py"
CANDIDATE_COMPRESS_DRIVER = REPOSITORY / "scripts" / "jls2-candidate-compress-v2.py"
FETCH_CORPUS = REPOSITORY / "scripts" / "fetch-clue-json-corpus-v2.py"
BENCHMARK = REPOSITORY / "scripts" / "benchmark-clue-jls2-public-validation-v2.py"
PBC_BENCHMARK = REPOSITORY / "scripts" / "benchmark-pbc-competitor.py"
EVALUATE = REPOSITORY / "scripts" / "evaluate-clue-jls2-public-validation-v2.py"
LOCK_VERIFIER = REPOSITORY / "scripts" / "verify-clue-jls2-public-validation-v2-lock.py"
NATIVE_BINARY = REPOSITORY / "native" / "target" / "release" / "clab-jls2"

CHUNK_SIZE = 1024 * 1024


class ReproductionError(RuntimeError):
    """A reproduction step failed in a way that voids the run."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: dict[str, Any]) -> str:
    """SHA-256 over a stable canonical JSON encoding of a mapping."""
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def bind_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the receipt with a sha256 over its own canonicalized content."""
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    bound = dict(body)
    bound["receipt_sha256"] = canonical_sha256(body)
    return bound


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_first_line(path: Path, prefix: str) -> Optional[str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                return line
    except OSError:
        return None
    return None


def machine_identity() -> dict[str, Any]:
    memory_bytes: Optional[int] = None
    cpu_model: Optional[str] = None
    system = platform.system()
    if system == "Linux":
        meminfo = _read_first_line(Path("/proc/meminfo"), "MemTotal:")
        if meminfo:
            memory_bytes = int(meminfo.split()[1]) * 1024
        model = _read_first_line(Path("/proc/cpuinfo"), "model name")
        if model and ":" in model:
            cpu_model = model.split(":", 1)[1].strip()
    elif system == "Darwin":
        try:
            memory_bytes = int(
                subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
            cpu_model = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError, ValueError):
            memory_bytes = None
    return {
        "system": system,
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_model": cpu_model,
        "cpu_count": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def git(*arguments: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY,
        check=check,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_state() -> dict[str, str]:
    return {
        "head_commit": git("rev-parse", "HEAD"),
        "tracked_status": git("status", "--porcelain", "--untracked-files=no"),
    }


def preflight_repository(
    pinned_commit: Optional[str], require_clean: bool
) -> dict[str, str]:
    state = git_state()
    print(f"[preflight] git HEAD: {state['head_commit']}")
    if pinned_commit and state["head_commit"] != pinned_commit:
        raise ReproductionError(
            "HEAD does not match the pinned reproduction commit: "
            f"HEAD={state['head_commit']} expected={pinned_commit}"
        )
    if require_clean and state["tracked_status"]:
        raise ReproductionError(
            "reproduction requires a clean tracked tree; found modifications:\n"
            + state["tracked_status"]
        )
    print(
        "[preflight] tracked tree "
        + ("clean" if not state["tracked_status"] else "DIRTY (smoke tolerated)")
    )
    return state


def verify_hashes(gates: dict[str, Any]) -> dict[str, str]:
    """Print and verify frozen candidate + instrument source hashes."""
    verified: dict[str, str] = {}
    checks: list[tuple[str, str]] = []
    for relative, expected in gates["candidate"]["frozen_paths"].items():
        checks.append((relative, expected))
    instrument = gates["instrument"]
    checks.append((instrument["clean_rss_path"], instrument["clean_rss_sha256"]))
    checks.append(
        (
            instrument["candidate_compress_driver_path"],
            instrument["candidate_compress_driver_sha256"],
        )
    )
    for relative, expected in checks:
        observed = sha256_file(REPOSITORY / relative)
        status = "ok" if observed == expected else "MISMATCH"
        print(f"[hash] {status} {relative}\n         expected {expected}")
        if observed != expected:
            print(f"         observed {observed}")
            raise ReproductionError(f"frozen source drifted: {relative}")
        verified[relative] = expected
    return verified


def verify_readiness_lock() -> dict[str, Any]:
    """Reuse the frozen readiness-lock verifier over the whole locked set."""
    completed = subprocess.run(
        [sys.executable, str(LOCK_VERIFIER), "--lock", str(LOCK_PATH)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ReproductionError(f"readiness lock verification failed: {completed.stderr}")
    print("[lock] readiness lock verified over the frozen locked path set")
    return json.loads(completed.stdout)


def build_native() -> dict[str, Any]:
    print("[build] cargo build --release --locked --bin clab-jls2")
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            str(REPOSITORY / "native" / "Cargo.toml"),
            "--bin",
            "clab-jls2",
        ],
        cwd=REPOSITORY,
        check=True,
    )
    if not NATIVE_BINARY.is_file():
        raise ReproductionError(f"native decoder was not produced: {NATIVE_BINARY}")
    digest = sha256_file(NATIVE_BINARY)
    print(f"[build] clab-jls2 sha256 (machine-dependent): {digest}")
    return {"path": str(NATIVE_BINARY), "sha256": digest}


def clean_child_measure(command: list[str], report_path: Path) -> dict[str, Any]:
    subprocess.run(
        [
            sys.executable,
            str(MEASURE_CLEAN_RSS),
            "--json-out",
            str(report_path),
            "--",
            *command,
        ],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    )
    return load_json(report_path)


# ----------------------------------------------------------------------------
# Smoke mode: candidate pipeline end to end on a tiny synthetic input.
# ----------------------------------------------------------------------------


def synthesize_ndjson(path: Path, records: int) -> None:
    levels = ("INFO", "WARN", "ERROR")
    with path.open("w", encoding="utf-8") as handle:
        for record_id in range(1, records + 1):
            record = {
                "id": record_id,
                "ts": f"2022-09-28T00:{record_id % 60:02d}:{record_id % 60:02d}Z",
                "level": levels[record_id % 3],
                "svc": f"svc-{record_id % 8}",
                "msg": "synthetic cloud event for reproduction smoke",
                "code": 200 + (record_id % 5),
                "path": f"/api/v1/resource/{record_id % 40}",
            }
            handle.write(json.dumps(record) + "\n")


def run_smoke(native: dict[str, Any], work: Path) -> dict[str, Any]:
    source = work / "smoke-source.jsonl"
    synthesize_ndjson(source, records=4000)
    source_bytes = source.stat().st_size
    source_sha = sha256_file(source)
    print(f"[smoke] synthesized {source_bytes} source bytes")

    first = work / "smoke.first.jls2"
    second = work / "smoke.second.jls2"
    compress_report = work / "smoke-compress.clean-rss.json"
    compress_command = [
        sys.executable,
        str(CANDIDATE_COMPRESS_DRIVER),
        "--source",
        str(source),
        "--destination",
        str(first),
    ]
    compress_measure = clean_child_measure(compress_command, compress_report)
    subprocess.run(
        compress_command[:-1] + [str(second)],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    )
    deterministic = sha256_file(first) == sha256_file(second)
    encoded_bytes = first.stat().st_size
    print(
        f"[smoke] compressed to {encoded_bytes} bytes; deterministic={deterministic}"
    )

    restored = work / "smoke-restored.jsonl"
    decode_report = work / "smoke-decode.clean-rss.json"
    decode_command = [
        str(NATIVE_BINARY),
        "decompress",
        str(first),
        "-o",
        str(restored),
        "--force",
    ]
    decode_measure = clean_child_measure(decode_command, decode_report)
    exact = (
        restored.is_file()
        and restored.stat().st_size == source_bytes
        and sha256_file(restored) == source_sha
    )
    print(f"[smoke] standalone native decode exact byte-identity={exact}")

    passed = bool(deterministic and exact and int(decode_measure["exit_code"]) == 0)
    receipt = {
        "schema": "jls2-v2-reproduction-smoke-v1",
        "mode": "smoke",
        "note": (
            "Candidate build, frozen compress driver, standalone native decode, "
            "clean-child instrument, and frozen-hash verification exercised end to "
            "end on a tiny synthetic input. This does not consume CLUE-LDS, does "
            "not run the Linux-only baselines or PBC specialist, and does not "
            "reproduce the frozen byte counts. Shim-floor eligibility is not "
            "asserted here because a tiny synthetic target is below the "
            "instrument's few-MiB floor by design; it is meaningful only on the "
            "full corpus. Full frozen reproduction on a dedicated Linux machine "
            "remains required."
        ),
        "native_binary": native,
        "synthetic_source": {
            "source_bytes": source_bytes,
            "source_sha256": source_sha,
            "encoded_bytes": encoded_bytes,
        },
        "candidate_compression": {
            "deterministic": deterministic,
            "clean_child_peak_rss_bytes": int(compress_measure["maxrss_bytes"]),
            "clean_child_shim_floor_bytes": int(compress_measure["shim_maxrss_bytes"]),
            "wall_ns": int(compress_measure["wall_ns"]),
        },
        "standalone_decode": {
            "exact_byte_identity": exact,
            "clean_child_peak_rss_bytes": int(decode_measure["maxrss_bytes"]),
            "clean_child_shim_floor_bytes": int(decode_measure["shim_maxrss_bytes"]),
            "wall_ns": int(decode_measure["wall_ns"]),
        },
        "smoke_passed": passed,
    }
    return receipt


# ----------------------------------------------------------------------------
# Full mode: rebuild the frozen environment and reproduce the frozen result.
# ----------------------------------------------------------------------------


def _run_step(command: list[str], env: Optional[dict[str, str]] = None) -> None:
    print("[run] " + " ".join(command))
    subprocess.run(command, cwd=REPOSITORY, check=True, env=env)


def build_standard_codecs(gates: dict[str, Any], tools: Path) -> dict[str, str]:
    """Build the pinned standard codecs into tools/bin, mirroring the workflow.

    Pins are single-sourced from the frozen gates file so this bundle cannot
    drift from the sealed contract. The build commands mirror
    .github/workflows/clue-jls2-public-validation-v2.yml.
    """
    sources = gates["baselines"]["required_external_sources"]
    bin_dir = tools / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    jobs = str(os.cpu_count() or 1)

    zstd = tools / "zstd"
    _run_step(["git", "clone", sources["zstd"]["repository"], str(zstd)])
    _run_step(["git", "-C", str(zstd), "checkout", "--detach", sources["zstd"]["commit"]])
    _run_step(["make", "-C", str(zstd), f"-j{jobs}", "zstd-release"])
    shutil.copy2(zstd / "programs" / "zstd", bin_dir / "zstd")

    lz4 = tools / "lz4"
    _run_step(["git", "clone", sources["lz4"]["repository"], str(lz4)])
    _run_step(["git", "-C", str(lz4), "checkout", "--detach", sources["lz4"]["commit"]])
    _run_step(["make", "-C", str(lz4), f"-j{jobs}"])
    shutil.copy2(lz4 / "lz4", bin_dir / "lz4")

    brotli = tools / "brotli"
    brotli_build = tools / "brotli-build"
    _run_step(["git", "clone", sources["brotli"]["repository"], str(brotli)])
    _run_step(
        ["git", "-C", str(brotli), "checkout", "--detach", sources["brotli"]["commit"]]
    )
    _run_step(
        [
            "cmake",
            "-S",
            str(brotli),
            "-B",
            str(brotli_build),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_INSTALL_PREFIX={tools}",
        ]
    )
    _run_step(["cmake", "--build", str(brotli_build), "--parallel"])
    _run_step(["cmake", "--install", str(brotli_build)])

    archive = tools / "7z-linux-x64.tar.xz"
    seven = sources["7zip"]
    _run_step(
        [
            "curl",
            "--fail",
            "--location",
            "--proto",
            "=https",
            "--tlsv1.2",
            seven["release_url"],
            "--output",
            str(archive),
        ]
    )
    if sha256_file(archive) != seven["asset_sha256"]:
        raise ReproductionError("7zip release asset sha256 differs from frozen value")
    _run_step(["tar", "-xJf", str(archive), "-C", str(bin_dir)])
    os.chmod(bin_dir / "7zz", 0o755)
    return {"bin": str(bin_dir), "lib": str(tools / "lib")}


def build_pbc(gates: dict[str, Any], pbc_dir: Path) -> None:
    """Clone and build the pinned PBC specialist, mirroring the workflow.

    The boost/colm URL and hash repairs are load-bearing and are kept in sync
    with .github/workflows/clue-jls2-public-validation-v2.yml.
    """
    specialist = gates["baselines"]["specialist"]
    _run_step(["git", "clone", specialist["repository"], str(pbc_dir)])
    _run_step(["git", "-C", str(pbc_dir), "checkout", "--detach", specialist["commit"]])
    license_sha = sha256_file(pbc_dir / "LICENSE")
    if license_sha != specialist["license_sha256"]:
        raise ReproductionError("PBC LICENSE sha256 differs from frozen value")
    _apply_pbc_dependency_repairs(pbc_dir)
    env = dict(os.environ)
    env["PBC_MAKE_JOBS"] = str(os.cpu_count() or 1)
    print("[run] (cd pbc && bash ./build.sh -r)")
    subprocess.run(["bash", "./build.sh", "-r"], cwd=pbc_dir, check=True, env=env)
    _run_step(
        [
            "git",
            "-C",
            str(pbc_dir),
            "checkout",
            "--",
            "third-party/externals/boost.cmake",
            "third-party/externals/colm.cmake",
        ]
    )
    if not (pbc_dir / "bin" / "pbc").is_file():
        raise ReproductionError("PBC binary was not produced")


def _apply_pbc_dependency_repairs(pbc_dir: Path) -> None:
    boost = pbc_dir / "third-party" / "externals" / "boost.cmake"
    boost.write_text(
        boost.read_text(encoding="utf-8").replace(
            "https://boostorg.jfrog.io/artifactory/main/release/1.67.0/source/"
            "boost_1_67_0.tar.gz",
            "https://archives.boost.io/release/1.67.0/source/boost_1_67_0.tar.gz",
        ),
        encoding="utf-8",
    )
    colm = pbc_dir / "third-party" / "externals" / "colm.cmake"
    text = colm.read_text(encoding="utf-8")
    text = text.replace(
        "https://github.com/adrian-thurston/colm/archive/refs/tags/0.14.7.tar.gz",
        "https://codeload.github.com/adrian-thurston/colm-suite/tar.gz/"
        "e88bda068d4a25f2afa7f48821e0f539405c8c6a",
    )
    text = text.replace(
        "URL_HASH MD5=213a9ddf207c5732f04941852ca8db62",
        "URL_HASH SHA256="
        "6f11b349722797165f5b71bac5dd71a2ade3cff1c45a9c0ae5522f0f71902ee1",
    )
    colm.write_text(text, encoding="utf-8")


def acquire_corpus(work: Path) -> Path:
    output = work / "clue-validation-v2"
    cache = work / "clue-cache-v2"
    _run_step(
        [
            sys.executable,
            str(FETCH_CORPUS),
            "--split",
            "public-validation",
            "--allow-public-validation",
            "--validation-lock",
            str(LOCK_PATH),
            "--output",
            str(output),
            "--cache",
            str(cache),
        ]
    )
    manifest = output / "manifest.json"
    if not manifest.is_file():
        raise ReproductionError("corpus acquisition produced no manifest")
    return manifest


def run_full(
    gates: dict[str, Any],
    native: dict[str, Any],
    work: Path,
) -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        raise ReproductionError(
            "full reproduction reproduces the frozen ubuntu-22.04 environment and "
            "requires Linux (found "
            f"{sys.platform}); use --smoke here or run the full pipeline on a "
            "dedicated Linux machine (see the reproduction protocol doc)."
        )
    tools = work / "frozen-codecs"
    paths = build_standard_codecs(gates, tools)
    env = dict(os.environ)
    env["PATH"] = paths["bin"] + os.pathsep + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = paths["lib"] + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    env["PYTHONPATH"] = str(REPOSITORY / "src") + os.pathsep + env.get("PYTHONPATH", "")

    pbc_dir = work / "pbc"
    build_pbc(gates, pbc_dir)

    manifest = acquire_corpus(work)

    evidence = work / "evidence"
    jls2_out = evidence / "jls2"
    _run_step(
        [
            sys.executable,
            str(BENCHMARK),
            "--manifest",
            str(manifest),
            "--gates",
            str(GATES_PATH),
            "--lock",
            str(LOCK_PATH),
            "--native-binary",
            str(NATIVE_BINARY),
            "--output",
            str(jls2_out),
        ],
        env=env,
    )
    pbc_result = evidence / "pbc-result.json"
    _run_step(
        [
            sys.executable,
            str(PBC_BENCHMARK),
            "--pbc-binary",
            str(pbc_dir / "bin" / "pbc"),
            "--pbc-repository",
            str(pbc_dir),
            "--manifest",
            str(manifest),
            "--accepted",
            str(jls2_out / "pbc-accepted.json"),
            "--gates",
            str(REPOSITORY / "config" / "clue-pbc-public-validation-v2-gates.json"),
            "--output",
            str(pbc_result),
            "--repetitions",
            "5",
            "--training-repetitions",
            "2",
        ],
        env=env,
    )
    decision_path = evidence / "decision.json"
    _run_step(
        [
            sys.executable,
            str(EVALUATE),
            "--receipt",
            str(jls2_out / "receipt.json"),
            "--performance",
            str(jls2_out / "performance" / "results.json"),
            "--pbc",
            str(pbc_result),
            "--gates",
            str(GATES_PATH),
            "--output",
            str(decision_path),
        ],
        env=env,
    )
    reproduced = load_json(decision_path)
    hosted = load_json(HOSTED_DECISION_PATH)
    comparison = compare_to_hosted(reproduced, hosted)
    return {
        "schema": "jls2-v2-reproduction-full-v1",
        "mode": "full",
        "native_binary": native,
        "reproduced_decision_sha256": sha256_file(decision_path),
        "hosted_decision_sha256": sha256_file(HOSTED_DECISION_PATH),
        "reproduced_aggregate": reproduced["aggregate"],
        "reproduced_family_rows": reproduced["family_rows"],
        "reproduced_gate_results": reproduced["gate_results"],
        "reproduced_result": reproduced["result"],
        "comparison": comparison,
        "verdict": comparison["verdict"],
    }


def compare_to_hosted(
    reproduced: dict[str, Any], hosted: dict[str, Any]
) -> dict[str, Any]:
    """Compare reproduced byte counts and gates against the frozen hosted result.

    Byte counts must match exactly. Speed and peak RSS are machine-dependent and
    are not required to match; the frozen gates are applied to the reproduced
    numbers by the evaluator itself.
    """
    checks: dict[str, bool] = {}
    checks["result_passed"] = reproduced.get("result") == "passed"
    checks["hosted_was_pass"] = hosted.get("result") == "passed"
    checks["aggregate_candidate_bytes_match"] = (
        int(reproduced["aggregate"]["candidate_bytes"])
        == int(hosted["aggregate"]["candidate_bytes"])
    )
    checks["aggregate_strongest_bytes_match"] = (
        int(reproduced["aggregate"]["strongest_eligible_bytes"])
        == int(hosted["aggregate"]["strongest_eligible_bytes"])
    )
    checks["original_bytes_match"] = (
        int(reproduced["aggregate"]["original_bytes"])
        == int(hosted["aggregate"]["original_bytes"])
    )
    hosted_families = {row["item_id"]: row for row in hosted["family_rows"]}
    family_ok = True
    for row in reproduced["family_rows"]:
        other = hosted_families.get(row["item_id"])
        if other is None or int(row["candidate_bytes"]) != int(other["candidate_bytes"]):
            family_ok = False
    checks["family_candidate_bytes_match"] = family_ok
    checks["all_gates_passed"] = all(reproduced["gate_results"].values())
    checks["gate_roster_matches_hosted"] = set(reproduced["gate_results"]) == set(
        hosted["gate_results"]
    )
    reproduced_ok = all(checks.values())
    verdict = (
        "REPRODUCED: byte counts and gate decisions match the frozen hosted result"
        if reproduced_ok
        else "NOT REPRODUCED: a byte count or gate decision diverged from the hosted result"
    )
    return {
        "checks": checks,
        "reproduced": reproduced_ok,
        "verdict": verdict,
        "byte_count_note": (
            "Byte counts are required to match exactly. Speed and peak RSS are "
            "machine-dependent and reported as measured; the frozen gates are "
            "applied to the reproduced numbers by the evaluator."
        ),
    }


def write_receipt(receipt: dict[str, Any], output: Optional[Path]) -> dict[str, Any]:
    receipt = dict(receipt)
    receipt["schema_version"] = 1
    receipt["generated_unix_time"] = int(time.time())
    receipt["repository"] = git_state()
    receipt["machine"] = machine_identity()
    receipt["claim_ceiling"] = (
        "Independent reproduction reproduces the SAME frozen category-scoped v2 "
        "result on the two named CLUE-LDS ranges. It is not a new score, does not "
        "change the immutable v1 not_passed, and supports no universal, "
        "market-leading, world-best, or state-of-the-art language."
    )
    receipt["independence_note"] = (
        "A GitHub rerun of the same workflow is NOT independent reproduction, and "
        "a run on the primary development machine is NOT independent either. "
        "Independent reproduction is a genuinely separate dedicated machine and "
        "operator-independent run."
    )
    bound = bind_receipt(receipt)
    if output is not None:
        if output.exists():
            raise ReproductionError(f"refusing to overwrite receipt: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(bound, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"[receipt] wrote {output}")
    return bound


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Exercise the candidate pipeline on a tiny synthetic input only.",
    )
    parser.add_argument(
        "--pinned-commit",
        default=None,
        help="Assert HEAD equals this commit before running (full mode pin).",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        default=None,
        help="Where to write the self-bound reproduction receipt JSON.",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep the temporary work directory instead of deleting it.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gates = load_json(GATES_PATH)

    preflight_repository(args.pinned_commit, require_clean=not args.smoke)
    verify_hashes(gates)
    if not args.smoke:
        verify_readiness_lock()
    native = build_native()

    work = Path(tempfile.mkdtemp(prefix="jls2-v2-repro-"))
    try:
        if args.smoke:
            body = run_smoke(native, work)
        else:
            body = run_full(gates, native, work)
    finally:
        if args.keep_work:
            print(f"[work] retained {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    receipt = write_receipt(body, args.receipt_out)
    if args.smoke:
        ok = bool(receipt["smoke_passed"])
        print("SMOKE PASS" if ok else "SMOKE FAIL")
        return 0 if ok else 1
    ok = bool(receipt["comparison"]["reproduced"])
    print(receipt["verdict"])
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
