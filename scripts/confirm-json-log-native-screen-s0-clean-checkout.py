#!/usr/bin/env python3
"""Clean-checkout confirmation for a frozen S0 JSON/log native screen run.

Clones the repository into a scratch directory, checks out the pinned commit,
verifies every engine-source file SHA-256 against a freeze record, rebuilds the
kernel, re-encodes every arm x item from the same corpus paths, and byte-compares
each fresh receipt with the original run's receipt. Receipts are content-derived
only, so a faithful clean checkout must reproduce them byte-for-byte. Exits
nonzero unless every receipt is identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_RELATIVE = "corpora/clue-json-log-development-v1"


class ConfirmationError(Exception):
    """A fail-closed clean-checkout confirmation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ConfirmationError(f"expected ordinary file: {path}")


def read_json(path: Path) -> dict[str, Any]:
    ordinary(path)
    return json.loads(path.read_bytes())


def git(*arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ConfirmationError(
            f"git {' '.join(arguments)} failed: {completed.stderr.strip()}"
        )


def load_items(config: dict[str, Any], items_config: Path | None) -> list[dict[str, Any]]:
    raw = (
        read_json(items_config)["items"]
        if items_config is not None
        else config["references"]["items"]
    )
    return [
        {"index": index, "id": entry["id"]}
        for index, entry in enumerate(raw)
    ]


def build_kernel(checkout: Path, skip_build: bool, kernel_binary: Path | None) -> Path:
    if kernel_binary is not None:
        ordinary(kernel_binary)
        return kernel_binary.resolve()
    binary = checkout / "native" / "target" / "release" / "clab-s0-kernel"
    if not skip_build:
        completed = subprocess.run(
            ["cargo", "build", "--release", "--locked", "--bin", "clab-s0-kernel"],
            cwd=checkout / "native",
            check=False,
        )
        if completed.returncode != 0:
            raise ConfirmationError("cargo build of clab-s0-kernel failed in the checkout")
    ordinary(binary)
    return binary


def reencode(
    kernel: Path,
    arm: str,
    item: dict[str, Any],
    corpus_dir: Path,
    segment_bytes: int,
    scratch: Path,
) -> Path:
    tape_out = scratch / "tapes" / arm / f"{item['id']}.tape"
    receipt_out = scratch / "receipts" / arm / f"{item['id']}.json"
    tape_out.parent.mkdir(parents=True, exist_ok=True)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(kernel),
            "encode",
            "--arm",
            arm,
            "--item-index",
            str(item["index"]),
            "--input",
            str(corpus_dir / f"{item['id']}.jsonl"),
            "--tape-out",
            str(tape_out),
            "--receipt-out",
            str(receipt_out),
            "--segment-bytes",
            str(segment_bytes),
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={"LC_ALL": "C", "TZ": "UTC", "PATH": _minimal_path()},
    )
    if completed.returncode != 0:
        raise ConfirmationError(
            f"re-encode failed for {arm}/{item['id']}: {completed.stderr.strip()}"
        )
    ordinary(receipt_out)
    return receipt_out


def _minimal_path() -> str:
    import os

    return os.environ.get("PATH", "/usr/bin:/bin")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--freeze-record", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--corpus-dir", type=Path, default=None)
    parser.add_argument("--items-config", type=Path, default=None)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--kernel-binary", type=Path, default=None)
    args = parser.parse_args()

    if len(args.commit) != 40 or any(
        character not in "0123456789abcdef" for character in args.commit
    ):
        raise SystemExit("clean-checkout commit must be a lowercase 40-hex SHA")
    if args.scratch_dir.exists():
        raise SystemExit(f"scratch directory must not exist: {args.scratch_dir}")

    run_dir = args.run_dir.resolve()
    try:
        checkout = args.scratch_dir / "checkout"
        git("clone", "--quiet", str(args.repo.resolve()), str(checkout))
        git("-C", str(checkout), "checkout", "--quiet", args.commit)

        freeze = read_json(args.freeze_record)
        if freeze["commit"] != args.commit:
            raise ConfirmationError("freeze record commit differs from --commit")
        for relative, expected in sorted(freeze["engine_source_files"].items()):
            path = checkout / relative
            ordinary(path)
            if sha256_file(path) != expected:
                raise ConfirmationError(f"engine source SHA differs: {relative}")

        kernel = build_kernel(checkout, args.skip_build, args.kernel_binary)
        config = read_json(checkout / "config" / "json-log-native-screen-s0-v1.json")
        items = load_items(config, args.items_config)
        item_by_id = {item["id"]: item for item in items}
        corpus_dir = (
            args.corpus_dir.resolve()
            if args.corpus_dir is not None
            else checkout / DEFAULT_CORPUS_RELATIVE
        )

        receipts_root = run_dir / "receipts"
        if not receipts_root.is_dir():
            raise ConfirmationError(f"original run has no receipts: {receipts_root}")
        arms = sorted(entry.name for entry in receipts_root.iterdir() if entry.is_dir())
        if not arms:
            raise ConfirmationError("original run has no arm receipts")

        comparisons: list[dict[str, Any]] = []
        all_identical = True
        for arm in arms:
            for original in sorted((receipts_root / arm).glob("*.json")):
                item_id = original.stem
                if item_id not in item_by_id:
                    raise ConfirmationError(f"receipt {arm}/{item_id} has no item entry")
                original_receipt = read_json(original)
                segment_bytes = int(original_receipt["segment_interval_bytes"])
                fresh = reencode(
                    kernel,
                    arm,
                    item_by_id[item_id],
                    corpus_dir,
                    segment_bytes,
                    args.scratch_dir,
                )
                identical = original.read_bytes() == fresh.read_bytes()
                all_identical = all_identical and identical
                comparisons.append(
                    {
                        "arm": arm,
                        "item_id": item_id,
                        "identical": identical,
                    }
                )

        report = {
            "confirmed": all_identical,
            "commit": args.commit,
            "run_dir": str(run_dir),
            "comparisons": comparisons,
        }
        (args.scratch_dir / "confirmation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except ConfirmationError as error:
        raise SystemExit(f"clean-checkout confirmation failed: {error}") from error

    print(json.dumps({"confirmed": all_identical, "receipts": len(comparisons)}))
    return 0 if all_identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
