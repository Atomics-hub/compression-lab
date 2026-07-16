#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request


REPOSITORY = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 1024 * 1024


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "compression-lab-corpus-fetch/1"},
    )
    partial = destination.with_suffix(destination.suffix + ".partial")
    with urllib.request.urlopen(request, timeout=120) as response:
        with partial.open("wb") as output:
            shutil.copyfileobj(response, output, CHUNK_SIZE)
    partial.replace(destination)


def build(
    config_path: Path,
    output: Path,
    cache: Path,
    allow_blind_validation: bool,
) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    splits = {source["split"] for source in config["sources"]}
    if "validation" in splits and not allow_blind_validation:
        raise ValueError(
            "refusing to open blind validation without "
            "--allow-blind-validation"
        )
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    manifest_items = []
    for source in config["sources"]:
        cached = cache / source["filename"]
        if not cached.is_file():
            print(f"download {source['url']}", flush=True)
            download(source["url"], cached)
        algorithm = source["publisher_digest_algorithm"]
        actual_publisher_digest = file_digest(cached, algorithm)
        if actual_publisher_digest != source["publisher_digest"]:
            raise ValueError(
                f"{source['filename']} {algorithm} mismatch: expected "
                f"{source['publisher_digest']}, got {actual_publisher_digest}"
            )
        sha256 = file_digest(cached, "sha256")
        expected_sha256 = source.get("sha256")
        if expected_sha256 is not None and sha256 != expected_sha256:
            raise ValueError(
                f"{source['filename']} sha256 mismatch: expected "
                f"{expected_sha256}, got {sha256}"
            )
        destination = output / source["filename"]
        if destination != cached:
            shutil.copyfile(cached, destination)
        manifest_items.append(
            {
                "dataset": source["dataset"],
                "family": source["family"],
                "filename": source["filename"],
                "path": str(destination),
                "size_bytes": destination.stat().st_size,
                "sha256": sha256,
                "publisher_digest_algorithm": algorithm,
                "publisher_digest": actual_publisher_digest,
                "split": source["split"],
            }
        )
        print(
            f"verified {source['family']} {destination.stat().st_size:,} bytes "
            f"sha256={sha256}",
            flush=True,
        )
    manifest = {
        "schema_version": 1,
        "name": config["name"],
        "claim_ceiling": config["claim_ceiling"],
        "source_record": config["source_record"],
        "config_path": str(config_path),
        "config_sha256": file_digest(config_path, "sha256"),
        "items": manifest_items,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "config" / "logtrie-json-log-train-v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "corpora" / "logtrie-json-log-train-v1",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPOSITORY / "corpora" / "_download-cache" / "logtrie-v1",
    )
    parser.add_argument("--allow-blind-validation", action="store_true")
    args = parser.parse_args()
    print(
        build(
            args.config,
            args.output,
            args.cache,
            args.allow_blind_validation,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
