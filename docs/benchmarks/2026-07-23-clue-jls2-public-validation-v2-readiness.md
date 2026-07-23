# CLUE-LDS JLS2 v2 public-validation readiness

## Decision

**Candidate and gates frozen; validation remains unopened and unauthorized.**

This is a second, separately frozen one-time public validation of the current
dieted JLS2 product decoder on two previously unopened CLUE-LDS temporal ranges.
It does not correct, replace, or reopen the immutable
`clue-jls2-one-time-public-validation-v1` `not_passed` score. A v2 result stands
on its own and is published whether it passes, fails, or is interrupted.

Acquisition remains disabled until a committed final readiness lock pins the
candidate, corpus, complete competitor roster, clean-child instrument, candidate
compress driver, runner, evaluator, publication surface, and one-attempt policy.
The intended public brand is **Atompress**; `JLS2` remains the technical codec
and on-disk stream identifier, so branding has no effect on the frozen bytes.

## Frozen candidate

The candidate is the current dieted shipping decoder. Its product lineage is
`native/src/jls2.rs` from PR #74 (`200c74b`), present unchanged on the
owner-decision baseline `d1a7319` and on this readiness baseline. The gate file
pins SHA-256 for the Python encoder, Rust transforms, standalone Rust decoder,
Cargo lock, and build metadata. Validation must build and run that exact
implementation from a detached worktree.

Development evidence is immutable and checksummed (the same committed JLS2
product development census and native-decoder cross-platform reproduction used
for v1). These are development results, not unseen validation.

## Corrected memory instrument

Every candidate resource row — cold-process compression peak RSS and standalone
native decode peak RSS — is measured through the clean-child instrument
`scripts/measure-clean-rss.py`. The v1 score read the standalone decode peak with
`os.wait4` reaped directly from the large benchmark parent, folding the parent's
resident watermark into the child reading. Under the clean-child instrument the
reading is taken by a deliberately tiny re-executed shim, and each reading
carries its own shim floor. A candidate reading is eligible only when the shim
floor is at most 64 MiB and at most 25% of the reading; a violation voids the
attempt as an instrument failure and is never converted into a pass. The worst
eligible cold-process standalone decoder peak RSS must be at most 536,870,912
bytes (512 MiB).

## Sealed score

Each of the two families is a 250,000-record window whose byte size and SHA-256
remain unknown until the single authorized acquisition:

| Item | Inclusive official IDs | Records |
| --- | ---: | ---: |
| clue-validation-v2-c | 28,000,001 .. 28,250,000 | 250,000 |
| clue-validation-v2-d | 40,000,001 .. 40,250,000 | 250,000 |

Both ranges are disjoint from every declared development and consumed validation
range. The acquisition path refuses any range that overlaps a range already
declared by a tracked corpus configuration, and refuses to open the
public-validation split without a valid final readiness lock over a clean
worktree.

## Competitor honesty

The roster is the same frozen standard set and the PBC-only specialist used for
v1. Emerging log specialists that cannot be reproduced are disclosed as
unavailable context; their absence is not a JLS2 win.

## One-way door

One acquisition and one scored attempt. Every failed or interrupted attempt is
retained. No candidate, range, runner, baseline, parameter, instrument,
threshold, evaluator, verifier, chart rule, or claim ceiling changes after
acquisition.
