# Atompress (JLS2) CLUE-LDS v2 public-validation results

**Status: passed** — category-scoped public-validation product pass on the two
named previously unopened CLUE-LDS temporal ranges.

## Claim ceiling (verbatim)

> A passing v2 score may support only a category-scoped public-validation product
> pass on the two named previously unopened CLUE-LDS temporal ranges. It does not
> change v1, prove a private holdout, establish independent reproduction, cover
> general files, or support universal, market-leading, world-best, or
> state-of-the-art language. A failing or interrupted score must be published
> under the same boundary.

This is a separate, frozen v2 result. The immutable
`clue-jls2-one-time-public-validation-v1` `not_passed` score is **unchanged**; v2
does not correct, replace, or reopen it. The private holdout remains sealed.

## Provenance

- Workflow: `.github/workflows/clue-jls2-public-validation-v2.yml`, run
  **30055586630** (`workflow_dispatch`, success).
- Head SHA: **b187308c86566e74a3243e9fe3664cd87fa3299f** (the #105 merge).
- Readiness lock verified at readiness commit
  **1d49d2b6273fe367c485b55e168f353167c7b5d7** over a clean tree.
- Runner class: GitHub-hosted `ubuntu-22.04`, 4 vCPU.
- Candidate: the dieted JLS2 decoder (`native/src/jls2.rs` lineage PR #74
  `200c74b`), 16 MiB segments, three standalone decode workers, internal
  Zstandard level 6.
- Retained artifact id `8583800718`, digest
  `sha256:ec04bb0fb8a16a0f5ed36b48047a01fcf4e78c080b0a548b9302b05ece92b904`;
  imported evidence sealed under `runs/clue-jls2-public-validation-v2/`
  (42 files; `SHA256SUMS` digest
  `37917103f7d860204c0420c90fc3c880fd789349a86d3d2fc2a5716d44a2cd6d`).

## Scored corpus

Two 250,000-record windows acquired exactly once:

| Item | Inclusive official IDs | Records | Source bytes |
| --- | ---: | ---: | ---: |
| clue-validation-v2-c | 28,000,001 .. 28,250,000 | 250,000 | 49,094,060 |
| clue-validation-v2-d | 40,000,001 .. 40,250,000 | 250,000 | 48,427,665 |

Aggregate source bytes: 97,521,725.

## Aggregate result

Atompress produced **522,423 bytes** on 97,521,725 source bytes (ratio 186.67).
The strongest eligible complete exact-byte result was **brotli-11** at
1,066,789 bytes — a frozen Atompress gain of **51.03%**.

## Full transparent comparison

| Codec | Role | Complete bytes | Ratio | Compress MB/s | Decompress MB/s | Comp peak RSS (B) | Decomp peak RSS (B) | Exact | Atompress smaller? |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| jls2 | candidate | 522,423 | 186.67 | 101.76 | 443.78 | 315,293,696 | 95,367,168 | yes | candidate |
| store | standard | 97,521,725 | 1.00 | 467.73 | 468.94 | 27,320,320 | 27,320,320 | yes | yes |
| lz4-1 | standard | 4,507,497 | 21.64 | 467.22 | 442.36 | 27,381,760 | 27,332,608 | yes | yes |
| gzip-9 | standard | 1,785,462 | 54.62 | 40.58 | 265.63 | 71,680,000 | 121,806,848 | yes | yes |
| bz2-9 | standard | 1,282,965 | 76.01 | 7.79 | 114.62 | 77,565,952 | 124,149,760 | yes | yes |
| zstd-3 | standard | 2,087,888 | 46.71 | 360.48 | 334.19 | 169,611,264 | 120,119,296 | yes | yes |
| zstd-9 | standard | 1,566,128 | 62.27 | 191.70 | 338.06 | 169,414,656 | 119,926,784 | yes | yes |
| zstd-19 | standard | 1,529,312 | 63.77 | 1.15 | 339.76 | 203,988,992 | 119,922,688 | yes | yes |
| brotli-11 | standard | 1,066,789 | 91.42 | 0.35 | 401.87 | 191,561,728 | 27,308,032 | yes | yes |
| lzma-9 | standard | 1,454,624 | 67.04 | 14.89 | 220.11 | 581,771,264 | 170,872,832 | yes | yes |
| 7zip-9 | standard | 1,455,274 | 67.01 | 20.37 | 284.49 | 521,220,096 | 55,652,352 | yes | yes |
| pbc-only | eligible specialist | 12,694,697 | 7.68 | 0.26 | 62.68 | not measured | not measured | yes | yes |
| LogFold | unavailable specialist context | — | — | — | — | — | — | — | — |
| LogPrism | unavailable specialist context | — | — | — | — | — | — | — | — |
| LogLite | unavailable specialist context | — | — | — | — | — | — | — | — |
| DeLog | unavailable specialist context | — | — | — | — | — | — | — | — |

PBC size uses identical corpus bytes; its speed is contextual (separate pinned
specialist harness). Unavailable rows are disclosures, not Atompress wins. The
candidate's compression and standalone-decode peak RSS are measured through the
clean-child instrument `scripts/measure-clean-rss.py`; standard-codec RSS is the
same-run cold-process worker reading.

## Family decisions

| Family | Source bytes | Atompress bytes | Strongest eligible | Eligible bytes | Gain | Passed |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| clue_validation_v2_c | 49,094,060 | 301,050 | brotli-11 | 580,089 | 48.10% | yes |
| clue_validation_v2_d | 48,427,665 | 221,373 | brotli-11 | 486,700 | 54.52% | yes |

## Candidate resource rows (clean-child instrument)

| Operation | Cold-process peak RSS (B) | Shim floor (B) | Floor ≤ 64 MiB | Floor ≤ 25% of reading | Memory gate ≤ 536,870,912 B | Eligible |
| --- | ---: | ---: | --- | --- | --- | --- |
| Cold-process compression | 315,293,696 | 13,557,760 | yes (12.93 MiB) | yes (4.30%) | pass | yes |
| Standalone native decode | 95,367,168 | 13,553,664 | yes (12.93 MiB) | yes (14.21%) | pass | yes |

The worst eligible cold-process standalone decoder peak RSS (95,367,168 B) is the
governing memory-gate value and is well within the 512 MiB (536,870,912 B) limit.
Both readings satisfy the shim-floor eligibility rule (shim floor at most 64 MiB
and at most 25% of the reading), so neither is an instrument failure.

## Speeds

- Aggregate compression: 101.76 MB/s (gate ≥ 100 MB/s).
- Aggregate standalone decode: 443.78 MB/s (gate ≥ 250 MB/s).

## Gates

All 20 frozen gates passed: aggregate ratio, both family ratios, aggregate and
per-repetition compression and standalone-decode speed, clean-child shim-floor
eligibility, compression memory, decompression memory, exact round-trip,
deterministic output, corruption rejection, bounded direct fallback, complete
frame accounting, complete standard roster, PBC specialist present, frozen
candidate paths, development evidence, first-score receipt, and unavailable
markers.

## Decision rule

> The first eligible score is final. Both temporal families, the aggregate, and
> every operational, integrity, memory, accounting, roster, and provenance gate
> must pass. A candidate resource reading is eligible only when its clean-child
> shim floor is at most 64 MiB and at most 25% of the reading; a shim-floor
> violation voids the attempt as an instrument failure and is never converted
> into a pass. No candidate path, parameter, threshold, corpus range, baseline
> setting, instrument, evaluator, runner, or chart rule may change after
> acquisition. A failed or interrupted scored attempt is retained and cannot be
> replaced by a tuned rerun.

Attempt 1 (run 30055586630's predecessor, run 30053212896) failed
pre-acquisition on an unpinned-linter infrastructure fault; no data was acquired
and no attempt was consumed. This scored attempt 2 is the first and only eligible
acquisition.

## What this does and does not establish

- **Does:** a category-scoped public-validation product pass for the dieted JLS2
  decoder on the two named previously unopened CLUE-LDS temporal ranges, with
  full exact-byte, memory, determinism, corruption-rejection, accounting, roster,
  and provenance evidence.
- **Does not:** change the immutable v1 `not_passed` score; prove a private
  holdout; establish independent reproduction; cover general files; or support
  universal, market-leading, world-best, or state-of-the-art language.

## Next steps (owner-gated)

1. Private holdout evaluation (currently sealed).
2. Independent reproduction on a dedicated machine to confirm the hosted-runner
   result.

Both are owner-gated and are prerequisites for any language beyond the
category-scoped boundary above.
