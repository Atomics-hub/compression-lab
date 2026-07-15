# Adaptive-v2 isolated hosted decision

Date: 2026-07-15

This is the first adaptive-v2 decision run on a clean, isolated hosted machine.
It used the unchanged calibrated recipe from the shared-host experiment and is
the controlling public-corpus result for the adaptive-v2 milestone.

GitHub Actions run
[`29447150079`](https://github.com/Atomics-hub/compression-lab/actions/runs/29447150079)
executed on a standard ARM64 `macos-15` runner with 3 logical CPUs. An earlier
hosted run, `29446067667`, is superseded because its workflow-created evidence
directory made the recorded checkout dirty.

## Provenance and execution

- Run ID: `20260715T201624Z-1193af79`.
- Git commit: `6eb438626779dfd4622780760e5e2ce5400472bd`.
- Branch: `agent/native-baseline-milestone`; working tree dirty: `false`.
- macOS 15.7.7 ARM64, Python 3.14.6, Rust 1.96.1.
- 8 digest-pinned files and 17,792,077 source bytes.
- 80 randomized warmups and 560 randomized measured trials.
- 7 measured repetitions, fixed seed `20260715`, and 5,000 deterministic
  bootstrap samples.
- Zero timeouts, worker failures, or SHA-256 round-trip failures.
- Zero unmet calibrated operation targets. Compression batches used 1–2,253
  iterations; decompression batches used 2–2,243 iterations.
- Both Zstandard levels reported `libzstd-ffi`.
- The private holdout remained unopened.

The guard waited for hosted-runner initialization load to decay, then admitted
the benchmark after three consecutive normalized samples of 1.414, 1.196, and
1.012/core. The recorded run-start load was 0.931/core, below the 1.5/core
ceiling.

## Aggregate result

| Codec | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
|---|---:|---:|---:|:---:|
| LZMA2 level 6 | 32.84 | 3.17 | 108.82 | yes |
| 7-Zip level 5 | 33.09 | 5.62 | 115.10 | yes |
| Brotli level 6 | 35.59 | 45.51 | 225.94 | yes |
| Zstandard level 9 | 35.90 | 65.75 | 677.31 | yes |
| Zstandard level 3 | 38.59 | 282.59 | 661.10 | yes |
| adaptive-v2 | 38.59 | 240.93 | 559.07 | no |
| gzip level 6 | 39.13 | 37.78 | 620.41 | no |
| adaptive-v1 | 43.63 | 122.93 | 445.50 | no |
| LZ4 level 1 | 50.94 | 306.18 | 344.10 | yes |
| store | 100.00 | 830.96 | 843.25 | yes |

Adaptive-v2 produced 6,866,648 bytes, 289 bytes more than Zstandard level 3.
It was approximately 14.7% slower to compress and 15.4% slower to decompress
than the direct Zstandard level-3 baseline. It was not Pareto-optimal.

The selector routed seven files to Zstandard level 3 and one already-compressed
file to store. Across seven repetitions this produced 49 measured Zstandard
routes and 7 store routes. The result is therefore primarily a Zstandard
wrapper with sampling and frame overhead, not a new competitive compression
mechanism.

## Gates

| Check | Actual | Required | Result |
|---|---:|---:|:---:|
| Round-trip failures | 0 | 0 | PASS |
| Expansion violations | 0 | 0 | PASS |
| Selector overhead | 6.73% | at most 5% | FAIL |
| Frontier coverage at 100 Mbps | 75.0% | at least 80% | FAIL |
| Measured repetitions | 7 | at least 7 | PASS |
| Unmet operation targets | 0 | 0 | PASS |
| Compression throughput CV | 6.41% | at most 5% | FAIL |
| Decompression throughput CV | 9.06% | at most 5% | FAIL |
| Frontier coverage range | 25.0 pp | at most 5 pp | FAIL |
| Preflight normalized load | 0.931/core | at most 1.5/core | PASS |

Adaptive-v2's per-repetition frontier coverage at 100 Mbps was 62.5%, 75.0%,
75.0%, 75.0%, 87.5%, 62.5%, and 75.0%. Its compression throughput ranged from
206.25 to 245.22 MB/s, and decompression throughput ranged from 461.28 to
598.04 MB/s.

At the product's modeled 100 Mbps objective, adaptive-v2 total-time CV was only
1.14%, but frontier membership remained unstable because several codecs were
close to the tolerance boundary. The strict component-throughput and frontier
gates correctly keep the result from becoming a product claim.

## Decision

Reject adaptive-v2 as the lead architecture. Do not lower the gates, tune its
selector, promote it, or open the private holdout. The clean result confirms
that adaptive-v2 is bounded by its Zstandard level-3 backend: it cannot beat
that backend's encoded size, and its sampling, framing, and dispatch add time.

The public-corpus oracle reinforces that conclusion. At 100 Mbps the best
per-file oracle improved on the best fixed codec by only 0.47%; at 10 Mbps the
gain was 0.38%. Another file-level selector over the same codec menu therefore
has little upside on this corpus.

The next candidate should be adaptive-v3 with a genuinely new hypothesis:
block- or segment-level structure detection, reversible transforms selected at
that granularity, and an entropy backend whose output can improve on fixed
Zstandard rather than merely wrap it. V3 must first clear correctness,
expansion, overhead, frontier, and repeatability gates on public data. The
private holdout stays sealed until that public decision gate passes.
