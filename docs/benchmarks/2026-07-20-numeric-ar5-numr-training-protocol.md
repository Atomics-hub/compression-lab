# AR5/NUM-R exact numeric specialist training protocol

## Status and claim ceiling

This document and `config/numeric-ar5-numr-training-v1.json` freeze the first
training-only research boundary for a new exact numeric specialist. They do not
authorize corpus acquisition, tool download, implementation measurement,
validation, or private-holdout access. The configuration intentionally has
`measurement_authorized: false`, null binary digests, and null results. Those
are fail-closed blockers, not blanks an experiment may ignore.

The strongest claim available after a clean pass is **training advancement on
the declared numeric tracks**. Nothing here supports a validation, holdout,
independent-reproduction, product, universal, market-leading, world-best, or
state-of-the-art claim.

The earlier DMS2 public-validation result is immutable and negative. Gisette
and Madelon are consumed evaluation families and are forbidden in this
training lane. AR5/NUM-R is a new binary numeric representation, not a retuning
of DMS2's text-matrix model.

## Research question

Can an exact, independently blocked numeric format beat the strongest
applicable floating-point, integer, matrix, time-series, and generic baselines
by at least 6% in complete bytes while retaining native-class decode speed,
bounded memory, deterministic output, streaming operation, and cross-machine
bit identity?

The candidate combines two ideas:

1. **AR5** applies ALP-style decimal recasting only when a deterministic
   integer-rational inverse recreates the original IEEE-754 word exactly, then
   subtracts a per-vector integer origin before residual coding.
2. **NUM-R** selects among the recast representation, XOR/front-bit coding,
   integer predictors, byte planes, a generic direct frame, and store. It
   compares complete candidate frames rather than idealized payload bits.

This is a hypothesis, not a claim that AR5 reproduces or improves ALP.

## Eligible inputs and split boundary

The declared tracks are float32 and float64 ordered time series, float32 and
float64 dense matrices, and signed/unsigned 16-, 32-, and 64-bit integer time
series and dense matrices. The original dtype, endian order, rank, dimensions,
layout, and optional timestamp representation are part of the source and must
round-trip exactly.

Before measurement, a separate corpus lock must identify every training item
by public source URL, immutable source revision, license and license-file
digest, selected member path, acquisition command, payload byte count, value
count, dtype, endian order, shape, layout, and SHA-256. Each declared track
needs at least two unrelated licensed families, three size strata, and both
smooth and adversarial/high-entropy examples. Generated edge cases supplement
but never replace licensed data.

Validation family names and hashes stay outside the training worktree until a
training candidate and runner are frozen. Private holdout identities stay with
an independent custodian. Training data may never be promoted into either
evaluation split. No validation or holdout byte may be sampled, decoded,
summarized, or used to choose an exponent, predictor, block size, or baseline.

## Exact input and block envelope

The input adapter accepts only the dtypes and layouts enumerated in the JSON
contract. It rejects ragged matrices, ambiguous native-endian aliases,
truncated words, shape/byte-count disagreement, and timestamp/value count
disagreement. Float exactness means word identity, not numerical equality:
`+0`, `-0`, infinities, subnormals, signaling/quiet state, NaN sign, and NaN
payload must survive unchanged.

Vectors contain 1,024 values. A superblock contains at most 65,536 values and
is independently decodable. Stream chunks are bounded at 64 MiB. A value count
not divisible by 1,024 produces one explicitly counted tail vector. File,
superblock, vector, and fallback headers; type and shape metadata; mode bytes;
all tables, seeds, coefficients, exceptions, padding, indexes, checksums, and
the footer count toward compressed size.

The source digest covers the canonical side-metadata encoding followed by the
original payload bytes. A decoder may not publish output until bounds,
structure, complete output size, and the source digest pass. Atomic output and
specific corruption errors are mandatory.

## AR5 decimal-origin recasting

For float32, the frozen exponent search is 0 through 10. For float64 it is 0
through 18. For each exponent `e`, factors `f = 0..e` are considered in stable
order. The implementation decomposes the IEEE sign, binary exponent, and
mantissa and uses checked integer powers of two and five. It must not depend on
host floating-point multiplication, casts, current rounding mode, extended
precision, fused operations, or fast-math.

A value is regular for `(e, f)` only when the proposed recast integer and the
integer-rational inverse reproduce the exact original IEEE word. The format
stores the deterministic minimum recast integer as the vector origin and codes
nonnegative offsets or predicted residuals. Nonfinite values and all failed
round trips are exceptions stored as exact raw words. The exception bitmap,
positions if used, raw words, count, exponent, factor, origin, bit width, and
padding all count.

