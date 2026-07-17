# Compression Lab Benchmark

- Run: 20260717T065643Z-a960c464
- Generated: 2026-07-17T06:56:53.066928+00:00
- Trials: 4
- Round-trip failures: 0
- Timing: parent wall clock including worker process startup

## Aggregate results

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Expanded items | Pareto |
|---|---:|---:|---:|---:|:---:|
| tbl1-stream-dense | 10.43 | 42.04 | 98.18 | 0 | yes |

## Adaptive-selector opportunity

The oracle chooses the best measured codec separately for each item with zero
selection cost. It is an upper bound, not a candidate result.

| Link | Best fixed | Fixed total ms | Oracle total ms | Oracle gain |
|---:|---|---:|---:|---:|
| 100 Mbps | tbl1-stream-dense | 11358.64 | 11358.64 | 0.00% |

## Repeatability

Intervals are 95% deterministic percentile-bootstrap confidence intervals of the per-repetition median.

| Codec | Compress MB/s median (CI) | Compression CV | Decompression CV | Frontier range at 100 Mbps |
|---|---:|---:|---:|---:|
| tbl1-stream-dense | 42.04 (42.04–42.04) | 0.00% | 0.00% | 0.00 pp |

## Interpretation guardrails

- Values are comparable only within this run and machine context.
- Timing scope: parent wall clock including worker process startup.
- Aggregate ratios are byte-weighted; the JSON retains every per-file trial.
- A private holdout corpus should be stored outside the repository and run only at decision gates.
