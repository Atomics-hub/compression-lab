# Adaptive-v2 calibrated native decision run

Date: 2026-07-15

This run tested the measurement changes selected after the quiet-window rerun:
Zstandard baselines moved from CLI subprocesses to the same direct `libzstd`
FFI path used by adaptive-v2, and every measured compression and decompression
operation ran in a calibrated batch for at least 250 ms. The benchmark also
recorded its exact Git revision and dirty state.

## Provenance and execution

- Run ID: `20260715T192919Z-d64e61fe`.
- Git commit: `463df95120d2aebb621e0ce5552584e3b4d44daa`.
- Branch: `agent/native-baseline-milestone`; working tree dirty: `false`.
- 8 digest-pinned files and 17,792,077 source bytes.
- 80 randomized warmups and 560 randomized measured trials.
- 7 measured repetitions, a fixed order seed of `20260715`, and 5,000
  deterministic bootstrap samples.
- Zero timeouts, worker failures, or SHA-256 round-trip failures.
- Zero unmet calibrated operation targets. Compression batches used 1–606
  iterations and decompression batches used 1–630 iterations.
- Both Zstandard levels reported `libzstd-ffi` as their codec engine.
- The private holdout remained unopened.

The quiet-host guard needed two bounded attempts. The first timed out above the
1.5/core ceiling. The second admitted the run after three consecutive normalized
load samples of 1.374, 1.247, and 1.124/core. The measured run therefore has a
valid preflight.

## Aggregate result

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
|---|---:|---:|---:|:---:|
| LZMA2 level 6 | 32.84 | 0.86 | 31.02 | yes |
| 7-Zip level 5 | 33.09 | 1.50 | 40.33 | yes |
| Brotli level 6 | 35.59 | 7.74 | 50.52 | yes |
| Zstandard level 9 | 35.90 | 18.77 | 232.70 | yes |
| Zstandard level 3 | 38.59 | 55.73 | 180.03 | yes |
| adaptive-v2 | 38.59 | 47.90 | 138.47 | no |
| gzip level 6 | 39.13 | 8.51 | 169.24 | no |
| adaptive-v1 | 43.63 | 25.19 | 133.84 | no |
| LZ4 level 1 | 50.94 | 70.26 | 70.55 | yes |
| store | 100.00 | 492.58 | 505.19 | yes |

Adaptive-v2 produced 6,866,648 bytes, only 289 bytes more than Zstandard level
3. In this run it was also slower than that direct baseline in both directions
and was not Pareto-optimal. Selector time was 4.52%, below the 5% ceiling.
These speed values are descriptive only because the repeatability contract
failed.

## Gates

The initial product gates did not pass:

| Check | Actual | Required | Result |
|---|---:|---:|:---:|
| Round-trip failures | 0 | 0 | PASS |
| Expansion violations | 0 | 0 | PASS |
| Selector overhead | 4.52% | at most 5% | PASS |
| Frontier coverage at 100 Mbps | 50.0% | at least 80% | FAIL |

The calibrated stability gates also did not pass:

| Check | Actual | Required | Result |
|---|---:|---:|:---:|
| Measured repetitions | 7 | at least 7 | PASS |
| Unmet operation targets | 0 | 0 | PASS |
| Compression throughput CV | 35.28% | at most 5% | FAIL |
| Decompression throughput CV | 36.01% | at most 5% | FAIL |
| Frontier coverage range | 37.5 pp | at most 5 pp | FAIL |
| Preflight normalized load | 1.124/core | at most 1.5/core | PASS |

Adaptive-v2's per-repetition frontier coverage at 100 Mbps was 62.5%, 62.5%,
37.5%, 75.0%, 62.5%, 50.0%, and 62.5%. Compression throughput ranged from
22.28 to 66.13 MB/s; decompression throughput ranged from 55.83 to 177.96 MB/s.

## Host evidence and decision

The run-start one-minute load was 11.24 on 10 logical CPUs, but it rose to
191.32 during the warmup and remained volatile throughout the measured run.
macOS reported no thermal, performance, or CPU-power warning. The benchmark
itself contributes load, so the during-run load is not an independent rejection
gate; however, the simultaneous high CV across every codec, including `store`
and direct in-process Zstandard, confirms that the shared machine did not
provide stable wall-clock scheduling.

Do not promote adaptive-v2, do not tune its selector from this run, and do not
open the private holdout. Calibrated batching and the direct Zstandard baseline
successfully removed two measurement confounders, but they did not make this
shared host a trustworthy decision environment. The next evidence-producing
step is an identical run on a dedicated or otherwise isolated machine. Only
after that run passes the repeatability gates should the project decide whether
adaptive-v2 needs algorithm changes or should be rejected in favor of a new
candidate architecture.