When all values are exceptional, the origin is zero and the selector normally
prefers XOR, byte-plane, direct, or store. The implementation may not canonicalize
NaNs or signed zero. Decimal candidates tie-break by complete vector bytes,
then exponent, factor, and origin.

## NUM-R predictors and residuals

Every eligible representation is an independently exact candidate:

- XOR-previous coding reuses a prior leading/trailing-zero window and has a
  stable explicit window-update syntax. Its complete front-bit and length
  metadata count.
- Delta and delta2 use checked widening or defined modulo-`2^N` arithmetic.
- Integer LPC orders 1, 2, and 4 use deterministic integer least-squares,
  checked 128-bit intermediates, signed 16-bit coefficients, explicitly stored
  seeds and coefficients, and lexicographic tie breaks. No BLAS, host float,
  nondeterministic reduction, or architecture-specific estimate may select a
  model.
- Residual choices are zigzag bitpack, two's-complement bitpack, zero-run plus
  bitpack, byte-plane plus Zstandard, and raw-word byte-plane plus Zstandard.
- Every candidate-internal Zstandard path is pinned to upstream revision
  `f8745da6ff1ad1e7bab384bd1f9d742439278e99`, level 9, one thread, no
  dictionary, frame checksum and content size enabled, and long-distance
  matching disabled. The format specification must freeze every effective
  context parameter before implementation or measurement.
- Byte-plane order is fixed by logical word significance, not host endian
  order. Restoration returns the original source endian order.

Overflow, coefficient failure, pathological exceptions, or a larger complete
frame simply makes that mode ineligible. It must never cause lossy coercion or
undefined behavior.

## Selector and fallback safety

For each vector or superblock, the encoder materializes every eligible complete
candidate frame. It chooses the smallest complete byte count, then the lower
declared decode-cost rank, then the lower stable mode ID. Probe input is bounded
to the current 64 MiB stream chunk. Probe wall time, allocations, exceptions,
and discarded output bytes count as compression overhead.

Direct Zstandard is eligible only when its complete self-contained frame is
smaller than store. Otherwise store wins. The format may exceed the source by
at most a frozen 96-byte top-level envelope, and per-item comparisons include
that envelope. Selector training may not use file paths, corpus labels,
validation-derived weights, external dictionaries, or machine-specific timing.

## Cheap ablation ladder

The ladder is frozen before implementation:

1. `NUM-R0`: store, direct Zstandard, and raw-word byte-plane fallback.
2. `NUM-R1`: add XOR/front-bit coding.
3. `AR5-A`: add exact decimal recasting without origin.
4. `AR5-B`: add the decimal origin.
5. `NUM-R2`: add delta and delta2.
6. `NUM-R3`: add LPC orders 1, 2, and 4.
7. `NUM-R4`: integrate exception encodings, residual entropy choices, and the
   deterministic selector.

The exact kill rules are in the JSON contract. A component below its declared
signal is removed rather than carried into a larger unfalsifiable combination.
LPC also dies if its compression time exceeds twice `NUM-R2`.

## Baseline lock and fair framing

The source identities below were selected from official repositories. This
turn queried repository metadata only; it did not acquire or build a tool.
Before any measurement, a separate acquisition lock must add source archive,
license, adapter-source, and built-binary SHA-256 values plus compiler/runtime
versions. The null binary hashes intentionally keep this protocol unauthorized.

