# Moonshot cycle 1, H9 grammar arm: prescreen sweep (KILL)

**Date:** 2026-07-23
**Lane:** 2 (Pareto moonshot), cycle 1
**Evidence class:** `development_only_prescreen` — synthetic and pinned
public data only. Not a counted development screen, not a candidate result.
**Evidence bundle:** `runs/moon-prescreen-cycle1-h9-v1/`
**Companions:** H1 floor sweep
(`docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md`) and H6 hybrid
sweep (`docs/benchmarks/2026-07-23-moon-cycle1-h6-prescreen.md`).

## Arm

`h9-grammar` (PR #84, branch `agent/moon-h9-grammar`): the offline
bounded-grammar prescreen arm — a naive offline Re-Pair pass that repeatedly
replaces the most frequent digram with a fresh nonterminal up to a fixed
rule budget, the diversifier of the cycle-1 slate. It captures repeated
phrases without byte alignment, the repetition class the H6 exact whole-line
cache provably could not reach.

**Preregistered kill line:** kill if bounded-grammar size > 1.3x local
ZPAQ-16MiB on the public set.

## What happened: the kill is computational, upstream of the ratio

The preregistered ratio kill-line was **never evaluable**. Naive offline
Re-Pair is worst-case O(rule_budget x n) per pass, and at prescreen scale on
realistic NDJSON it did not finish a single snapshot inside budget. Every
run in this sweep terminated at the runner's hard wall limit. No grammar
size was ever produced, so **no ratio numbers exist and none are quoted**.

The observed kill is therefore computational infeasibility of naive offline
Re-Pair at prescreen scale on realistic data, not a measured ratio.

## Sizing decision (why 12 MiB, then 4 MiB, and not 24 MiB)

The 24 MiB cycle basis used by the H1/H6 sweeps was **never attempted** for
H9. PR #84's measured synthetic throughput (~42.5 KB/s) projects ~593 s to
process 24 MiB against a 600 s per-run budget — no margin. The helm went
straight to 12 MiB slices, then to 4 MiB to confirm, rather than spend runs
on a 24 MiB attempt certain to time out.

## Results

Runner budget was 600 s per run plus a hard-kill grace; every run reports
`status: killed_by_budget`, `kill_reason: wall_timeout`, `wall_seconds`
630.0. The kernel receipts carry `null` for every downstream field
(projected bytes, ratios, decode-match, peak RSS) because none was reached.

**s12 (12 MiB slices), runs 22–25:**

| Snapshot | status | kill_reason | wall_seconds |
|---|---|---|---:|
| gharchive-2026-05-15-14-s12 | killed_by_budget | wall_timeout | 630.0 |
| gharchive-2026-06-15-14-s12 | killed_by_budget | wall_timeout | 630.0 |
| moon-syn-high-dup-s12 | killed_by_budget | wall_timeout | 630.0 |
| moon-syn-many-templates-s12 | killed_by_budget | wall_timeout | 630.0 |

**s4 (4 MiB slices), runs 26–29:**

| Snapshot | status | kill_reason | wall_seconds |
|---|---|---|---:|
| gharchive-2026-05-15-14-s4 | killed_by_budget | wall_timeout | 630.0 |
| gharchive-2026-06-15-14-s4 | killed_by_budget | wall_timeout | 630.0 |
| moon-syn-high-dup-s4 | killed_by_budget | wall_timeout | 630.0 |
| moon-syn-many-templates-s4 | killed_by_budget | wall_timeout | 630.0 |

8 of 8 timed out. Quartering the input to 4 MiB did not bring any snapshot,
public or synthetic, inside budget.

## Coverage (stated explicitly, no silent caps)

Only **4 of the 7 cycle corpora** were attempted per size: both GH Archive
hours (2026-05-15-14, 2026-06-15-14) and two synthetic regimes
(moon-syn-high-dup, moon-syn-many-templates). After 8/8 timeouts across both
sizes, the remaining 3 synthetic regimes were **not spent** — running them
would only re-buy the same wall-timeout. This is a deliberate coverage stop,
recorded here so it is not mistaken for a full-corpus result.

## Predicted vs observed

- **Predicted kill:** ratio-based — bounded-grammar size > 1.3x local
  ZPAQ-16MiB on the public set.
- **Observed kill:** wall-time — naive offline Re-Pair does not terminate
  within the per-run budget at prescreen scale, at 12 MiB or 4 MiB.

The observed kill fires **upstream of the ratio**: the arm never produces a
size to compare, so the preregistered criterion is not reached, let alone
passed or failed. The two are mechanically distinct and are reported as
distinct.

## Disposition

**H9 is KILLED for cycle 1.** The kill is naive offline Re-Pair's
compute cost at prescreen scale on realistic data, not any ratio it
achieved. An incremental Re-Pair (priority queue plus per-symbol occurrence
lists, near-linear rather than O(rule_budget x n)) is a **possible cycle-2
proposal, not funded now**; it would need its own preregistration and budget
before any run.

Cycle run budget after this sweep: **29 of 160** (7 H1 + 14 H6 + 8 H9).

## Next in cycle 1

The cycle kill/nominate report over all funded arms (H1, H8, H6, H9),
pending the remaining slate.
