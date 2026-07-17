# Compression Lab Benchmark

- Run: 20260717T125746Z-f2ce8e24
- Generated: 2026-07-17T14:12:55.748345+00:00
- Trials: 99
- Round-trip failures: 0
- Timing: parent wall clock including worker process startup

## Aggregate results

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |
|---|---:|---:|---:|---:|:---:|
| jls2 | 1.73 | 109.90 | 116.43 | 0 | yes |
| brotli-11 | 2.11 | 0.37 | 253.86 | 0 | yes |
| zstd-19 | 2.41 | 1.05 | 268.83 | 0 | yes |
| bz2-9 | 2.64 | 1.37 | 25.26 | 0 | no |
| lzma-9 | 2.74 | 1.59 | 82.29 | 0 | no |
| 7zip-9 | 2.74 | 6.44 | 164.58 | 0 | yes |
| zstd-9 | 2.79 | 124.70 | 300.48 | 0 | yes |
| zstd-3 | 3.70 | 313.60 | 248.62 | 0 | yes |
| gzip-9 | 4.06 | 49.19 | 288.08 | 0 | no |
| lz4-1 | 6.91 | 387.73 | 278.96 | 0 | yes |
| store | 100.00 | 416.08 | 479.03 | 0 | yes |

## Adaptive-selector opportunity

The oracle chooses the best measured codec separately for each item with zero
selection cost. It is an upper bound, not a candidate result.

| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |
|---:|---|---:|---:|---:|
| 10 Mbps | jls2 | 6419.86 | 5960.15 | 7.16% |
| 100 Mbps | zstd-3 | 2071.09 | 2071.09 | 0.00% |
| 1000 Mbps | lz4-1 | 1367.30 | 1353.59 | 1.00% |

## Repeatability

Intervals are 95% deterministic percentile-bootstrap confidence intervals of the per-repetition median.

| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |
|---|---:|---:|---:|---:|
| 7zip-9 | 6.18 (5.16–7.08) | 15.65% | 7.43% | 0.00 pp |
| brotli-11 | 0.34 (0.34–0.35) | 1.86% | 9.50% | 0.00 pp |
| bz2-9 | 1.30 (1.24–1.83) | 22.16% | 16.49% | 0.00 pp |
| gzip-9 | 49.19 (47.91–49.85) | 2.01% | 4.31% | 0.00 pp |
| jls2 | 110.27 (83.79–160.27) | 32.89% | 56.36% | 0.00 pp |
| lz4-1 | 334.26 (309.12–422.91) | 16.82% | 23.86% | 33.33 pp |
| lzma-9 | 1.59 (1.43–2.13) | 21.11% | 5.13% | 0.00 pp |
| store | 346.23 (332.32–358.06) | 3.73% | 12.63% | 0.00 pp |
| zstd-19 | 1.15 (0.97–1.17) | 10.32% | 23.87% | 0.00 pp |
| zstd-3 | 264.94 (245.57–423.41) | 31.34% | 13.22% | 0.00 pp |
| zstd-9 | 105.97 (86.92–141.43) | 24.82% | 8.79% | 66.67 pp |

## Interpretation guardrails

- Values are comparable only within this run and machine context.
- Timing scope: parent wall clock including worker process startup.
- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.
- A private holdout corpus should be stored outside the repository and run only at decision gates.
