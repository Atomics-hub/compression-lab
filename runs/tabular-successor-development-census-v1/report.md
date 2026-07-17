# Compression Lab Benchmark

- Run: 20260717T073359Z-48ac5ec8
- Generated: 2026-07-17T07:35:39.617680+00:00
- Trials: 66
- Round-trip failures: 0
- Timing: parent wall clock per operation excluding Python worker startup; includes amortized IPC and file I/O, with measured operations batched to 0 ms or 4096 iterations

## Aggregate results

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |
|---|---:|---:|---:|---:|:---:|
| bz2-9 | 8.85 | 4.09 | 28.06 | 0 | yes |
| lzma-9 | 9.09 | 0.69 | 50.55 | 0 | yes |
| tbl1-stream-dense | 9.11 | 45.52 | 278.26 | 0 | yes |
| 7zip-9 | 9.14 | 3.34 | 124.44 | 0 | no |
| brotli-11 | 9.42 | 0.43 | 239.36 | 0 | no |
| zstd-19 | 9.67 | 1.81 | 720.14 | 0 | yes |
| gzip-9 | 12.33 | 3.60 | 695.15 | 0 | yes |
| zstd-9 | 12.38 | 57.32 | 595.30 | 0 | yes |
| zstd-3 | 15.00 | 154.90 | 542.01 | 0 | yes |
| lz4-1 | 26.40 | 255.90 | 311.16 | 0 | yes |
| store | 100.00 | 1627.18 | 2189.08 | 0 | yes |

## Adaptive-selector opportunity

The oracle chooses the best measured codec separately for each item with zero
selection cost. It is an upper bound, not a candidate result.

| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |
|---:|---|---:|---:|---:|
| 10 Mbps | tbl1-stream-dense | 1834.38 | 1765.28 | 3.77% |
| 100 Mbps | zstd-3 | 378.34 | 378.34 | 0.00% |
| 1000 Mbps | store | 169.05 | 115.34 | 31.77% |

## Repeatability

Intervals are 95% deterministic percentile-bootstrap confidence intervals of the per-repetition median.

| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |
|---|---:|---:|---:|---:|
| 7zip-9 | 3.34 (3.34–3.34) | 0.00% | 0.00% | 0.00 pp |
| brotli-11 | 0.43 (0.43–0.43) | 0.00% | 0.00% | 0.00 pp |
| bz2-9 | 4.09 (4.09–4.09) | 0.00% | 0.00% | 0.00 pp |
| gzip-9 | 3.60 (3.60–3.60) | 0.00% | 0.00% | 0.00 pp |
| lz4-1 | 255.90 (255.90–255.90) | 0.00% | 0.00% | 0.00 pp |
| lzma-9 | 0.69 (0.69–0.69) | 0.00% | 0.00% | 0.00 pp |
| store | 1627.18 (1627.18–1627.18) | 0.00% | 0.00% | 0.00 pp |
| tbl1-stream-dense | 45.52 (45.52–45.52) | 0.00% | 0.00% | 0.00 pp |
| zstd-19 | 1.81 (1.81–1.81) | 0.00% | 0.00% | 0.00 pp |
| zstd-3 | 154.90 (154.90–154.90) | 0.00% | 0.00% | 0.00 pp |
| zstd-9 | 57.32 (57.32–57.32) | 0.00% | 0.00% | 0.00 pp |

## Interpretation guardrails

- Values are comparable only within this run and machine context.
- Timing scope: parent wall clock per operation excluding Python worker startup; includes amortized IPC and file I/O, with measured operations batched to 0 ms or 4096 iterations.
- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.
- A private holdout corpus should be stored outside the repository and run only at decision gates.
