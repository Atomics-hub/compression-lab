# Moonshot cycle 2, C3 live-adaptation arm: prescreen sweep (KILL)

**Date:** 2026-07-23
**Lane:** 2 (Pareto moonshot), cycle 2
**Evidence class:** `development_only_prescreen` — pinned public data only.
Not a counted development screen, not a candidate result, not comparable to
any frozen CLUE number.
**Evidence bundle:** `runs/moon-cycle2-c3-prescreen-v1/`
**Cycle charter:** `docs/benchmarks/2026-07-23-moonshot-cycle2-charter.md`
**H1 floor comparison:** the original cycle-1 H1 receipts
(`docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md`), unchanged.

## Arm

`c3-live-adaptation` (arm id 104), the first and cheapest arm of the cycle-2
slate and the attribution-clean test of the live-adaptation hypothesis. It
holds H1's contexts, grammar, and hashed-mixing structure identical and changes
**only** the counter dynamics — a fast-cold / slow-warm nonstationary EWMA
update — plus a **neutral-residual adaptive recalibration (APM) chain** layered
on H1's identical context set. Every part is live per stream; nothing is frozen
offline, no new context is added, and no reference decision is charged. Declared
mutable model state: **126,238,720 bytes**, identical on both snapshots.

## Preregistration (frozen before execution)

The public prescreen manifest `config/moon-c3-public-prescreen-v1.json`
(sha256 `0c4c9202ace9b3108fc636228973ded6e8873800852adbd2b694bcfdc6856924`)
was **merged to main in PR #95 before either public snapshot was measured**.
It fixes the arm id, the H1 floor bytes per snapshot, the slice basis, and the
integer kill rule.

**Preregistered kill criterion** (byte-identical in the manifest, kernel
receipts, and runner receipts):

> Kill if C3 complete bytes are at least 0.97x H1 complete bytes on both public
> snapshots, OR any exactness, identity, ledger, unaccounted-state, 600-second
> wall, or 512 MiB decode-RSS gate fails.

The rule is an **exact integer, two-snapshot AND**: kill when
`C3_bytes * 100 >= H1_bytes * 97` on **both** snapshots; equality kills; any
operational gate failure kills regardless of ratio. It is applied by
`scripts/moon-prescreen-runner.py::c3_ratio_gate_kills`. Prose percentages in
this report do not override that integer rule.

## Operational preflight (all clean)

