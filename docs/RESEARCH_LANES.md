# Active research lanes

**Read this before touching the repo.** It exists so that any agent or
contributor picking up this project knows what is active, what is frozen, what
is dead, and which rules are load-bearing. Updated when a lane opens, closes,
or changes status. Status date: 2026-07-23.

## Standing rules (apply to every lane)

1. **Honest evidence is the product.** Conservative claims, published negative
   results, exact reproducible measurements. Measurements and receipts outrank
   model opinions.
2. **Sealed data stays sealed.** Consumed validation families are never
   reused. Private holdout identities are absent from this repo by design.
   Opening a validation or holdout path is a one-way door that only the
   project owner dispatches.
3. **Development-data looks are budgeted.** Screens that read licensed
   development items leak information with every look. Prescreen on synthetic
   or public data (unlimited); frozen development screens are counted and
   preregistered (manifests, runner, verifier, freeze record, one shot).
4. **Frozen artifacts are immutable.** Published runs under `runs/`, frozen
   protocols under `docs/benchmarks/`, and the protected JLS2 entry source
   `native/src/lib.rs` (SHA-256
   `ec3ba58920c8701c3eac6a6c4150c3b4474248e203376c158ec376a2b3411127`) must not
   change. `native/Cargo.toml` is pinned by the frozen A3 preflight
   (SHA-256 `984a69ab00314eaef3659fbc7642c0ea738f7d19d3895cf6530738278691c707`);
   do not edit it without understanding that binding.
5. Small branches from `origin/main`, CI green before merge, no new
   dependencies without cause.

## Lane 1 (V2 DESIGN APPROVED 2026-07-23): JLS2 decoder memory

- **Frozen result (immutable):** under the one-acquisition/one-score frozen
  contract, JLS2's public validation is a recorded `not_passed` (run
  `29606109504`, exit code 2). That no-pass is final; the diagnostic below
  invalidates the *reading*, not the *result*. JLS2 did not pass, "would not
  have passed" / "now passes" are barred, and there is no recomputed frozen
  score. See
  `docs/benchmarks/2026-07-23-jls2-memory-gate-instrument-addendum.md`.
