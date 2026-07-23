#!/usr/bin/env python3
"""Deterministic synthetic NDJSON emitter for the moonshot cycle-1 prescreen.

Development-only prescreen infrastructure (Lane 2, the Pareto moonshot). It
emits parameterized NDJSON whose regime we control, so the harness can predict
which mechanism should win each regime as its own sanity check. Output is a
pure function of ``--seed`` and the regime parameters; a companion receipt pins
the generator version, seed, parameters, and the SHA-256 of the emitted bytes.

This generator never reads any corpus, licensed development item, or network
resource. It only writes synthetic bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

GENERATOR_VERSION = "moon-synthetic-corpus-v1"

# A small fixed template vocabulary. Real records interpolate these skeletons,
# so template_count controls how many distinct record shapes appear.
TEMPLATES = (
    '{{"ts":"{ts}","level":"{level}","session":"{session}","event":"login","user":"{value}"}}',
    '{{"ts":"{ts}","level":"{level}","session":"{session}","event":"request",'
    '"path":"/api/{value}","status":{status}}}',
    '{{"ts":"{ts}","level":"{level}","session":"{session}","event":"metric",'
    '"name":"{value}","count":{status}}}',
    '{{"ts":"{ts}","level":"{level}","session":"{session}","event":"error","code":"{value}"}}',
    '{{"ts":"{ts}","level":"{level}","session":"{session}","event":"heartbeat","ok":true}}',
)
LEVELS = ("debug", "info", "warn", "error")


class Rng:
    """A tiny deterministic SplitMix64. Kept in-file so the corpus is a pure
    function of the seed with no dependency on the platform RNG."""

    __slots__ = ("state",)

    _MASK = (1 << 64) - 1

    def __init__(self, seed: int) -> None:
        self.state = seed & self._MASK

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self._MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self._MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self._MASK
        return z ^ (z >> 31)

    def below(self, bound: int) -> int:
        if bound <= 0:
            raise ValueError("bound must be positive")
        return self.next_u64() % bound


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit deterministic synthetic NDJSON for the moonshot prescreen.",
    )
    parser.add_argument("--seed", type=int, required=True, help="deterministic seed")
    parser.add_argument(
        "--records", type=int, default=1000, help="number of NDJSON records to emit"
    )
    parser.add_argument(
        "--record-size",
        type=int,
        default=160,
        help="approximate target size in bytes for the variable value field",
    )
    parser.add_argument(
        "--key-cardinality",
        type=int,
        default=64,
        help="number of distinct session keys",
    )
    parser.add_argument(
        "--value-cardinality",
        type=int,
        default=256,
        help="number of distinct value strings in the pool",
    )
    parser.add_argument(
        "--session-concurrency",
        type=int,
        default=16,
        help="number of sessions active in the rolling window",
    )
    parser.add_argument(
        "--duplication-factor",
        type=float,
        default=1.0,
        help="expected number of times each emitted record recurs (>= 1.0)",
    )
    parser.add_argument(
        "--timestamp-monotonicity",
        type=float,
        default=1.0,
        help="fraction of records whose timestamp does not step backward [0, 1]",
    )
    parser.add_argument(
        "--template-count",
        type=int,
        default=len(TEMPLATES),
        help=f"number of record templates to use (1..{len(TEMPLATES)})",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="path for the emitted NDJSON"
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        required=True,
        help="path for the content-derived receipt JSON",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing outputs"
    )
    return parser.parse_args(argv)


def validate(args: argparse.Namespace) -> None:
    if args.records < 0:
        raise ValueError("--records must be non-negative")
    if args.record_size < 1:
        raise ValueError("--record-size must be positive")
    if args.key_cardinality < 1:
        raise ValueError("--key-cardinality must be positive")
    if args.value_cardinality < 1:
        raise ValueError("--value-cardinality must be positive")
    if args.session_concurrency < 1:
        raise ValueError("--session-concurrency must be positive")
    if args.duplication_factor < 1.0:
        raise ValueError("--duplication-factor must be at least 1.0")
    if not 0.0 <= args.timestamp_monotonicity <= 1.0:
        raise ValueError("--timestamp-monotonicity must be in [0, 1]")
    if not 1 <= args.template_count <= len(TEMPLATES):
        raise ValueError(f"--template-count must be in 1..{len(TEMPLATES)}")


def value_pool(rng: Rng, cardinality: int, size: int) -> list[str]:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    pool: list[str] = []
    for _ in range(cardinality):
        length = max(1, size)
        chars = [alphabet[rng.below(len(alphabet))] for _ in range(length)]
        pool.append("".join(chars))
    return pool


def format_timestamp(step: int) -> str:
    minute = (step // 60) % 60
    second = step % 60
    hour = (step // 3600) % 24
    return f"2026-07-22T{hour:02d}:{minute:02d}:{second:02d}Z"


def render(
    template: str, *, ts: str, level: str, session: str, value: str, status: int
) -> str:
    return template.format(
        ts=ts, level=level, session=session, value=value, status=status
    )


def emit(args: argparse.Namespace) -> bytes:
    rng = Rng(args.seed)
    values = value_pool(rng, args.value_cardinality, args.record_size)
    sessions = [f"s{index:06x}" for index in range(args.key_cardinality)]
    templates = TEMPLATES[: args.template_count]

    lines: list[str] = []
    clock = 0
    emitted = 0
    duplication = max(1, round(args.duplication_factor))
    target = args.records
    while emitted < target:
        # Build one fresh record, then repeat it `duplication` times (bounded by
        # the remaining budget) to realize the duplication factor.
        if rng.below(1000) < round(args.timestamp_monotonicity * 1000):
            clock += 1
        else:
            clock = max(0, clock - rng.below(4))
        template = templates[rng.below(len(templates))]
        session = sessions[rng.below(args.session_concurrency) % len(sessions)]
        value = values[rng.below(len(values))]
        level = LEVELS[rng.below(len(LEVELS))]
        status = 200 + rng.below(5)
        record = render(
            template,
            ts=format_timestamp(clock),
            level=level,
            session=session,
            value=value,
            status=status,
        )
        for _ in range(duplication):
            if emitted >= target:
                break
            lines.append(record)
            emitted += 1
    payload = "".join(line + "\n" for line in lines)
    return payload.encode("utf-8")


def build_receipt(args: argparse.Namespace, data: bytes) -> dict[str, object]:
    return {
        "schema": "moon-synthetic-corpus-receipt-v1",
        "generator_version": GENERATOR_VERSION,
        "evidence_stage": "development_only_prescreen",
        "seed": args.seed,
        "parameters": {
            "records": args.records,
            "record_size": args.record_size,
            "key_cardinality": args.key_cardinality,
            "value_cardinality": args.value_cardinality,
            "session_concurrency": args.session_concurrency,
            "duplication_factor": args.duplication_factor,
            "timestamp_monotonicity": args.timestamp_monotonicity,
            "template_count": args.template_count,
        },
        "emitted_bytes": len(data),
        "emitted_sha256": hashlib.sha256(data).hexdigest(),
    }


def receipt_bytes(receipt: dict[str, object]) -> bytes:
    return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_output(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path} without --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    validate(args)
    data = emit(args)
    receipt = build_receipt(args, data)
    write_output(args.output, data, args.force)
    write_output(args.receipt_out, receipt_bytes(receipt), args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
