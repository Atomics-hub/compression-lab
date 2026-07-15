from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from .codecs import all_codecs, resolve_codecs
from .corpus import freeze_holdout, generate_corpus, import_corpus, verify_holdout
from .gates import evaluate_candidate, load_json, write_gate_report
from .runner import run_benchmark


DEFAULT_CODECS = "store,adaptive-v0,adaptive-v1,gzip-1,gzip-6,gzip-9,bz2-1,bz2-9,lzma-0,lzma-6,lzma-9"


def _csv_strings(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _csv_floats(value: str) -> List[float]:
    try:
        return [float(item) for item in _csv_strings(value)]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compression-lab",
        description="Reproducible lossless-compression benchmark harness",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-corpus", help="generate a deterministic smoke corpus")
    init.add_argument("--output", type=Path, required=True)
    init.add_argument("--size-scale", type=float, default=1.0)
    init.add_argument("--seed", type=int, default=20260715)

    ingest = subparsers.add_parser(
        "import-corpus", help="import licensed files with required provenance"
    )
    ingest.add_argument("--source", type=Path, required=True)
    ingest.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--category", required=True)
    ingest.add_argument("--split", choices=("train", "validation", "holdout"), required=True)
    ingest.add_argument("--dataset", required=True)
    ingest.add_argument("--license-spdx", required=True)
    ingest.add_argument("--source-url", required=True)

    freeze = subparsers.add_parser(
        "freeze-holdout", help="write a cryptographic commitment for a private holdout"
    )
    freeze.add_argument("--corpus", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--overwrite", action="store_true")

    verify = subparsers.add_parser(
        "verify-holdout", help="verify a private holdout against its frozen commitment"
    )
    verify.add_argument("--corpus", type=Path, required=True)
    verify.add_argument("--lock", type=Path, required=True)

    subparsers.add_parser("list-codecs", help="list built-in codec adapters")

    run = subparsers.add_parser("run", help="run a benchmark")
    run.add_argument("--corpus", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--codecs", default=DEFAULT_CODECS)
    run.add_argument("--splits", default="validation")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--warmups", type=int, default=1)
    run.add_argument("--bandwidths", type=_csv_floats, default=[10.0, 100.0, 1000.0])
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--keep-work", action="store_true")

    evaluate = subparsers.add_parser("evaluate", help="evaluate a candidate against gates")
    evaluate.add_argument("--results", type=Path, required=True)
    evaluate.add_argument("--gates", type=Path, required=True)
    evaluate.add_argument("--candidate", required=True)
    evaluate.add_argument("--bandwidth", type=float, default=100.0)
    evaluate.add_argument("--output", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init-corpus":
        manifest = generate_corpus(args.output, args.size_scale, args.seed)
        print(manifest)
        return 0
    if args.command == "import-corpus":
        manifest = import_corpus(
            args.source,
            args.output,
            args.category,
            args.split,
            args.dataset,
            args.license_spdx,
            args.source_url,
        )
        print(manifest)
        return 0
    if args.command == "freeze-holdout":
        print(freeze_holdout(args.corpus, args.output, args.overwrite))
        return 0
    if args.command == "verify-holdout":
        valid = verify_holdout(args.corpus, args.lock)
        print("verified" if valid else "mismatch")
        return 0 if valid else 2
    if args.command == "list-codecs":
        print(json.dumps([codec.__dict__ for codec in all_codecs()], indent=2))
        return 0
    if args.command == "run":
        codecs = resolve_codecs(_csv_strings(args.codecs))
        benchmark = run_benchmark(
            corpus_root=args.corpus,
            output_dir=args.output,
            codecs=codecs,
            repetitions=args.repetitions,
            warmups=args.warmups,
            splits=_csv_strings(args.splits),
            bandwidths_mbps=args.bandwidths,
            timeout_seconds=args.timeout,
            keep_work=args.keep_work,
        )
        print(args.output / "report.md")
        return 1 if benchmark.failures else 0
    if args.command == "evaluate":
        report = evaluate_candidate(
            load_json(args.results),
            load_json(args.gates),
            args.candidate,
            args.bandwidth,
        )
        write_gate_report(report, args.output)
        print(args.output)
        return 0 if report["passed"] else 2
    raise AssertionError(args.command)
