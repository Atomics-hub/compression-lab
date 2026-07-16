# Version 0.1 release-candidate benchmark

## Decision

The product and evidence pipeline pass the release-candidate engineering gate.
The market-leadership claim does not. Compression Lab 0.1 can be released as an
alpha adaptive compressor and research platform, but it must not be described
as the best, universally superior, or state of the art.

The frozen comparison completed 448 measured file-codec pairs with zero
round-trip failures. The machine verifier accepted the complete 8-file,
8-codec, 7-repetition matrix and exact source commit.

## Frozen protocol

- Hosted run: [GitHub Actions 29474818325](https://github.com/Atomics-hub/compression-lab/actions/runs/29474818325)
- Candidate commit: `24ca07a3075d67581b72c14693e96cd3e108076c`
- Run ID: `20260716T055401Z-cbe94543`
- Host: GitHub-hosted macOS 15.7.7, ARM64, 3 logical CPUs
- Python: 3.12.10
- Corpus: 17,792,077 bytes across 8 digest-pinned public files and 5 categories
- Repetitions: 7 after 1 warmup, independently shuffled with seed 20260716
- Timing: persistent workers, 250 ms minimum measured operation duration
- Integrity: per-trial SHA-256, per-segment CRC32, and final frame SHA-256

The public-starter configuration explicitly caps this corpus at engineering
starter evidence. It is diverse enough to reject broad claims, not large or
independent enough to establish market leadership.

## Aggregate results

| Codec | Encoded bytes | Encoded % | Compress MB/s | Decompress MB/s | Pareto |
|---|---:|---:|---:|---:|:---:|
| 7zip-9 | 5,840,211 | 32.82 | 6.96 | 128.20 | yes |
| lzma-9 | 5,841,992 | 32.83 | 1.79 | 71.32 | no |
| brotli-11 | 5,857,317 | 32.92 | 0.70 | 256.95 | yes |
| brotli-6 | 6,332,761 | 35.59 | 50.08 | 257.25 | yes |
| zstd-9 | 6,386,970 | 35.90 | 78.23 | 709.19 | yes |
| adaptive-v3 | 6,747,896 | 37.93 | 70.62 | 376.96 | **no** |
| zstd-3 | 6,866,359 | 38.59 | 311.60 | 724.06 | yes |
| gzip-9 | 6,927,807 | 38.94 | 17.83 | 566.23 | no |

Encoded sizes are deterministic for these exact inputs and codec versions.
Timing is host-scoped: per-codec throughput coefficients of variation ranged
from 9.02% to 28.27%, so small speed differences must not be generalized.

## Interpretation

Adaptive-v3 was 118,463 bytes (1.73%) smaller than zstd-3 and 179,911 bytes
(2.60%) smaller than gzip-9. It was 360,926 bytes (5.65%) larger than zstd-9.
On this run zstd-9 also compressed and decompressed faster, strictly dominating
adaptive-v3 in the reported aggregate size/speed space.

The correct launch claim is therefore narrow: Compression Lab is a usable,
versioned, integrity-checked adaptive compressor whose specialized transforms
beat zstd-3 and gzip-9 on this pinned mixed starter corpus. It is not the ratio
leader or the general-purpose default yet. Further ratio work needs a new
representation or entropy-model hypothesis and a fresh predeclared public
train/validation split; the private holdout remains sealed.
