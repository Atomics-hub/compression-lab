# Compression Lab Benchmark

- Run: 20260717T040220Z-870a57d9
- Generated: 2026-07-17T06:56:42.957670+00:00
- Trials: 220
- Round-trip failures: 0
- Timing: parent wall clock per operation excluding Python worker startup; includes amortized IPC and file I/O, with measured operations batched to 0 ms or 4096 iterations

## Aggregate results

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |
|---|---:|---:|---:|---:|:---:|
| 7zip-9 | 10.07 | 1.93 | 141.44 | 0 | yes |
| lzma-9 | 10.08 | 0.54 | 45.23 | 0 | no |
| tbl1-stream-dense | 10.43 | 107.67 | 403.39 | 0 | yes |
| brotli-11 | 10.55 | 0.43 | 258.15 | 0 | no |
| zstd-19 | 10.78 | 1.31 | 372.62 | 0 | no |
| bz2-9 | 12.77 | 2.39 | 23.68 | 0 | no |
| zstd-9 | 13.43 | 51.20 | 344.36 | 0 | no |
| zstd-3 | 16.58 | 247.36 | 343.45 | 0 | yes |
| gzip-9 | 18.60 | 6.26 | 333.42 | 0 | no |
| lz4-1 | 35.44 | 878.25 | 423.25 | 0 | yes |
| store | 100.00 | 1382.93 | 812.06 | 0 | yes |

## Adaptive-selector opportunity

The oracle chooses the best measured codec separately for each item with zero
selection cost. It is an upper bound, not a candidate result.

| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |
|---:|---|---:|---:|---:|
| 10 Mbps | tbl1-stream-dense | 25547.25 | 25547.25 | 0.00% |
| 100 Mbps | tbl1-stream-dense | 5397.41 | 5071.84 | 6.03% |
| 1000 Mbps | lz4-1 | 1700.90 | 1700.90 | 0.00% |

## Repeatability

Intervals are 95% deterministic percentile-bootstrap confidence intervals of the per-repetition median.

| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |
|---|---:|---:|---:|---:|
| 7zip-9 | 1.93 (1.50–2.22) | 16.18% | 4.33% | 0.00 pp |
| brotli-11 | 0.42 (0.35–0.45) | 10.10% | 10.82% | 0.00 pp |
| bz2-9 | 2.39 (1.48–2.41) | 18.63% | 15.24% | 0.00 pp |
| gzip-9 | 6.00 (5.51–6.29) | 4.84% | 11.41% | 0.00 pp |
| lz4-1 | 688.58 (454.89–949.64) | 27.72% | 20.05% | 0.00 pp |
| lzma-9 | 0.55 (0.43–0.60) | 12.21% | 13.99% | 0.00 pp |
| store | 1422.92 (871.82–1624.48) | 29.55% | 10.67% | 0.00 pp |
| tbl1-stream-dense | 102.08 (64.36–108.62) | 18.51% | 32.91% | 0.00 pp |
| zstd-19 | 1.26 (1.15–1.56) | 13.34% | 14.16% | 0.00 pp |
| zstd-3 | 235.64 (146.25–256.75) | 23.45% | 7.58% | 25.00 pp |
| zstd-9 | 40.26 (28.89–62.30) | 31.78% | 20.94% | 0.00 pp |

## Interpretation guardrails

- Values are comparable only within this run and machine context.
- Timing scope: parent wall clock per operation excluding Python worker startup; includes amortized IPC and file I/O, with measured operations batched to 0 ms or 4096 iterations.
- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.
- A private holdout corpus should be stored outside the repository and run only at decision gates.
