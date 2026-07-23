# JLS2 memory-gate instrument-invalidity addendum

**Date:** 2026-07-23
**Lane:** 1 (JLS2 decoder memory), `docs/RESEARCH_LANES.md`
**Scope:** This is a docs-only addendum. It changes no frozen surface, no
validation config, no run, and no code. It records that the recorded
memory-gate reading was invalidated as a measurement-instrument defect while
the frozen no-pass result itself stands, immutable.
**Governing contract:**
`config/clue-jls2-public-validation-gates.json` —
`authorization.maximum_acquisitions: 1`,
`authorization.maximum_scored_attempts: 1`,
`authorization.prohibit_post_score_tuning: true`, and the `decision_rule`:
"The first eligible score is final ... No candidate path, parameter,
threshold, corpus range, baseline setting, evaluator, runner, or chart rule
may change after acquisition. A failed or interrupted scored attempt is
retained and cannot be replaced by a tuned rerun."

## 1. The frozen result stands (this does not change)

The single authorized acquisition and score for
`clue-jls2-one-time-public-validation-v1` completed in GitHub Actions run
`29606109504` at merge commit `b9cdc9e797b36709ba4c17c23a4c6585670254e3`, and
the frozen enforcement step returned exit code 2 — a complete, valid
`not_passed` decision, not an infrastructure failure
(`docs/benchmarks/2026-07-17-clue-jls2-public-validation-result-status.md`;
receipt `runs/clue-jls2-public-validation-v1-import.json`; publication
`runs/clue-jls2-public-validation-v1/publication/README.md`).

The recorded reason for the no-pass was the memory gate: standalone
decompression peak RSS was recorded as **651,517,952 bytes (621.3 MiB)**,
over the `maximum_cold_decompression_peak_rss_mib: 512.0` gate. Every other
frozen gate passed; the ratio result was decisive (96,934,483 source bytes →
489,591 complete JLS2 bytes, 52.97% smaller than the strongest eligible
standard, Brotli-11). Both CLUE validation ranges are consumed.

Under the frozen contract — one acquisition, one score, and no post-score
change to runner or evaluator — **JLS2 did not pass, and that no-pass is
final and immutable.** Nothing below re-scores it, revives it, or supports
any claim that JLS2 "passes", "would have passed", or has a corrected frozen
score. The frozen decision is the recorded `not_passed`.

## 2. What the diagnostic legitimately establishes

The recorded 621.3 MiB reading was invalidated as a **measurement-instrument
defect**, not as a decoder-memory fact. This finding is about the instrument
that produced the number; it does not, and cannot, alter the frozen decision
in Section 1.

Full evidence:
`docs/benchmarks/2026-07-23-jls2-rss-instrument-diagnostic.md`, evidence
bundle `runs/jls2-rss-instrument-diagnostic-v1/` (rounds 1–5 report JSON,
rounds 3–4 syscall traces, `SHA256SUMS`). The diagnostic ran entirely on
fully synthetic data and is explicitly not a gate measurement, not corpus
evidence, and not a re-score.

**The defect.** The frozen number was produced by
`scripts/benchmark-clue-jls2-public-validation.py::run_process`, which reaps a
`subprocess.Popen`ed `clab-jls2 decompress` child with `os.wait4(pid, 0)` and
records `usage.ru_maxrss`. Spawned from a large Python parent with no
`preexec_fn`, that call is vfork-eligible and reports the **parent's**
historical resident high-water mark, not the decoder's footprint. Five
diagnostic rounds first refuted every allocator-behavior hypothesis
(`MALLOC_ARENA_MAX`, mmap threshold, transparent hugepages, jemalloc via
`LD_PRELOAD`, extreme trim thresholds — all byte-identical), then reproduced
and isolated the instrument itself.

**The decisive control (round 5, run `29981392849`).** On the old
instrument, a **1 MB** decode read **698.8 MiB** — byte-identical to the
698.8 MiB read for a 200 MB decode. A 1 MB decode cannot use 698.8 MiB; an
identical reading for 1 MB and 200 MB inputs is only possible if the number
is a property of the spawning parent, not of the decode. Measured cleanly
(GNU `time -v` from a tiny parent), the same dieted decoder peaked at
**162.9 MiB** at full parallelism on a 200 MB synthetic item, **122.5 MiB**
at 3 CPUs, and **4.9 MiB** on the 1 MB item. Corroborating: the round-4
`strace` trace shows the decoder making only ~203 MiB of anonymous
read-write mappings over its whole life while the old instrument reported
679.6 MiB. Every diagnostic cell reproduced the source bytes exactly.

## 3. What may and may not be concluded

**May be concluded:**

- The specific 621.3 MiB memory-gate reading is a known
  measurement-instrument artifact (parent-footprint inheritance across
  `wait4`/`getrusage` from a fat Python parent), biased upward, never
  downward.
- On corrected synthetic diagnostics, the dieted decoder fits comfortably
  under the 512 MiB gate (clean peak 162.9 MiB at full workers on a 200 MB
  synthetic item, roughly 3x under the gate).
- The A2 context-reuse and inline-single-worker "no effect" results were
  likely polluted-vs-polluted comparisons and must be reread before being
  cited.

**May NOT be concluded (forbidden):**

- That JLS2 "now passes", "would have passed", or is anything other than the
  frozen `not_passed`.
- Any recomputed, corrected, or implied frozen score.
- Any change to `axiom_wins` / category-win standing, or to the evidence
  boundary already published for the frozen result.
- Any inference that the *frozen validation items* fit under the gate. The
  clean numbers are synthetic-item diagnostics; what the consumed validation
  families measure under a corrected instrument is unknown and is not
  measurable under this consumed, frozen protocol.

## 4. The honest path forward

Correcting an invalidated instrument does not reopen a consumed, frozen
protocol. The only legitimate route to a corrected memory result is a
**new, separately frozen protocol**, and every step is owner-dispatched:

1. Owner decision to open a corrected-memory validation at all.
2. A newly frozen corrected-memory protocol — corrected clean child peak-RSS
   instrument (small-parent spawn, never `getrusage(RUSAGE_SELF/CHILDREN)`
   inside a large worker) — pinned against **previously unopened** CLUE-LDS
   validation families. The consumed ranges (`clue-validation-a`,
   `clue-validation-b`) are never reused.
3. Owner-dispatched acquisition and a single score under that new freeze.
4. Only then, in sequence and per the existing claim ceiling: the sealed
   private holdout, and independent reproduction, before any
   state-of-the-art language.

Validation- and holdout-path dispatch remains owner-only. This addendum does
not authorize any of the above; it records the boundary.
