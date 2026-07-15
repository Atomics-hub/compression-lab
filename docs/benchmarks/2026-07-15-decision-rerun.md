# Adaptive-v2 quiet-window decision rerun

Date: 2026-07-15

This rerun held adaptive-v2, the ten-codec set, corpus, seed, levels, warmups,
and seven-repetition recipe unchanged. It began only after normalized
one-minute host load remained below the 1.5/core preflight ceiling for three
consecutive samples.

## Result

- Run ID: `20260715T183909Z-b2798314`.
- 8 digest-pinned files and 17,792,077 source bytes.
- 80 randomized warmups and 560 randomized measured trials.
- Zero timeouts, worker failures, or SHA-256 round-trip failures.
- Preflight load: 9.48 on 10 logical CPUs, or 0.95/core: PASS.
- macOS reported no thermal, performance, or CPU-power warning.

| Codec | Compressed % | Compress MB/s | Decompress MB/s |
|---|---:|---:|---:|
| LZMA2 level 6 | 32.84 | 1.12 | 49.29 |
| 7-Zip level 5 | 33.09 | 1.93 | 45.35 |
| Brotli level 6 | 35.59 | 12.25 | 71.40 |
| Zstandard level 9 | 35.90 | 19.07 | 82.43 |
| adaptive-v2 | 38.59 | 69.77 | 162.01 |
| Zstandard level 3 | 38.65 | 47.66 | 74.26 |
| gzip level 6 | 39.13 | 16.68 | 168.37 |
| adaptive-v1 | 43.63 | 52.71 | 145.01 |
| LZ4 level 1 | 50.94 | 83.02 | 91.30 |
| store | 100.00 | 402.40 | 348.40 |

The original median-only gates passed: exact round trips, bounded expansion,
4.95% selector overhead against a 5% ceiling, and 100% frontier coverage on
per-item median rows against an 80% target.

The repeatability gates still failed:

| Stability check | Actual | Required | Result |
|---|---:|---:|:---:|
| Measured repetitions | 7 | at least 7 | PASS |
| Compression throughput CV | 30.30% | at most 5% | FAIL |
| Decompression throughput CV | 21.18% | at most 5% | FAIL |
| Frontier coverage range | 12.5 pp | at most 5 pp | FAIL |
| Preflight normalized load | 0.95/core | at most 1.5/core | PASS |

Adaptive-v2's per-repetition frontier coverage at 100 Mbps was 87.5%, 87.5%,
100%, 100%, 100%, 100%, and 87.5%. Its compression CPU-throughput CV was
17.11%, and decompression CPU-throughput CV was 15.14%; corrected child-process
CPU accounting therefore confirms that wall scheduling noise is not the only
remaining measurement variance.

## Decision

Do not promote adaptive-v2 and do not tune its selector thresholds from this
run. Its encoded size is deterministic and closely matches Zstandard level 3
(38.594% versus 38.645%), while substantially stronger ratio-oriented codecs
remain smaller. The candidate passes the old median product gate but not the
repeatability contract required to trust that gate.

Another identical run on this shared host is unlikely to resolve the issue.
The next engineering step is calibrated, longer-duration timing with native
in-process baseline bindings, beginning with Zstandard so adaptive-v2 and its
closest baseline use the same library path. A final product decision should
then run on a dedicated or otherwise isolated machine. The private holdout
remains unopened until that measurement path is stable.
