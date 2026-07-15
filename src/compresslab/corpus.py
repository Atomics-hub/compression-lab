from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import random
import re
import shutil
import struct
import tarfile
from pathlib import Path
from typing import Dict, Iterable, List

from .models import CorpusItem


MANIFEST_NAME = "manifest.json"
CORPUS_SCHEMA_VERSION = 2
SUPPORTED_CORPUS_SCHEMA_VERSIONS = {1, 2}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repeat_to_size(seed: bytes, size: int) -> bytes:
    if not seed:
        return b""
    return (seed * ((size + len(seed) - 1) // len(seed)))[:size]


def _random_bytes(rng: random.Random, size: int) -> bytes:
    return bytes(rng.getrandbits(8) for _ in range(size))


def _deterministic_tar(file_count: int, target_size: int) -> bytes:
    output = io.BytesIO()
    per_file = max(128, target_size // max(1, file_count))
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for index in range(file_count):
            module = (
                f'"""Generated module {index:04d}."""\n\n'
                f"CONSTANT = {index % 17}\n\n"
                "def transform(value):\n"
                f"    return (value * {index % 11 + 1} + CONSTANT) % 65521\n\n"
                "def validate(values):\n"
                "    return all(transform(v) >= 0 for v in values)\n"
            ).encode("utf-8")
            payload = _repeat_to_size(module, per_file)
            info = tarfile.TarInfo(f"src/package_{index % 12:02d}/module_{index:04d}.py")
            info.size = len(payload)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


def _json_logs(size: int) -> bytes:
    rows: List[bytes] = []
    total = 0
    index = 0
    while total < size:
        row = json.dumps(
            {
                "timestamp": f"2026-07-15T12:{(index // 60) % 60:02d}:{index % 60:02d}Z",
                "level": ("INFO", "INFO", "INFO", "WARN", "ERROR")[index % 5],
                "service": f"worker-{index % 8}",
                "request_id": f"req-{index:08d}",
                "latency_ms": 4 + (index * 17) % 240,
                "message": ("completed request", "cache hit", "queued task")[index % 3],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        rows.append(row)
        total += len(row)
        index += 1
    return b"".join(rows)[:size]


def _numeric_f32(size: int) -> bytes:
    count = size // 4
    output = bytearray(count * 4)
    for index in range(count):
        value = math.sin(index / 50.0) * 100.0 + (index % 1024) * 0.001
        struct.pack_into("<f", output, index * 4, value)
    return bytes(output)


def generate_corpus(destination: Path, size_scale: float = 1.0, seed: int = 20260715) -> Path:
    if size_scale <= 0:
        raise ValueError("size_scale must be positive")
    destination.mkdir(parents=True, exist_ok=True)
    data_dir = destination / "validation"
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    unit = max(64 * 1024, int(512 * 1024 * size_scale))

    prose = (
        b"Compression should be judged as a complete system. "
        b"Ratio, speed, memory, energy, random access, and safety all matter.\n"
    )
    random_payload = _random_bytes(rng, unit)
    precompressed_payload = gzip.compress(_random_bytes(rng, unit), compresslevel=9, mtime=0)
    sparse = (
        b"\x00" * (unit // 3)
        + _repeat_to_size(b"ABCD1234", unit // 3)
        + b"\xff" * (unit - 2 * (unit // 3))
    )
    mixed = (
        _repeat_to_size(prose, unit // 3)
        + _random_bytes(rng, unit // 3)
        + _numeric_f32(unit - 2 * (unit // 3))
    )

    payloads = [
        ("text-repetitive", "text", "text.txt", _repeat_to_size(prose, unit)),
        ("json-logs", "structured-text", "logs.jsonl", _json_logs(unit * 2)),
        ("numeric-f32", "numeric", "signals.f32", _numeric_f32(unit * 2)),
        ("source-tree-tar", "small-file-bundle", "source-tree.tar", _deterministic_tar(160, unit * 2)),
        ("random", "incompressible", "random.bin", random_payload),
        ("already-compressed", "already-compressed", "random.bin.gz", precompressed_payload),
        ("sparse-runs", "runs", "sparse.bin", sparse),
        ("mixed-regions", "mixed", "mixed.bin", mixed),
    ]

    items: List[Dict[str, object]] = []
    for item_id, category, filename, payload in payloads:
        path = data_dir / filename
        path.write_bytes(payload)
        items.append(
            {
                "id": item_id,
                "path": str(path.relative_to(destination)),
                "category": category,
                "split": "validation",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "dataset": "compression-lab-smoke",
                "license_spdx": "LicenseRef-CompressionLab-Synthetic",
                "source_url": "",
                "provenance": {"generator": "compression-lab", "seed": seed},
            }
        )

    manifest = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "generator": "compression-lab",
        "seed": seed,
        "size_scale": size_scale,
        "items": items,
    }
    manifest_path = destination / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.").lower()
    return normalized or "item"


def import_corpus(
    source: Path,
    destination: Path,
    category: str,
    split: str,
    dataset: str,
    license_spdx: str,
    source_url: str,
) -> Path:
    """Copy licensed source files into a provenance-aware corpus."""
    if split not in {"train", "validation", "holdout"}:
        raise ValueError("split must be train, validation, or holdout")
    required = {
        "category": category,
        "dataset": dataset,
        "license_spdx": license_spdx,
        "source_url": source_url,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise ValueError(f"missing provenance field(s): {', '.join(missing)}")
    if source.is_symlink():
        raise ValueError("source symlinks are not accepted")
    source = source.resolve()
    destination = destination.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_dir():
        try:
            destination.relative_to(source)
        except ValueError:
            pass
        else:
            raise ValueError("corpus destination cannot be inside the imported source")
    candidates = [source] if source.is_file() else sorted(
        path for path in source.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if not candidates:
        raise ValueError(f"no regular files found under {source}")

    manifest_path = destination / MANIFEST_NAME
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != CORPUS_SCHEMA_VERSION:
            raise ValueError("imports require a schema-version 2 corpus")
    else:
        manifest = {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "generator": "compression-lab-import",
            "items": [],
        }
    existing_ids = {str(item["id"]) for item in manifest["items"]}
    base = source.parent if source.is_file() else source
    data_dir = destination / split / _slug(category)
    data_dir.mkdir(parents=True, exist_ok=True)

    for path in candidates:
        relative = path.relative_to(base)
        digest = sha256_file(path)
        item_id = f"{_slug(dataset)}-{_slug(relative.as_posix())}-{digest[:12]}"
        if item_id in existing_ids:
            continue
        stored_name = f"{digest[:12]}-{_slug(path.name)}"
        stored_path = data_dir / stored_name
        shutil.copyfile(path, stored_path)
        manifest["items"].append(
            {
                "id": item_id,
                "path": str(stored_path.relative_to(destination)),
                "category": category,
                "split": split,
                "size_bytes": stored_path.stat().st_size,
                "sha256": digest,
                "dataset": dataset,
                "license_spdx": license_spdx,
                "source_url": source_url,
                "provenance": {"source_relative_path": relative.as_posix()},
            }
        )
        existing_ids.add(item_id)

    manifest["items"] = sorted(manifest["items"], key=lambda item: item["id"])
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def holdout_commitment(root: Path) -> Dict[str, object]:
    items = load_corpus(root, ("holdout",))
    canonical_items = [
        {
            "id": item.id,
            "category": item.category,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "dataset": item.dataset,
            "license_spdx": item.license_spdx,
            "source_url": item.source_url,
        }
        for item in sorted(items, key=lambda value: value.id)
    ]
    canonical = json.dumps(
        canonical_items, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "split": "holdout",
        "item_count": len(items),
        "total_bytes": sum(item.size_bytes for item in items),
        "commitment_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def freeze_holdout(root: Path, output: Path, overwrite: bool = False) -> Path:
    if output.exists() and not overwrite:
        raise FileExistsError(f"holdout lock already exists: {output}")
    payload = holdout_commitment(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def verify_holdout(root: Path, lock_path: Path) -> bool:
    expected = json.loads(lock_path.read_text(encoding="utf-8"))
    return expected == holdout_commitment(root)


def load_corpus(root: Path, splits: Iterable[str] = ("validation",)) -> List[CorpusItem]:
    manifest_path = root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in SUPPORTED_CORPUS_SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported corpus schema in {manifest_path}")
    wanted = set(splits)
    items: List[CorpusItem] = []
    for raw in manifest["items"]:
        if raw["split"] not in wanted:
            continue
        path = root / raw["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != raw["size_bytes"] or digest != raw["sha256"]:
            raise ValueError(f"Corpus integrity check failed for {path}")
        items.append(
            CorpusItem(
                id=raw["id"],
                path=path,
                category=raw["category"],
                split=raw["split"],
                size_bytes=size,
                sha256=digest,
                dataset=str(raw.get("dataset", "")),
                license_spdx=str(raw.get("license_spdx", "")),
                source_url=str(raw.get("source_url", "")),
                provenance=dict(raw.get("provenance", {})),
            )
        )
    if not items:
        raise ValueError(f"No corpus items matched splits: {sorted(wanted)}")
    return items
