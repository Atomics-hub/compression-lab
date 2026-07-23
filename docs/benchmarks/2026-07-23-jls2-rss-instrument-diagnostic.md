# JLS2 decoder RSS: the 621.3 MiB reading is a measurement-instrument artifact

**Date:** 2026-07-23
**Lane:** 1 (JLS2 decoder memory), `docs/RESEARCH_LANES.md`
**Evidence class:** diagnostic on fully synthetic data. Not a gate
measurement, not corpus evidence, not a compression-quality claim, and not a
re-score of the frozen public validation.
**Evidence bundle:** `runs/jls2-rss-instrument-diagnostic-v1/`

## Conclusion

The peak-RSS instrument used to measure the JLS2 native decoder — `wait4`'s
`ru_maxrss` for a subprocess spawned from a large Python parent — reports the
**parent's** resident footprint, not the decoder's. Measured with a clean
instrument, the dieted decoder (main `200c74b`) peaks at **162.9 MiB** at
full parallelism on a 200 MB synthetic item (ubuntu-22.04, 4 vCPU), and
**4.9 MiB** on a 1 MB item. The frozen public-validation reading of
651,517,952 bytes (621.3 MiB) was produced by
`scripts/benchmark-clue-jls2-public-validation.py::run_process`, which reaps
a `subprocess.Popen`ed `clab-jls2 decompress` child with `os.wait4(pid, 0)`
and records `usage.ru_maxrss` — the identical wait4-from-a-large-parent
instrument this diagnostic reproduces and refutes. Because that call sets no
`preexec_fn`, it is vfork-eligible and reads the spawning parent's
historical peak, matching this diagnostic's unrestricted cells. (The
separate in-process harness telemetry in
`src/compresslab/worker.py::_peak_rss_bytes`, a
`max(getrusage(RUSAGE_SELF), getrusage(RUSAGE_CHILDREN))` inside a large
worker, has its own accumulation problem for any future subprocess-based
gate, but it is not the source of the frozen number.) Whether the frozen
memory gate is re-scored on the frozen validation family with a corrected
instrument is an owner decision; nothing in this diagnostic touches the
frozen result.

## The decisive experiment (round 5, run 29981392849)

| Cell | Artifact | Old instrument (`wait4` from fat parent) | Clean instrument (GNU `time -v`, tiny parent) |
|---|---|---:|---:|
| full parallelism | 200 MB source | 698.8 MiB | **162.9 MiB** |
| 3 CPUs | 200 MB source | 533.4 MiB | 122.5 MiB |
| full parallelism | **1 MB source** | **698.8 MiB** | **4.9 MiB** |

The control row is the proof: decoding a 1 MB source cannot use 698.8 MiB,
and the old instrument reports the identical number for the 1 MB and 200 MB
decodes. The reading is a property of the spawning parent, not of the
decoder. Every cell reproduced the source bytes exactly.

## How the artifact works

On Linux, a child created by `fork()` from a large parent starts with the
parent's resident pages mapped copy-on-write, and the pre-`execve` resident
watermark is folded into the accounting that `wait4` later reports as
`ru_maxrss`. Two further observations confirm the mechanism:

- Cells that set CPU affinity through `preexec_fn` force CPython down the
  plain-`fork` path and read 533.4 MiB; cells without `preexec_fn` allow
  the `vfork` fast path and read 698.8 MiB — consistent with plain fork
  capturing the parent's current resident size and vfork sharing the
  parent's address space, whose high-water mark is the parent's historical
  peak. This asymmetry manufactured a fake "worker-count step" in rounds
  1–4: the step tracked the spawn path, not the worker pool.
- The round-4 syscall trace (`strace -f` over
  `mmap/munmap/mremap/mprotect/brk/madvise`) shows the decoder making only
  ~203 MiB of anonymous read-write mappings over its entire life while the
  old instrument reported 679.6 MiB — more than three times every page the
  process ever made writable.

## What was refuted on the way (all archived in the bundle)

| Round | Run | Hypothesis | Result |
|---|---|---|---|
| 1 | 29979759484 | glibc arena count (`MALLOC_ARENA_MAX`) | no effect |
| 2 | 29980499529 | dynamic mmap threshold (`MALLOC_MMAP_THRESHOLD_=131072`) | no effect, byte-identical |
| 3 | 29980724926 | transparent hugepages; `GLIBC_TUNABLES` spelling | no effect, byte-identical |
| 4 | 29981022229 | allocator itself (LD_PRELOAD jemalloc), extreme threshold `=1`, `MALLOC_TRIM_THRESHOLD_=0`, tmpfs output | all byte-identical — allocator provably irrelevant |
| 5 | 29981392849 | measurement instrument | **proven: parent-footprint artifact; clean decoder peak 162.9 MiB** |

Byte-identical readings across two different allocators were the pivotal
anomaly: no allocator-behavior hypothesis can produce that, only a reading
taken before the decoder ever ran.

A separate counting-allocator instrumentation of the same decode (macOS,
Rust global allocator; session-local, not archived in this bundle) measured
true peak live bytes at exactly `workers x 16 MiB` — one segment buffer per
in-flight worker — consistent with the clean Linux readings once shared
libraries and zstd contexts are added. It is corroborating context only;
the archived round-5 clean readings are the primary evidence.

## Consequences

1. **Lane 1's premise changes.** The lane assumed a real 109.3 MiB overage
   against the 512 MiB gate. The dieted decoder's honest synthetic-item
   peak at full parallelism is ~163 MiB, roughly 3x under the gate. The
   remaining question is what the frozen validation items measure under a
   corrected instrument, which only an owner-dispatched re-measurement can
   answer.
2. **The product harness instrument needs a fix** before any future memory
   gate is scored: child peak RSS must be taken from a small-parent spawn
   (e.g. a GNU-`time`-style wrapper) or an equivalent clean channel, never
   from `getrusage(RUSAGE_SELF/CHILDREN)` inside a large worker process.
   Historical receipts that used the old instrument remain what they are:
   readings of the harness, biased upward, never downward — compression-side
   readings and all byte/ratio numbers are unaffected.
3. **Prior rejected memory work should be reread in this light.** The
   A2 context-reuse and inline-single-worker results likely compared
   polluted readings against polluted readings — deltas near zero are
   exactly what an instrument artifact predicts — pending confirmation of
   each run's exact measurement path before any of those rejections is
   formally revisited.

## Reproduction

`scripts/experiment-jls2-rss-arena.py` (round-5 form, this branch) via the
`jls2-rss-arena-experiment` workflow: builds the decoder, synthesizes a
200 MB and a 1 MB NDJSON source, compresses both with the product codec, and
decodes them under the old and clean instruments. Every earlier round's
script form is recoverable from this branch's history; every round's report
JSON (and rounds 3–4 syscall traces) are archived in
`runs/jls2-rss-instrument-diagnostic-v1/` with SHA256SUMS.
