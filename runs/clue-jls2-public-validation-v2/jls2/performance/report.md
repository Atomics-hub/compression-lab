# Compression Lab Benchmark

- Run: 20260724T003328Z-04b21004
- Generated: 2026-07-24T01:13:12.803833+00:00
- Trials: 110
- Round-trip failures: 0
- Timing: parent wall clock including worker process startup

## Aggregate results

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |
|---|---:|---:|---:|---:|:---:|
| jls2 | 0.54 | 101.76 | 203.67 | 0 | yes |
| brotli-11 | 1.09 | 0.35 | 401.87 | 0 | yes |
| bz2-9 | 1.32 | 7.79 | 114.62 | 0 | no |
| lzma-9 | 1.49 | 14.89 | 220.11 | 0 | yes |
| 7zip-9 | 1.49 | 20.37 | 284.49 | 0 | yes |
| zstd-19 | 1.57 | 1.15 | 339.76 | 0 | yes |
| zstd-9 | 1.61 | 191.70 | 338.06 | 0 | yes |
| gzip-9 | 1.83 | 40.58 | 265.63 | 0 | no |
| zstd-3 | 2.14 | 360.48 | 334.19 | 0 | yes |
| lz4-1 | 4.62 | 467.22 | 442.36 | 0 | yes |
| store | 100.00 | 467.73 | 468.94 | 0 | yes |

## Adaptive-selector opportunity

The oracle chooses the best measured codec separately for each item with zero
selection cost. It is an upper bound, not a candidate result.

| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |
|---:|---|---:|---:|---:|
| 10 Mbps | jls2 | 1855.07 | 1855.07 | 0.00% |
| 100 Mbps | zstd-3 | 729.37 | 729.37 | -0.00% |
| 1000 Mbps | lz4-1 | 465.25 | 465.25 | 0.00% |

## Repeatability

Intervals are 95% deterministic percentile-bootstrap confidence intervals of the per-repetition median.

| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |
|---|---:|---:|---:|---:|
| 7zip-9 | 20.37 (20.16–20.50) | 0.68% | 0.78% | 0.00 pp |
| brotli-11 | 0.35 (0.35–0.35) | 0.05% | 0.24% | 0.00 pp |
| bz2-9 | 7.79 (7.78–7.81) | 0.21% | 3.39% | 0.00 pp |
| gzip-9 | 40.58 (40.55–40.59) | 0.04% | 1.32% | 0.00 pp |
| jls2 | 102.27 (98.44–103.32) | 1.88% | 35.70% | 0.00 pp |
| lz4-1 | 467.56 (465.46–468.70) | 0.29% | 1.21% | 0.00 pp |
| lzma-9 | 14.88 (14.84–14.94) | 0.25% | 0.73% | 0.00 pp |
| store | 466.49 (465.05–467.93) | 0.25% | 1.65% | 0.00 pp |
| zstd-19 | 1.15 (1.15–1.15) | 0.15% | 0.58% | 0.00 pp |
| zstd-3 | 361.55 (359.54–362.92) | 0.43% | 0.68% | 0.00 pp |
| zstd-9 | 191.70 (188.89–193.16) | 1.04% | 0.97% | 0.00 pp |

## Interpretation guardrails

- Values are comparable only within this run and machine context.
- Timing scope: parent wall clock including worker process startup.
- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.
- A private holdout corpus should be stored outside the repository and run only at decision gates.
