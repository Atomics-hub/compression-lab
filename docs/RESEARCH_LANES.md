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

## Lane 1 (ACTIVE, foreground): JLS2 decoder memory — the first category win

- **Goal:** reduce JLS2 decoder peak RSS from 621.3 MiB to ≤ 512 MiB with the
  frozen bitstream unchanged, passing JLS2's last failed gate.
- **Why it matters:** JLS2's frozen public-validation score (52.97% smaller
  than the strongest eligible standard) already clears every other gate. The
  memory gate is the only thing between the platform and its first honest
  category win.
- **Route 1 (preferred):** decoder-only engineering; keeps the frozen score.
  First deliverable is a trustworthy allocation-lifetime profile — the A3
  attribution audit was rejected, so no validated memory map exists.
- **Route 2 (fallback, owner-gated):** a format-level ratio-for-memory trade.
  That creates a new candidate and consumes a fresh validation family; it is
  not started without an explicit owner decision.
- **Already tried and rejected — do not naively re-run:** decompression
  context reuse (`runs/`/docs history), inline single-worker decode, and the
  A3 declared-size-lifetime attribution audit.

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
- **Status:** cycle 1 in design. No frozen moonshot protocol exists yet;
  nothing in this lane is authorized to read development items until one does.

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
