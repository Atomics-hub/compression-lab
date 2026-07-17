"""Manifest-bound benchmark runner for results schema version 5.

The version-4 runner remains frozen because historical public-validation
receipts bind its exact source digest. This module stages an exact named
manifest for that engine, verifies the observed corpus, and adds the stronger
provenance required by all future scores.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional, Sequence

from . import runner as legacy_runner
from .corpus import MANIFEST_NAME, load_corpus_manifest
from .models import BenchmarkRun, CodecSpec


RUNNER_API_VERSION = 2


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stage_manifest(
    source: Path, destination: Path, splits: Sequence[str]
) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    wanted = set(splits)
    staged_items = []
    for raw in payload["items"]:
        if raw["split"] not in wanted:
            continue
        item = dict(raw)
        item["path"] = str((source.parent / raw["path"]).resolve())
        staged_items.append(item)
    staged = {**payload, "items": staged_items}
    destination.write_text(
        json.dumps(staged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_benchmark(
    corpus_root: Path,
    output_dir: Path,
    codecs: Sequence[CodecSpec],
    repetitions: int = 3,
    warmups: int = 1,
    splits: Sequence[str] = ("validation",),
    bandwidths_mbps: Sequence[float] = (10.0, 100.0, 1000.0),
    timeout_seconds: float = 120.0,
    keep_work: bool = False,
    execution_mode: str = "cold-process",
    order_seed: int = 20260715,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2000,
    minimum_trial_time_ms: float = 0.0,
    max_batch_iterations: int = 4096,
    manifest_path: Optional[Path] = None,
) -> BenchmarkRun:
    """Run against exactly ``manifest_path`` and emit results schema version 5."""

    selected_manifest = (
        manifest_path if manifest_path is not None else corpus_root / MANIFEST_NAME
    ).resolve()
    manifest_sha256 = _hash(selected_manifest)
    expected_items = load_corpus_manifest(selected_manifest, splits)

    runner_source = Path(__file__).resolve()
    legacy_runner_source = Path(legacy_runner.__file__).resolve()
    corpus_loader_source = Path(load_corpus_manifest.__code__.co_filename).resolve()
    source_digests = {
        "source_sha256": _hash(runner_source),
        "legacy_runner_source_sha256": _hash(legacy_runner_source),
        "corpus_loader_source_sha256": _hash(corpus_loader_source),
    }

    with tempfile.TemporaryDirectory(prefix="compression-lab-manifest-stage-") as raw:
        staging_root = Path(raw)
        _stage_manifest(selected_manifest, staging_root / MANIFEST_NAME, splits)
        if _hash(selected_manifest) != manifest_sha256:
            raise ValueError(
                f"Corpus manifest changed while staging: {selected_manifest}"
            )
        run = legacy_runner.run_benchmark(
            corpus_root=staging_root,
            output_dir=output_dir,
            codecs=codecs,
            repetitions=repetitions,
            warmups=warmups,
            splits=splits,
            bandwidths_mbps=bandwidths_mbps,
            timeout_seconds=timeout_seconds,
            keep_work=keep_work,
            execution_mode=execution_mode,
            order_seed=order_seed,
            confidence_level=confidence_level,
            bootstrap_samples=bootstrap_samples,
            minimum_trial_time_ms=minimum_trial_time_ms,
            max_batch_iterations=max_batch_iterations,
        )

    expected_ids = [item.id for item in expected_items]
    observed_ids = [str(item["id"]) for item in run.corpus]
    if observed_ids != expected_ids:
        raise RuntimeError(
            "Benchmark corpus differs from the exact selected manifest: "
            f"expected {expected_ids}, observed {observed_ids}"
        )
    if _hash(selected_manifest) != manifest_sha256:
        raise RuntimeError(f"Corpus manifest changed during the run: {selected_manifest}")

    sources = {
        "source_sha256": _hash(runner_source),
        "legacy_runner_source_sha256": _hash(legacy_runner_source),
        "corpus_loader_source_sha256": _hash(corpus_loader_source),
    }
    if sources != source_digests:
        raise RuntimeError("Benchmark runner dependency source changed during the run")

    run.schema_version = 5
    provenance: Dict[str, Any] = {
        "runner": {"api_version": RUNNER_API_VERSION, **source_digests},
        "corpus_manifest": {
            "path": str(selected_manifest),
            "sha256": manifest_sha256,
            "selected_item_count": len(expected_ids),
            "selected_item_ids": expected_ids,
        },
    }
    run.config = {**provenance, **run.config}
    legacy_runner._write_outputs(run, output_dir)
    return run
