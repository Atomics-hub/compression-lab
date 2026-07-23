"""Generate the S0 freeze record that authorizes the development measurement.

The frozen protocol forbids any S0 corpus measurement until the engine source,
both constants manifests, the runner, the verifier, and the clean-checkout
confirmation procedure are committed and hash-pinned. This script derives that
record deterministically from the working tree; the guard test regenerates it
and fails if the committed record disagrees with the tree, so the record can
never go stale silently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


PROTOCOL_RELATIVE = "docs/benchmarks/2026-07-21-json-log-native-screen-s0-protocol.md"
CONFIG_RELATIVE = "config/json-log-native-screen-s0-v1.json"
BASE_MANIFEST_RELATIVE = "config/json-log-native-screen-s0-constants-base-v1.json"
REFINED_MANIFEST_RELATIVE = "config/json-log-native-screen-s0-constants-refined-v1.json"
RUNNER_RELATIVE = "scripts/benchmark-json-log-native-screen-s0.py"
VERIFIER_RELATIVE = "scripts/verify-json-log-native-screen-s0-run.py"
CONFIRMATION_RELATIVE = "scripts/confirm-json-log-native-screen-s0-clean-checkout.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_version(command: str) -> str:
    output = subprocess.run(
        [command, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not output:
        raise SystemExit(f"{command} --version produced no output")
    return output


def build_record(repo_root: Path, engine_commit: str, toolchain: dict[str, str]) -> dict:
    config = json.loads((repo_root / CONFIG_RELATIVE).read_bytes())
    freeze_requirements = config["screen"]["freeze_requirements_before_measurement"]
    protocol_path = repo_root / PROTOCOL_RELATIVE
    protocol_sha256 = sha256_file(protocol_path)
    if protocol_sha256 != freeze_requirements["protocol_sha256"]:
        raise SystemExit("protocol file does not match the frozen protocol SHA-256")

    base_manifest = json.loads((repo_root / BASE_MANIFEST_RELATIVE).read_bytes())
    engine_files = base_manifest["source_toolchain_build_identity"]["engine_source_files"]
    engine_source_sha256 = {}
    for relative in engine_files:
        path = repo_root / relative
        if not path.is_file():
            raise SystemExit(f"missing engine source file: {relative}")
        engine_source_sha256[relative] = sha256_file(path)

    return {
        "schema_version": 1,
        "name": "axiom-json-log-native-screen-s0-freeze-v1",
        "purpose": (
            "Hash-pinned freeze record binding the engine source, constants "
            "manifests, runner, verifier, and clean-checkout confirmation "
            "procedure before the single authorized S0 development measurement. "
            "This record is the binding document the constants manifests refer "
            "to; no S0 corpus measurement is authorized unless the working tree "
            "matches every hash below."
        ),
        "protocol_path": PROTOCOL_RELATIVE,
        "protocol_sha256": protocol_sha256,
        "screen_config_path": CONFIG_RELATIVE,
        "screen_config_sha256": sha256_file(repo_root / CONFIG_RELATIVE),
        "engine_commit": engine_commit,
        "engine_source_sha256": engine_source_sha256,
        "base_constants_manifest_path": BASE_MANIFEST_RELATIVE,
        "base_constants_manifest_sha256": sha256_file(
            repo_root / BASE_MANIFEST_RELATIVE
        ),
        "refined_constants_manifest_path": REFINED_MANIFEST_RELATIVE,
        "refined_constants_manifest_sha256": sha256_file(
            repo_root / REFINED_MANIFEST_RELATIVE
        ),
        "runner_path": RUNNER_RELATIVE,
        "runner_sha256": sha256_file(repo_root / RUNNER_RELATIVE),
        "verifier_path": VERIFIER_RELATIVE,
        "verifier_sha256": sha256_file(repo_root / VERIFIER_RELATIVE),
        "confirmation_path": CONFIRMATION_RELATIVE,
        "confirmation_sha256": sha256_file(repo_root / CONFIRMATION_RELATIVE),
        "toolchain_build_receipt": {
            "rustc": toolchain["rustc"],
            "cargo": toolchain["cargo"],
            "build_command": "cargo build --release --locked --bin clab-s0-kernel",
            "build_profile": "lto=fat, codegen-units=1, panic=abort, strip=true",
        },
        "measurement_authorization": (
            "Exactly one ordered development measurement per arm under the base "
            "constants manifest, followed by its deterministic clean-checkout "
            "confirmation. The refined profile runs only if the full arm lands "
            "in the predeclared refinement band, using the refined constants "
            "manifest under these same hashes."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--engine-commit",
        required=True,
        help="Commit whose tree the engine source hashes describe.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to config/json-log-native-screen-s0-freeze-v1.json.",
    )
    parser.add_argument("--rustc-version", default=None)
    parser.add_argument("--cargo-version", default=None)
    arguments = parser.parse_args()

    commit = arguments.engine_commit.lower()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise SystemExit("--engine-commit must be a full 40-hex commit id")

    toolchain = {
        "rustc": arguments.rustc_version or tool_version("rustc"),
        "cargo": arguments.cargo_version or tool_version("cargo"),
    }
    record = build_record(arguments.repo_root.resolve(), commit, toolchain)
    output = arguments.output or (
        arguments.repo_root.resolve()
        / "config"
        / "json-log-native-screen-s0-freeze-v1.json"
    )
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
