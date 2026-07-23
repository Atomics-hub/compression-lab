# Moonshot cycle 1: kill/nominate report

**Date:** 2026-07-23
**Lane:** 2 (Pareto moonshot), cycle 1
**Evidence class:** every number below is `development_only_prescreen` —
synthetic and pinned public data only. No counted development screen was
earned this cycle, no candidate or SOTA claim is made, and nothing here is
comparable to a frozen CLUE number.

This report closes cycle 1 over the full helm-approved funded slate — H1
(floor), H8 (frozen static mixer), H6 (whole-line reuse hybrid), H9 (bounded
grammar) — after all four have been prescreened. Per-arm evidence bundles and
sweep charts:

- H1: `runs/moon-prescreen-cycle1-h1-v1/`,
  `docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md`
- H8: `runs/moon-prescreen-cycle1-h8-v1/`,
  `docs/benchmarks/2026-07-23-moon-cycle1-h8-prescreen.md`
- H6: `runs/moon-prescreen-cycle1-h6-v1/`,
  `docs/benchmarks/2026-07-23-moon-cycle1-h6-prescreen.md`
- H9: `runs/moon-prescreen-cycle1-h9-v1/`,
  `docs/benchmarks/2026-07-23-moon-cycle1-h9-prescreen.md`

## Outcome in one line

**All four funded arms are KILLED at prescreen. No arm earned a counted
development screen.** Cycle run budget consumed: **36 of 160** (7 H1 + 14 H6 +
8 H9 + 7 H8). The E1-established ~21.3% headroom on `json_logs` remains
unreached by any bounded-memory arm this cycle.

## Predicted vs observed, per arm

### H1 — floor (shared hashed mixing + confirm-byte eviction)

- **Preregistered kill line:** projected bytes exceed 1.10x local
  zpaq `-m5 -B16` on ≥2 public snapshots at ≤256 MiB state, or peak decode
  RSS > 512 MiB.
- **Observed:** both public snapshots sit at **1.265** and **1.292** vs local
  zpaq16 — far outside 1.10x — with peak RSS ~276 MiB, inside budget. Across
  all seven slices the zpaq16 ratio ranges **1.265–1.392x**; the single
  predeclared capacity refinement (18-bit SSE) produced **byte-identical**
  projected bytes on both public slices, so the base numbers are the arm's
  honest ceiling at this table size.
- **Disposition:** **KILLED.** Bounded ~114 MiB single-pass shared-table
  mixing does not reach ZPAQ-class ratio on this data. The audit-mandated real
  N-input logistic mixer is in place, so "crippled mixing" is not an available
  objection to the kill.

### H8 — frozen static mixer (transferability probe)

- **Preregistered kill line:** frozen-mixer complete bytes exceed 1.02x
  adaptive H1 complete bytes on the unseen month.
- **Observed:** on the unseen month B, H8/H1 = **1.1368 > 1.02** (decisive; the
  arm also loses in-distribution at 1.1274 on train month A, and 1.15–1.22 on
  synthetics). All seven runs measured, decode-matched, peak RSS 264.6 MiB.
- **Disposition:** **KILLED.** Per the audit P2-A caveat, the ~12–14% loss is
  bounded, jointly attributed to freezing the weights *and* removing M5's
  secondary recalibration — not a pure weight-freezing measurement. But the
  train→eval gap is only ~0.9 points, which is attribution-clean: this
  frozen-mixer design lost by a similar margin on both tested months, so
  month-to-month transfer is not what drives its loss — enough to leave H2
  unfunded. Live per-stream adaptivity is the leading explanation for the
  residual loss, though on two months against one frozen design it is not a
  universal result. **Consequence: the H2 distillation family stays UNFUNDED
  for cycle 2.**

### H6 — whole-line reuse hybrid (floor + m3-style value reuse)

- **Preregistered kill line:** beat max(H1-alone, M3-alone) by ≥3% on the
  public set.
- **Observed:** the hybrid **loses** to H1-alone on both public snapshots
  (+0.08% and +0.09% — the arm pays one decision bit per line for cache hits
  that essentially never fire on real log lines). Only the many-templates
  synthetic, with enough exact whole-line collisions, profits at **−1.14%**.
