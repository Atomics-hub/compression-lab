#!/usr/bin/env python3
"""Reconstruct the already-acquired text/source development corpus.

Unlike ``fetch-text-source-development.py``, which performs a *first*
acquisition and only accepts ``declared_unacquired`` sources, this script
rebuilds a corpus whose development sources are already ``acquired_development``.
Every rebuilt bundle is bound to the immutable acquisition receipt
(``runs/text-source-development-acquisition-v1.json``): archive digest, derived
byte count, and derived bundle SHA-256 must match the receipt exactly. It fails
closed before any network access on a roster mismatch and never selects sealed
validation or private-holdout sources. It does not, and must not, reset any
declaration back to ``declared_unacquired``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Any
import xml.parsers.expat


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPOSITORY / "config" / "text-source-category-protocol-v1.json"
DEFAULT_RULES = REPOSITORY / "config" / "text-source-path-rules-v1.json"
DEFAULT_RECEIPT = REPOSITORY / "runs" / "text-source-development-acquisition-v1.json"
FETCHER_SCRIPT = REPOSITORY / "scripts" / "fetch-text-source-development.py"
ACQUIRED_STATE = "acquired_development"
UNACQUIRED_STATE = "declared_unacquired"


def _load_fetcher():
    specification = importlib.util.spec_from_file_location(
        "fetch_text_source_development", FETCHER_SCRIPT
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("unable to load the text/source acquisition primitives")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


FETCHER = _load_fetcher()
BUILDERS = FETCHER.BUILDERS
file_digest = FETCHER.file_digest


def _receipt_index(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if receipt.get("public_validation_accessed") is not False:
        raise ValueError("acquisition receipt reports public-validation access")
    if not receipt.get("passed", False):
        raise ValueError("acquisition receipt is not a passing development receipt")
    index: dict[str, dict[str, Any]] = {}
    for item in receipt["items"]:
        source_id = item["source_id"]
        if source_id in index:
            raise ValueError(f"duplicate source in acquisition receipt: {source_id}")
        for field in ("archive_sha256", "bundle_size_bytes", "bundle_sha256", "format"):
            if field not in item:
                raise ValueError(f"receipt item {source_id} missing field {field}")
        index[source_id] = item
    if len(index) != receipt.get("item_count", len(index)):
        raise ValueError("receipt item_count disagrees with the item roster")
    return index


def _bind_to_receipt(manifest: dict[str, Any], expected: dict[str, Any]) -> None:
    source_id = manifest["source_id"]
    if manifest["format"] != expected["format"]:
        raise ValueError(f"reconstructed format differs from receipt: {source_id}")
    if manifest["archive_sha256"] != expected["archive_sha256"]:
        raise ValueError(f"reconstructed archive SHA-256 differs from receipt: {source_id}")
    if manifest["bundle_size_bytes"] != expected["bundle_size_bytes"]:
        raise ValueError(f"reconstructed byte count differs from receipt: {source_id}")
    if manifest["bundle_sha256"] != expected["bundle_sha256"]:
        raise ValueError(f"reconstructed bundle SHA-256 differs from receipt: {source_id}")


def _selected_development(
    rows: list[dict[str, Any]], track: str
) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        status = row.get("acquisition_status")
        if status == ACQUIRED_STATE:
            selected.append(row)
        elif status == UNACQUIRED_STATE:
            raise ValueError(
                f"{track} development is not fully acquired; reconstruction cannot "
                "run while a declared source is unacquired and must not reset state"
            )
        else:
            raise ValueError(f"unexpected {track} development acquisition status: {status}")
    return selected


def reconstruct_development(
    *,
    protocol_path: Path,
    rules_path: Path,
    receipt_path: Path,
    output: Path,
    cache: Path,
) -> Path:
    if output.exists():
        raise ValueError(f"refusing to replace development corpus: {output}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_index = _receipt_index(receipt)

    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    source_development = _selected_development(
        protocol["source_code"]["development"], "source"
    )
    wiki_development = _selected_development(
        protocol["natural_language"]["development"], "Wikimedia"
    )

    selected_ids = [row["id"] for row in source_development + wiki_development]
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("duplicate development source ID in the protocol")
    if set(selected_ids) != set(receipt_index):
        raise ValueError(
            "acquired development roster does not match the acquisition receipt"
        )

    expected_rules = protocol["source_code"]["bundle_rule"]["path_rules_sha256"]
    if file_digest(rules_path) != expected_rules:
        raise ValueError("source path-rule digest differs from the protocol")

    cache.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    manifests: list[dict[str, Any]] = []
    try:
        for source in source_development:
            expected = receipt_index[source["id"]]
            archive = FETCHER.ensure_download(source["archive_url"], cache)
            if file_digest(archive) != expected["archive_sha256"]:
                raise ValueError(
                    f"downloaded archive digest differs from receipt: {source['id']}"
                )
            evidence_url = source.get("publisher_digest_source")
            publisher_evidence = (
                FETCHER.ensure_download(evidence_url, cache)
                if evidence_url is not None
                else None
            )
            manifest = FETCHER._source_manifest(
                source, archive, publisher_evidence, stage, rules_path
            )
            _bind_to_receipt(manifest, expected)
            manifests.append(manifest)
        for source in wiki_development:
            expected = receipt_index[source["id"]]
            checksum = FETCHER.ensure_download(source["checksum_url"], cache)
            archive = FETCHER.ensure_download(source["archive_url"], cache)
            if file_digest(archive) != expected["archive_sha256"]:
                raise ValueError(
                    f"downloaded archive digest differs from receipt: {source['id']}"
                )
            manifest = FETCHER._wikimedia_manifest(source, archive, checksum, stage)
            _bind_to_receipt(manifest, expected)
            manifests.append(manifest)

        if len(manifests) != len(receipt_index):
            raise ValueError("reconstructed item count does not match the receipt")

        aggregate = {
            "schema_version": 1,
            "name": "text-source-development-corpus-v1",
            "reconstruction": True,
            "claim_ceiling": (
                "Deterministic reconstruction of an already-acquired development "
                "corpus verified against the immutable acquisition receipt; no "
                "validation, benchmark win, private holdout, or state-of-the-art evidence."
            ),
            "protocol_path": BUILDERS.repository_reference(protocol_path),
            "protocol_sha256": file_digest(protocol_path),
            "rules_path": BUILDERS.repository_reference(rules_path),
            "rules_sha256": file_digest(rules_path),
            "receipt_path": BUILDERS.repository_reference(receipt_path),
            "receipt_sha256": file_digest(receipt_path),
            "acquisition_commit": receipt["acquisition_commit"],
            "public_validation_accessed": False,
            "toolchain": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "expat": xml.parsers.expat.EXPAT_VERSION,
                "builder_sha256": file_digest(FETCHER.BUILDER_SCRIPT),
                "fetcher_sha256": file_digest(FETCHER_SCRIPT),
                "reconstructor_sha256": file_digest(Path(__file__)),
            },
            "items": [
                {
                    "source_id": manifest["source_id"],
                    "format": manifest["format"],
                    "archive_sha256": manifest["archive_sha256"],
                    "bundle_path": manifest["bundle_path"],
                    "bundle_size_bytes": manifest["bundle_size_bytes"],
                    "bundle_sha256": manifest["bundle_sha256"],
                    "manifest_path": f"{manifest['source_id']}.manifest.json",
                }
                for manifest in manifests
            ],
        }
        BUILDERS.write_json_atomic(stage / "manifest.json", aggregate)
        os.replace(stage, output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "corpora" / "text-source-development-v1",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPOSITORY / "corpora" / "_download-cache" / "text-source-v1",
    )
    args = parser.parse_args()
    try:
        manifest = reconstruct_development(
            protocol_path=args.protocol,
            rules_path=args.rules,
            receipt_path=args.receipt,
            output=args.output,
            cache=args.cache,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f"development reconstruction refused: {error}") from error
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
