# Moonshot cycle 1, H8 static-mixer arm: prescreen sweep (KILL)

**Date:** 2026-07-23
**Lane:** 2 (Pareto moonshot), cycle 1
**Evidence class:** `development_only_prescreen` — synthetic and pinned
public data only. Not a counted development screen, not a candidate result,
not comparable to any frozen CLUE number.
**Evidence bundle:** `runs/moon-prescreen-cycle1-h8-v1/`
**Companions:** H1 floor sweep
(`docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md`), H6 hybrid sweep
(`docs/benchmarks/2026-07-23-moon-cycle1-h6-prescreen.md`), and H9 grammar
sweep (`docs/benchmarks/2026-07-23-moon-cycle1-h9-prescreen.md`).

## Arm

`h8-static-mixer` (PR #88, merged at `91b4371`): the cycle-1 **transferability
probe** (draft §2-H8). It keeps H1's adaptive shared 96 MiB context table and
adaptive SSE but **replaces** H1's adaptive per-context logistic mixer — and
the s0 adaptive mixer table it fed — with a **frozen static weight vector**
(129 weights, 516 B) indexed by `(context slot x confidence bucket)`, learned
OFFLINE on the pinned public month-A slice only. It asks cheaply whether
mixing's benefit is structural and transferable or must be learned live per
stream; its answer gates the H2 distillation family. Declared mutable model
state: **109,314,564 bytes** (context table 100,663,296 + adaptive SSE
8,650,752 + frozen weights 516). No `s0` edits.

**Preregistered kill line** (byte-identical in kernel and runner receipts):
> Kill if frozen-mixer complete bytes exceed 1.02x adaptive H1 complete bytes
> on the unseen month.

**Month discipline** (helm-pinned before any measurement): train month A =
`gharchive-2026-05-15-14` slice `-s24`, eval month B = `gharchive-2026-06-15-14`
slice `-s24` (unseen holdout). The frozen weights were trained only on month A;
month B was read for the first time in this sweep.

## Results (same 24 MiB pinned slices and references as the H1/H6 sweeps)

Adaptive-H1 complete bytes are the base-profile numbers published in the H1
sweep; the H8/H1 column is the preregistered kill quantity.

| Snapshot | H8 complete bytes | H1 complete bytes | H8/H1 | wall (s) |
|---|---:|---:|---:|---:|
| gharchive-2026-05-15-14-s24 (train A) | 4,069,501 | 3,609,680 | 1.1274 | 121.48 |
| gharchive-2026-06-15-14-s24 (eval B, unseen) | 3,998,995 | 3,517,625 | **1.1368** | 120.38 |
| moon-syn-high-dup-s24 | 1,062,773 | 922,982 | 1.1515 | 108.93 |
| moon-syn-high-sessions-s24 | 1,306,701 | 1,101,389 | 1.1864 | 141.68 |
| moon-syn-jittery-time-s24 | 1,222,639 | 1,033,755 | 1.1827 | 140.00 |
| moon-syn-low-dup-s24 | 1,496,400 | 1,231,195 | 1.2154 | 212.76 |
| moon-syn-many-templates-s24 | 1,336,677 | 1,108,284 | 1.2061 | 257.71 |

Runs 30–36, all `status: measured`. All seven re-decode byte-exactly. Clean
peak RSS is 264.6 MiB on every run — 8.6 MiB **over** the draft's 256 MiB
target, but safely under the binding 512 MiB runner decode gate. Wall time
108.9–257.7 s per run, all comfortably
under the 600 s per-run budget (consistent with PR #88's pre-merge 155.21 s
measurement on the real 24 MiB month-A item). Cycle run budget after this
sweep: **36 of 160**.

## Position against the preregistered kill line

- **Predicted kill:** frozen-mixer complete bytes exceed 1.02x adaptive H1
  complete bytes on the unseen month.
- **Observed:** on the unseen month B, H8/H1 = **1.1368 > 1.02** → **KILL,
  decisive** (the arm misses the line by ~11.7 points, not a marginal miss).

The frozen mixer also loses in-distribution: on the train month A the arm is
already at H8/H1 = 1.1274 (~12.7% worse than adaptive H1 on the very data its
weights were fit to). The synthetic regimes are worse still, 1.15–1.22.

## Interpretation (three points, stated mechanically)

1. **Bounded attribution of the loss (audit P2-A, binding).** H8 removes not
   only H1's adaptive mixer weights but also M5's secondary adaptive
   recalibration mix (it keeps SSE only). That direction of change handicaps
   H8, so the ~12–14% loss measured here is a **bounded, jointly-attributed**
   quantity — frozen weights *and* removed recalibration together — not a pure
   measurement of weight-freezing alone. Clean attribution of the freezing
   cost by itself would require an H1 variant with the M5 recalibration mix
   also removed; that variant was not built or run this cycle.

2. **The transfer question is attribution-clean.** Whatever the loss's
   composition, the train→eval gap is only ~0.9 points (1.1274 on seen
   month A → 1.1368 on unseen month B). What the evidence establishes is
   narrow and specific: **this frozen-mixer design — which also removed M5's
   secondary recalibration — lost by a similar margin on both tested months**,
   so month-to-month transfer is not what drives its loss. That is enough to
   leave H2 unfunded. **Live per-stream adaptivity is the leading
   explanation** for the residual loss, but on two months against one frozen
   design it is not established as a universal result. This reading does not
   depend on decomposing the loss, so P2-A does not weaken it.

3. **Consequence (per the helm review).** H8 did not survive its kill line, so
   the **H2 distillation family stays UNFUNDED for cycle 2.** The prescreen was
   built to answer exactly this gating question, and the answer is negative.

## Provenance (evidence record)

The adversarial implementation audit independently retrained the frozen mixer
from the pinned month-A slice (sha `a6873fde…`) and reproduced the committed
`h8-static-mixer-weights.bin` **byte-identically** (weight file sha256
`ad0d73cdfcac3e376731852eaf99b1c146a933e9f8efbdd49743bf7b538c908e`),
establishing training determinism and month-A-only lineage in one check. The
references are the same local kanzi-max and zpaq `-method 54` build used across
the cycle (`local-references-s24.json`, sha `5fb1a001…`), run on the identical
slice bytes.

## Disposition

**H8 is KILLED for cycle 1**, decisively, on its preregistered unseen-month
kill line. The transferable signal is that static offline mixing does not
recover live adaptive mixing on this data (the loss is nearly the same seen and
unseen), which is why the H2 distillation family is not funded for cycle 2. The
kill/nominate report over all funded arms is
`docs/benchmarks/2026-07-23-moon-cycle1-report.md`.
