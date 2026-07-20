#!/usr/bin/env python3
"""Run the authorized synthetic-only AR5/NUM-R exactness preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import struct

from compresslab.numeric_ar5_numr import compress, decompress, inspect


def packed(values, code: str, endian: str) -> bytes:
    prefix = "<" if endian == "little" else ">"
    return b"".join(struct.pack(prefix + code, value) for value in values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42330)
    args = parser.parse_args()
    generator = random.Random(args.seed)
    cases = [
        (
            "float64-decimal-origin",
            packed([round(math.sin(index / 10), 3) for index in range(1024)], "d", "little"),
            "float64",
            "little",
        ),
        (
            "float32-special-words",
            b"".join(
                word.to_bytes(4, "big")
                for word in (0, 1 << 31, 1, 0x7F800000, 0x7FC12345, 0x7F812345)
            ),
            "float32",
            "big",
        ),
        (
            "int64-byte-planes",
            packed(range(1024), "q", "little"),
            "int64",
            "little",
        ),
        (
            "float64-xor-front-bit",
            packed([1.25] * 5, "d", "little"),
            "float64",
            "little",
        ),
        (
            "uint64-incompressible",
            generator.randbytes(8 * 1024),
            "uint64",
            "little",
        ),
    ]
    receipts = []
    for name, source, dtype, endianness in cases:
        shape = (len(source) // (4 if dtype == "float32" else 8),)
        first = compress(
            source,
            dtype=dtype,
            endianness=endianness,
            shape=shape,
            layout="one_dimensional_ordered_series",
        )
        second = compress(
            source,
            dtype=dtype,
            endianness=endianness,
            shape=shape,
            layout="one_dimensional_ordered_series",
        )
        if first != second or decompress(first, max_output_size=len(source)) != source:
            raise ValueError(f"synthetic exactness or determinism failed: {name}")
        corrupted = bytearray(first)
        corrupted[len(corrupted) // 2] ^= 1
        try:
            decompress(bytes(corrupted))
        except ValueError:
            pass
        else:
            raise ValueError(f"synthetic corruption was accepted: {name}")
        details = inspect(first)
        receipts.append(
            {
                "name": name,
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "frame_sha256": hashlib.sha256(first).hexdigest(),
                "exact": True,
                "deterministic": True,
                "corruption_rejected": True,
                "accounting": details,
            }
        )
    result = {
        "schema_version": 1,
        "name": "numeric-ar5-numr-synthetic-preflight-v1",
        "seed": args.seed,
        "synthetic_cases": receipts,
        "corpus_accessed": False,
        "benchmark_measurement": False,
        "validation_accessed": False,
        "private_holdout_accessed": False,
        "claim_ceiling": "synthetic exactness, determinism, corruption rejection, and complete-byte accounting only",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
