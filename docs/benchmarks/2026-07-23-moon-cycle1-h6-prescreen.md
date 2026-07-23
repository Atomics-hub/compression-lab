# Moonshot cycle 1, H6 hybrid arm: prescreen sweep

**Date:** 2026-07-23
**Lane:** 2 (Pareto moonshot), cycle 1
**Evidence class:** `development_only_prescreen` — synthetic and pinned
public data only. Not a counted development screen, not a candidate result.
No kill/nominate decision is made here; the cycle report follows the
remaining funded arms.
**Evidence bundle:** `runs/moon-prescreen-cycle1-h6-v1/`
**Companion:** H1 floor sweep,
`docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md`.

## Arm

`h6-hybrid` (PR #82, loss-exact firewall revision `cde31a2`): the H1
shared-table mixing floor plus a whole-line reuse layer that faithfully
reimplements s0's M3 cache mechanism (65,536 slots x 128-byte values,
CLOCK with reference protection) at NDJSON-line granularity. One charged
decision bit per line; reference hits charge a 16-bit slot tree and skip
the line's bytes; misses flow through the byte-identical H1 floor and then
teach the cache. The reuse layer's decision and reference bits charge
through a dedicated mixer fully disjoint from the floor's, so on the miss
substream the floor loss is bit-for-bit pure H1 (audit-mandated
loss-exactness, asserted in tests). Declared mutable state: 148,654,078
bytes (~141.8 MiB).

## Results (same 24 MiB pinned slices and references as the H1 sweep)

| Slice | H1 projected | H6 projected | H6 vs H1 | H6 vs local zpaq16 | exact |
|---|---:|---:|---:|---:|:--:|
| gharchive-2026-05-15-14-s24 | 3,609,680 | 3,612,689 | +0.08% | 1.266 | yes |
| gharchive-2026-06-15-14-s24 | 3,517,625 | 3,520,639 | +0.09% | 1.293 | yes |
| moon-syn-low-dup-s24 | 1,231,195 | 1,234,053 | +0.23% | 1.331 | yes |
| moon-syn-high-dup-s24 | 922,982 | 925,763 | +0.30% | 1.396 | yes |
| moon-syn-many-templates-s24 | 1,108,284 | 1,095,668 | −1.14% | 1.310 | yes |
| moon-syn-high-sessions-s24 | 1,101,389 | 1,104,216 | +0.26% | 1.337 | yes |
| moon-syn-jittery-time-s24 | 1,033,755 | 1,036,610 | +0.28% | 1.272 | yes |

All seven runs re-decode byte-exactly; clean peak RSS 305–331 MiB, inside
the budget. Cycle run budget after this sweep: 21 of 160.

## Reading

Whole-LINE reuse buys nothing on this data. Real log lines are near-unique
at byte granularity (timestamps, ids, counters), so exact-line cache hits
essentially never fire on the GH Archive slices, and the arm pays its one
decision bit per line for nothing (+0.08–0.09%). The synthetic regimes
repeat *values*, not whole lines (each emitted line carries a fresh
timestamp/sequence), so the same tax appears there; only the
many-templates regime has enough exact-line collisions to profit (−1.14%).

Against H6's preregistered kill line — beat max(H1-alone, M3-alone) by
≥3% on the public set — the hybrid currently *loses* to H1-alone on both
public snapshots.

The mechanism lesson is sharper than the number: S0's M3 won at
whole-VALUE (field) granularity after parsing, and that repetition is
invisible to an exact whole-line cache at raw byte granularity. This is
direct evidence for the deferred H5 (content-defined chunking below line
granularity) and raises the interest of H9 (grammar compression, which
captures repeated phrases without alignment) — both would target exactly
the repetition this arm provably could not reach.

## Next in cycle 1

H8 (frozen offline mixer weights) and H9 (bounded grammar compression),
then the cycle kill/nominate report over all funded arms.

## Deviation record: the two H6 sweeps (runs 8–14 and 15–21)

H6 was measured twice. Runs **8–14** were the *first* H6 sweep; runs
**15–21** (the seven receipts published above as
`runs/moon-prescreen-cycle1-h6-v1/`) are the corrected re-run. Both sets are
retained. The superseded first sweep is published additively — receipts, RSS
reports, sweep-summary, and a `SHA256SUMS` — under
`runs/moon-prescreen-cycle1-h6-v1/superseded-runs-8-14/`; no tapes are kept.

**Why superseded.** The first sweep **under-declared the arm's mutable model
state**. It reported `declared_model_state_bytes = 129,517,566`; the corrected
figure is `148,654,078` (the ~141.8 MiB quoted under *Arm*). The correction
adds the reuse layer's **dedicated mixer** — which H6 runs fully disjoint from
the H1 floor mixer, so it is separately-held mutable state that must be charged.
The 19,136,512-byte delta is exactly one M5 mixer's declared state:
`MIXER_BUCKETS · MIXER_ENTRY_BYTES + (1 << SSE_BASE_BUCKET_BITS) · SSE_NODES · 2`
= `2^20 · 10 + 2^17 · 33 · 2` = `10,485,760 + 8,650,752` =
`19,136,512` bytes. (`native/src/moon/h6.rs` `h6_declared_state_bytes` sums the
floor plus `reuse_mixer_bytes + reuse_sse_bytes`; the corrected total is
regression-pinned at `148,654,078` in
`declared_state_accounts_for_floor_cache_reference_and_decisions`.) The single
committed touch of `h6.rs` (PR #82, `0baf774`) already carries the corrected
formula, so the fix was made in-flight between the two sweeps and is not a
separate commit; the mechanism above is reconstructed arithmetically from the
h6 constants and matches the observed delta exactly.

**Why the measurements are unaffected.** `declared_model_state_bytes` is a
declared accounting quantity; it does not enter the coder. Every compression
measurement is **byte-identical** across the two sweeps: same tape bytes and
tape SHA-256, same `projected_complete_bytes`, same ratios per snapshot. Only
the declared state and the trivially process-dependent `peak_rss`/`wall_seconds`
differ (separate processes). The results table and the reading above are
therefore unchanged by the correction.

**Budget.** Both sweeps consumed real budget: 7 runs each, 14 H6 runs total.
That honest count is why the cycle report attributes **14 of the 36** cycle-1
runs to H6 even though only seven H6 receipts are the published record. The
absent run indices 8–14 in the public sequence (1–7 H1, 15–21 H6, 22–29 H9,
30–36 H8) are exactly this superseded first sweep, now published here.
