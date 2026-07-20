#!/usr/bin/env python3
"""Bounded deterministic WKC1 and AXWK2 fuzz harness."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import random
import sys
import tempfile
from types import ModuleType
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


TRANSFORM = load_script(
    "wk_c1_transform_for_fuzz",
    REPOSITORY / "scripts" / "text-source-wk-c1-transform.py",
)
RUNNER = load_script(
    "wk_c1_runner_for_fuzz",
    REPOSITORY / "scripts" / "benchmark-text-source-wk-c1-screen.py",
)
TOKENS = (
    b"plain",
    b"|=",
    b"[[link|label=value]]",
    b"<!-- {{protected}} -->",
    b"<nowiki>{{protected|x}}</nowiki>",
    b"{{T|a=one|two}}",
    b"{{T|nested={{U|x=y}}}}",
    b"{{{parameter|default}}}",
    b"{{unclosed|x",
    bytes(range(32)),
)


def payload_for(rng: random.Random, maximum_input_bytes: int) -> bytes:
    output = bytearray()
    while len(output) < maximum_input_bytes and rng.randrange(5):
        token = rng.choice(TOKENS)
        remaining = maximum_input_bytes - len(output)
        output.extend(token[:remaining])
    return bytes(output)


def fuzz(*, seed: int, iterations: int, maximum_input_bytes: int) -> dict[str, Any]:
    if not 0 <= iterations <= 10_000:
        raise ValueError("iterations must be between zero and 10000")
    if not 0 <= maximum_input_bytes <= 1024 * 1024:
        raise ValueError("maximum input must be between zero and 1 MiB")
    rng = random.Random(seed)
    mutations_rejected = 0
    roundtrips = 0
    with tempfile.TemporaryDirectory(prefix="wk-c1-fuzz-") as raw:
        root = Path(raw)
        for iteration in range(iterations):
            payload = payload_for(rng, maximum_input_bytes)
            for variant in RUNNER.VARIANTS:
                frame = TRANSFORM.encode(payload, variant)
                if TRANSFORM.decode(frame, len(payload)) != payload:
                    raise AssertionError("WKC1 fuzz roundtrip differs")
                roundtrips += 1
                if frame:
                    mutated = bytearray(frame)
                    mutated[rng.randrange(len(mutated))] ^= 1 << rng.randrange(8)
                    try:
                        restored = TRANSFORM.decode(bytes(mutated), len(payload))
                    except (IndexError, TRANSFORM.FormatError):
                        mutations_rejected += 1
                    else:
                        if restored != payload:
                            raise AssertionError("mutated WKC1 decoded to different bytes")

                source = root / f"source-{iteration}"
                backend = root / f"backend-{iteration}"
                artifact = root / f"artifact-{iteration}"
                extracted = root / f"extracted-{iteration}"
                source.write_bytes(payload)
                backend.write_bytes(frame)
                RUNNER.wrap_payload(variant, source, backend, artifact)
                mutated_artifact = bytearray(artifact.read_bytes())
                mutated_artifact[-1] ^= 1
                artifact.write_bytes(mutated_artifact)
                try:
                    RUNNER.unwrap_payload(
                        variant,
                        artifact,
                        extracted,
                        source_bytes=len(payload),
                        source_sha256=RUNNER.sha256_file(source),
                    )
                except ValueError:
                    mutations_rejected += 1
                else:
                    raise AssertionError("mutated AXWK2 payload was accepted")
    return {
        "seed": seed,
        "iterations": iterations,
        "maximum_input_bytes": maximum_input_bytes,
        "roundtrips": roundtrips,
        "mutations_rejected": mutations_rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260719)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--maximum-input-bytes", type=int, default=4096)
    args = parser.parse_args()
    try:
        result = fuzz(
            seed=args.seed,
            iterations=args.iterations,
            maximum_input_bytes=args.maximum_input_bytes,
        )
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"WK-C1 fuzz failed: {error}") from error
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
