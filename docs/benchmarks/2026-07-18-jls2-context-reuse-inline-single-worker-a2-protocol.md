# JLS2 A2 reusable-context plus inline-single-worker protocol

## Purpose

Test the isolated marginal value of removing the redundant inner scoped thread
when `decompress_streams` has computed exactly one worker. The A1 product at
commit `131547f35747cc0ff9dedbdef66d8a9516a7464f` already reuses one
`zstd::bulk::Decompressor` per stream worker. A2 keeps that implementation and
changes only where the existing one-worker body executes.

This experiment is frozen before any A2 candidate code or measurement. It is
development-only operational evidence. The retained CLUE-LDS public-validation
no-pass is immutable; its two consumed ranges must not be acquired,
reconstructed, decoded, or rescored. The private holdout remains sealed.

## Exact A1 baseline

The baseline is the complete A1 candidate commit
`131547f35747cc0ff9dedbdef66d8a9516a7464f`. The baseline binary must be built
from a detached worktree at that exact commit. Comparing against an earlier
pre-context-reuse implementation is prohibited because it would confound the
A1 context-reuse effect with the A2 inline-execution effect.

The A2 benchmark imports the frozen A1 runner
`scripts/benchmark-jls2-context-reuse.py` only after verifying its SHA-256 is
`d8073d8c96e923fb88689be565051c1f03c0a362c2c1e28c0000dbc14e632f96`.
This binds A2 to the repaired Linux fixture preflight and schedule used by A1.
The imported native measurement helper and development corpus manifest are
also pinned by SHA-256 in the A2 runner and must not drift.

## Frozen A2 change

The A2 candidate may change only `native/src/jls2.rs`, and only the
`decompress_streams` execution path after its existing `workers` computation:

- when `workers == 1`, execute the existing worker-zero body inline on the
  calling thread;
- create one reusable Zstandard decompressor, visit every stream in the same
  order, preserve every existing error and decoded-output check, and place the
  restored streams into the same result slots; and
- when `workers > 1`, retain the A1 scoped-worker implementation unchanged.

The inline path eliminates only the redundant inner `thread::scope` and
single `scope.spawn`. It must not change the outer segment workers, segment
batching, channel-worker-limit computation, worker-count computation,
round-robin assignment, stream or segment order, allocation strategy, byte
format, encoder, decoder CLI, selector, integrity validation, output
publication, error text, or corruption behavior. No declared-size-aware
batching, adaptive scheduling, streaming reassembly, or other memory change
belongs to A2.

## Frozen inputs and identities

Run on GitHub-hosted `ubuntu-22.04`, where `wait4` measures cold-child RSS and
Linux KiB values are converted to bytes.

Reuse the complete A1 development fixture contract without modification:

1. the three licensed CLUE-LDS development ranges pinned by size and SHA-256 in
   `config/clue-json-log-corpus-v1.json`; and
2. the generated `jls2-context-stress-256` fixture containing exactly 21,800
   compact NDJSON records with the ordered keys `k000` through `k255` and the
   one-digit value `(record_index + key_index) mod 10`.

Generate each complete JLS2 fixture twice on the Linux measurement host with
the unchanged encoder. Require the two generated archives for an input to have
identical complete size and SHA-256, retain one, and supply that exact frame to
both binaries. A frame hash from another operating system is not an eligible
invariant. Record source/frame sizes and SHA-256, commands, parent wall time,
cold-child peak RSS, restored-output identity, host, compiler, candidate and
baseline commits, and binary SHA-256.

The stress fixture is operational memory evidence only. It is not corpus or
compression-ratio evidence. Neither consumed public-validation input nor any
private-holdout byte is eligible for this experiment.

## Frozen schedule

- one discarded warmup for every input and binary;
- seven measured rounds;
- the exact A1 alternating baseline/candidate order per input and round;
- a fresh process and fresh destination for every decode;
- parent wall time includes startup, complete file I/O, integrity validation,
  and atomic output publication; and
- every restored output is checked outside the timed interval for exact size
  and SHA-256.

This is 8 warmup plus 56 measured decodes, or 64 scheduled exact round trips.

## Immutable A2 selection gates

The A2 candidate passes only if all are true:

1. all 64 scheduled round trips are exact;
2. both binaries receive byte-identical complete JLS2 frames;
3. corruption and malformed-input unit tests remain green;
4. candidate peak RSS is at most 448 MiB on every input, preserving 64 MiB of
   headroom below the product boundary;
5. candidate peak RSS on `jls2-context-stress-256` is at least 5% below exact
   A1. This is the frozen minimum material marginal reduction for A2;
6. candidate peak RSS is no higher than A1 on any CLUE development family;
7. candidate median aggregate throughput is at least 95% of A1;
8. every candidate family median is at least 250 MB/s and every candidate
   aggregate measured round is at least 225 MB/s; and
9. candidate aggregate coefficient of variation is at most 20%.

Failure of the material stress-memory gate rejects A2 even if it remains under
448 MiB or improves speed. Failure caused solely by a noisy hosted-speed gate
may be repeated once on a different clean hosted runner with the exact same
commits, frames, schedule, and thresholds. No input or threshold may change.

## Decision boundary

A pass retains A1 context reuse plus the inline-one-worker path for a separately
frozen future validation gate. A failure retains exact A1 and makes the next
eligible memory experiment separately frozen declared-size-aware native
batching. Either decision leaves the consumed public-validation no-pass
unchanged and cannot authorize a rerun of those ranges.

Claim ceiling: **development-only decoder-memory evidence.** It cannot support
public-validation, private-holdout, independent-reproduction, universal,
market-leading, world-best, or state-of-the-art language.