- **Resolution:** the 621.3 MiB reading that failed the memory gate is a
  measurement-instrument artifact, not decoder memory. Five diagnostic
  rounds (`docs/benchmarks/2026-07-23-jls2-rss-instrument-diagnostic.md`,
  evidence `runs/jls2-rss-instrument-diagnostic-v1/`, PR #75) proved that
  `wait4` `ru_maxrss` for a child spawned from a large Python parent reports
  the parent's footprint: decoding a 1 MB source reads 698.8 MiB on that
  instrument, byte-identical to a 200 MB decode. Measured cleanly (PR #77's
  tiny-parent instrument), the dieted decoder (PR #74) peaks at 162.9 MiB at
  full parallelism on a 200 MB synthetic item — about 3x under the gate.
- **What remains is an owner decision, not engineering:** any corrected
  memory re-validation is a *new, separately frozen protocol* on previously
  unopened validation families — not a re-score of this consumed, frozen
  attempt. Owner-dispatched, followed in sequence by the sealed private
  holdout and independent reproduction. Validation-path dispatch stays
  owner-only.
- **Owner decision:** build a full fresh public-validation v2 protocol for the
  current dieted shipping decoder on two untouched 250k-record CLUE-LDS ranges
  (28,000,001–28,250,000 and 40,000,001–40,250,000), using the clean tiny-parent
  RSS instrument. Design, implementation, and freeze are approved; acquisition
  and scoring remain separately owner-dispatched. Decision record:
  `docs/benchmarks/2026-07-23-jls2-public-validation-v2-owner-decision.md`.
- **V2 RESULT — PASSED (category-scoped), 2026-07-24:** the fresh v2 protocol
  scored `passed` on the two named previously unopened ranges (run
  `30055586630`, head `b187308`, 20/20 gates): 522,423 B vs brotli-11 1,066,789 B
  (51.03% aggregate gain; families 48.10%/54.52%), worst eligible clean-child
  standalone-decode peak RSS 95,367,168 B (< 512 MiB gate). This is a separate
  frozen result and does **not** change the immutable v1 `not_passed`. Evidence
  sealed under `runs/clue-jls2-public-validation-v2/`; results doc
  `docs/benchmarks/2026-07-24-clue-jls2-public-validation-v2-results.md`.
  Dedicated-machine independent confirmation and the sealed private holdout
  remain pending and owner-gated.
- **Corollary:** the A2 context-reuse and inline-single-worker "no effect"
  results likely compared polluted readings against polluted readings;
  reread before citing them, pending confirmation of each run's exact
  measurement path.
- **Prior status (historical):** goal was 621.3 → ≤ 512 MiB via Route 1
  (decoder-only) or owner-gated Route 2 (format trade). Route 1's buffer
  diet (PR #74) merged and remains valuable (real live-memory reduction);
  Route 2 is moot.

### CI defect discovered during Lane 1 (2026-07-23, FIXED)

**History.** The Windows CI jobs ran multi-command `run:` blocks under pwsh,
which only propagates the LAST command's exit code — so the `cargo test`
failures for `native/` were silently swallowed on Windows since at least #68.
Two `clab-s0-kernel` tests (`default_sse_bucket_bits_are_seventeen_and_recorded`,
`refined_bits_hold_the_tape_and_move_only_mixer_loss`) build tape filenames via
`{bits:?}`, embedding quotes that Windows forbids, so they never passed on
Windows. The file is byte-pinned by the S0 freeze record
(`test_json_log_s0_freeze_record`), so the in-file fix is barred (PR #80 was
withdrawn for exactly this).

**Resolution (owner-authorized).** The enforcement gap is closed:

1. Every multi-command pwsh `run:` block in `ci.yml` and `release.yml` was
   split so each command is its own step (one pwsh-cmdlet block, the Windows
   archive assembly in `release.yml`, instead uses `$ErrorActionPreference =
   'Stop'` plus an explicit `$LASTEXITCODE` check). Each command's exit code
   now fails the job on Windows, matching the fail-fast behaviour the
   non-Windows (bash) legs already had.
2. The Windows matrix leg of the native `cargo test` steps skips exactly those
   two freeze-pinned tests via `-- --skip
   default_sse_bucket_bits_are_seventeen_and_recorded --skip
   refined_bits_hold_the_tape_and_move_only_mixer_loss` (their filenames are
   illegal on NTFS). No other native test is skipped, and the non-Windows legs
   are unchanged.

Windows now runs all native tests except those two named skips.

## Lane 2 (ACTIVE — CYCLE 2 APPROVED 2026-07-23): the Pareto moonshot

- **Goal:** move the ratio/memory/speed Pareto frontier for structured-text
  compression — ZPAQ-class ratios at practical decode budgets. Not a raw-ratio
  chase; the Shannon wall and the E1 census bound what "better ratio" can
  mean.
- **Evidence base (from two honest kills):** E2-A showed the frontier is
  purchasable with context memory (592–1,272 MiB decode RSS — unacceptable);
  S0 showed a bounded structure-aware kernel loses to brute mixing (best arm
  6.0× Kanzi), that whole-value reuse is the one strongly positive mechanism
  (+53.7 MB attribution), and that per-lane context fragmentation and charged
  dictionary misses are net losses.
- **Method:** hypothesis batches → cheap prescreens on synthetic/public
  corpora → survivors earn a counted, preregistered development screen
  (S0-style freeze: constants manifests, runner, independent verifier,
  clean-checkout confirmation, one measurement). Every cycle has a compute
  ceiling; most cycles are expected to end in kills, and kills are published.
- **Status (2026-07-23):** cycle 1 CLOSED — all four funded arms KILLED at
  prescreen, no counted development screen earned, 36 of 160 cycle runs used.
  Kill/nominate report: `docs/benchmarks/2026-07-23-moon-cycle1-report.md`.
  Helm-approved slate:
  H1 (shared hashed mixing + confirm-byte eviction, the floor arm, built in
  PR #76 with a moon-local N-input integer logistic mixer after audit),
  then H8 (frozen offline mixer weights), H6 (hybrid with the m3-style
  value-reuse layer), H9 (bounded grammar compression, the diversifier).
  Infrastructure merged: `native/src/moon/` + `clab-moon-kernel` (#76), the
  clean peak-RSS instrument (#77), the pinned public-corpus fetcher (#78),
  and the budgeted prescreen runner (#79). Prescreen basis: 24 MiB
  line-aligned slices of five synthetic regimes plus two pinned GH Archive
  hours, with kanzi-max and zpaq `-method 54` references computed on the
  identical slice bytes. Everything is `development_only_prescreen`. No
  frozen moonshot protocol exists yet; nothing in this lane is authorized
  to read development items until one does.
- **Cycle 2:** build and synthetic/public prescreen are approved under
  `docs/benchmarks/2026-07-23-moonshot-cycle2-charter.md`. Order: C3 live
  adaptation, C1 match model, C2 pooled value reuse, C5 BWT; C4 is
  precheck-gated and C6 requires C1+C2 survival. C3 implementation is the
  immediate task. No development, validation, or holdout access is authorized.
- **H1 loss decomposition (runs 38→40) — PUBLISHED 2026-07-23.** Attribution of
  the H1 floor arm's coding loss across two public snapshots: ~78% string_value,
  ~11% number_value, ~43% inside long repeats; timestamps/framing/cold-start
  immaterial (≤~0.9%). Funds C1 (match-mixer, repeat mass), C2 (value-context,
  string pot), and C8 (expert-mixture, 0.93× H1 kill frozen pre-measurement).
  Evidence `runs/moon-h1-loss-decomposition-v1/`, doc
  `docs/benchmarks/2026-07-23-moon-h1-loss-decomposition-diagnostic.md`; 40 of
  160 cycle runs used.
- **C3 (live adaptation) — KILLED at prescreen 2026-07-23.** Preregistered
  two-snapshot AND kill line (integer `C3·100 >= H1·97` on both public
  snapshots; manifest `config/moon-c3-public-prescreen-v1.json` merged in PR #95
  before execution). C3/H1 = 1.0654 and 1.0648 — ~6.5% larger than the H1 floor
  on both snapshots, so `c3_ratio_gate_kills` → True. All operational gates
  clean: exact redecode, ~295.7 MiB peak RSS, 211.9/245.7 s walls, and the
  synthetic precheck passed (PR #94); the kill is a ratio kill on real data.
  C3 changed only counter dynamics (fast-cold/slow-warm EWMA) plus a neutral
  APM chain over H1's identical contexts/grammar. Leading explanation (one
  frozen design, two snapshots): faster live adaptation over the same context
  set miscalibrates rather than helps — the live-adaptivity signal is not about
  update speed; richer context/expert structure (C1/C2/C6) remains the live
  test. Evidence `runs/moon-cycle2-c3-prescreen-v1/`, chart
  `docs/benchmarks/2026-07-23-moon-cycle2-c3-prescreen.md`; 38 of 160 cycle runs
  used.
- **H9 (bounded grammar) — KILLED at prescreen 2026-07-23.** Naive offline
  Re-Pair (worst case O(rule_budget x n)) does not terminate inside the
  600 s per-run budget at prescreen scale on realistic NDJSON: 8 of 8 runs
  wall-timeout at 12 MiB and then 4 MiB (the 24 MiB basis was never
  attempted — ~42.5 KB/s projects ~593 s, no margin). The preregistered
  ratio kill-line (grammar size > 1.3x local ZPAQ-16MiB) was never
  evaluable — no size was produced, so no ratio numbers exist. Observed
  kill is computational, upstream of the ratio. Evidence
  `runs/moon-prescreen-cycle1-h9-v1/`, chart
  `docs/benchmarks/2026-07-23-moon-cycle1-h9-prescreen.md`; 29 of 160 cycle
  runs used. An incremental Re-Pair (priority queue + occurrence lists,
  near-linear) is a possible cycle-2 proposal, not funded now.
- **H8 (frozen static mixer) — KILLED at prescreen 2026-07-23.** On the unseen
  month (kill line: frozen-mixer complete bytes > 1.02x adaptive H1 on month B)
  H8/H1 = 1.1368, decisive; the arm also loses in-distribution (1.1274 on
  train month A) and on synthetics (1.15–1.22). The ~12–14% loss is bounded,
  jointly attributed to freezing the weights and removing M5's recalibration
  (audit P2-A), but the train→eval gap is only ~0.9 points — attribution-clean:
  live per-stream adaptivity, not month-to-month transfer, is the cost. The H2
  distillation family stays UNFUNDED for cycle 2. Evidence
  `runs/moon-prescreen-cycle1-h8-v1/`, chart
  `docs/benchmarks/2026-07-23-moon-cycle1-h8-prescreen.md`; 36 of 160 cycle
  runs used.
- **H1 and H6 — KILLED at prescreen 2026-07-23** on their preregistered lines
  (H1: 1.265 and 1.292 vs 1.10x local zpaq16 on both public snapshots, refined
  18-bit SSE byte-identical; H6: whole-line reuse loses to the floor on both
  public snapshots, only many-templates profits −1.14%). Charts
  `docs/benchmarks/2026-07-23-moon-cycle1-h1-prescreen.md` and
  `...-h6-prescreen.md`. Cycle 1 closes with all four funded arms killed; see
  the kill/nominate report for transferable signals.

## Closed lanes (do not reopen without new evidence)

- **S0 JSON/log native screen — KILLED 2026-07-22** by its own preregistered
  gates. Evidence: `runs/json-log-native-screen-s0-v1/`, chart:
  `docs/benchmarks/2026-07-22-json-log-native-screen-s0-results.md`. No
  further S0 measurement is authorized; the kernel (`native/src/s0/`,
  `clab-s0-kernel`) remains as reusable measurement infrastructure.
- **E2-A bounded generic context scaling — KILLED** (5.78% vs 10% minimum):
  `runs/json-context-ceiling-e2-a-v1/`.
- **JLS2 context-reuse, inline single-worker, A3 attribution — REJECTED**
  (see their publications in `runs/` and docs history).
- **E1 frontier census — COMPLETE** (training-only diagnostic; headroom map:
  json_logs +21.3%, numeric +7.8%, tabular +3.1%, wikimedia ≈0, source < 0).

## Known repo quirks

- The JLS2-A3 preflight workflow
  (`.github/workflows/jls2-declared-size-lifetime-a3-attribution.yml`) is
  RETIRED (2026-07-23): its pull_request trigger is removed and only manual
  dispatch remains. The A3 lane concluded with a published rejection; the
  hosted preflight could no longer pass (attribution-enforcement drift since
  2026-07-20, plus frozen file pins that predate later product work on
  `native/src/jls2.rs`). All A3 evidence remains immutable in `runs/`, docs,
  and git history.
- `runs/` and `corpora/` are gitignored; published run evidence is force-added
  selectively. Large tapes/artifacts stay out of git, pinned by SHA256SUMS.
