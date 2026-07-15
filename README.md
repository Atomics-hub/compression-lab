# Compression Lab

Compression Lab is the executable measurement foundation for a new adaptive
lossless-compression system. It is intentionally independent of the eventual
codec so that every new selector, transform, predictor, and container revision
is judged by the same contract.

Version 0.1 provides:

- deterministic heterogeneous corpus generation;
- isolated codec workers for store, gzip/DEFLATE, bzip2/BWT, and LZMA2;
- SHA-256 round-trip verification for every trial;
- separate cold-process and persistent-worker wall timing modes;
- deterministic randomized trial order, host-load sampling, per-repetition
  confidence intervals, and repeatability gates;
- calibrated operation batches with explicit target-completion telemetry;
- in-process Zstandard baselines using the same `libzstd` path as adaptive-v2
  and adaptive-v3;
- worker CPU telemetry that includes completed external-codec child processes;
- worker peak-RSS telemetry;
- compressed size, throughput, expansion, and transfer-time utility at
  configurable bandwidths;
- aggregate and per-file JSON, aggregate CSV, and a Markdown run report;
- Pareto marking across size, compression speed, and decompression speed;
- explicit train/validation/holdout split support.
- an adaptive-v0 self-describing frame that samples content and safely chooses
  between store and gzip-1, including original-size and SHA-256 verification.
- provenance-required real-corpus intake and cryptographically frozen private
  holdouts;
- an optimized Rust delta-transpose library with a verified Python fallback;
- exact native executable and version capture for Zstd, LZ4, Brotli, and 7-Zip.
- an adaptive-v2 frame that can route to store, Zstandard, LZ4, or
  delta-transpose plus Zstandard without breaking version-1 decoding.
- an adaptive-v3 segmented frame with per-segment recipes and CRC32 checks,
  whole-file SHA-256 verification, and a whole-stream fallback that prevents
  segmentation from silently worsening compressed size.

The built-in codecs use Python's standard-library bindings. That keeps the
harness dependency-free and gives us a working baseline on a clean machine.
Native Zstd, LZ4, Brotli, and 7-Zip adapters are discovered automatically when
their CLI executables are installed. Unavailable adapters remain visible
through list-codecs but cannot be selected accidentally.

## Quick start

Use any Python 3.9 or newer:

    cd /path/to/compression-lab
    export PYTHONPATH="$PWD/src"
    python3 -m compresslab init-corpus --output corpora/smoke
    python3 -m compresslab run \
      --corpus corpora/smoke \
      --output runs/smoke \
      --repetitions 3 \
      --warmups 1

For the exact ten-codec steady-state stability recipe, including corpus and
native-library verification, randomized order, seven measurements, and both
gate reports:

    scripts/run-stability.sh

The script waits for three qualifying preflight samples and exits non-zero when
the quiet window times out or a research gate fails. Inspect the generated gate
reports before treating that as an infrastructure error.

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

## Current limitations

- Workers read each file into memory; streaming and random-access tests come
  with the candidate container.
- Persistent Python workers remove interpreter startup. Zstandard uses an
  in-process library binding; LZ4, Brotli, and 7-Zip baselines still include
  native CLI process startup.
- Peak RSS is the worker high-water mark, not incremental allocation.
- Energy, hardware counters, archive metadata, encryption, and malicious-input
  fuzzing are not yet measured.
- The generated smoke corpus is deliberately small and synthetic.