- **Disposition:** **KILLED.** Real log lines are near-unique at byte
  granularity (timestamps, ids, counters), so an exact whole-line cache reaches
  none of the whole-*value* repetition that won in S0's M3. This is direct
  evidence for the deferred H5 (sub-line content-defined chunking); the
  whole-line reuse mechanism itself is dead at this granularity.

### H9 — bounded grammar (naive offline Re-Pair, the diversifier)

- **Preregistered kill line:** bounded-grammar size > 1.3x local
  zpaq-16MiB on the public set (a **ratio** criterion).
- **Observed:** the ratio kill-line was **never evaluable.** Naive offline
  Re-Pair (worst case O(rule_budget x n)) did not finish a single snapshot
  inside the 600 s per-run budget: **8 of 8 runs wall-timeout** at 12 MiB and
  again at 4 MiB. The 24 MiB basis was never attempted (~42.5 KB/s projects
  ~593 s, no margin). No grammar size was produced, so no ratio numbers exist
  and none are quoted.
- **Disposition:** **KILLED**, computationally — upstream of the ratio. The
  observed kill is compute infeasibility of naive offline Re-Pair at prescreen
  scale on realistic NDJSON, distinct from the (never-reached) ratio criterion.

## Budget accounting

| Arm | Runs | Cumulative |
|---|---:|---:|
| H1 | 7 | 7 |
| H6 | 14 | 21 |
| H9 | 8 | 29 |
| H8 | 7 | 36 |

H6's 14 runs are two 7-run sweeps: the corrected published sweep (runs 15–21)
plus a superseded first sweep (runs 8–14) that under-declared model state and is
retained at `runs/moon-prescreen-cycle1-h6-v1/superseded-runs-8-14/` — see the
deviation record in the H6 prescreen doc.

**36 of 160** cycle runs consumed. 124 runs remain unspent; they are not
carried as credit — a cycle-2 slate would preregister its own budget.

## Transferable signals for cycle-2 hypothesis formation

Stated conservatively; each is grounded in a published sweep above, not in a
counted screen.

1. **Per-stream adaptivity is the leading explanation for the mixing value.**
   H8 shows this frozen-mixer design (which also removed M5's secondary
   recalibration) loses ~12–14% and by a similar margin on both tested months —
   so the cost is not cross-month transfer, and live adaptivity is the leading
   explanation rather than an established universal result. Freezing the mixer
   to distill it away is not promising on this data.
2. **Whole-line reuse is dead; static mixtures are dead.** H6 shows exact
   whole-line caching buys nothing on realistic logs (loses to the floor on
   both public snapshots); H8 shows a static weight mixture cannot recover the
   adaptive mixer. Neither mechanism is worth re-funding as-is.
3. **The repetition that matters is sub-line, whole-value.** S0's positive M3
   signal was whole-*value* (field) reuse after parsing; H6 confirms it is
   invisible to a raw whole-line cache. A sub-line, content-defined or
   field-granular reuse mechanism (deferred H5) targets exactly this gap.
4. **Incremental Re-Pair is a possible but UNFUNDED cycle-2 proposal.** H9's
   kill was compute, not ratio: an incremental Re-Pair (priority queue +
   per-symbol occurrence lists, near-linear rather than O(rule_budget x n))
   could make the ratio evaluable, but it would need its own preregistration
   and budget before any run.
5. **The H2 distillation family stays UNFUNDED** for cycle 2, per H8's answer.

None of these clears the standing bar: the E1 census puts ~21.3% recoverable
headroom on `json_logs`, and no cycle-1 arm reached it under a bounded-memory,
practical-decode budget. Most cycles are expected to end in kills; publishing
four honest kills and the mechanism lessons above is the measurement this cycle
existed to make.

## Status

Cycle 1 is **CLOSED**. No frozen moonshot protocol exists yet and nothing in
this lane is authorized to read development items. A cycle-2 slate, if opened,
must preregister its arms, kill lines, and budget anew.
