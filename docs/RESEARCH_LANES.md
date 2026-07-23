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

## Lane 1 (RESOLVED at the diagnostic level 2026-07-23, owner decision pending): JLS2 decoder memory

- **Resolution:** the 621.3 MiB reading that failed the memory gate is a
  measurement-instrument artifact, not decoder memory. Five diagnostic
  rounds (`docs/benchmarks/2026-07-23-jls2-rss-instrument-diagnostic.md`,
  evidence `runs/jls2-rss-instrument-diagnostic-v1/`, PR #75) proved that
  `wait4` `ru_maxrss` for a child spawned from a large Python parent reports
  the parent's footprint: decoding a 1 MB source reads 698.8 MiB on that
  instrument, byte-identical to a 200 MB decode. Measured cleanly (PR #77's
  tiny-parent instrument), the dieted decoder (PR #74) peaks at 162.9 MiB at
  full parallelism on a 200 MB synthetic item — about 3x under the gate.
- **What remains is an owner decision, not engineering:** re-scoring the
  frozen memory gate on the frozen validation family with the corrected
  instrument (an RSS re-measurement only; the frozen 52.97% ratio and all
  byte results are untouched). Validation-path dispatch stays owner-only.
- **Corollary:** the A2 context-reuse and inline-single-worker "no effect"
  results likely compared polluted readings against polluted readings;
  reread before citing them, pending confirmation of each run's exact
  measurement path.
- **Prior status (historical):** goal was 621.3 → ≤ 512 MiB via Route 1
  (decoder-only) or owner-gated Route 2 (format trade). Route 1's buffer
  diet (PR #74) merged and remains valuable (real live-memory reduction);
  Route 2 is moot.

### Known CI defect discovered during Lane 1 (2026-07-23, unresolved)

The Windows CI jobs run multi-command `run:` blocks under pwsh, which only
propagates the LAST command's exit code — the `cargo test` failures for
`native/` have been silently swallowed on Windows since at least #68. Two
`clab-s0-kernel` tests (`default_sse_bucket_bits_are_seventeen_and_recorded`,
`refined_bits_hold_the_tape_and_move_only_mixer_loss`) build tape filenames
via `{bits:?}`, embedding quotes that Windows forbids, so they have NEVER
passed on Windows. The file is byte-pinned by the S0 freeze record
(`test_json_log_s0_freeze_record`), so the in-file fix is barred (PR #80 was
withdrawn for exactly this). Resolving this — e.g. a workflow-level
`--skip` of those two tests on Windows plus splitting the pwsh blocks so
failures propagate again — changes CI enforcement and freeze-adjacent
surfaces, so it is flagged for an owner decision rather than patched ad hoc.

## Lane 2 (ACTIVE, background): the Pareto moonshot

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
- **Status (2026-07-23):** cycle 1 prescreen RUNNING. Helm-approved slate:
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
