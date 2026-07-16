# Compression Lab

Compression Lab is an adaptive lossless file compressor and the reproducible
research harness used to decide every algorithm change. It writes
self-describing `.clab` frames, verifies every decoded file with SHA-256, and
keeps backward decoding for frame versions 1 through 3.

The current encoder combines Zstandard with independently reversible numeric
and structured-text transforms, segmented routing, and exact whole-frame
fallback. It never chooses a complete candidate larger than its compared
fallback. A Rust library accelerates transforms; the Python package supplies a
portable Zstandard backend.

## Status: 0.1 release candidate

This is alpha software, not a universal compression winner. In the frozen
seven-repetition release comparison on the pinned mixed public starter corpus,
adaptive-v3 produced 6,747,896 bytes versus 6,866,359 for zstd-3 (1.73%
smaller) and 6,927,807 for gzip-9 (2.60% smaller). However, zstd-9 produced
6,386,970 bytes and was faster in both directions on that host, so adaptive-v3
was not Pareto-optimal. The expanded JSON study also remained larger than
zstd-9, Brotli-11, LZMA-9, and 7-Zip-9. Those limits are part of the result: see
`docs/benchmarks/2026-07-16-release-candidate.md` and `docs/benchmarks/` for
protocols, negative experiments, and host-scoped evidence.

Do not describe Compression Lab as state of the art on all data. Its strongest
current claim is an evidence-backed adaptive research candidate with a usable,
integrity-checked file format.

## Quick start

After the owner publishes version 0.1.0, install the native wheel from PyPI:

    python -m pip install compression-lab

Until then, use Python 3.9 or newer and Rust stable for a source checkout:

    cd /path/to/compression-lab
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .

Compress, inspect, and restore a file:

    clab compress report.json
    clab info report.json.clab
    clab decompress report.json.clab -o restored.json

`compression-lab` is the equivalent descriptive command; both entry points use
the same CLI and version.

Compression refuses to overwrite an output unless `--force` is supplied. The
decoder rejects a declared output above 2 GiB by default; change the bound with
`--max-output-size 512MiB` or explicitly disable it with `unlimited`.

Standard input and output use `-`:

    printf 'hello\n' | clab compress - -o - > hello.clab
    clab decompress hello.clab -o -

Python applications use the stable byte or file API:

```python
import compresslab

frame = compresslab.compress(b"lossless data" * 1000)
original = compresslab.decompress(frame, max_output_size=10_000_000)

compressed_path = compresslab.compress_file("report.json")
restored_path = compresslab.decompress_file(compressed_path, "report.copy.json")
```

The format contract is in `docs/file-format.md`; security boundaries are in
`SECURITY.md`. Dependency and benchmark-tool licenses are summarized in
`THIRD_PARTY_NOTICES.md`.

## Reproduce the research harness

Generate the deterministic smoke corpus and run the default comparison:

    python3 -m compresslab init-corpus --output corpora/smoke
    python3 -m compresslab run \
      --corpus corpora/smoke \
      --output runs/smoke \
      --repetitions 3 \
      --warmups 1

For the frozen release comparison against gzip-9, zstd-3/9, Brotli-6/11,
LZMA-9, and 7-Zip-9, including public-corpus verification, randomized order,
seven measurements, and machine-checked evidence completeness:

    scripts/run-release-benchmark.sh

The script waits for three qualifying preflight samples and exits non-zero when
the quiet window times out, a codec is absent, a round trip fails, the commit is
dirty or wrong, or the frozen trial matrix is incomplete.

The run writes:

- results.json: canonical complete result, including every trial;
- summary.csv: aggregate codec comparison;
- report.md: concise human-readable result.

List the registered codecs:

    python3 -m compresslab list-codecs

Run the tests:

    scripts/build-native.sh
    python3 -m unittest discover -s tests -v

Rebuild the digest-pinned public starter corpus:

    scripts/fetch-public-starter.py

## Measurement contract

Every result is valid only for its exact corpus, machine, interpreter, codec
version, and settings. The harness records those inputs and follows these rules:

