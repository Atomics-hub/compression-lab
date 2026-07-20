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

The runner writes one canonical-JSON, atomically promoted receipt per item,
codec, and repetition. Resume accepts a receipt only when its complete field
roster, repository commit, config SHA-256, development-manifest SHA-256, item
identity, repetition, exact command, process types, artifact accounting, and
outcome remain internally consistent. Timeouts, missing tools, nonzero exits,
inexact restoration, or nondeterministic artifact identities remain visible
and cannot be counted as wins.

## Publication contract

Publication is allowed only after all 630 receipts reproduce the complete
105-row summary, every measured round trip is exact, and every five-repetition
artifact group is byte-identical. The publisher independently freezes the
exact codec commands, ten-tool binary roster and identities, source commits,
clean repository state, host identity, config/manifest paths, and 15 preflight
round trips.

The immutable checked-in directory contains exactly five ordinary files:

- `README.md`: human comparison, integrity statement, and claim ceiling;
- `comparison.json`: machine-readable chart rows and evidence bindings;
- `comparison.svg`: all 15 practical standards, size, speed, RSS, and status;
- `evidence.json`: the complete result plus all 630 decision-bearing trial
  receipts; and
- `receipt.json`: SHA-256 identities for every other publication artifact.

Process stdout and stderr can contain machine-local paths. `evidence.json`
therefore replaces only those stream bodies with their UTF-8 byte counts,
SHA-256 commitments, and empty/artifact/redacted classifications. Commands,
timings, RSS, source and artifact identities, exactness, and every field used
to reconstruct a decision remain present. Local absolute-path markers are a
publication error. `scripts/verify-text-source-baseline-publication.py`
reconstructs every aggregate and verifies the complete five-file bundle using
only checked-in evidence; it does not require the ignored corpus or private raw
run directory.

The research-ceiling codecs (ZPAQ, paq8px, cmix, and NNCP) remain a separate
declared tier. They will be measured after the complete practical roster under
their larger frozen resource budget; practical leadership alone is not a
world-best claim. The exact admission, accounting, hardware, and availability
rules are recorded in the
[research-ceiling audit](2026-07-17-text-source-research-ceiling-audit.md).
