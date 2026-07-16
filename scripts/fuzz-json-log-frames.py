#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from compresslab.json_log_codec import compress, decompress  # noqa: E402
from compresslab.native import json_columnar_reassemble  # noqa: E402


def expect_rejection(data: bytes, max_output_size: int) -> None:
    try:
        restored = decompress(data, max_output_size=max_output_size)
    except ValueError:
        return
    raise AssertionError(
        f"corrupted JLS2 frame decoded unexpectedly ({len(restored)} bytes)"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--mutations", type=int, default=2000)
    parser.add_argument("--random-frames", type=int, default=2000)
    parser.add_argument("--roundtrips", type=int, default=250)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.mutations, args.random_frames, args.roundtrips) < 1:
        raise ValueError("fuzz counts must be positive")
    rng = random.Random(args.seed)

    source = b"".join(
        f'{{"id":{index},"event":"tick","value":"v-{index % 7}"}}\n'.encode()
        for index in range(64)
    )
    valid, _ = compress(source, segment_size=256)
    truncations = 0
    for length in range(len(valid)):
        expect_rejection(valid[:length], len(source))
        truncations += 1

    single_bit_mutations = 0
    for index in range(len(valid)):
        for bit in range(8):
            candidate = bytearray(valid)
            candidate[index] ^= 1 << bit
            expect_rejection(bytes(candidate), len(source))
            single_bit_mutations += 1

    mutations = 0
    for _ in range(args.mutations):
        candidate = bytearray(valid)
        index = rng.randrange(len(candidate))
        candidate[index] ^= 1 << rng.randrange(8)
        expect_rejection(bytes(candidate), len(source))
        mutations += 1

    random_frames = 0
    for _ in range(args.random_frames):
        random_frame = rng.randbytes(rng.randrange(0, 1025))
        expect_rejection(random_frame, 1024 * 1024)
        random_frames += 1

    raw_transform_rejections = 0
    for _ in range(args.random_frames):
        random_transform = rng.randbytes(rng.randrange(0, 1025))
        try:
            json_columnar_reassemble(
                random_transform,
                rng.randrange(0, 4097),
            )
        except ValueError:
            raw_transform_rejections += 1
            continue
        raise AssertionError("random JCT1 transform decoded unexpectedly")

    roundtrips = 0
    for _ in range(args.roundtrips):
        size = rng.randrange(0, 16 * 1024)
        if rng.randrange(2):
            candidate_source = rng.randbytes(size)
        else:
            rows = []
            total = 0
            index = 0
            while total < size:
                row = (
                    f'{{"id":{index},"event":"event-{index % 11}",'
                    f'"value":"{"x" * (index % 31)}"}}\n'
                ).encode()
                rows.append(row)
                total += len(row)
                index += 1
            candidate_source = b"".join(rows)[:size]
        encoded, _ = compress(candidate_source, segment_size=1024)
        if decompress(encoded, max_output_size=len(candidate_source)) != (
            candidate_source
        ):
            raise AssertionError("random JLS2 round trip failed")
        roundtrips += 1

    payload = {
        "schema_version": 1,
        "claim_ceiling": "deterministic local fuzz evidence only",
        "seed": args.seed,
        "valid_frame_bytes": len(valid),
        "truncations_rejected": truncations,
        "single_bit_mutations_rejected": single_bit_mutations,
        "mutations_rejected": mutations,
        "random_frames_rejected": random_frames,
        "random_raw_transforms_rejected": raw_transform_rejections,
        "random_roundtrips": roundtrips,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
