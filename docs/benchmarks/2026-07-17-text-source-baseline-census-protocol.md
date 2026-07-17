# Text and source practical baseline census protocol

## Purpose

This census identifies the real ratio and speed frontier on the seven verified
development items before any Axiom representation or model is selected. It is
development evidence only. Public validation remains sealed and the census
cannot support a product win, market-leading, world-best, or state-of-the-art
claim.

The executable protocol is frozen in
`config/text-source-baseline-toolchain-v1.json`. The development input receipt
is `runs/text-source-development-acquisition-v1.json`.

## Comparable unit

Each competitor receives one identical complete derived item and must emit one
self-contained artifact that can restore that item exactly. Every artifact byte
is counted. There are no external dictionaries, uncounted models, hidden
preprocessors, or directory-solid advantages.

All ratio runs use one codec thread. Each item/codec pair receives one warmup
and five shuffled measured repetitions. A result is eligible only when all five
round trips are exact and all five artifact SHA-256 identities match. Median
wall time is reported, peak child RSS is retained, and source-code and English
Wikimedia tracks are ranked separately.

## Required practical roster

| Codec | Frozen ratio setting |
| --- | --- |
| store | exact byte copy |
| LZ4 1.10.0 | level 1, one thread |
| host gzip | level 9, deterministic header |
| bzip2 1.0.8 | level 9 |
| bzip3 1.5.3 | 511 MiB block, one job |
| zstd 1.5.7 | levels 3, 9, 19, and ultra 22; one thread |
| Brotli 1.2.0 | quality 11 |
| host XZ | LZMA2 preset 9 extreme, one thread |
| 7-Zip 26.02 | LZMA2 level 9 and PPMd level 9; one thread; complete `.7z` bytes |
| Kanzi 2.5.3 | level 9, 1 GiB maximum block, one job |
| libbsc 3.3.12 | 512 MiB block, adaptive QLFC (`-e2`) |

Kanzi is built from commit
`6eea1658897019ab3107df2806d5e534ef0798df`; libbsc is built from commit
`5e5c2ef0fb1298626936b091f6e4ae539e5b0071`. Both source archives are bound by
exact byte counts and SHA-256 values. The bootstrap records the compiler-facing
configuration and resulting host binary identities. bzip3 is the exact 1.5.3
Homebrew bottle on this macOS measurement host.

## Failure and resumption rules

The runner writes one atomically promoted receipt per item, codec, and
repetition. Resume accepts a receipt only when its repository commit, config
SHA-256, and development-manifest SHA-256 match the current attempt. Timeouts,
missing tools, nonzero exits, inexact restoration, or nondeterministic artifact
identities remain visible and cannot be counted as wins.

The research-ceiling codecs (ZPAQ, paq8px, cmix, and NNCP) remain a separate
declared tier. They will be measured after the complete practical roster under
their larger frozen resource budget; practical leadership alone is not a
world-best claim.
