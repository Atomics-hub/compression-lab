from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from ._constants import DEFAULT_MAX_OUTPUT_SIZE


DEFAULT_CODECS = "store,adaptive-v0,adaptive-v1,adaptive-v2,adaptive-v3,gzip-1,gzip-6,gzip-9,bz2-1,bz2-9,lzma-0,lzma-6,lzma-9"


def _csv_strings(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _csv_floats(value: str) -> list[float]:
    try:
        return [float(item) for item in _csv_strings(value)]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _byte_size(value: str):
    normalized = value.strip().lower().replace("_", "")
    if normalized in {"none", "unlimited"}:
        return None
    multipliers = {
        "": 1,
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "kib": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "mib": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
        "gib": 1024**3,
        "t": 1024**4,
        "tb": 1024**4,
        "tib": 1024**4,
    }
    number = normalized
    suffix = ""
    while number and number[-1].isalpha():
        suffix = number[-1] + suffix
        number = number[:-1]
    try:
        result = int(number) * multipliers[suffix]
    except (KeyError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"invalid byte size: {value}") from exc
    if result < 0:
        raise argparse.ArgumentTypeError("byte size cannot be negative")
    return result


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", help="input file, or - for standard input")
    parser.add_argument("-o", "--output", help="output file, or - for standard output")
    parser.add_argument("-f", "--force", action="store_true", help="replace output")


def _stream_input(path: str) -> bytes:
    return sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()


def _stream_output(path: str, data: bytes, overwrite: bool) -> None:
    if path == "-":
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        from .api import _atomic_write

        _atomic_write(Path(path), data, overwrite)


def _run_compress(args: argparse.Namespace) -> int:
    from .api import compress as compress_bytes
    from .api import compress_file, default_compressed_path

    output = args.output
    if output is None:
        output = "-" if args.input == "-" else str(default_compressed_path(args.input))
    if args.input != "-" and output != "-":
        result = compress_file(args.input, output, overwrite=args.force)
        print(result)
        return 0
    _stream_output(output, compress_bytes(_stream_input(args.input)), args.force)
    return 0


def _run_decompress(args: argparse.Namespace) -> int:
    from .api import decompress as decompress_bytes
    from .api import decompress_file, default_decompressed_path

    output = args.output
    if output is None:
        output = "-" if args.input == "-" else str(default_decompressed_path(args.input))
    if args.input != "-" and output != "-":
        result = decompress_file(
            args.input,
            output,
            overwrite=args.force,
            max_output_size=args.max_output_size,
        )
        print(result)
        return 0
    restored = decompress_bytes(
        _stream_input(args.input), max_output_size=args.max_output_size
    )
    _stream_output(output, restored, args.force)
    return 0


def _run_json_compress(args: argparse.Namespace) -> int:
    from .experimental import (
        compress_json_log_file,
        compress_json_logs,
        default_json_log_compressed_path,
    )

    if args.segment_size is None:
        raise ValueError("segment size cannot be unlimited")
    output = args.output
    if output is None:
        output = (
            "-"
            if args.input == "-"
            else str(default_json_log_compressed_path(args.input))
        )
    if args.input != "-" and output != "-":
        result = compress_json_log_file(
            args.input,
            output,
            overwrite=args.force,
            segment_size=args.segment_size,
        )
        print(result)
        return 0
    encoded = compress_json_logs(
        _stream_input(args.input),
        segment_size=args.segment_size,
    )
    _stream_output(output, encoded, args.force)
    return 0


def _run_json_decompress(args: argparse.Namespace) -> int:
    from .experimental import (
        decompress_json_log_file,
        decompress_json_logs,
        default_json_log_decompressed_path,
    )

    output = args.output
    if output is None:
        output = (
            "-"
            if args.input == "-"
            else str(default_json_log_decompressed_path(args.input))
        )
    if args.input != "-" and output != "-":
        result = decompress_json_log_file(
            args.input,
            output,
            overwrite=args.force,
            max_output_size=args.max_output_size,
        )
        print(result)
        return 0
    restored = decompress_json_logs(
        _stream_input(args.input),
        max_output_size=args.max_output_size,
    )
    _stream_output(output, restored, args.force)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compression-lab",
        description="Adaptive lossless compressor and reproducible benchmark lab",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compress_command = subparsers.add_parser(
        "compress", aliases=["c"], help="compress a file or standard input"
    )
    _add_output_arguments(compress_command)

    decompress_command = subparsers.add_parser(
        "decompress", aliases=["d"], help="decompress a .clab frame"
    )
    _add_output_arguments(decompress_command)
    decompress_command.add_argument(
        "--max-output-size",
        type=_byte_size,
        default=DEFAULT_MAX_OUTPUT_SIZE,
        metavar="SIZE",
        help="allocation safety limit (default: 2GiB; use unlimited to disable)",
    )

    info = subparsers.add_parser("info", help="inspect a frame without decoding it")
    info.add_argument("input", help="frame file, or - for standard input")

    json_compress = subparsers.add_parser(
        "json-compress",
        aliases=["jc"],
        help="compress JSON logs with the experimental JLS2 codec",
    )
    _add_output_arguments(json_compress)
    json_compress.add_argument(
        "--segment-size",
        type=_byte_size,
        default=16 * 1024 * 1024,
        metavar="SIZE",
        help="record-aligned segment target (default: 16MiB)",
    )

    json_decompress = subparsers.add_parser(
        "json-decompress",
        aliases=["jd"],
        help="decompress an experimental JLS2 frame",
    )
    _add_output_arguments(json_decompress)
    json_decompress.add_argument(
        "--max-output-size",
        type=_byte_size,
        default=DEFAULT_MAX_OUTPUT_SIZE,
        metavar="SIZE",
        help="allocation safety limit (default: 2GiB; use unlimited to disable)",
    )

    json_info = subparsers.add_parser(
        "json-info",
        help="inspect experimental JLS2 metadata without decoding",
    )
    json_info.add_argument("input", help="frame file, or - for standard input")

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
    run.add_argument(
        "--manifest",
        type=Path,
        help="exact corpus manifest to use (defaults to CORPUS/manifest.json)",
    )
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--codecs", default=DEFAULT_CODECS)
    run.add_argument("--splits", default="validation")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--warmups", type=int, default=1)
    run.add_argument("--bandwidths", type=_csv_floats, default=[10.0, 100.0, 1000.0])
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--keep-work", action="store_true")
    run.add_argument(
        "--execution-mode",
        choices=("cold-process", "persistent-worker"),
        default="cold-process",
    )
    run.add_argument("--order-seed", type=int, default=20260715)
    run.add_argument("--confidence-level", type=float, default=0.95)
    run.add_argument("--bootstrap-samples", type=int, default=2000)
    run.add_argument("--minimum-trial-time-ms", type=float, default=0.0)
    run.add_argument("--max-batch-iterations", type=int, default=4096)

    evaluate = subparsers.add_parser("evaluate", help="evaluate a candidate against gates")
    evaluate.add_argument("--results", type=Path, required=True)
    evaluate.add_argument("--gates", type=Path, required=True)
    evaluate.add_argument("--candidate", required=True)
    evaluate.add_argument("--bandwidth", type=float, default=100.0)
    evaluate.add_argument("--output", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"compress", "c"}:
        try:
            return _run_compress(args)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"compression-lab: {exc}", file=sys.stderr)
            return 2
    if args.command in {"decompress", "d"}:
        try:
            return _run_decompress(args)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"compression-lab: {exc}", file=sys.stderr)
            return 2
    if args.command == "info":
        from .api import inspect_frame

        try:
            info = inspect_frame(_stream_input(args.input))
        except (OSError, TypeError, ValueError) as exc:
            print(f"compression-lab: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(info.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command in {"json-compress", "jc"}:
        try:
            return _run_json_compress(args)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"compression-lab: {exc}", file=sys.stderr)
            return 2
    if args.command in {"json-decompress", "jd"}:
        try:
            return _run_json_decompress(args)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"compression-lab: {exc}", file=sys.stderr)
            return 2
    if args.command == "json-info":
        from .experimental import inspect_json_log_frame

        try:
            frame_info = inspect_json_log_frame(_stream_input(args.input))
        except (OSError, TypeError, ValueError) as exc:
            print(f"compression-lab: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(frame_info.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "init-corpus":
        from .corpus import generate_corpus

        manifest = generate_corpus(args.output, args.size_scale, args.seed)
        print(manifest)
        return 0
    if args.command == "import-corpus":
        from .corpus import import_corpus

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
        from .corpus import freeze_holdout

        print(freeze_holdout(args.corpus, args.output, args.overwrite))
        return 0
    if args.command == "verify-holdout":
        from .corpus import verify_holdout

        valid = verify_holdout(args.corpus, args.lock)
        print("verified" if valid else "mismatch")
        return 0 if valid else 2
    if args.command == "list-codecs":
        from .codecs import all_codecs, probe_codec_versions

        print(
            json.dumps(
                [codec.__dict__ for codec in probe_codec_versions(all_codecs())],
                indent=2,
            )
        )
        return 0
    if args.command == "run":
        from .benchmark_runner import run_benchmark
        from .codecs import resolve_codecs

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
            execution_mode=args.execution_mode,
            order_seed=args.order_seed,
            confidence_level=args.confidence_level,
            bootstrap_samples=args.bootstrap_samples,
            minimum_trial_time_ms=args.minimum_trial_time_ms,
            max_batch_iterations=args.max_batch_iterations,
            manifest_path=args.manifest,
        )
        print(args.output / "report.md")
        return 1 if benchmark.failures else 0
    if args.command == "evaluate":
        from .gates import evaluate_candidate, load_json, write_gate_report

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
