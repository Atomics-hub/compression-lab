# Pareto moonshot cycle 2 charter

**Date:** 2026-07-23  
**Status:** build and public/synthetic prescreen approved; no development,
validation, or private-holdout access authorized  
**Evidence class:** all cycle-2 measurements remain
`development_only_prescreen` until a separately frozen owner-dispatched gate
says otherwise.

## Objective

Test whether memory-efficient live adaptation and uncharged sub-line reuse can
close the JSON/log ratio gap left by cycle 1 while preserving exact decoding,
bounded memory, and practical execution. Every enhancement compares with the
original published H1 floor; cycle 2 does not move its baseline mid-cycle.

## Funded slate and order

1. **C3 — nonstationary counters plus adaptive recalibration.** Cheapest
   attribution-clean test of the live-adaptation hypothesis and the first build.
2. **C1 — byte match model as a mixer input.** Flagship live sub-line reuse
   mechanism with no charged reference decision.
3. **C2 — pooled whole-value reuse as a mixer input.** Structure-aware test of
   the positive S0-M3 signal without H6's line-level decision tax.
4. **C5 — bounded-block BWT transform.** Orthogonal block-sorting diversifier.
5. **C4 — incremental Re-Pair.** Precheck-gated only; no full sweep unless its
   synthetic throughput and memory projection clear the declared bounds.
6. **C6 — C1+C2 composition.** Built only if both components survive.

H2/static distillation, whole-line reuse, per-lane context splitting, charged
online dictionaries, and naive `O(rule_budget * n)` Re-Pair remain unfunded.

## Binding execution discipline

- The original H1 cycle-1 receipts remain the comparison floor for every arm.
- Before any public measurement, every arm must demonstrate encode plus
  immediate exact redecode on a seed-pinned synthetic 4 MiB item. The arm must
  project at least 1.5x margin under the 600-second 24 MiB wall or preregister a
  smaller public slice basis before measurement.
- Synthetic throughput prechecks are off-ledger. Every read of a pinned public
  slice is a counted run, including a throughput probe.
- Each arm's kernel constant and runner `KILL_LINES` string must be
  byte-identical and covered by a binding test.
- The persistent cycle budget remains capped at 160 total runs. Cycle 1 used
  36. Cycle 2 may spend at most 60 additional runs without a new owner ruling.
- Decode RSS above 512 MiB, wall time above 600 seconds, non-exact redecode,
  identity mismatch, ledger divergence, or unaccounted warm state is a recorded
  kill or invalid attempt according to the preregistered rule.
- No edit may alter S0 behavior, protected `native/src/lib.rs`, frozen
  protocols, or published run artifacts.
- No development item is read unless a surviving arm first earns a separately
  preregistered counted screen and the owner dispatches it.

## Arm gates

- **C3:** kill if both public snapshots are `>= 0.97 * H1` complete bytes, or
  resource/exactness gates fail. Record quarter-by-quarter bits per byte to
  distinguish warm-up from capacity limits.
- **C1:** kill if both public snapshots are `>= 0.90 * H1`, or resource/exactness
  gates fail.
- **C2:** kill if both public snapshots are `>= 0.95 * H1`, if it is no smaller
  than C1 on both public snapshots, or resource/exactness gates fail.
- **C5:** kill if both public snapshots are `> 1.10 * local zpaq16`, suffix-array
  construction exceeds the preregistered wall, or resource/exactness gates
  fail.
- **C4:** stop before public runs if the synthetic 4 MiB precheck projects over
  500 seconds at 24 MiB or projects over 512 MiB RSS. If cleared, kill when the
  public grammar result exceeds `1.15 * local zpaq16` or operational gates fail.
- **C6:** build only if C1 and C2 survive; kill if both public snapshots are
  `>= 0.95 * min(C1, C2)` or operational gates fail.

Exact integer comparisons, rounding direction, reference framing, slice basis,
and resource scopes must be frozen in each arm's implementation PR before the
first public run. Prose percentages do not override those integer rules.

## Outcomes

- **Kill:** the arm crosses its preregistered kill line.
- **Keep-alive:** at least 10% smaller than H1 but still larger than local
  zpaq16. This is a cycle-3 research lead, not a candidate.
- **Nominate:** complete bytes `<= local zpaq16` on at least two disjoint public
  snapshots, exact on every item, peak decode RSS `<= 512 MiB`, quarantine and
  leave-one-out attribution clean, and every warm state decoder-reproducible or
  charged. Nomination requests a separately frozen development screen; it does
  not authorize one.

Every completed arm receives a published comparison chart, raw receipts,
complete-size and speed/resource rows, exact evidence stage, and claim ceiling.

## Immediate authorization

C3 implementation may begin from `origin/main`. Its first PR may add only the
isolated arm, shared moonshot-only helpers, constants/runner bindings, synthetic
tests, and the synthetic precheck path. It may not measure a pinned public slice
until implementation review is complete and its public prescreen config is
frozen in a later commit.

