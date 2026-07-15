# Adaptive-v2 benchmark stability experiment

Date: 2026-07-15

This experiment changed the measurement method, not adaptive-v2. Its purpose
was to determine whether the earlier 25–75% frontier-coverage swings were an
algorithm result or benchmark noise.

## Method

- 8 digest-pinned public files totaling 17,792,077 source bytes.
- 10 codecs using the same settings as the prior public adaptive-v2 run.
- One randomized warmup block containing 80 file-codec pairs.
- Seven independently randomized measured blocks containing 560 total trials.
- Deterministic order seed `20260715`.
- One persistent isolated Python worker per codec.
- Parent wall time excludes Python worker startup but includes IPC, file I/O,
  and native CLI startup for external baseline codecs.
- 5,000-sample deterministic percentile-bootstrap confidence intervals.
- System load captured at every block boundary and macOS thermal signals
  captured at run start and end.

The run completed all 560 measured trials with zero round-trip failures.

## Median item-level aggregate

| Codec | Compressed % | Compress MB/s | Decompress MB/s |
|---|---:|---:|---:|
| LZMA2 level 6 | 32.84 | 0.68 | 33.90 |
| 7-Zip level 5 | 33.09 | 1.27 | 31.02 |
| Brotli level 6 | 35.59 | 9.14 | 47.70 |
| Zstandard level 9 | 35.90 | 14.75 | 48.52 |
| adaptive-v2 | 38.59 | 41.76 | 128.93 |
| Zstandard level 3 | 38.65 | 27.99 | 53.13 |
| gzip level 6 | 39.13 | 13.21 | 138.83 |
| adaptive-v1 | 43.63 | 44.39 | 96.51 |
| LZ4 level 1 | 50.94 | 64.10 | 63.44 |
| store | 100.00 | 280.59 | 225.63 |

These wall-throughput values are recorded for completeness but are not valid
for promotion because the repeatability and host-load gates failed.

## Gate result

The original median-only product gates all passed: exact round trips, bounded
expansion, 3.64% selector overhead against a 5% ceiling, and 100% frontier
coverage on the per-item median rows against an 80% target.

The new stability gates rejected that apparent pass:

| Stability check | Actual | Required | Result |
|---|---:|---:|:---:|
| Measured repetitions | 7 | at least 7 | PASS |
| Compression throughput CV | 40.19% | at most 5% | FAIL |
| Decompression throughput CV | 41.13% | at most 5% | FAIL |
| Frontier coverage range | 50.0 pp | at most 5 pp | FAIL |
| Maximum normalized 1-minute host load | 28.96/core | at most 1.5/core | FAIL |

Adaptive-v2's per-repetition frontier coverage at 100 Mbps was 87.5%, 87.5%,
87.5%, 100%, 87.5%, 100%, and 50%. Its aggregate compression-throughput
median was 38.65 MB/s with a 95% bootstrap interval of 35.28–44.88 MB/s, but
one repetition fell to 5.06 MB/s. Decompression had the same contamination
pattern, with a 13.61 MB/s minimum versus a 116.14 MB/s median.

Recorded one-minute load average rose from 58.16 at run start to 289.64 at run
end on a 10-logical-CPU host. macOS reported no thermal or CPU-power warning,
so shared-machine contention—not a reported thermal throttle—is the supported
explanation.

CPU telemetry in this specific run should not be used to compare external
codecs: the worker then counted only its own CPU time. The harness now measures
the delta for both the persistent worker and completed native child processes.

## Decision

Do not promote the old median-only pass and do not tune adaptive-v2 against this
run. Correctness and deterministic encoded sizes remain valid; comparative
wall-time and frontier claims do not.

The next decision run must use the same frozen candidate and recipe on a quiet
or dedicated host and pass both repeatability and host-load gates. If it then
maintains at least 80% frontier coverage, proceed to a fully native streaming
compressor. If the stable result is strong only on numeric/scientific data,
narrow the product to that domain. If it fails broadly, replace the transform
or predictor rather than continuing selector-threshold tuning.
