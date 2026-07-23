"""Fetch and pin PUBLIC prescreen corpora for the moonshot lane (Lane 2).

Prescreen looks at synthetic and public data are unlimited (charter,
Standing Rule 3), but every byte an arm reads must be pinned first: this
tool downloads from an explicit host allowlist, records URL, compressed and
decompressed SHA-256 and sizes into a receipt, and refuses lineage-hazard
sources outright. The CLUE development/validation corpora are never touched
by this tool; it has no path into `corpora/`.

Allowed sources:
- data.gharchive.org - hourly public GitHub event NDJSON (log-shaped JSON).

Denied outright (lineage hazard, charter §Lane 2 / cycle-1 draft §5):
- zenodo.org and any URL or name containing "ait" or "landauer" - the
  AIT-LDS family shares authorship lineage with the sealed CLUE corpus.

Usage:
  python scripts/moon-fetch-public-corpora.py \
      --destination DIR --receipt-out RECEIPT.json \
      --gharchive 2026-05-15-14 [--gharchive 2026-06-15-14 ...]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

TOOL_VERSION = "moon-fetch-public-corpora-v1"
ALLOWED_HOSTS = {"data.gharchive.org"}
DENYLIST_TOKENS = ("zenodo", "ait-lds", "ait_lds", "landauer")
GHARCHIVE_HOUR = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{1,2}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SystemExit(f"refusing non-https source: {url}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise SystemExit(f"host is outside the public-corpus allowlist: {url}")
    lowered = url.lower()
    for token in DENYLIST_TOKENS:
        if token in lowered:
            raise SystemExit(f"lineage-hazard source refused: {url}")


def fetch(url: str, destination: Path) -> None:
    check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": TOOL_VERSION})
    with urllib.request.urlopen(request) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def fetch_gharchive_hour(hour: str, destination: Path) -> dict[str, object]:
    if not GHARCHIVE_HOUR.match(hour):
        raise SystemExit(f"not a GH Archive hour (YYYY-MM-DD-H): {hour}")
    url = f"https://data.gharchive.org/{hour}.json.gz"
    compressed = destination / f"gharchive-{hour}.json.gz"
    decompressed = destination / f"gharchive-{hour}.ndjson"
    if not compressed.exists():
        fetch(url, compressed)
    with gzip.open(compressed, "rb") as source, decompressed.open("wb") as output:
        shutil.copyfileobj(source, output)
    return {
        "kind": "gharchive-hour",
        "hour": hour,
        "url": url,
        "compressed_path": str(compressed),
        "compressed_bytes": compressed.stat().st_size,
        "compressed_sha256": sha256_file(compressed),
        "decompressed_path": str(decompressed),
        "decompressed_bytes": decompressed.stat().st_size,
        "decompressed_sha256": sha256_file(decompressed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    parser.add_argument(
        "--gharchive",
        action="append",
        default=[],
        metavar="YYYY-MM-DD-H",
        help="GH Archive hour to fetch (repeatable)",
    )
    arguments = parser.parse_args()
    if not arguments.gharchive:
        raise SystemExit("nothing to fetch: pass at least one --gharchive hour")

    arguments.destination.mkdir(parents=True, exist_ok=True)
    items = [
        fetch_gharchive_hour(hour, arguments.destination)
        for hour in arguments.gharchive
    ]
    receipt = {
        "schema": "moon-public-corpora-receipt-v1",
        "tool_version": TOOL_VERSION,
        "allowed_hosts": sorted(ALLOWED_HOSTS),
        "denylist_tokens": list(DENYLIST_TOKENS),
        "items": items,
    }
    arguments.receipt_out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in items:
        print(
            f"{item['hour']}: {item['decompressed_bytes']:,} bytes "
            f"sha256={item['decompressed_sha256'][:16]}..."
        )
    print(f"wrote {arguments.receipt_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