1. Every measured decode must reproduce the source SHA-256 exactly.
2. Timed trials are preceded by configurable warmups.
3. Every warmup and measured repetition block is independently shuffled from a
   recorded deterministic seed.
4. The median trial represents each item × codec pair, while per-repetition
   aggregates retain confidence intervals and coefficients of variation.
5. Calibrated steady-state trials repeat an operation until its minimum timing
   duration is reached and fail validation if any batch hits its cap early.
6. Aggregate compression ratios are byte-weighted.
7. Cold-process mode includes Python worker startup. Persistent-worker mode
   excludes Python startup but retains IPC, file I/O, and external CLI startup.
8. CPU time and memory are worker-local telemetry and are not substituted for
   wall time.
9. Transfer utility is compression time + encoded bytes over the selected link
   + decompression time.
10. Public validation data is for iteration. Private holdout data should live
   outside the repository and run only at decision gates.
11. A benchmark failure, timeout, corrupt round trip, unstable throughput, or
    excessive host load remains visible and makes the CLI exit non-zero.

## Corpus model

The smoke corpus includes repetitive text, JSON logs, float32 signals, a
deterministic source-tree TAR, random bytes, already-compressed bytes, long
runs, and mixed compressible/incompressible regions. It validates the harness;
it is not sufficient evidence for a market claim.

Production corpus work should add current, licensed examples of documents,
source repositories, build artifacts, databases, executables, backups, media,
scientific arrays, tiny-file directories, and damaged or adversarial inputs.
Each public family needs a separate private holdout family.

## Planned algorithm seam

The candidate architecture plugs in at three separately measurable layers:

1. **Selector:** cheap sampled features choose store, a proven backend, or a
   specialized path.
2. **Transforms:** reversible structure exposure such as numeric delta and
   transpose, text tokenization, or executable branch normalization.
3. **Predictor:** a new compact, bounded, deterministic probability model whose
   residuals feed an entropy coder.

Each layer must be removable. This lets the data tell us whether the genuinely
new predictor creates value beyond routing and preprocessing.

The adaptive-v0 codec is intentionally only a routing baseline. It proves the
container and measurement seam; it is not the proposed novel predictor and
must not be presented as a new compression breakthrough.

Adaptive-v1 adds a reversible 32-bit delta plus byte-transpose transform. Its
encoder compares raw and transformed samples using a staged 16–48 KiB probe,
while the same version-one decoder frame can execute either recipe. The hot
transform is implemented in a small Rust `cdylib`; the Python reference remains
available as a portability fallback and a byte-equivalence oracle.

The first measured transform result and its failed gates are recorded in
docs/benchmarks/2026-07-15-transform-smoke.md.

The first real-file native-baseline integration result is recorded in
docs/benchmarks/2026-07-15-public-starter-integration.md. Adaptive-v1 passed the
selector-overhead gate there but remained below the frontier-coverage gate.

Adaptive-v2 replaces gzip as the balanced backend with direct `libzstd` FFI,
retains LZ4 as a versioned fast-mode recipe, and combines Zstandard with the
native numeric transform. Its first repeated results are recorded in
docs/benchmarks/2026-07-15-adaptive-v2.md. The architecture is retained, but the
candidate still fails the frontier-coverage product gate.

The first seven-repetition steady-state experiment is recorded in
docs/benchmarks/2026-07-15-stability.md. It demonstrates why the repeatability
and host-load gates are required: the median candidate result passed the old
gate while severe shared-machine contention made that pass unfit for promotion.

The quiet-window decision rerun is recorded in
docs/benchmarks/2026-07-15-decision-rerun.md. A valid preflight was not enough:
the unchanged candidate still missed throughput and frontier repeatability, so
the next benchmark needed calibrated native in-process baselines before the
private holdout could be opened.

The calibrated native decision run is recorded in
docs/benchmarks/2026-07-15-calibrated-native.md. All operation-duration and
correctness checks passed, but the shared host became heavily contended during
the run. Adaptive-v2 missed both the 80% product frontier gate and all three
repeatability gates. The private holdout remains sealed until an identical run
passes on a dedicated or otherwise isolated machine.