- **Synthetic precheck (off-ledger, PR #94):** exact 4 MiB encode + immediate
  redecode, 29.515582375 s wall, 177.093494250 s projected at 24 MiB (inside
  the 600 s wall with margin), 164,970,496 B clean peak RSS, 126,238,720 B
  declared state. The precheck **passed**; it reproduced byte-identically
  cross-machine in the implementation audit. This kill is a ratio kill on real
  data, not an operational failure.
- **Exactness:** both runs re-decode byte-exactly — kernel receipts carry
  `decode_matches_source: true` and `decoded_sha256` equal to the source
  sha256 on both snapshots.
- **Resource gates:** clean peak RSS ~295.7 MiB on both runs (295,747,584 and
  295,731,200 B), well under the 512 MiB decode gate. Walls 211.85 s and
  245.66 s, both under the 600 s per-run budget.
- **State accounting:** declared model state 126,238,720 B on both runs;
  ledger `raw_literal_bytes: 0`; no unaccounted warm state.

## Results (both pinned public snapshots)

H1 floor complete bytes are the original cycle-1 H1 receipts named in the
frozen manifest; the C3/H1 column is the preregistered kill quantity.

| Snapshot | C3 complete bytes | H1 floor bytes | C3/H1 | integer test `C3·100 ≥ H1·97` | wall (s) | peak RSS (B) |
|---|---:|---:|---:|:--:|---:|---:|
| gharchive-2026-05-15-14-s24 | 3,845,577 | 3,609,680 | 1.065351 | 384,557,700 ≥ 350,138,960 → **True** | 211.85 | 295,747,584 |
| gharchive-2026-06-15-14-s24 | 3,745,493 | 3,517,625 | 1.064779 | 374,549,300 ≥ 341,209,625 → **True** | 245.66 | 295,731,200 |

Runs 37–38, both `status: measured`, `kill_reason: null` (no operational gate
fired; the kill is the ratio verdict). C3 is **6.54% larger than H1 on
2026-05-15** and **6.48% larger on 2026-06-15** — it loses to the floor on both
snapshots. Cycle run budget after this sweep: **38 of 160**.

### Reference framing (recorded, not a kill quantity)

The prescreen also records C3 against the local kanzi-max and zpaq `-method 54`
builds computed on the identical slice bytes (`local-references-s24.json`,
sha `5fb1a001…`):

| Snapshot | C3 / local kanzi | C3 / local zpaq16 |
|---|---:|---:|
| gharchive-2026-05-15-14-s24 | 1.3713 | 1.3472 |
| gharchive-2026-06-15-14-s24 | 1.4106 | 1.3756 |

For context, cycle-1 H1 sat at 1.2646 / 1.2919 against local zpaq16 on these
same two snapshots. C3 is **worse against the zpaq16 reference than H1 is** on
both — consistent with, and no softer than, the H1-floor verdict above.

## Predicted vs observed (mechanical)

- **Predicted kill:** C3 complete bytes `>= 0.97 * H1` on **both** public
  snapshots (integer `C3·100 >= H1·97`), equality killing.
- **Observed:** both snapshots satisfy the integer test (True and True), so the
  two-snapshot AND gate `c3_ratio_gate_kills` returns **True** → **KILL**. The
  arm misses by a wide margin: it is ~6.5% *larger* than H1, not marginally
  over a 3%-smaller bar.

The predicted and observed kills coincide exactly: a ratio kill on real data,
with every operational gate clean. There is no upstream (compute/exactness)
kill here — unlike H9 — and no jointly-attributed removal — unlike H8.

## Interpretation (leading explanation; one frozen design, two snapshots)

C3 changed **only** counter update dynamics (fast-cold / slow-warm EWMA) and
added a neutral-residual APM recalibration chain, on H1's **identical** contexts
and grammar, with everything live. Against that single frozen design it lost
~6.5% on **both** real snapshots. The mechanically bounded reading:

- On this data, **faster nonstationary adaptation over the same context set
  miscalibrates rather than helps** — the added update speed and residual-APM
  layer cost bits instead of recovering them.
- Therefore the cycle-1 "live adaptivity" signal is **not about update
  dynamics.** Speeding the counters over H1's fixed context set is not the lever.

This is stated as the **leading explanation**, not a proven universal: it rests
on one frozen C3 design and two public snapshots. It does **not** claim live
adaptivity is worthless in general — only that this specific realization of
"more/faster live adaptation over the same structure" regresses here. The
remaining cycle-2 candidates that target **richer context / expert structure**
rather than update speed — C1 (byte match model as a mixer input), C2 (pooled
whole-value reuse), and C6 (their composition) — are unaffected by this result
and remain the live tests of the adaptivity hypothesis.

## Provenance (evidence record)

The adversarial implementation audit verdict was **sound-with-P2s, no P0/P1**:
the measurement is valid. Determinism and charging honesty were verified
independently, and the synthetic precheck reproduced **byte-identically**
cross-machine. The two public runs decode-match their sources, declare a
constant 126,238,720 B model state, and were produced under the manifest frozen
in PR #95 before execution. References are the same local kanzi-max and zpaq
`-method 54` build used across the lane, run on the identical slice bytes.

## Disposition

**C3 is KILLED for cycle 2** on its preregistered two-snapshot ratio line,
decisively (~6.5% over the floor on both snapshots), with every operational gate
clean. The transferable signal: on this data, faster live counter dynamics plus
neutral-residual recalibration over H1's identical context set do not beat the
floor — so the live-adaptation hypothesis, if it holds at all, is not about
update speed but about richer context/expert structure, which the surviving
C1/C2/C6 arms test next.
