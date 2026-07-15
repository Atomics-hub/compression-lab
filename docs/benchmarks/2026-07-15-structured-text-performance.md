# Adaptive-v3 structured-text performance pass

## Purpose

The structured-text alpha produced the first clean licensed real-file size win
over direct Zstandard level 3, but compressed at only 13.16 MB/s. This pass
profiles and removes avoidable selector work without changing the frame, recipe,
dictionary policy, or encoded bytes.

This remains a local public-validation experiment. It is not an isolated hosted
gate, and the private holdout remained sealed.

## Profile finding

On the 9.5 MB SQLite source file, the original path spent a median 800.7 ms in
Python dictionary ranking and then repeated the same ranking in native Rust.
Native transform time was 265.1 ms, while raw and transformed Zstandard level-3
encodes together cost about 218.7 ms. The duplicate Python ranking pass was the
dominant avoidable cost.

The optimized path:

- ranks the dictionary once in native Rust;
- reads the actual selected dictionary size from the reversible transform
  header;
- uses collision-checked 128-bit token fingerprints behind Rust's randomized
  hash table, avoiding repeated full-token hashing and temporary allocation;
- retains byte-equivalence against the Python reference implementation;
- adds a regression test that fails if the native path calls Python ranking.

## Clean result

The tested clean revision was
`a3ad1753aaf3c2785e0d5029c0aae75155438e0d`. The benchmark used the same public
corpus and method as the structured-text alpha: one warmup, two measured
repetitions, deterministic shuffle seed `20260715`, persistent workers, a 25 ms
minimum operation batch, and 1,000 bootstrap samples.

Canonical evidence:

- `runs/adaptive-v3-performance-public-clean/results.json`

All 64 measured round trips passed.

| Codec | Compressed bytes | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | --- |
| adaptive-v2 | 6,866,648 | 83.06 | 202.60 | no |
| adaptive-v3 | 6,742,240 | 22.49 | 133.84 | no |
| zstd-3 | 6,866,359 | 95.02 | 237.04 | yes |
| zstd-9 | 6,386,970 | 26.62 | 221.00 | yes |

Adaptive-v3 output remained exactly 6,742,240 bytes. Compression throughput
increased from 13.16 to 22.49 MB/s, a 70.85% improvement across the two clean
runs. Decompression changed from 143.99 to 133.84 MB/s even though that code was
unchanged, which is treated as shared-host variation rather than a regression
claim.

## Decision

Keep the optimization. It removes redundant work, preserves every size win, and
has direct equivalence and regression coverage.

Do not promote adaptive-v3 or open the private holdout. Zstandard level 9 still
produces 5.56% fewer bytes, compresses about 15.5% faster in this run, and
decompresses substantially faster. The next performance target is the native
token-count/encode pass, followed by fused or streaming transformed decode to
avoid materializing and copying the intermediate token stream.
