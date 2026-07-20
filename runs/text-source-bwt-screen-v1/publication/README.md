# BWT decomposition screen: rejected on both tracks

![All four BWT diagnostics against Kanzi-max](comparison.svg)

> **Claim ceiling:** Training-split custom Kanzi pipeline decomposition only. Complete archives are exact competitor diagnostics, not Axiom artifacts, Axiom wins, validation results, private-holdout results, independent reproduction, novel-algorithm results, or state-of-the-art evidence.

All 32 retained trials decoded exactly and produced byte-identical repeats. Every custom BWT chain was larger than Kanzi-max on both training tracks, so neither track admitted a token-BWT prototype. No Axiom artifact was built and `axiom_wins` remains 0.

## Source code: CPython + TypeScript

Decision: `reject_raw_bwt_direction_for_track`.

| Baseline / diagnostic | Complete bytes | Gain vs Kanzi-max | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Kanzi max (level 9) | 6,221,486 | 0.00% | 11.28x | 8.86% | — | — | — / — | ✅ / ✅ | immutable practical comparison baseline |
| TB1 TEXT + UTF + BWT / TPAQX | 8,608,181 | -38.36% | 8.15x | 12.26% | 2.43 | 2.30 | 1599.22 / 1477.31 | ✅ / ✅ | rejected: 38.36% larger than Kanzi-max; no signal |
| TB2 TEXT + UTF + BWT + SRT + ZRLT / TPAQX | 8,383,238 | -34.75% | 8.37x | 11.94% | 5.23 | 5.25 | 1584.83 / 1462.89 | ✅ / ✅ | rejected: 34.75% larger than Kanzi-max; no signal |
| TB3 level-6 control / FPAQ | 8,457,517 | -35.94% | 8.30x | 12.05% | 15.84 | 24.86 | 726.52 / 736.16 | ✅ / ✅ | rejected: 35.94% larger than Kanzi-max; no signal |
| TB4 raw BWT + SRT + ZRLT / TPAQX | 8,383,704 | -34.75% | 8.37x | 11.94% | 2.93 | 3.68 | 1632.14 / 1519.05 | ✅ / ✅ | rejected: 34.75% larger than Kanzi-max; no signal |

## English Wikimedia: Wikibooks + Wikinews

Decision: `reject_raw_bwt_direction_for_track`.

| Baseline / diagnostic | Complete bytes | Gain vs Kanzi-max | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Kanzi max (level 9) | 24,156,788 | 0.00% | 5.56x | 18.00% | — | — | — / — | ✅ / ✅ | immutable practical comparison baseline |
| TB1 TEXT + UTF + BWT / TPAQX | 28,362,606 | -17.41% | 4.73x | 21.13% | 2.87 | 3.14 | 1662.50 / 1529.03 | ✅ / ✅ | rejected: 17.41% larger than Kanzi-max; no signal |
| TB2 TEXT + UTF + BWT + SRT + ZRLT / TPAQX | 27,399,632 | -13.42% | 4.90x | 20.41% | 3.71 | 3.53 | 1652.52 / 1519.03 | ✅ / ✅ | rejected: 13.42% larger than Kanzi-max; no signal |
| TB3 level-6 control / FPAQ | 27,565,891 | -14.11% | 4.87x | 20.54% | 9.36 | 19.07 | 781.17 / 805.88 | ✅ / ✅ | rejected: 14.11% larger than Kanzi-max; no signal |
| TB4 raw BWT + SRT + ZRLT / TPAQX | 27,470,474 | -13.72% | 4.89x | 20.47% | 2.14 | 2.35 | 1528.12 / 1528.61 | ✅ / ✅ | rejected: 13.72% larger than Kanzi-max; no signal |

## Evidence boundary

- Frozen result SHA-256: `ef0c65b19ba6a7a6d5f3a9c439f5b2a5f9b563dec133862b4225b9490723e9fd`.
- Trial-receipt manifest SHA-256: `db50944920790df3959c84855ac7525d8d94c3c12b350de8dddd95a120d51c2b`.
- Public evidence SHA-256: `ca4706658dab1f23b4becfba80b274b1c57aa488c52fa95e84211c949bfb5eef`.
- Size accounting: Every byte value is one complete decodable .knz archive per item, aggregated once over the identical two-item track.
- Speed and memory: BWT rows show same-host medians and peak RSS from the retained trials. Baseline speed/RSS was not copied into this diagnostic result and is intentionally blank.
- Publication and verification are offline: no corpus, reserved evaluation, public validation, or private holdout bytes are required or accessed.
