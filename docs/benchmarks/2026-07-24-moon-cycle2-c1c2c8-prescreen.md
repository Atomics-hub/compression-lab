# Moonshot cycle 2, C1/C2/C8 match-mixer / value-context / expert-mixture: prescreen sweep (1 survives, 2 killed)

**Date:** 2026-07-24
**Lane:** 2 (Pareto moonshot), cycle 2
**Evidence class:** `development_only_prescreen` — pinned public data only.
Not a counted development screen, not a candidate result, not comparable to
any frozen CLUE number.
**Evidence bundle:** `runs/moon-cycle2-c1c2c8-prescreen-v1/`
**Cycle charter:** `docs/benchmarks/2026-07-23-moonshot-cycle2-charter.md`
**H1 floor comparison:** the original cycle-1 H1 receipts
(`docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md`), unchanged.

## Arms

Three arms measured in a single frozen sweep, in the manifest-fixed order
C1 → C2 → C8 (C2's reducer reads C1's receipts):

- **`c1-match-mixer`** (arm id 105) — adds a byte-level match model as a mixer
  input over H1's identical context set, targeting the repeat mass the H1 loss
  decomposition attributed to inside-long-repeat coding. Declared mutable model
  state **136,773,760 bytes**, identical on both snapshots.
- **`c2-value-context`** (arm id 106) — pooled whole-value reuse: value-context
  views feeding a shared string pot, targeting the ~78% string_value / ~11%
  number_value loss share. Declared model state **220,676,096 bytes**.
- **`c8-expert-mixture`** (arm id 107) — replaces H1's shared logistic mixer
  with per-bucket expert gating under non-negative weights. Declared model state
  **119,963,648 bytes**.

## Preregistration (frozen before execution)

The public prescreen manifest
`config/moon-cycle2-c1c2c8-public-prescreen-v1.json`
(sha256 `433d7eb641d49d82cb83b1e03fd7042725c906bc0c6f914db7a991924d44f872`)
was **merged to main in PR #107 (commit 6b1f1ff) before any of the six runs
was measured**. It fixes each arm id, the H1 floor bytes per snapshot, the slice
basis, the integer kill rules, and the kernel commit
(`kernel_commit 1519bbc`, `native/` untouched through 6b1f1ff). The runner
config actually executed is copied into the bundle as
`sweep-cycle2-c1c2c8-config.json` (sha256 `9d6d37e0…`); the local references
snapshot is `local-references-s24.json` (sha256 `5fb1a001…`).

**Preregistered kill criteria** (byte-identical in the manifest, kernel
receipts, and runner receipts):

- **C1:** kill if C1 complete bytes are at least 0.90x H1 on **both** public
  snapshots (integer `C1·100 >= H1·90`, two-snapshot AND; equality kills), or
  any operational gate fails. Reducer
  `scripts/moon-prescreen-runner.py::c1_ratio_gate_kills`.
- **C2:** kill if C2 crosses `0.95 * H1` on **both** snapshots (integer
  `C2·100 >= H1·95`) **OR** C2 is no smaller than C1 on **both** snapshots
  (`C2 >= C1`) — a disjunction, each side an AND over both snapshots; equality
  kills/crosses; or any operational gate fails. Reducer
  `c2_ratio_gate_kills`.
- **C8:** kill if C8 complete bytes are at least 0.93x H1 on **both** snapshots
  (integer `C8·100 >= H1·93`, two-snapshot AND; equality kills), or any
  operational gate fails. Reducer `c8_ratio_gate_kills`.

Prose percentages in this report do not override those integer rules. The
frozen H1 floor complete bytes are **3,609,680** (gharchive-2026-05-15-14-s24)
and **3,517,625** (gharchive-2026-06-15-14-s24).

## Operational preflight (all clean)

Every one of the six measured runs passed all operational gates; no gate fired
on any arm, so all three verdicts are ratio verdicts on real data.

