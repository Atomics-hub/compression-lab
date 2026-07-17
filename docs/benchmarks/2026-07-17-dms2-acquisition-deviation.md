# DMS2 first-acquisition deviation

Status: public-validation bytes acquired; zero compression scores started.

The first and only authorized DMS2 acquisition exposed an acquisition-scope
bug before scoring. The frozen wrapper invoked the successor corpus fetcher for
the complete `public_validation` split, so it acquired two record-table items
in addition to the two dense-matrix item IDs explicitly frozen in the DMS2
lock.

The complete first-acquisition manifest is retained with SHA-256
`187ea52098338107d41893bb358536e710edb949e6bbc0b1400e7a9e6ba177c7`.
No DMS2 or baseline compression was run before the deviation was identified.

## Pre-score resolution

The scoring manifest is projected deterministically to the exact ordered
`authorization.expected_item_ids` already committed in
`config/dms2-public-validation-lock.json`:

1. `uci-gisette-train`
2. `uci-madelon-train`

The projection does not consult file contents, sizes, entropy, compressibility,
or codec output. The candidate, format, baselines, evaluator, pass thresholds,
and single-score limit remain unchanged. The unchanged benchmark runner still
rejects any manifest whose item IDs, families, tracks, order, licenses, byte
lengths, or SHA-256 digests differ from the frozen gates.

The two unexpectedly acquired record-table items are retained and disclosed
but excluded from DMS2 scoring:

| Item | Bytes | Exact item SHA-256 | Status |
|---|---:|---|---|
| `uci-student-dropout` | 533,230 | `3ef126de5cefff26eb11fbb4237f1a1401cb64b488e2f1d598c23cedeb4c45ae` | acquired, unscored |
| `uci-room-occupancy` | 931,630 | `c090ee5c94b61762bfec9d22767864490b51030f98cca030f02822468db25d9c` | acquired, unscored |

This deviation consumes those two record-table families for future honest
validation planning. They must not later be described as sealed or fresh.

## Claim ceiling

This record proves only that the acquisition deviation was detected and
resolved before scoring with an ID-based rule that was frozen in advance. It
is not compression-performance evidence. Any DMS2 performance claim still
depends on the retained first score, the frozen evaluator, private holdout, and
independent reproduction gates.
