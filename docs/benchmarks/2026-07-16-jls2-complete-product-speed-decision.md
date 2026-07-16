# JLS2 complete-product speed decision

## Decision

Pass the complete-product development speed and memory gates on the accepted
JLS2 representation. Keep blind validation sealed until the independent
log-specific competitor gate is resolved.

The earlier failed local runs remain part of the record. They established the
need for byte-stable scheduling changes and showed that laptop load averages
were not sufficient to identify macOS background contention. The controlling
pass came from a fresh hosted runner and remains development evidence, not a
public throughput or state-of-the-art claim.

## Frozen gate

Protocol:
`docs/benchmarks/2026-07-16-jls2-complete-product-speed-protocol.md`

Required:

- at least five repetitions;
- start load at or below 1.0 per logical CPU;
- 75 MB/s compression on every family;
- 100 MB/s aggregate compression;
- 250 MB/s decompression on every family;
- exact accepted JLS2 bytes, determinism, and round-trip integrity.

## Initial complete-product run

Evidence: `runs/jls2-complete-product-quiet-development.json`

Commit: `b76aea9eae5fc389ccf04afa55d8432b9ddab383`

The run started at 0.566 normalized load. It retained exact accepted bytes,
deterministic frames, and exact round trips.

| Family | Compression MB/s | Decompression MB/s |
| --- | ---: | ---: |
| Apache | 82.32 | 257.07 |
| HealthApp | 74.85 | 232.03 |
| HPC | 109.35 | 182.83 |
| Mac | 108.55 | 215.86 |
| ZooKeeper | 108.65 | 248.00 |

Aggregate compression was 95.65 MB/s and aggregate decompression was
209.50 MB/s.

This was a near miss for compression and a clear failure for multi-segment
decode.

## Byte-stable optimizations

The next commits:

- decompressed the skeleton and value channels concurrently;
- reassembled JCT1 directly into the FFI destination instead of allocating and
  copying a second full output;
- added a bounded two-segment file-decode pipeline;
- computed the identical nested source hash once during candidate selection;
- skipped redundant nested-output hashing when the enclosing JLS2 stream
  verifies the complete restored output.

All accepted encoded sizes and SHA-256 values remained identical.

A same-host alternating diagnostic showed that two-segment file decode was:

- 2.03x faster on HealthApp;
- 1.50x faster on HPC;
- 1.39x faster on Mac.

This diagnostic establishes the direction of the change, not a publishable
rate.

## Compression scheduling and single-segment decode

Commit `799db691f25ecb37c03a3713dac12465ae9aba5c` additionally:

- compressed the JSON-column skeleton and all value channels in one bounded
  stream batch;
- compressed at most two independent JLS2 segments concurrently while
  preserving source order;
- retained the complete direct-Zstandard fallback comparison for every
  segment;
- avoided thread-pool creation for a one-segment file decode;
- froze both compression and decompression pipelines at two in-flight
  segments.

The frame representation did not change. Every accepted encoded size and
SHA-256 remained exact.

## Optimized eligible run

Evidence: `runs/jls2-complete-product-quiet-optimized-v2.json`

Commit: `0855477b2bd48bd6c1a79ccd0cf963f3da126a4a`

The guard used a stricter 0.70 load/core wait for five consecutive samples.
The benchmark started at 0.644 and remained at or below 0.766 normalized load.

| Family | Compression MB/s | Decompression MB/s |
| --- | ---: | ---: |
| Apache | 73.06 | 172.93 |
| HealthApp | 59.23 | 254.63 |
| HPC | 79.41 | 273.45 |
| Mac | 68.30 | 174.61 |
| ZooKeeper | 40.15 | 210.59 |

Aggregate compression was 65.50 MB/s and aggregate decompression was
229.14 MB/s.

HealthApp and HPC now passed the decode gate, but the full gate failed. Sample
times on the same operation varied by up to several multiples across local
runs even under acceptable reported load. The result remains valid for this
host and run; it is not evidence that the optimization regressed universally.

## Controlling hosted pass

Evidence: `runs/jls2-complete-product-hosted-development.json`

Workflow:
`https://github.com/Atomics-hub/compression-lab/actions/runs/29534867956`

The result JSON SHA-256 is
`7410c415541373950cda7cd9183e3261bf0b1673c9e16f6bee37e81aea6bc88b`.
The downloaded artifact matched its checksummed files.

The runner was macOS 15.7.7 on a three-logical-CPU Apple M1 virtual machine,
Python 3.12.10, libzstd 1.5.7, and the native Rust transform. The sustained
preflight passed at 0.498 normalized load; the run stayed at or below 0.672.

| Family | Compression MB/s | Decompression MB/s |
| --- | ---: | ---: |
| Apache | 145.29 | 354.41 |
| HealthApp | 198.41 | 647.74 |
| HPC | 188.96 | 623.18 |
| Mac | 190.74 | 583.84 |
| ZooKeeper | 153.41 | 413.27 |

Aggregate compression was 183.66 MB/s and aggregate decompression was
564.59 MB/s. Every speed, integrity, determinism, accepted-byte, clean-commit,
and repetition gate passed.

Cross-platform CI for the same commit also passed on Linux, macOS, Windows,
Python 3.9 through 3.14, native wheel installation, packaging, Rust tests, and
the hostile-frame smoke:
`https://github.com/Atomics-hub/compression-lab/actions/runs/29534867841`.

## Memory gate

The final bounded-pipeline memory run passed on every family:

`runs/jls2-complete-product-memory-parallel-development.json`

The maximum compression resident set was 386,433,024 bytes on HPC. The maximum
decompression resident set was 171,409,408 bytes on HPC. Both are below the
536,870,912-byte ceiling. The evidence also verifies the two-worker
compression and decompression bounds.

## Next gate

1. Reproduce at least one eligible byte-exact log-specific competitor under
   its license and official build instructions, or formally establish that no
   currently auditable candidate satisfies the frozen eligibility rules.
2. Keep validation sealed until that independent competitor decision is
   complete.
3. If the competitor gate passes, freeze this exact candidate and open the
   three-family public validation split once.
4. Do not use this development pass as a world-best, market-leading, or public
   absolute-throughput claim.
