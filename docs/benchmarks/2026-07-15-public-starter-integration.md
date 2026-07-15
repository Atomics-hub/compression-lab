# Native-baseline public starter integration

Date: 2026-07-15

This is a repeated adapter-integration result on a small public starter corpus.
It is directional evidence only and does not support a market or
state-of-the-art claim.

## Run contract

- Corpus: 8 digest-pinned real files, 17,792,077 source bytes
- Categories: source code, SQLite database, structured JSON, PDF, compressed ZIP
- Trials: 144 measured after 72 warmups; two measurements per item and codec
- Correctness: 144 of 144 measured round trips reproduced the source SHA-256
- Timing: parent wall clock including Python worker startup
- Native transform: optimized Rust `cdylib`, loaded through `ctypes`
- Selector probe: 16 KiB first stage, optional expansion to 48 KiB

Native baselines recorded in `results.json`:

- Zstandard 1.5.7
- LZ4 1.10.0
- Brotli 1.2.0
- 7-Zip 26.02

## Aggregate result

| Codec | Compressed % | Compress MB/s | Decompress MB/s |
|---|---:|---:|---:|
| LZMA2 level 6 | 32.84 | 1.22 | 6.89 |
| 7-Zip level 5 | 33.09 | 1.99 | 6.97 |
| Brotli level 6 | 35.59 | 5.83 | 7.77 |
| Zstandard level 9 | 35.90 | 6.02 | 7.29 |
| Zstandard level 3 | 38.65 | 7.62 | 7.28 |
| gzip level 6 | 39.13 | 5.57 | 8.18 |
| adaptive-v1 | 43.63 | 6.90 | 7.61 |
| LZ4 level 1 | 50.94 | 7.99 | 7.70 |
| store | 100.00 | 8.19 | 8.02 |

## Gate result

| Check | Result |
|---|---|
| Bit-exact round trips | PASS: 0 failures |
| Bounded expansion | PASS: 0 violating items |
| Selector overhead | PASS: 1.20% versus a 5% ceiling |
| Frontier coverage at 100 Mbps | FAIL: 75.0% versus an 80% target |

The candidate selected no numeric transform because this starter corpus has no
numeric array item. That is a corpus gap, not evidence against the transform.
The candidate still trails the leading ratio codecs substantially and misses
the product gate. The next candidate revision should route between native
Zstandard/LZ4/store plus specialized transforms instead of using gzip-1 as its
only compressed backend.
