# Moonshot cycle 1, H1 floor arm: first prescreen sweep

**Date:** 2026-07-23
**Lane:** 2 (Pareto moonshot), cycle 1
**Evidence class:** `development_only_prescreen` — synthetic and pinned
public data only. Not a counted development screen, not a candidate result,
not comparable to any frozen CLUE number. No kill/nominate decision is made
in this document; the cycle's kill/nominate report comes after the funded
arms (H1, H8, H6, H9) have all been prescreened.
**Evidence bundle:** `runs/moon-prescreen-cycle1-h1-v1/`

## Setup

- **Arm:** `h1-floor` (PR #76): one shared open-addressed context table,
  2^24 cells x 6 bytes, hashed byte orders {1,2,3,4,6,8} plus sparse and
  word contexts, check-byte collision eviction, mixed by a moon-local
  9-input integer logistic mixer feeding the s0 SSE stage read-only.
  Declared mutable model state: 119,947,264 bytes (~114.4 MiB).
- **Basis:** 24 MiB line-aligned prefix slices of seven corpora — five
  synthetic regimes (seed-pinned generator receipts) and two pinned GH
  Archive hours (2026-05-15-14, 2026-06-15-14). Slice SHA-256s pinned
  before measurement (`slices-receipt.json`).
- **References:** kanzi 2.5.3 `--level=9 --block=1g --jobs=1` and zpaq 7.15
  `-method 54 -threads 1` (local NOJIT arm64 build from the cached source
  zip; output is algorithm-identical to the imported binary), both run on
  the identical slice bytes, binaries SHA-pinned in every receipt.
- **Instrument:** every kernel run measured through the clean tiny-parent
  peak-RSS instrument (PR #77); runner (PR #79) enforced the 160-run cycle
  budget (7 used) and per-run limits.

## Results (base profile, 17-bit SSE)

| Slice | H1 projected bytes | vs local kanzi | vs local zpaq16 | clean peak RSS | exact |
|---|---:|---:|---:|---:|:--:|
| gharchive-2026-05-15-14-s24 | 3,609,680 | 1.287 | 1.265 | 275.2 MiB | yes |
| gharchive-2026-06-15-14-s24 | 3,517,625 | 1.325 | 1.292 | 276.0 MiB | yes |
| moon-syn-low-dup-s24 | 1,231,195 | 1.948 | 1.328 | 278.0 MiB | yes |
| moon-syn-high-dup-s24 | 922,982 | 2.207 | 1.392 | 278.0 MiB | yes |
| moon-syn-many-templates-s24 | 1,108,284 | 2.041 | 1.325 | 276.0 MiB | yes |
| moon-syn-high-sessions-s24 | 1,101,389 | 2.057 | 1.333 | 278.2 MiB | yes |
| moon-syn-jittery-time-s24 | 1,033,755 | 1.971 | 1.269 | 278.6 MiB | yes |

Every run re-decoded byte-exactly and stayed inside the memory budget
(encode-side clean peak ~276-279 MiB, dominated by the 114 MiB model state
plus the resident 24 MiB source, tape, and encode bookkeeping).

Reference note: on every one of these seven slices, kanzi-max beats
zpaq-m54 (by 1.8-2.5% on the GH Archive slices and 47-59% on the highly
templated synthetics) — the opposite ordering from the frozen CLUE items.
Local references per snapshot are not optional.

## Refined-profile probe (18-bit SSE, the one predeclared capacity step)

The single predeclared capacity refinement (`--sse-bucket-bits 18`,
declared state 128,598,016 bytes) was probed on both public slices:
projected complete bytes are **byte-identical to the base profile**
(3,609,680 and 3,517,625). The extra SSE capacity buys nothing on this
data — the same behavior the s0 sibling showed outside crafted colliding
corpora — so the base-profile numbers above are the arm's honest ceiling
at this table size.

## Position against the preregistered kill line

The H1 kill line (cycle-1 draft §2, echoed in every receipt): kill if
projected bytes exceed **1.10x local zpaq -m5 -B16 on at least two public
snapshots** at ≤256 MiB state, or peak decode RSS exceeds 512 MiB.

As measured, both public snapshots sit at **1.265 and 1.292** — well
outside 1.10x — with memory far inside budget. Unless the remaining funded
arms change the picture for the mechanism (H6 composes this floor with the
whole-value-reuse layer that won in S0), the floor arm is on track for its
preregistered kill when the cycle report is written. That would be the
expected outcome class for this lane: most cycles end in kills, and a
clean kill of "bounded 114 MiB single-pass shared-table mixing reaches
ZPAQ-class ratio" is itself the measurement this cycle exists to make.

Honesty caveats recorded now, before the cycle report:

1. 24 MiB slices understate an adaptive model's asymptote more than they
   understate the references' (all models warm up, but the H1 table is
   still filling at slice end). Same-bytes comparison bounds, not removes,
   this effect.
2. The mixer is the audit-mandated real N-input logistic mixer, so the
   "crippled mixing" objection to a kill no longer applies; remaining
   capacity levers (larger table, order tuning) are legitimate cycle-2
   variations if any arm survives near the line — none currently is.

## Next in cycle 1

H8 (frozen offline mixer weights — transferability probe), H6 (floor +
m3-style value reuse), H9 (bounded grammar compression). The cycle
kill/nominate report follows the last prescreen.