The controlling isolated-host result is recorded in
docs/benchmarks/2026-07-15-isolated-decision.md. A clean ARM64 macOS hosted run
reduced timing variance but still rejected adaptive-v2: it missed selector,
frontier, and repeatability gates and remained dominated by direct Zstandard
level 3. Adaptive-v2 is frozen as a rejected architecture. The next candidate
must test a genuinely new block- or segment-level compression hypothesis; the
private holdout remains sealed.

Adaptive-v3 is the first alpha of that segment-level hypothesis. It divides
input into 1 MiB regions, samples each region, and chooses store, Zstandard
level 3, or native delta-transpose plus Zstandard independently. The encoder
also constructs a whole-stream candidate and emits whichever complete frame is
smaller. Segment counts, transformed segments, and stored segments are retained
in benchmark schema version 4 so routing behavior is auditable rather than
inferred from aggregate size.

The clean alpha result is recorded in
docs/benchmarks/2026-07-15-adaptive-v3-alpha.md. Segmentation preserved large
numeric-transform gains on the synthetic smoke corpus, but every licensed
public file selected the whole-stream fallback. The current recipe set is
therefore rejected for general-purpose promotion while the version-3 frame is
retained as the substrate for the next independently reversible transform.

Adaptive-v3 alpha 2 adds that first transform: a native reversible identifier
dictionary for structured text. Its clean result is recorded in
docs/benchmarks/2026-07-15-structured-text-alpha.md. It is the first candidate
to beat direct Zstandard level 3 on aggregate licensed real-file size, saving
1.81%, but it remains off the Pareto frontier because encode and decode are
still materially slower and Zstandard level 9 remains smaller. The recipe is
retained for performance work, not promoted as the default.

The first native performance pass is recorded in
docs/benchmarks/2026-07-15-structured-text-performance.md. Removing a redundant
Python dictionary-ranking pass increased clean aggregate compression throughput
from 13.16 to 22.49 MB/s without changing encoded size. Adaptive-v3 is closer to
Zstandard level 9 speed but remains dominated by it on ratio and decode speed.

The bounded-selector follow-up is recorded in
docs/benchmarks/2026-07-15-sampled-dictionary-ranking.md. Ranking from a
deterministic 1 MiB sample preserves a 1.64% size win over Zstandard level 3 and
compresses 34.3% faster than Zstandard level 9 in the clean local run, at a
5.74% size cost. Adaptive-v3 reaches the measured Pareto frontier for the first
time, but still requires faster decode, broader data, and isolated repetition.

The bounded-memory decode follow-up is recorded in
docs/benchmarks/2026-07-15-streaming-decode.md. It incrementally feeds
Zstandard output into a stateful Rust token decoder and removes the complete
transformed-stream allocation. A paired large-file measurement reduced the
decode-time peak-RSS increase by 34.3% while costing 5.1% throughput. The path
is retained for scaling, but the speed tax must be removed by fusing the stream
loop behind one native boundary before promotion.

That fusion is recorded in docs/benchmarks/2026-07-15-fused-decode.md. One
native call now owns the complete Zstandard stream lifecycle and token state
machine. With a 4 MiB size-capped buffer, the controlled large-file pair was
2.4% faster than the original two-stage decoder while using 24.8% less
incremental peak memory. The clean public result preserved all encoded bytes,
64/64 round trips, and the adaptive-v3 Pareto position; whole-frame decode
overhead remains the next measured target.

The whole-frame profile is recorded in
docs/benchmarks/2026-07-15-whole-frame-decode.md. It rejects both a branch-only
decoder rewrite and per-file raw Zstandard dictionaries with direct A/B
evidence. The retained change writes fused structured output directly into the
final frame buffer, reducing large-frame decode peak growth by 22.1% with a
near-neutral 0.35% paired speed improvement and no integrity compromise. The
next ratio-preserving speed hypothesis is an isolated STX2 command-stream
prototype, not more Python bookkeeping work.

