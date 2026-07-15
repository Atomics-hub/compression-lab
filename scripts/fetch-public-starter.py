#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.corpus import import_corpus  # noqa: E402


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "--output", str(destination), url],
        check=True,
        timeout=180,
    )


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(config_path: Path, output: Path, cache: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for index, source in enumerate(config["sources"]):
        url = source["url"]
        archive = cache / f"{index:02d}-{Path(url).name}"
        if not archive.exists():
            print(f"download {url}", flush=True)
            _download(url, archive)
        actual = _digest(archive, source["digest_algorithm"])
        if actual != source["digest"]:
            raise ValueError(f"digest mismatch for {url}: {actual}")

        import_source = archive
        members = source.get("zip_members", [])
        if members:
            extracted = cache / f"{index:02d}-extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                for member in members:
                    if member not in names or Path(member).is_absolute() or ".." in Path(member).parts:
                        raise ValueError(f"unsafe or missing ZIP member: {member}")
                    bundle.extract(member, extracted)
            import_source = extracted

        import_corpus(
            import_source,
            output,
            source["category"],
            source["split"],
            source["dataset"],
            source["license_spdx"],
            url,
        )
        archive_category = source.get("also_import_archive_as")
        if archive_category:
            import_corpus(
                archive,
                output,
                archive_category,
                source["split"],
                f"{source['dataset']}-archive",
                source["license_spdx"],
                url,
            )
    return output / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=REPOSITORY / "config" / "public-starter-v1.json"
    )
    parser.add_argument(
        "--output", type=Path, default=REPOSITORY / "corpora" / "public-starter-v1"
    )
    parser.add_argument(
        "--cache", type=Path, default=REPOSITORY / "corpora" / "_download-cache"
    )
    args = parser.parse_args()
    print(build(args.config, args.output, args.cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
