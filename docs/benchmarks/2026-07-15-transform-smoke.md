# Adaptive-v1 transform smoke benchmark

Date: 2026-07-15

This is a local synthetic smoke result. It validates an experiment and does not
support a market, production, or state-of-the-art claim.

## Run contract

- Corpus: eight deterministic synthetic items, 5,875,890 source bytes
- Trials: 176 measured trials
- Repetitions: two measured runs after one warmup
- Timing: parent wall clock including Python worker startup
- Correctness: source and restored SHA-256 must match
- Machine and interpreter details: retained in the ignored raw results.json

## Aggregate result

| Codec | Compressed % | Compress MB/s | Decompress MB/s |
|---|---:|---:|---:|
| adaptive-v1 | 31.23 | 4.60 | 5.58 |
| LZMA2 level 6 | 33.16 | 3.79 | 7.28 |
| LZMA2 level 0 | 34.65 | 5.96 | 8.17 |
| gzip level 9 | 40.90 | 7.23 | 8.69 |
| adaptive-v0 | 41.62 | 7.54 | 8.37 |
| store | 100.00 | 8.43 | 8.27 |

Adaptive-v1 selected delta-transpose plus gzip-1 for the float32 signal,
mixed-region input, and long-run input. On the float32 signal it produced
424,371 bytes, versus 590,864 for LZMA2 level 6 and 950,720 for gzip level 1.

## Gate result

| Check | Result |
|---|---|
| Bit-exact round trips | PASS: 0 failures |
| Bounded expansion | PASS: 0 violating items |
| Selector overhead | FAIL: 16.16% versus a 5% ceiling |
| Frontier coverage at 100 Mbps | FAIL: 37.5% versus an 80% target |

The zero-cost per-item oracle improved total task time by 6.38% over the best
fixed codec at 100 Mbps. This supports further selector research, but the oracle
is not an implementable result.

## Decision

Keep the transform and move it into optimized native code before expanding its
scope. The ratio gain is large enough to investigate. The current Python
implementation is too slow, the sample transform is too expensive, and the
corpus is too synthetic to establish external validity.

Next experiment:

1. implement delta-transpose in Rust or C with SIMD-friendly byte planes;
2. reduce selector sampling from 192 KiB to a staged 16–48 KiB probe;
3. benchmark against native Zstd, LZ4, and Brotli;
4. add real licensed numeric, database, executable, document, and media corpora;
5. freeze an external private holdout before tuning thresholds.