That STX2 size gate is recorded in
docs/benchmarks/2026-07-15-stx2-command-stream.md. The reversible one-byte-token
prototype round-tripped every structured file, but its best per-file policy was
306,452 bytes, or 10.24%, larger than STX1 and also lost to direct zstd-3 on
every file. It was rejected before native or frame integration, leaving
production code and the private holdout untouched.

The first predictor-seam experiment is recorded in
docs/benchmarks/2026-07-15-context-xor-predictor.md. A bounded dual-context
native model produced 69–87% correct top predictions on structured files, but
XOR residuals grew aggregate output by 26.72%. Separating a bit-packed success
mask from unchanged miss bytes still lost by 11.38%. The prototype was removed:
future predictor work must send calibrated distributions directly to an
arithmetic or ANS coder instead of wrapping top-one predictions around
Zstandard.

The calibrated-distribution follow-up is recorded in
docs/benchmarks/2026-07-15-multi-order-probability-model.md. A normalized,
bounded order-0-through-8 model projected 0.92% fewer bytes than direct zstd-3
on the five structured files, but remained 2.78% larger than STX1, grew the
complete public corpus by 1.66%, and scanned at only about 1.50 MB/s. It failed
the predeclared integration gate, so no arithmetic or ANS format was added and
the temporary prototype was removed.

The first retained representation-specific successor is recorded in
docs/benchmarks/2026-07-15-token-side-channel.md. For JSON only, adaptive-v3 can
remove every marker-following token byte from the STX1 skeleton and compress
that ordered side channel separately. Exact complete-payload comparison keeps
STX1 for C/source files. The new recipe reduced the licensed JSON frame by
5,915 bytes, moved aggregate adaptive-v3 output to 6,747,896 bytes, or 1.73%
below direct zstd-3, passed all 64 public benchmark round trips, and retained a
within-run Pareto position. The result is a one-file JSON-family signal, not a
general or market-leading claim.

The external-validity follow-up is recorded in
docs/benchmarks/2026-07-15-expanded-json-decision.md. Four independently
sourced JSON families reject broad generalization: the raw channel won only
Natural Earth GeoJSON and was 3.51% larger than STX1 in aggregate. Integrated
adaptive-v3 still beat zstd-3 by 5.52% through exact per-file representation
selection, but lost to zstd-9, Brotli, LZMA, and 7-Zip on ratio and was not
Pareto. The generic-benefit hypothesis is rejected; the private holdout remains
sealed and no validation-tuned selector was added.

The first cheap-benefit estimator is rejected in
docs/benchmarks/2026-07-15-json-estimator-training-decision.md. Ten public
training families show that a two-threshold rule can perfectly isolate the two
winners in-sample, but family-level leave-one-out captures 0% of available
savings and incurs 1.247% payload regret.

The bounded real-compression follow-up is rejected in
docs/benchmarks/2026-07-15-fixed-sign-sampled-probe-decision.md. Its original
100 Mbps objective also selected `never`. A separately frozen 24 KiB sign rule
then separated all ten training families but failed the one-time six-family
blind validation: it skipped both small winners and captured 0 of 420 available
bytes. No sampled selector was integrated or tuned on the consumed validation
set, and the private holdout remains sealed. New ratio work must change the
representation or entropy model rather than further tune STX1 channel routing.

## Current limitations

- Workers read each file into memory; streaming and random-access tests come
  with the candidate container.
- `.clab` stores one byte stream. It does not preserve directory trees,
  filenames, permissions, timestamps, links, or other archive metadata.
- Persistent Python workers remove interpreter startup. Zstandard uses an
  in-process library binding; LZ4, Brotli, and 7-Zip baselines still include
  native CLI process startup.
- Peak RSS is the worker high-water mark, not incremental allocation.
- Energy, hardware counters, archive metadata, encryption, and coverage-guided
  native sanitizers are not yet measured. CI does run deterministic hostile-frame
  tests and seeded mutational fuzzing; that is not a security proof.
- The generated smoke corpus is deliberately small and synthetic.