| Baseline | Frozen upstream | License | Applicability |
|---|---|---|---|
| FastLanes ALP and integer paths | [`cwida/FastLanes@f0edc102`](https://github.com/cwida/FastLanes/tree/f0edc1020a538f1f8098640fce8347c9ac247a0d) | MIT | float32/64 and integer arrays |
| Chimp128 paper artifact | [`panagiotisl/chimp@320d397`](https://github.com/panagiotisl/chimp/tree/320d397157c7e0696b3c64dc1711fc17a3add3da) | Apache-2.0 | float64 time series |
| Gorilla reference-class adapter | [`ghilesmeddour/gorilla-time-series-compression@093544c`](https://github.com/ghilesmeddour/gorilla-time-series-compression/tree/093544c6e643aef911ff83527f595bc2d9280ed8) | MIT | float32/64 time series |
| Blosc2 shuffle/bytedelta + Zstandard | [`Blosc/c-blosc2@d52cbee`](https://github.com/Blosc/c-blosc2/tree/d52cbeec8afb35ada7ea62f04168e5d970d9c40b) | BSD-3-Clause | all fixed-width tracks |
| fpzip 1.3.0 exact mode | [`LLNL/fpzip@4a539c0`](https://github.com/LLNL/fpzip/tree/4a539c06d98b1c029b08324a086d4b75689a2b72) | BSD-3-Clause | float matrices |
| Zstandard 1.5.7 | [`facebook/zstd@f8745da`](https://github.com/facebook/zstd/tree/f8745da6ff1ad1e7bab384bd1f9d742439278e99) | BSD-3-Clause or GPL-2.0-only | generic ratio control |
| Brotli 1.2.0 | [`google/brotli@028fb5a`](https://github.com/google/brotli/tree/028fb5a23661f123017c060daa546b55cf4bde29) | MIT | generic ratio control |
| LZ4 1.10.0 | [`lz4/lz4@ebb370c`](https://github.com/lz4/lz4/tree/ebb370ca83af193212df4dcbadcc5d87bc0de2f0) | BSD-2-Clause | generic speed control |
| Store | in-tree adapter | MIT | incompressibility floor |

The exact build and encode/decode command templates are frozen in the JSON
configuration. FastLanes, Chimp, Gorilla, Blosc2, and fpzip need thin reviewed
adapters because native research counters are not necessarily portable complete
artifacts. An adapter must serialize every byte required for an independent
decode. Ideal bit counts, compressed payloads without type/shape metadata,
JVM/Python objects without serialization, and library buffers without their
frame metadata are inadmissible.

Baseline applicability is resolved from the item's declared track and dtype.
Chimp and Gorilla additionally require a source-provided complete timestamp
column. They are ineligible for value-only series, and an adapter may not
manufacture synthetic timestamps to make them applicable. Every track must
retain an applicable specialist as well as the generic controls. Acquisition
lock verification must resolve every command placeholder (`input`, `output`,
`dtype`, `shape`, `typesize`, and `timestamps`) before authorizing a run.

For a track, the ratio baseline is the smallest complete artifact among every
applicable specialist and generic control. The speed baseline is reported
separately; no single composite score may hide a ratio loss or impractical
runtime.

## Schedule and runtime accounting

Each input/variant has one discarded warmup and seven measured cold-child
rounds in a predeclared alternating Latin-style order. Every trial uses a fresh
process and atomic destination. Parent wall time includes startup, input read,
type/shape validation, analysis and every selector probe, compression or
decompression, complete metadata/index/checksum handling, output write and
flush, publication, and restored SHA-256 verification. Acquisition and
compilation are excluded.

Peak RSS is whole-child `wait4` accounting or an independently verified
platform equivalent. Temporary candidate frames, sampled values, exception
tables, coefficient solving, and selector scratch memory count. Report both
median aggregate and every item/round; never subtract adapter overhead.

## Immutable gates

A training candidate advances only if all are true:

1. every candidate and baseline decode restores exact side metadata and bytes;
2. candidate complete bytes are at least 6% smaller than the strongest
   applicable baseline in aggregate **and on every declared track**;
3. no item is more than 0.5% larger than its equally framed safe direct/store
   fallback;
4. median compression is at least 300 MB/s and at least 50% of the fastest
   ratio baseline;
5. median decompression is at least 1,000 MB/s and at least 80% of the fastest
   ratio baseline;
6. peak RSS is at most 512 MiB, and stream chunks never exceed 64 MiB;
7. two encoded repetitions are byte-identical;
8. pinned x86_64 and arm64 builds emit the same bytes and cross-decode each
   other's frames exactly;
9. truncated, corrupted, overflowing, wrong-type, wrong-shape, and wrong-endian
   inputs fail specifically without partial publication; and
10. complete accounting and selector/runtime overhead checks pass.

After a training pass, a separately frozen fresh validation must repeat the 6%
aggregate and per-track advancement with no tuning or rerun. Only then may an
independently held, one-shot private holdout target at least 5% aggregate and
per-track advancement. A failure never authorizes changing the gate after
seeing the failed split.

The holdout threshold is one percentage point below the 6% training and fresh
validation thresholds solely to tolerate ordinary split variance in a
one-shot, independently controlled evaluation. It does not permit tuning,
rerunning, or changing the candidate after validation.

## Required next step

Freeze a licensed training manifest and a baseline acquisition/binary lock.
Only after both pass independent review may implementation and synthetic
format/corruption tests begin. No benchmark command in this protocol is
currently authorized to run.
