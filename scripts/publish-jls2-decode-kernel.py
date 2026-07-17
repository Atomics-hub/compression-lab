#!/usr/bin/env python3
"""Publish the development-only JLS2 decode-kernel evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
EXPECTED_BASE = "493f6ac5a2ea32c1d870698e38cb1732b6423c20"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def validate(
    ab: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]
) -> None:
    if not ab["passed"]:
        raise ValueError("A/B gate did not pass")
    if ab["base"]["commit"] != EXPECTED_BASE or baseline["git"]["commit"] != EXPECTED_BASE:
        raise ValueError("baseline commit mismatch")
    candidate_commit = ab["candidate"]["commit"]
    if candidate["git"]["commit"] != candidate_commit:
        raise ValueError("candidate commit mismatch")
    if any(
        state["dirty"]
        for state in (ab["base"], ab["candidate"], baseline["git"], candidate["git"])
    ):
        raise ValueError("evidence includes a dirty repository")
    if not candidate["passed"]:
        raise ValueError("candidate complete-product gate did not pass")
    if baseline["passed"]:
        raise ValueError("baseline complete-product gate unexpectedly passed")
    if baseline["aggregate"]["encoded_bytes"] != candidate["aggregate"]["encoded_bytes"]:
        raise ValueError("complete-product encoded byte count changed")
    baseline_rows = {row["family"]: row for row in baseline["rows"]}
    for row in candidate["rows"]:
        before = baseline_rows[row["family"]]
        if (row["encoded_bytes"], row["encoded_sha256"]) != (
            before["encoded_bytes"],
            before["encoded_sha256"],
        ):
            raise ValueError(f"encoded fixture changed: {row['family']}")
        if not row["roundtrip_verified"]:
            raise ValueError(f"candidate round trip failed: {row['family']}")


def render(
    ab: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]
) -> str:
    aggregate = ab["summary"]["aggregate"]
    before_product = baseline["aggregate"]
    after_product = candidate["aggregate"]
    product_improvement = (
        after_product["decompression_mbps"]
        / before_product["decompression_mbps"]
        - 1
    ) * 100
    lines = [
        "# JLS2 decode-kernel development gate",
        "",
        "**Result: passed.** The optimized decoder preserved every compressed byte and exact round trip. In seven alternating A/B rounds, median aggregate byte-API decode speed improved **{:.2f}%**, and the candidate exceeded 250 MB/s in **7/7** rounds.".format(
            aggregate["median_paired_improvement_percent"]
        ),
        "",
        "## Before and after",
        "",
        "| Measurement | Baseline | Candidate | Change | Result |",
        "| --- | ---: | ---: | ---: | --- |",
        "| Alternating byte API, median aggregate | {:.2f} MB/s | {:.2f} MB/s | +{:.2f}% paired median | ✅ 7/7 candidate rounds ≥250 MB/s |".format(
            aggregate["median_baseline_mbps"],
            aggregate["median_candidate_mbps"],
            aggregate["median_paired_improvement_percent"],
        ),
        "| Complete file product, aggregate | {:.2f} MB/s | {:.2f} MB/s | +{:.2f}% | ✅ candidate gate passed |".format(
            before_product["decompression_mbps"],
            after_product["decompression_mbps"],
            product_improvement,
        ),
        "| Complete encoded bytes | {:,} | {:,} | unchanged | ✅ exact accepted frames |".format(
            before_product["encoded_bytes"], after_product["encoded_bytes"]
        ),
        "",
        "The alternating benchmark isolates the in-memory decoder and alternates which build runs first. The complete-product benchmark separately includes file I/O and the public experimental API.",
        "",
        "## Family A/B chart",
        "",
        "| Development family | Baseline median | Candidate median | Median paired change | Paired range | Encoded bytes | Exact |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in ab["summary"]["families"]:
        lines.append(
            "| {} | {:.2f} MB/s | {:.2f} MB/s | {:+.2f}% | {:+.2f}% to {:+.2f}% | {:,} | ✅ |".format(
                row["family"],
                row["median_baseline_mbps"],
                row["median_candidate_mbps"],
                row["median_paired_improvement_percent"],
                row["minimum_paired_improvement_percent"],
                row["maximum_paired_improvement_percent"],
                row["encoded_bytes"],
            )
        )
    lines.extend(
        [
            "",
            "## Complete-product gate",
            "",
            "| Gate | Baseline | Candidate |",
            "| --- | --- | --- |",
        ]
    )
    for gate, passed in candidate["gate_results"].items():
        baseline_passed = baseline["gate_results"][gate]
        lines.append(
            f"| {gate.replace('_', ' ')} | {'✅' if baseline_passed else '❌'} | {'✅' if passed else '❌'} |"
        )
    lines.extend(
        [
            "",
            "Compression code was unchanged. The compression-gate differences above are retained host-timing context and are not attributed to this decoder optimization.",
            "",
            "## Evidence boundary",
            "",
            f"- Base commit: `{ab['base']['commit']}`",
            f"- Candidate commit: `{ab['candidate']['commit']}`",
            f"- Manifest SHA-256: `{ab['manifest']['sha256']}`",
            f"- Source bytes: {ab['manifest']['source_bytes']:,}",
            f"- Schedule: {ab['settings']['rounds']} alternating rounds × {ab['settings']['iterations_per_family_per_round']} timed decodes per family per build",
            "- Timing: in-memory JLS2 byte API; internal payload and restored-byte SHA-256 checks included",
            "- Raw samples, fixture hashes, source hashes, native-library hashes, runtime, and exactness checks: [`ab-result.json`](ab-result.json)",
            "- Complete-product raw results: [`product-baseline.json`](product-baseline.json) and [`product-candidate.json`](product-candidate.json)",
            "",
            "Claim ceiling: **development-only decoder evidence on the existing Apache, HealthApp, HPC, Mac, and ZooKeeper families.** It is not a fresh unseen-corpus score and does not change the retained JLS2 public-validation failure. The public validation still shows JLS2 28.77% smaller than zstd-9 in aggregate, mixed against Brotli-11, with the old decoder missing its 250 MB/s gate. A fresh independently sourced corpus is required before claiming that the speed gate is solved out of sample.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ab", type=Path, required=True)
    parser.add_argument("--product-baseline", type=Path, required=True)
    parser.add_argument("--product-candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ab = load(args.ab)
    baseline = load(args.product_baseline)
    candidate = load(args.product_candidate)
    validate(ab, baseline, candidate)
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "ab-result.json": args.ab,
        "product-baseline.json": args.product_baseline,
        "product-candidate.json": args.product_candidate,
    }
    for name, source in artifacts.items():
        shutil.copyfile(source, args.output / name)
    write_text(args.output / "README.md", render(ab, baseline, candidate))
    artifact_sha256 = {
        name: sha256_file(args.output / name)
        for name in (*artifacts, "README.md")
    }
    receipt = {
        "schema_version": 1,
        "gate": "jls2-decode-kernel-development-v1",
        "status": "passed",
        "base_commit": ab["base"]["commit"],
        "candidate_commit": ab["candidate"]["commit"],
        "manifest_sha256": ab["manifest"]["sha256"],
        "source_bytes": ab["manifest"]["source_bytes"],
        "aggregate_byte_api": ab["summary"]["aggregate"],
        "aggregate_product": {
            "baseline_decompression_mbps": baseline["aggregate"]["decompression_mbps"],
            "candidate_decompression_mbps": candidate["aggregate"]["decompression_mbps"],
            "encoded_bytes_unchanged": baseline["aggregate"]["encoded_bytes"],
        },
        "candidate_product_gates": candidate["gate_results"],
        "artifact_sha256": artifact_sha256,
        "publisher_sha256": sha256_file(Path(__file__)),
        "claim_ceiling": ab["claim_ceiling"],
    }
    write_json(args.output / "receipt.json", receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
