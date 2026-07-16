#!/usr/bin/env python3
"""Seeded mutational fuzzer for the versioned public frame decoder."""

from __future__ import annotations

import argparse
import hashlib
import random
import struct

import compresslab
from compresslab.worker import _adaptive_compress, _adaptive_v2_compress


MAX_FUZZ_OUTPUT = 1024 * 1024
_ALLOWED_REJECTIONS = (OSError, RuntimeError, TypeError, ValueError)


def _seed_frames() -> list[bytes]:
    rng = random.Random(11)
    sources = [
        b"",
        b"fuzz-seed repeated_identifier\n" * 2_000,
        b"[" + b",\n".join(
            (
                b'{"identifier": "shared_value", "index": '
                + str(index).encode("ascii")
                + b"}"
            )
            for index in range(2_000)
        ) + b"]",
        b"".join(struct.pack("<I", index * 17) for index in range(16_384)),
        rng.randbytes(64 * 1024),
    ]
    current = [compresslab.compress(source) for source in sources]
    legacy = []
    for source in sources[1:]:
        legacy.append(_adaptive_compress(source, allow_transform=True)[0])
        legacy.append(_adaptive_v2_compress(source)[0])
    return current + legacy


def _mutate(rng: random.Random, seed: bytes) -> bytes:
    data = bytearray(seed)
    strategy = rng.randrange(7)
    if strategy == 0 and data:
        return bytes(data[: rng.randrange(len(data))])
    if strategy == 1 and data:
        for _ in range(rng.randint(1, min(8, len(data)))):
            index = rng.randrange(len(data))
            data[index] ^= 1 << rng.randrange(8)
    elif strategy == 2:
        index = rng.randrange(len(data) + 1)
        data[index:index] = rng.randbytes(rng.randrange(1, 33))
    elif strategy == 3 and data:
        start = rng.randrange(len(data))
        del data[start : start + rng.randrange(1, min(65, len(data) - start + 1))]
    elif strategy == 4:
        data.extend(rng.randbytes(rng.randrange(1, 65)))
    elif strategy == 5 and len(data) >= 14:
        data[6:14] = rng.randrange(MAX_FUZZ_OUTPUT * 2).to_bytes(8, "big")
    else:
        suffix = rng.randbytes(rng.randrange(0, 512))
        data = bytearray(
            struct.pack(
                ">4sBBQ32s",
                b"CLAB",
                rng.choice((1, 2, 3, 255)),
                rng.randrange(0, 10),
                rng.randrange(0, MAX_FUZZ_OUTPUT * 2),
                rng.randbytes(32),
            )
            + suffix
        )
    return bytes(data)


def run_fuzz(iterations: int, seed: int) -> tuple[int, int]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    rng = random.Random(seed)
    frames = _seed_frames()
    accepted = 0
    rejected = 0

    for frame in frames:
        restored = compresslab.decompress(frame, max_output_size=MAX_FUZZ_OUTPUT)
        info = compresslab.inspect_frame(frame)
        if hashlib.sha256(restored).hexdigest() != info.sha256:
            raise AssertionError("valid seed restored bytes with the wrong digest")
        accepted += 1

    for _ in range(iterations):
        frame = _mutate(rng, rng.choice(frames))
        try:
            restored = compresslab.decompress(
                frame, max_output_size=MAX_FUZZ_OUTPUT
            )
        except _ALLOWED_REJECTIONS:
            rejected += 1
            continue
        info = compresslab.inspect_frame(frame)
        if len(restored) != info.original_size:
            raise AssertionError("decoder returned the wrong output length")
        if hashlib.sha256(restored).hexdigest() != info.sha256:
            raise AssertionError("decoder returned bytes with the wrong digest")
        accepted += 1
    return accepted, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260716)
    args = parser.parse_args()
    accepted, rejected = run_fuzz(args.iterations, args.seed)
    print(
        f"frame fuzz complete: accepted={accepted} rejected={rejected} "
        f"iterations={args.iterations} seed={args.seed}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
