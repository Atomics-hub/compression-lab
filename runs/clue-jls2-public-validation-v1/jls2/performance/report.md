# Compression Lab Benchmark

- Run: 20260717T192150Z-98b20aa9
- Generated: 2026-07-17T19:58:20.936824+00:00
- Trials: 110
- Round-trip failures: 0
- Timing: parent wall clock including worker process startup

## Aggregate results

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |
|---|---:|---:|---:|---:|:---:|
| jls2 | 0.51 | 109.58 | 206.17 | 0 | yes |
| brotli-11 | 1.07 | 0.37 | 388.79 | 0 | yes |
| bz2-9 | 1.23 | 8.00 | 96.20 | 0 | no |
| 7zip-9 | 1.30 | 21.33 | 268.11 | 0 | yes |
| lzma-9 | 1.30 | 13.75 | 225.93 | 0 | no |
| zstd-19 | 1.35 | 1.35 | 369.27 | 0 | yes |
| zstd-9 | 1.47 | 188.33 | 372.16 | 0 | yes |
| gzip-9 | 1.81 | 37.24 | 253.82 | 0 | no |
| zstd-3 | 2.10 | 397.58 | 365.82 | 0 | yes |
| lz4-1 | 4.48 | 434.42 | 408.72 | 0 | yes |
| store | 100.00 | 437.34 | 441.81 | 0 | yes |

## Adaptive-selector opportunity

The oracle chooses the best measured codec separately for each item with zero
selection cost. It is an upper bound, not a candidate result.

| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |
|---:|---|---:|---:|---:|
| 10 Mbps | jls2 | 1746.44 | 1746.44 | 0.00% |
| 100 Mbps | zstd-3 | 671.96 | 671.96 | 0.00% |
| 1000 Mbps | lz4-1 | 495.04 | 495.04 | 0.00% |

## Repeatability

Intervals are 95% deterministic percentile-bootstrap confidence intervals of the per-repetition median.

| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |
|---|---:|---:|---:|---:|
| 7zip-9 | 21.46 (21.10–21.71) | 1.35% | 0.99% | 0.00 pp |
| brotli-11 | 0.37 (0.37–0.37) | 0.04% | 0.32% | 0.00 pp |
| bz2-9 | 7.99 (7.93–8.06) | 0.74% | 2.71% | 0.00 pp |
| gzip-9 | 37.12 (35.54–37.51) | 2.20% | 0.32% | 0.00 pp |
| jls2 | 109.39 (108.44–111.66) | 1.17% | 1.76% | 0.00 pp |
| lz4-1 | 431.93 (425.40–442.45) | 1.68% | 2.49% | 0.00 pp |
| lzma-9 | 13.79 (13.69–13.80) | 0.34% | 1.04% | 0.00 pp |
| store | 439.47 (433.29–447.82) | 1.25% | 1.85% | 0.00 pp |
| zstd-19 | 1.36 (1.34–1.37) | 0.80% | 1.61% | 0.00 pp |
| zstd-3 | 394.89 (389.45–405.67) | 1.82% | 1.33% | 0.00 pp |
| zstd-9 | 190.40 (184.40–193.15) | 1.76% | 1.75% | 0.00 pp |

## Interpretation guardrails

- Values are comparable only within this run and machine context.
- Timing scope: parent wall clock including worker process startup.
- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.
- A private holdout corpus should be stored outside the repository and run only at decision gates.
