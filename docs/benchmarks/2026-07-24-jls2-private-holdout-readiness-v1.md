# JLS2 private-holdout readiness audit and frozen one-shot decision rule v1

**Date:** 2026-07-24
**Status:** readiness audit; **NOT READY**. This document is a preconditions
audit plus a frozen one-shot holdout decision rule. It is **not** an
acquisition, authorizes no acquisition, and consumes no holdout data.
**Evidence effect:** none. It records no measurements, downloads no binaries,
and changes no immutable v1 or v2 artifact.

This document audits whether the sealed private-holdout evaluation of the
category JSON/log candidate (JLS2 / Axiom) is ready to be dispatched, and
freezes the mechanical one-shot rule that a future owner-dispatched holdout
evaluation would follow. It sits after the frozen JLS2 v2 public-validation
pass
(`docs/benchmarks/2026-07-24-clue-jls2-public-validation-v2-results.md`),
the frozen JSON/log championship roster
(`docs/benchmarks/2026-07-24-json-log-championship-roster-v1.md`,
`config/json-log-championship-roster-v1.json`), and the reproduction bundle
(`docs/benchmarks/2026-07-24-jls2-v2-reproduction-protocol.md`,
`scripts/reproduce-jls2-v2.py`), and enforces the `docs/RESEARCH_LANES.md`
standing rule 2 (sealed data, one-way door, owner-only dispatch).

## Claim ceiling

The only claim permitted now or at any future holdout execution is a
**category-scoped public-validation product pass on the two named previously
unopened CLUE-LDS temporal ranges** (the frozen JLS2 v2 claim ceiling). A
future private-holdout pass, if it were ever earned, could extend this only to
a **category-scoped private-holdout pass** on that single sealed acquisition —
still not a universal, state-of-the-art, market-leading, world-best, or "beats
all compressors" claim. Tools that cannot be reproduced comparably remain
**unavailable or contextual, never beaten**. Unavailable specialists are
unavailable, not beaten.

## 1. Preconditions checklist (verified statuses)

