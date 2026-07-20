# JLS2 A3 synthetic audit note

## Scope

This is a local diagnostic note, not an A3 gate result. It uses only the
deterministic generated `jls2-context-stress-256` contract. No CLUE,
public-validation, or private-holdout byte was accessed. The host was macOS
26.5.2 arm64, so its generated frame hash is not compared with or substituted
for a Linux-generated A/B frame.

## Reproducible inputs

- generated source bytes: 50,270,800;
- generated source SHA-256:
  `873b0a0a7565fe8ee59c7f6deb377b83bd64677ccd87dc25e570ccd6b05a51c5`;
- local encoded bytes: 9,225;
- local encoded SHA-256:
  `9c140f37e15d7baf73a0ac63a5a5d4d5038a13ca0414fa92f402923bc7ed8fe8`;
  and
- segment count: 3 direct segments.

The frame was inspected by `scripts/audit-jls2-a3-memory-plan.py` with four
logical CPUs and the frozen 32 MiB proposed batch budget.

## Declared-memory finding

The current A2 count-based batch holds all three direct segment outputs, for a
declared live working upper bound of 50,270,800 bytes. The proposed A3 plan
holds two segments in its largest batch, for 33,552,300 bytes. The declared
decoded-live reduction upper bound is therefore 16,718,500 bytes. Shortening
encoded-frame lifetime contributes at most another 3,163 report-only bytes on
this local fixture. Those bytes receive zero authorization credit and are not
added to the decoded-concurrency gate.

The A3 audit kill threshold is 105,202,484 attributed bytes. Declared buffers
and encoded lifetime alone do not reach it. This does not yet kill the broader
hypothesis because Zstandard or allocator pages correlated with concurrent
segment decode have not been observed. It does prohibit an A3 product
candidate now.

## Required next evidence

Run a Linux diagnostic child on this generated stress contract with the frozen
phase checkpoints from the A3 protocol. It must report RSS plus allocator
in-use/free-arena/mmap state before the batch, at maximum live batch, after raw
and restored buffers drop, and after audit-only `malloc_trim(0)`. Only
phase-correlated decoded-concurrency releases may close the 88,483,984-byte gap
between the declared decoded upper bound and the frozen attribution threshold.

Until that evidence exists, the A3 kill gate status is
`hosted_attribution_required`, `passed` is false, product A/B authorization is
false, and the pre-A1 product baseline remains retained. A lifetime-only
release cannot change that status.
