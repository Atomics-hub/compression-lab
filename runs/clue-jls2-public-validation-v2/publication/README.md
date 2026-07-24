# Atompress (JLS2) CLUE-LDS v2 public-validation first score

Status: **passed**.

This is the second, separately frozen one-time public validation on two previously unopened CLUE-LDS ranges. It does not correct, replace, or reopen the immutable v1 not_passed score.

Atompress produced 522,423 bytes on 97,521,725 source bytes. The strongest eligible complete exact-byte result was brotli-11 at 1,066,789 bytes, a frozen Atompress gain of 51.03%.

Candidate peak RSS is measured through the clean-child instrument: cold-process compression peak 315,293,696 bytes (shim floor 13,557,760 bytes); standalone decode peak 95,367,168 bytes (shim floor 13,553,664 bytes).

![Complete compressed-byte comparison](comparison.svg)

## Full transparent comparison

| Codec | Role | Complete bytes | Ratio | Compress MB/s | Decompress MB/s | Exact | Atompress smaller? | Measurement basis |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| jls2 | candidate | 522,423 | 186.67 | 101.76 | 443.78 | yes | candidate | same-run complete-file; standalone native pass on same host and corpus |
| store | standard | 97,521,725 | 1.00 | 467.73 | 468.94 | yes | yes | same-run complete-file; same-run complete-file |
| lz4-1 | standard | 4,507,497 | 21.64 | 467.22 | 442.36 | yes | yes | same-run complete-file; same-run complete-file |
| gzip-9 | standard | 1,785,462 | 54.62 | 40.58 | 265.63 | yes | yes | same-run complete-file; same-run complete-file |
| bz2-9 | standard | 1,282,965 | 76.01 | 7.79 | 114.62 | yes | yes | same-run complete-file; same-run complete-file |
| zstd-3 | standard | 2,087,888 | 46.71 | 360.48 | 334.19 | yes | yes | same-run complete-file; same-run complete-file |
| zstd-9 | standard | 1,566,128 | 62.27 | 191.70 | 338.06 | yes | yes | same-run complete-file; same-run complete-file |
| zstd-19 | standard | 1,529,312 | 63.77 | 1.15 | 339.76 | yes | yes | same-run complete-file; same-run complete-file |
| brotli-11 | standard | 1,066,789 | 91.42 | 0.35 | 401.87 | yes | yes | same-run complete-file; same-run complete-file |
| lzma-9 | standard | 1,454,624 | 67.04 | 14.89 | 220.11 | yes | yes | same-run complete-file; same-run complete-file |
| 7zip-9 | standard | 1,455,274 | 67.01 | 20.37 | 284.49 | yes | yes | same-run complete-file; same-run complete-file |
| pbc-only | eligible specialist | 12,694,697 | 7.68 | 0.26 | 62.68 | yes | yes | identical bytes; separate pinned specialist run; separate pinned specialist run; contextual |
| LogFold | unavailable specialist context | unavailable | unavailable | unavailable | unavailable | unavailable | not measured | unavailable or ineligible; unavailable or ineligible |
| LogPrism | unavailable specialist context | unavailable | unavailable | unavailable | unavailable | unavailable | not measured | unavailable or ineligible; unavailable or ineligible |
| LogLite | unavailable specialist context | unavailable | unavailable | unavailable | unavailable | unavailable | not measured | unavailable or ineligible; unavailable or ineligible |
| DeLog | unavailable specialist context | unavailable | unavailable | unavailable | unavailable | unavailable | not measured | unavailable or ineligible; unavailable or ineligible |

PBC size uses identical corpus bytes but its speed is contextual because it ran in a separate pinned specialist harness. Unavailable rows are disclosures, not Atompress wins.

## Family decisions

| Family | Source bytes | Atompress bytes | Strongest eligible | Eligible bytes | Gain | Passed |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| clue_validation_v2_c | 49,094,060 | 301,050 | brotli-11 | 580,089 | 48.10% | yes |
| clue_validation_v2_d | 48,427,665 | 221,373 | brotli-11 | 486,700 | 54.52% | yes |

## Frozen gates

| Gate | Result |
| --- | --- |
| aggregate compression speed | pass |
| aggregate ratio | pass |
| aggregate standalone decompression speed | pass |
| all family ratio | pass |
| bounded direct fallback | pass |
| clean child shim floor eligibility | pass |
| complete frame accounting | pass |
| complete standard roster | pass |
| compression memory | pass |
| corruption rejection | pass |
| decompression memory | pass |
| deterministic output | pass |
| development evidence | pass |
| exact roundtrip | pass |
| first score receipt | pass |
| frozen candidate paths | pass |
| minimum compression repetition speed | pass |
| minimum standalone decompression repetition speed | pass |
| pbc specialist present | pass |
| unavailable markers | pass |

## Evidence boundary

A passing v2 score may support only a category-scoped public-validation product pass on the two named previously unopened CLUE-LDS temporal ranges. It does not change v1, prove a private holdout, establish independent reproduction, cover general files, or support universal, market-leading, world-best, or state-of-the-art language. A failing or interrupted score must be published under the same boundary.

The private holdout remains sealed.