| # | Precondition | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Immutable JLS2 v2 publication sealed | **met** | v2 pass (#106), run `30055586630`, head `b187308`, 20/20 frozen gates; evidence sealed under `runs/clue-jls2-public-validation-v2/`; `docs/benchmarks/2026-07-24-clue-jls2-public-validation-v2-results.md` |
| 2 | Championship roster frozen ahead of execution | **met** | #109 froze roster, identities, framing, gates, and decision reducer: `docs/benchmarks/2026-07-24-json-log-championship-roster-v1.md`, `config/json-log-championship-roster-v1.json` |
| 3 | Kanzi and ZPAQ integrated or explicitly ineligible | **NOT met — blocker** | The roster declares Kanzi-max and ZPAQ (level-5, 16 MiB block) as `eligible (pending Linux build)`; neither has ever been executed inside a frozen championship protocol on the frozen runner. Until each is run comparably, or documented unavailable/contextual with its exact reason, no championship-tier holdout claim is admissible. See roster rule "Kanzi and ZPAQ may not be quietly omitted from any championship claim." |
| 4 | Clean reproduction bundle built and executed on a dedicated machine | **partial — blocker** | Bundle built and `--smoke` tested on the primary development Mac (#110, `scripts/reproduce-jls2-v2.py`); the **independent dedicated-machine full-pipeline execution is NOT yet performed** and is required per `docs/benchmarks/2026-07-24-jls2-v2-reproduction-protocol.md` §"What counts as independent" |
| 5 | No tooling ambiguity | **met (roster level)** | Roster pins every tool identity by version, source commit, and settings, with binary SHA-256s pinned or an explicit capture-at-execution rule; instrument `scripts/measure-clean-rss.py` pinned by SHA-256 `805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306` |
| 6 | Exact one-shot holdout decision rule frozen | **met (by this document)** | §2 below freezes the mechanical rule |
| 7 | Complete resource gates | **met — inherited verbatim from v2** | §"Inherited gates" below cites the v2 frozen gate list; no gate is restated loosely |
| 8 | Per-family and per-item regression limits | **met — frozen here, bound to #109** | §"Regression limits" below mirrors v2's per-family rule and binds to the roster's frozen regression section; no conflicting numbers introduced |

### Inherited gates (verbatim from the frozen v2 contract, precondition 7)

The holdout inherits the JLS2 v2 frozen gates without change. The authoritative
list is the 20 frozen gates enumerated in
`docs/benchmarks/2026-07-24-clue-jls2-public-validation-v2-results.md` §"Gates":

> aggregate ratio, both family ratios, aggregate and per-repetition
> compression and standalone-decode speed, clean-child shim-floor eligibility,
> compression memory, decompression memory, exact round-trip, deterministic
> output, corruption rejection, bounded direct fallback, complete frame
> accounting, complete standard roster, PBC specialist present, frozen
> candidate paths, development evidence, first-score receipt, and unavailable
> markers.

The load-bearing frozen numeric bindings, cited exactly and not paraphrased,
are:

- **Standalone decode memory gate:** worst cold-process standalone decode peak
  RSS at most **512 MiB (536,870,912 bytes)**, measured through the clean-child
  instrument `scripts/measure-clean-rss.py`
  (`config/clue-jls2-public-validation-v2-gates.json`; roster `memory_rules`
  `eligible_decode_gate_bytes` = 536870912).
- **Compression memory gate:** at most **536,870,912 bytes** cold-process peak
  RSS (roster `memory_rules` `eligible_compress_gate_bytes` = 536870912).
- **Shim-floor eligibility:** the clean-child shim floor must be at most
  **64 MiB (67,108,864 bytes)** *and* at most **25%** of the reading; a
  shim-floor violation voids the attempt as an instrument failure and is never
  converted into a pass (v2 decision rule, verbatim; roster `memory_rules`
  `shim_floor_max_bytes` = 67108864, `shim_floor_max_fraction_of_maxrss` =
  0.25).
- **Speed tiers:** at least **100 MB/s** aggregate compression and at least
  **250 MB/s** aggregate standalone decompression (roster `speed_tiers`;
  reported for context on every tool, not a ratio decision).
- **Per-item wall / timeout:** **1800.0 s** per item; a tool that does not
  finish an item within the budget is a recorded did-not-finish for that item
  and is never silently dropped
  (`config/clue-jls2-public-validation-v2-gates.json` `timeout_seconds` =
  1800.0; roster framing "Timeout").
- **Exactness, determinism, corruption rejection, complete-byte accounting:**
  byte-exact roundtrip preserving record order and timezone text; deterministic
  output; corruption rejection; complete-frame accounting over every container,
  header, dictionary, pattern file, or framing wrapper (v2 gates, unchanged).

### Regression limits (precondition 8, bound to #109)

Frozen for the holdout, consistent with the roster's frozen `regression_rules`
and mirroring the v2 per-family rule; no conflicting numbers are introduced:

- **Per-family gain:** each temporal family requires at least **5%** smaller
  complete exact bytes than the strongest eligible available tool on that
  family (roster `regression_rules.per_family_minimum_gain_percent` = 5.0;
  mirrors v2's per-family gates).
- **Aggregate gain:** at least **5%** smaller complete exact bytes than the
  strongest eligible available tool in aggregate
  (roster `regression_rules.aggregate_minimum_gain_percent` = 5.0).
- **Per-item no-regression epsilon:** JLS2 must be the smallest eligible
  complete archive on **every** family (roster `regression_rules.per_item`);
  segment framing may not regress against an equally framed direct fallback,
  with the frozen tolerance **epsilon = 0 bytes**
  (roster `regression_rules.segment_fallback_regression_bytes` = 0). This
  0-byte segment-fallback tolerance is the declared per-item epsilon; no other
  epsilon is invented.

## 2. Frozen one-shot holdout decision rule

Mechanical; integer arithmetic on byte counts where applicable.

1. **Single acquisition.** The sealed private holdout is acquired exactly once,
   only through the owner's sealed mechanism. Its identities never enter the
   repository.
2. **Single scoring pass.** One frozen scoring pass over that acquisition. No
   tuning, no parameter change, no rerun, no post-score adjustment of any
   candidate path, threshold, baseline setting, instrument, evaluator, runner,
   or chart rule.
3. **Pass condition.** The holdout **passes only if all** of the following hold:
   - every inherited v2 gate passes (the 20 gates above: ratio, speed,
     clean-child shim-floor eligibility, compression memory, decompression
     memory, exactness, determinism, corruption rejection, bounded direct
     fallback, complete frame accounting, complete standard roster, PBC
     specialist present, frozen candidate paths, development evidence,
     first-score receipt, and unavailable markers); **and**
   - the frozen regression limits pass (per-family ≥ 5% and aggregate ≥ 5%
     smaller complete exact bytes, per-family JLS2 smallest eligible archive,
     0-byte segment-fallback tolerance); **and**
   - JLS2's complete exact-byte archive is strictly the smallest against
     **every eligible available roster tool** on every family and in aggregate.
   Contextual tools (in-repo but over the 512 MiB decode gate or not
   byte-exact) and unavailable tools (no reproducible implementation) are
   reported alongside the decision but are never counted as beaten and never
   counted as beating JLS2.
4. **Failure handling.** Any gate failure, any regression-limit failure, any
   non-smallest eligible archive on any family or aggregate, or any
   interruption is a **recorded, published `not_passed`** under this same claim
   boundary. There is **no re-attempt on the same holdout identities**: those
   identities are consumed and sealed one-way.
5. **First eligible score is final.** The first eligible scored attempt is
   retained whether it passes, fails, or is interrupted.

**Claim a pass would earn.** A pass earns only a **category-scoped
private-holdout pass** on that single sealed acquisition, added to the existing
category-scoped public-validation pass. It would **not** prove a universal,
market-leading, world-best, or state-of-the-art result; would **not** cover
general files; would **not** change the immutable v1 `not_passed`; and would
**not** convert any unavailable specialist into a beaten one.

## 3. Sealing rules

- Private-holdout identities **never** appear in this repository, by design
  (`docs/RESEARCH_LANES.md` standing rule 2).
- Acquisition happens **only** through the owner's sealed mechanism.
- Owner dispatch of a holdout acquisition is a **one-way door**: consumed
  holdout identities are never reused, and a `not_passed` is final.
- **Merging this document does not authorize acquisition.** It freezes the
  audit and the decision rule only. Acquisition, tool integration, and scoring
  remain separately owner-dispatched, and only after the blockers below clear.

## 4. Readiness verdict

**NOT READY — blockers: (a) dedicated-machine independent reproduction of the
JLS2 v2 public-validation pass is unexecuted; (b) Kanzi and ZPAQ have never
been executed inside a frozen championship protocol.**

### Minimal path to READY

1. Execute the reproduction bundle
   (`scripts/reproduce-jls2-v2.py`,
   `docs/benchmarks/2026-07-24-jls2-v2-reproduction-protocol.md`) on a genuinely
   independent dedicated Linux machine, operator-independent, from a clean
   checkout, and obtain a `REPRODUCED` verdict with its self-bound receipt
   delivered to the owner. (Clears blocker a.)
2. Build Kanzi-max and ZPAQ (level-5, 16 MiB block) for the frozen
   `ubuntu-22.04` 4-vCPU runner and execute both inside a frozen championship
   protocol under the #109 roster gates, capturing their pinned binary
   SHA-256s at execution; or, if either cannot run comparably, document the
   exact reason and classify it unavailable or contextual per the roster's
   "Kanzi and ZPAQ may not be quietly omitted" rule. (Clears blocker b.)
3. With (1) and (2) cleared, the owner may dispatch a single sealed
   private-holdout acquisition and score it exactly once under §2 above.

Until steps 1 and 2 are complete, the readiness verdict remains NOT READY and
no holdout acquisition is authorized.

## What this document does not do

It acquires no holdout, records no measurements, downloads no binaries,
integrates no tools, changes no immutable v1 or v2 artifact, and asserts
nothing beyond the frozen v2 claim ceiling. Reproduction execution, Kanzi/ZPAQ
integration, holdout acquisition, and holdout scoring all remain separately
owner-dispatched.
