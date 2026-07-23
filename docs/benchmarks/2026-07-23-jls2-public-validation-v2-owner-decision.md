# JLS2 fresh public-validation v2: owner decision

**Date:** 2026-07-23  
**Status:** design approved; implementation and freeze authorized; acquisition
and scoring are **not yet authorized**  
**Evidence effect:** none. This document is a decision record, not a benchmark.

## Decision

Build a new, separately frozen **full public-validation** protocol for the
current dieted JLS2 product decoder. The protocol will use two previously
unopened CLUE-LDS record ranges and the corrected tiny-parent RSS instrument.
It will rerun the complete product gate on those new families: complete archive
size against the frozen standard/specialist roster, compression and standalone
decode speed, cold-process compression and decode RSS, exactness, determinism,
corruption rejection, fallback, accounting, provenance, and portability.

This is not a correction or replacement of
`clue-jls2-one-time-public-validation-v1`. That score remains an immutable
`not_passed`. A v2 result stands on its own and must be published whether it
passes, fails, or is interrupted.

## Owner rulings

1. **Protocol scope:** full fresh validation, not a memory-only re-gate. A
   narrow memory fact would consume unseen data without being capable of
   establishing a complete category-scoped product pass.
2. **Candidate:** the current dieted shipping decoder. The product lineage is
   `native/src/jls2.rs` from PR #74 (`200c74b`), as present on the owner-decision
   baseline `d1a7319`. The readiness lock must pin every candidate path by
   SHA-256 and pin the final readiness commit before acquisition.
3. **Fresh families:** exactly two 250,000-record windows:
   - `clue-validation-v2-c`: ids `28,000,001..28,250,000` inclusive;
   - `clue-validation-v2-d`: ids `40,000,001..40,250,000` inclusive.

   These ranges are disjoint from all declared development and consumed
   validation ranges. Because the immutable member is already proven to extend
   beyond id 45,250,000 and enforces `id == line_number`, both selected ranges
   avoid tail-existence uncertainty. Their byte sizes and SHA-256 values remain
   unknown until the single authorized acquisition.
4. **Runner class:** GitHub-hosted `ubuntu-22.04`, 4 vCPU, matching the original
   evidence class. Candidate parameters remain 16 MiB segments, three
   standalone decode workers, and internal Zstandard level 6 unless the new
   gates file freezes a stricter pre-acquisition value.
5. **RSS instrument:** `scripts/measure-clean-rss.py`, currently SHA-256
   `805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306`.
   Every compression and standalone decode resource row must use the corrected
   instrument or another explicitly frozen clean-child equivalent.
6. **Shim-floor validity:** a scored resource reading is eligible only when
   `shim_maxrss_bytes <= 64 MiB` **and**
   `shim_maxrss_bytes <= 25% of maxrss_bytes`. Violation voids the attempt as
   an instrument failure; it is never converted into a pass.
7. **Memory gate:** worst eligible cold-process standalone decoder peak RSS
   must be `<= 536,870,912` bytes (512 MiB). The worst item and repetition
   governs.
8. **Provenance breadth:** record throughput and full operational evidence.
   Unlike a memory-only diagnostic, v2 is intended to support a complete
   category-scoped decision.
9. **One-way door:** one acquisition and one scored attempt. Retain every
   failed or interrupted attempt. No post-acquisition change to candidate,
   ranges, runner, baselines, parameters, instrument, thresholds, evaluator,
   verifier, chart rules, or claim ceiling.

## Required implementation bundle before acquisition can be considered

- new corpus selection, gates, and final lock files under distinct `v2` names;
- a lock verifier that proves the worktree and historical readiness blobs;
- an acquisition path that refuses consumed/overlapping ranges and refuses an
  unlocked worktree;
- a benchmark runner using clean-child RSS for candidate resource gates;
- an independent evaluator/decision renderer and publication verifier;
- a workflow with `workflow_dispatch` only after the final lock is merged;
- tests for overlap refusal, lock drift, one-attempt enforcement, shim-floor
  failure, threshold boundaries, roster completeness, exactness, tampering,
  and pass/fail publication;
- a clean-checkout confirmation and a pre-dispatch adversarial audit.

The build and freeze stages may use repository fixtures and synthetic data.
They must not acquire, list, stat, hash, sample, or otherwise inspect either new
family before the final owner dispatch.

## Claim ceiling

A passing v2 score may support only a **category-scoped public-validation
product pass on the two named previously unopened CLUE-LDS temporal ranges**.
It does not change v1, prove a private holdout, establish independent
reproduction, cover general files, or support universal, market-leading,
world-best, or state-of-the-art language. A failing or interrupted score must
be published under the same boundary.

