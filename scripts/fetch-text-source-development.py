#!/usr/bin/env python3
"""Acquire and build only the declared text/source development corpora."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Any, Optional
import urllib.parse
import urllib.request
import xml.parsers.expat


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPOSITORY / "config" / "text-source-category-protocol-v1.json"
DEFAULT_RULES = REPOSITORY / "config" / "text-source-path-rules-v1.json"
BUILDER_SCRIPT = REPOSITORY / "scripts" / "build-text-source-corpora.py"
CHUNK_SIZE = 1024 * 1024
MAXIMUM_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_HOSTS = {
    "dumps.wikimedia.org",
    "github.com",
    "static.rust-lang.org",
    "www.python.org",
}


def load_builders():
    specification = importlib.util.spec_from_file_location(
        "build_text_source_corpora", BUILDER_SCRIPT
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("unable to load text/source corpus builders")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BUILDERS = load_builders()


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"development URL is outside the frozen allowlist: {url}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"development URL contains forbidden components: {url}")
    return parsed


def url_filename(url: str) -> str:
    parsed = _validated_url(url)
    filename = urllib.parse.unquote(Path(parsed.path).name)
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ValueError(f"development URL has an unsafe filename: {url}")
    return filename


def download(url: str, destination: Path) -> None:
    _validated_url(url)
    partial = destination.with_name(destination.name + ".partial")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "axiom-compression-corpus-fetch/1"},
    )
    observed = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with partial.open("wb") as output:
                while chunk := response.read(CHUNK_SIZE):
                    observed += len(chunk)
                    if observed > MAXIMUM_ARCHIVE_BYTES:
                        raise ValueError("development download exceeded the 2 GiB safety cap")
                    output.write(chunk)
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def ensure_download(url: str, cache: Path) -> Path:
    destination = cache / url_filename(url)
    if not destination.is_file():
        print(f"download {url}", flush=True)
        download(url, destination)
    return destination


def verify_publisher_digest(path: Path, source: dict[str, Any]) -> dict[str, str]:
    expected_size = source.get("archive_size_bytes")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError(f"archive byte count mismatch for {source['id']}")
    algorithm = source.get("publisher_digest_algorithm")
    expected = source.get("publisher_digest")
    if algorithm is None or expected is None:
        return {}
    observed = file_digest(path, algorithm)
    if observed != expected:
        raise ValueError(f"publisher {algorithm} mismatch for {source['id']}")
    return {"algorithm": algorithm, "digest": observed}


def parse_checksum_file(
    checksum_path: Path,
    *,
    expected_filename: str,
    algorithm: str,
) -> str:
    expected_hex_length = hashlib.new(algorithm).digest_size * 2
    matches = []
    for raw_line in checksum_path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split()
        if len(fields) != 2:
            continue
        digest, filename = fields
        filename = filename.lstrip("*")
        if filename == expected_filename:
            matches.append(digest.lower())
    if len(matches) != 1 or len(matches[0]) != expected_hex_length:
        raise ValueError(f"checksum file does not uniquely pin {expected_filename}")
    try:
        bytes.fromhex(matches[0])
    except ValueError as error:
        raise ValueError(f"invalid {algorithm} in checksum file") from error
    return matches[0]


def _source_manifest(
    source: dict[str, Any],
    archive: Path,
    publisher_evidence: Optional[Path],
    stage: Path,
    rules_path: Path,
) -> dict[str, Any]:
    verify_publisher_digest(archive, source)
    destination = stage / f"{source['id']}.axsrc"
    manifest = BUILDERS.build_source_bundle(
        archive_path=archive,
        destination=destination,
        source=source,
        rules_path=rules_path,
    )
    manifest["provenance"] = {
        "archive_url": source["archive_url"],
        "release_url": source["release_url"],
        "license_spdx": source["license_spdx"],
        "license_url": source["license_url"],
        "publisher_digest_algorithm": source.get("publisher_digest_algorithm"),
        "publisher_digest": source.get("publisher_digest"),
        "publisher_digest_source": source.get("publisher_digest_source"),
        "publisher_evidence_file": (
            publisher_evidence.name if publisher_evidence is not None else None
        ),
        "publisher_evidence_sha256": (
            file_digest(publisher_evidence) if publisher_evidence is not None else None
        ),
        "publisher_tag_commit": source.get("publisher_tag_commit"),
    }
    BUILDERS.write_json_atomic(stage / f"{source['id']}.manifest.json", manifest)
    return manifest


def _wikimedia_manifest(
    source: dict[str, Any],
    archive: Path,
    checksum: Path,
    stage: Path,
) -> dict[str, Any]:
    algorithm = source["publisher_digest_algorithm"]
    checksum_digest = parse_checksum_file(
        checksum,
        expected_filename=archive.name,
        algorithm=algorithm,
    )
    if checksum_digest != source["publisher_digest"]:
        raise ValueError(f"checksum declaration drifted for {source['id']}")
    verify_publisher_digest(archive, source)
    destination = stage / f"{source['id']}.axwkt"
    manifest = BUILDERS.build_wikimedia_bundle(
        archive_path=archive,
        destination=destination,
        source=source,
    )
    manifest["provenance"] = {
        "archive_url": source["archive_url"],
        "checksum_url": source["checksum_url"],
        "checksum_file": checksum.name,
        "checksum_file_sha256": file_digest(checksum),
        "publisher_digest_algorithm": algorithm,
        "publisher_digest": checksum_digest,
        "license_expression": (
            "CC-BY-SA-4.0 AND GFDL-1.3-or-later, subject to page-specific "
            "exceptions and third-party material"
        ),
        "legal_url": "https://dumps.wikimedia.org/legal.html",
    }
    BUILDERS.write_json_atomic(stage / f"{source['id']}.manifest.json", manifest)
    return manifest


def acquire_development(
    *,
    protocol_path: Path,
    rules_path: Path,
    output: Path,
    cache: Path,
) -> Path:
    if output.exists():
        raise ValueError(f"refusing to replace development corpus: {output}")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    source_development = protocol["source_code"]["development"]
    wiki_development = protocol["natural_language"]["development"]
    if any(row["acquisition_status"] != "declared_unacquired" for row in source_development):
        raise ValueError("source development declaration is not in the unacquired state")
    if any(row["acquisition_status"] != "declared_unacquired" for row in wiki_development):
        raise ValueError("Wikimedia development declaration is not in the unacquired state")
    expected_rules = protocol["source_code"]["bundle_rule"]["path_rules_sha256"]
    if file_digest(rules_path) != expected_rules:
        raise ValueError("source path-rule digest differs from the protocol")

    cache.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    manifests: list[dict[str, Any]] = []
    try:
        for source in source_development:
            archive = ensure_download(source["archive_url"], cache)
            evidence_url = source.get("publisher_digest_source")
            publisher_evidence = (
                ensure_download(evidence_url, cache) if evidence_url is not None else None
            )
            manifests.append(
                _source_manifest(
                    source,
                    archive,
                    publisher_evidence,
                    stage,
                    rules_path,
                )
            )
        for source in wiki_development:
            checksum = ensure_download(source["checksum_url"], cache)
            archive = ensure_download(source["archive_url"], cache)
            manifests.append(
                _wikimedia_manifest(source, archive, checksum, stage)
            )
        aggregate = {
            "schema_version": 1,
            "name": "text-source-development-corpus-v1",
            "claim_ceiling": (
                "Development acquisition and deterministic corpus construction only; "
                "no validation, benchmark win, private holdout, or state-of-the-art evidence."
            ),
            "protocol_path": BUILDERS.repository_reference(protocol_path),
            "protocol_sha256": file_digest(protocol_path),
            "rules_path": BUILDERS.repository_reference(rules_path),
            "rules_sha256": file_digest(rules_path),
            "public_validation_accessed": False,
            "toolchain": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "expat": xml.parsers.expat.EXPAT_VERSION,
                "builder_sha256": file_digest(BUILDER_SCRIPT),
                "fetcher_sha256": file_digest(Path(__file__)),
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
        manifest = acquire_development(
            protocol_path=args.protocol,
            rules_path=args.rules,
            output=args.output,
            cache=args.cache,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f"development acquisition refused: {error}") from error
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
