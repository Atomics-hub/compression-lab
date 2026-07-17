#!/usr/bin/env python3
"""Exercise manifest-bound benchmark selection and write a compact receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from compresslab.cli import build_parser
from compresslab.codecs import resolve_codecs
from compresslab.benchmark_runner import run_benchmark


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def corpus_item(item_id: str, path: str, data: bytes) -> Dict[str, Any]:
    return {
        "id": item_id,
        "path": path,
        "category": "manifest-binding-fixture",
        "split": "validation",
        "size_bytes": len(data),
        "sha256": sha256_bytes(data),
        "dataset": "compression-lab-manifest-binding-fixture-v1",
        "license_spdx": "LicenseRef-CompressionLab-Synthetic",
        "source_url": "",
        "provenance": {"generator": "audit-benchmark-manifest-binding.py"},
    }


def check(name: str, passed: bool, evidence: str) -> Dict[str, Any]:
    if not passed:
        raise AssertionError(f"{name}: {evidence}")
    return {"check": name, "status": "pass", "evidence": evidence}


def audit(output: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="compression-lab-manifest-audit-") as raw:
        root = Path(raw)
        corpus = root / "corpus"
        corpus.mkdir()
        first = b"alpha-record\n" * 32
        second = b"beta-record\n" * 32
        (corpus / "first.bin").write_bytes(first)
        (corpus / "second.bin").write_bytes(second)
        first_item = corpus_item("fixture-alpha", "first.bin", first)
        second_item = corpus_item("fixture-beta", "second.bin", second)
        default_payload = {
            "schema_version": 2,
            "generator": "compression-lab-manifest-binding-audit",
            "items": [first_item, second_item],
        }
        projected_payload = {**default_payload, "items": [second_item]}
        default_manifest = corpus / "manifest.json"
        projected_manifest = corpus / "scoring-manifest.json"
        write_json(default_manifest, default_payload)
        write_json(projected_manifest, projected_payload)

        explicit = run_benchmark(
            corpus,
            root / "explicit-run",
            resolve_codecs(["store"]),
            repetitions=1,
            warmups=0,
            bandwidths_mbps=[100.0],
            bootstrap_samples=100,
            manifest_path=projected_manifest,
        )
        identity = explicit.config["corpus_manifest"]
        checks.append(
            check(
                "explicit manifest path honored",
                identity["path"] == str(projected_manifest.resolve()),
                f"name={Path(identity['path']).name}; exact_resolved_path=True",
            )
        )
        expected_sha256 = sha256_bytes(projected_manifest.read_bytes())
        checks.append(
            check(
                "exact manifest SHA-256 recorded",
                identity["sha256"] == expected_sha256,
                expected_sha256,
            )
        )
        explicit_ids = [row["id"] for row in explicit.corpus]
        checks.append(
            check(
                "sibling manifest ignored",
                explicit_ids == ["fixture-beta"],
                f"selected={explicit_ids}; sibling_has=fixture-alpha,fixture-beta",
            )
        )
        checks.append(
            check(
                "selected item identities recorded",
                identity["selected_item_ids"] == explicit_ids
                and identity["selected_item_count"] == len(explicit_ids),
                f"count={identity['selected_item_count']}; ids={explicit_ids}",
            )
        )

        default = run_benchmark(
            corpus,
            root / "default-run",
            resolve_codecs(["store"]),
            repetitions=1,
            warmups=0,
            bandwidths_mbps=[100.0],
            bootstrap_samples=100,
        )
        default_ids = [row["id"] for row in default.corpus]
        checks.append(
            check(
                "manifest.json compatibility default retained",
                default_ids == ["fixture-alpha", "fixture-beta"],
                f"selected={default_ids}",
            )
        )

        invalid_payload = json.loads(projected_manifest.read_text(encoding="utf-8"))
        invalid_payload["items"][0]["sha256"] = "0" * 64
        invalid_manifest = corpus / "invalid-manifest.json"
        write_json(invalid_manifest, invalid_payload)
        invalid_output = root / "invalid-run"
        rejected = False
        try:
            run_benchmark(
                corpus,
                invalid_output,
                resolve_codecs(["store"]),
                repetitions=1,
                warmups=0,
                manifest_path=invalid_manifest,
            )
        except ValueError as exc:
            rejected = "Corpus integrity check failed" in str(exc)
        checks.append(
            check(
                "invalid manifest rejected before output",
                rejected and not invalid_output.exists(),
                f"rejected={rejected}; output_exists={invalid_output.exists()}",
            )
        )

        parsed = build_parser().parse_args(
            [
                "run",
                "--corpus",
                str(corpus),
                "--manifest",
                str(projected_manifest),
                "--output",
                str(root / "cli-run"),
            ]
        )
        checks.append(
            check(
                "CLI exposes exact manifest selection",
                parsed.manifest == projected_manifest,
                "--manifest parsed as an exact Path",
            )
        )

        runner = explicit.config["runner"]
        digests_valid = all(
            re.fullmatch(r"[0-9a-f]{64}", str(runner.get(field, "")))
            for field in (
                "source_sha256",
                "legacy_runner_source_sha256",
                "corpus_loader_source_sha256",
            )
        )
        checks.append(
            check(
                "runner dependency digests recorded",
                runner.get("api_version") == 2 and digests_valid,
                f"api_version={runner.get('api_version')}",
            )
        )
        checks.append(
            check(
                "results schema identifies hardened semantics",
                explicit.schema_version == 5,
                f"schema_version={explicit.schema_version}",
            )
        )

    receipt = {
        "schema_version": 1,
        "gate": "benchmark-manifest-binding-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "checks": checks,
        "summary": {"passed": len(checks), "failed": 0, "total": len(checks)},
        "runner_identity": runner,
        "fixture_manifest_sha256": expected_sha256,
        "claim_ceiling": (
            "Proves exact manifest selection, integrity, and result provenance on a "
            "synthetic fixture only. It does not prove benchmark representativeness, "
            "compression speed, compression ratio, or state-of-the-art performance."
        ),
    }
    write_json(output, receipt)
    return receipt


def build_audit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/benchmark-manifest-binding-v1/receipt.json"),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_audit_parser().parse_args(argv)
    receipt = audit(args.output)
    print(
        f"{receipt['status']}: {receipt['summary']['passed']}/"
        f"{receipt['summary']['total']} checks; {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
