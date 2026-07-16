# JLS2 complete-product speed decision

## Decision

Fail the complete-product speed gate. Keep the accepted JLS2 representation,
decode optimizations, and frozen thresholds. Do not open blind validation.

Two eligible development runs are retained because they answer different
questions. Neither is a public throughput claim.

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

## Next gate

The post-pipeline memory run passed on every family:

`runs/jls2-complete-product-memory-development.json`

The maximum compression resident set was 307,773,440 bytes on HPC. The maximum
decompression resident set was 201,621,504 bytes on HPC. Both are below the
536,870,912-byte ceiling.

1. Obtain a sustained, isolated benchmark host or a long cool window with no
   unrelated build activity.
2. Repeat the unchanged five-repetition protocol.
3. Do not relax thresholds or select only favorable families.
4. Keep validation sealed until one complete run passes every speed and memory
   gate and an eligible byte-exact log-specific competitor is reproduced.