- **Synthetic prechecks (off-ledger):** each arm's 4 MiB exact-redecode
  precheck passed before the sweep — C1 (PR #103, 185,466,880 B clean peak RSS),
  C2 (PR #101, 260,030,464 B), C8 (PR #102, 156,139,520 B), all
  `decode_matches_source true`.
- **Exactness:** all six runs re-decode byte-exactly — kernel receipts carry
  `decode_matches_source: true` and `decoded_sha256` equal to the source
  sha256 on both snapshots.
- **Resource gates:** clean peak RSS is well under the 512 MiB (536,870,912 B)
  decode gate on every run — C1 ≈ 293.9 / 291.9 MiB (308,150,272 /
  306,036,736 B), C2 ≈ 372.1 MiB (390,217,728 B on both), C8 ≈ 276.5 / 276.1
  MiB (289,947,648 / 289,488,896 B). All six walls are under the 600 s per-run
  budget (max 271.0 s).
- **State accounting:** declared model state is constant per arm across both
  snapshots (C1 136,773,760 B; C2 220,676,096 B; C8 119,963,648 B); ledger
  `raw_literal_bytes: 0`; no unaccounted warm state.

## Results (both pinned public snapshots)

Complete bytes are `projected_complete_bytes` from each runner receipt; the
kill quantity is the integer comparison shown per arm.

### C1 (`c1-match-mixer`) — vs 0.90x H1

| Snapshot | C1 complete bytes | H1 floor bytes | C1/H1 | integer test `C1·100 ≥ H1·90` | wall (s) | peak RSS (B) |
|---|---:|---:|---:|:--:|---:|---:|
| gharchive-2026-05-15-14-s24 | 3,255,543 | 3,609,680 | 0.901891 | 325,554,300 ≥ 324,871,200 → **True** | 271.0 | 308,150,272 |
| gharchive-2026-06-15-14-s24 | 3,116,902 | 3,517,625 | 0.886082 | 311,690,200 ≥ 316,586,250 → **False** | 242.7 | 306,036,736 |

Two-snapshot AND: True **and** False → `c1_ratio_gate_kills` = **False**.

### C2 (`c2-value-context`) — vs 0.95x H1, and vs C1

| Snapshot | C2 complete bytes | H1 floor bytes | C2/H1 | `C2·100 ≥ H1·95` | C1 complete bytes | `C2 ≥ C1` | wall (s) | peak RSS (B) |
|---|---:|---:|---:|:--:|---:|:--:|---:|---:|
| gharchive-2026-05-15-14-s24 | 3,417,834 | 3,609,680 | 0.946852 | 341,783,400 ≥ 342,919,600 → False | 3,255,543 | 3,417,834 ≥ 3,255,543 → **True** | 220.5 | 390,217,728 |
| gharchive-2026-06-15-14-s24 | 3,328,189 | 3,517,625 | 0.946144 | 332,818,900 ≥ 334,174,375 → False | 3,116,902 | 3,328,189 ≥ 3,116,902 → **True** | 213.7 | 390,217,728 |

H1 side: False and False → does not kill. C1-dominance side: True and True →
kills. Disjunction → `c2_ratio_gate_kills` = **True**.

### C8 (`c8-expert-mixture`) — vs 0.93x H1

| Snapshot | C8 complete bytes | H1 floor bytes | C8/H1 | integer test `C8·100 ≥ H1·93` | wall (s) | peak RSS (B) |
|---|---:|---:|---:|:--:|---:|---:|
| gharchive-2026-05-15-14-s24 | 3,590,055 | 3,609,680 | 0.994563 | 359,005,500 ≥ 335,700,240 → **True** | 231.2 | 289,947,648 |
| gharchive-2026-06-15-14-s24 | 3,499,017 | 3,517,625 | 0.994710 | 349,901,700 ≥ 327,139,125 → **True** | 176.8 | 289,488,896 |

Two-snapshot AND: True **and** True → `c8_ratio_gate_kills` = **True**.

All six runs are `status: measured`, `kill_reason: null` (no operational gate
fired). Runs 47–52.

### Specialist confrontation (charter-required for survivors)

The charter requires any survivor to be confronted with the local kanzi-max and
zpaq `-method 54` builds computed on the identical slice bytes
(`local-references-s24.json`, sha `5fb1a001…`) **before** any counted
development screen may be proposed. Nomination requires the arm to be no larger
than local zpaq16 on the snapshots. C1 is the only survivor:

| Snapshot | C1 bytes | local kanzi-max | C1 / kanzi-max | local zpaq -m54 | C1 / zpaq16 |
|---|---:|---:|---:|---:|---:|
| gharchive-2026-05-15-14-s24 | 3,255,543 | 2,804,326 | 1.1609 | 2,854,515 | 1.1405 |
| gharchive-2026-06-15-14-s24 | 3,116,902 | 2,655,198 | 1.1739 | 2,722,828 | 1.1447 |

C1 is **larger than both local specialists on both snapshots** → it does **not**
meet the nomination bar (`<= local zpaq16`). No counted development screen is
proposed or earned.

## Predicted vs observed (mechanical)

- **C1:** predicted kill iff `C1·100 >= H1·90` on both; observed True/False →
  **survives** the kill line.
- **C2:** predicted kill iff (`C2·100 >= H1·95` on both) OR (`C2 >= C1` on
  both); observed the C1-dominance side fires (True/True) → **killed**.
- **C8:** predicted kill iff `C8·100 >= H1·93` on both; observed True/True →
  **killed**.

Predicted and observed verdicts coincide exactly on all three arms, every
operational gate clean.

## Interpretation (leading explanations; one frozen design per arm, two snapshots)

- **C1 (survives, keep-alive lead, not a candidate).** Adding the byte match
  model as a mixer input buys real bits over the H1 floor: aggregate
  6,372,445 / 7,127,305 = **0.8941x H1 (10.59% smaller)**, per-snapshot
  0.90189x / 0.88608x (**9.81% / 11.39% smaller**). But it crosses its 0.90x
  kill line on only one of the two snapshots, so it does **not** kill and does
  **not** meet the survivor line for a nominee — and it is 1.14–1.17x the local
  specialists on both snapshots. Note honestly: the charter keep-alive text
  ("at least 10% smaller than H1") has **no frozen integer reducer**, so both
  the per-snapshot readings (9.81% / 11.39%) and the aggregate reading (10.59%)
  are published without a mechanical pass/fail; the only frozen verdicts are
  "survived the kill line" and "did not earn a screen". C1 is classified a
  **keep-alive research lead for a future cycle**, not a candidate.
- **C2 (killed by the C1-dominance clause).** The pooled value-context views add
  real signal vs H1 (0.9469 / 0.9461, both under the 0.95 line — the H1 side
  does not kill), but strictly **less** than the match model adds: C2 >= C1 on
  both snapshots, so the dominance clause fires. The frozen rule retires this
  implementation — whatever whole-value reuse contributes here is subsumed by
  C1's repeat-mass gain.
- **C8 (killed decisively on the 0.93 line).** The expert-mixture with
  non-negative gating essentially matched the H1 floor — only ~0.5% smaller
  (0.9946 / 0.9947), far above the 0.93x line. Replacing H1's shared logistic
  mixer with per-bucket expert gating bought almost nothing on real data.

These are stated as leading explanations, not proven universals: each rests on
one frozen arm design and two public snapshots.

## Runs-budget accounting (including a disclosed tooling failure)

This sweep's first attempt failed for a tooling reason and is disclosed in full.
The runner was pointed at a kernel binary path that had never been built (an
upstream cargo `-p` invocation failed silently), so all six runs of the first
attempt were charged with status `encode_failed` / kill_reason
`encode_nonzero_exit` (see `attempt1-toolfail/`, run indices 41–46, wall
~0.18 s each, all numeric fields null). The ledger was charged honestly for the
wasted budget and the measured re-run separately:

- 40 consumed before this sweep (36 cycle 1 + 4 decomposition/C3-era per the
  existing ledger history).
- → **46** after the six-run tooling failure (attempt 1, `encode_failed`).
- → **52** after the six measured re-runs (runs 47–52).

Cycle run budget after this sweep: **52 of 160**. Cycle-2 spend so far
= **16 of 60** (runs 37–52), within the cycle-2 allowance of at most 60 runs
beyond cycle 1's 36. Tapes stay out of git; all six tape sha256 values are
pinned in `SHA256SUMS` and match the `tape_sha256` fields in the kernel
receipts.

## What is and is not authorized next

- **C1:** a keep-alive research lead only. Any future work on the match-mixer
  requires a **new cycle proposal** with its own preregistered lines; C1 earned
  **no counted development screen** in cycle 2 (it did not meet the survivor
  nomination bar against the local specialists).
- **C2, C8:** killed; retired for cycle 2.
- **C6 (composition of C1 and C2):** the charter requires **both** C1 and C2 to
  survive before C6 is built. C2 died, so **C6 is not built and not
  authorized**.
- No development, validation, or holdout access is authorized. Everything here
  is `development_only_prescreen` on pinned public GH Archive slices; nothing in
  this report is comparable to any frozen CLUE number.

## Provenance (evidence record)

The six measured runs decode-match their sources, declare constant per-arm model
state, and were produced under the manifest frozen in PR #107 (commit 6b1f1ff)
before execution, kernel built from main at `kernel_commit 1519bbc` with
`native/` untouched. References are the same local kanzi-max and zpaq
`-method 54` builds used across the lane, run on the identical slice bytes. The
disclosed attempt-1 tooling failure is retained under `attempt1-toolfail/` with
its own sweep-summary so the honest ledger charge (40 → 46 → 52) is auditable.
