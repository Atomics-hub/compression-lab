# AR5/NUM-R first executable candidate preflight

## Claim boundary

This is a synthetic-only implementation preflight for the cheapest frozen
AR5/NUM-R ablation. It is not a corpus experiment or a benchmark. No training,
validation, or private-holdout item was acquired or accessed, no external
baseline was executed, and no ratio or speed comparison is authorized.

The only supported claim is that one bounded Python prototype produced
deterministic, exact, self-describing frames for the declared synthetic cases,
rejected the exercised corruption/truncation cases, and counted its complete
frame bytes. The candidate remains internal and is not wired into the public
CLI or API.

## Official-source and runtime lock

`config/numeric-ar5-numr-toolchain-lock-v1.json` binds eight official GitHub
source trees by repository URL, full commit, Git tree, license path, license
byte count, and license SHA-256: FastLanes, Chimp, Gorilla, Blosc2, fpzip,
Zstandard, Brotli, and LZ4. The acquisition verifier checked clean detached
checkouts in the ignored `.research-tools` cache. Its lock-file SHA-256 was
`1affbf51fc0bc2f7a59472ca1cc37ed2e7785d5c5ad6f22256a574585501fba6`.

The executable candidate runtime is separately locked to CPython 3.12.12,
`python-zstandard` 0.25.0's C extension
`b5a59cf2ff46dd1fc9e7959ccae934136a4c128c7ab747dfdbfcc16fd1f755b5`,
and bundled libzstd 1.5.7. Zstandard uses level 9, the single-thread API,
content size and checksum enabled, and no dictionary ID. This is a local arm64
prototype lock, not the future two-architecture product lock.

All external baseline binaries and adapters remain unbuilt and unauthorized.
The source lock prevents identity drift; it does not pretend that research
library buffers are already comparable self-contained artifacts.

## Executable NMR1 envelope

`compresslab.numeric_ar5_numr` implements 1,024-value independently decodable
blocks within a 64 MiB in-memory input ceiling. The frame carries dtype,
explicit source endian order, rank, shape, layout, vector size, source size,
block count, every block mode/count/length, every transform payload, a digest
of side metadata plus original bytes, and a digest of the encoded frame.

For each block the selector materializes these complete payloads before making
a deterministic `(bytes, mode ID)` choice:

1. equally framed raw store;
2. XOR-previous with explicit new/reused leading/trailing-zero windows;
3. logical-significance byte planes plus the locked Zstandard frame; and
4. for floats, exact decimal-origin recasting with raw-word exceptions.

AR5 decomposes source IEEE words into integer rationals, rounds scaled values
to nearest-even using integer arithmetic, bounds recast integers to signed 128
bits, and accepts a value only when an integer-only rational-to-IEEE inverse
recreates the original word. Nonfinite values, negative zero, and every value
that does not pass that proof are stored as exact raw-word exceptions. The
exception bitmap, count, words, exponent/factor, signed origin, offset width,
packed offsets, and padding all live inside the compared payload.
Pairs with the same `exponent - factor` have identical scale and payload size;
the implementation applies the frozen tie break directly and evaluates their
canonical lowest-exponent representative `(power, 0)` once.

The selector assertion proves each emitted frame is no larger than the same
metadata, block headers, digests, and raw store payload. This is a zero-byte
regression relative to its equally framed store fallback, stronger than the
frozen 96-byte allowance. It is not a claim that the complete frame is smaller
than the original unframed input.

## Synthetic preflight receipt

The deterministic seed was 42,330. The script reports complete frames; the
sizes below are test evidence, not benchmark results.

| Synthetic case | Selected mode | Source bytes | Complete frame bytes | Frame SHA-256 |
|---|---:|---:|---:|---|
| float64 rounded sine | AR5 decimal origin | 8,192 | 1,675 | `c1505f31ac9166a99b66b3d53cb89342e675c5593b4b3fce2ec9b7a6bb8e4f81` |
| float32 special raw words | store | 24 | 136 | `df1bbc16c5468bd618cdf5e3f7ffcbce586e35590421ee83be7794e0617a1bc2` |
| int64 monotone sequence | byte-plane Zstandard | 8,192 | 409 | `2875c3f303c93d4ac5722c9ddbf7bf87dfa13ff7b67bfaed7abf21ff92a1887c` |
| float64 repeated value | XOR/front-bit | 40 | 121 | `9ce07bdbf677f916007550c9c03622e3c812baa7d281ac5154b642bc5984e9b8` |
| uint64 seeded random words | store | 8,192 | 8,304 | `83120cf54ff88b540e264c4a647cc1f2ddfc2af3c4cc2f95edb22d69e1f7489d` |

Focused tests cover all eight dtypes and both endian orders, rank-one and
matrix layouts, tail blocks, signed zero, infinities, subnormals, quiet and
signaling NaN payloads, 2,000 seeded finite IEEE reconstruction checks per
float width, seeded raw-word fuzz, deterministic frame identity, a one-bit
mutation at every byte position of one frame, every truncation of that frame, caller
output bounds, shape disagreement, and the store ceiling.

## Remaining blockers and compute estimate

Corpus measurement remains blocked on four concrete artifacts:

1. reviewed complete-artifact adapters and built-binary locks for every
   specialist baseline;
2. identical candidate behavior and binary identities on pinned x86_64 and
   arm64 hosts;
3. a licensed training-only corpus manifest with unrelated families and exact
   item identities; and
4. a frozen cold-child benchmark runner plus dedicated-host receipt.

The current machine also lacks Maven, so the pinned Chimp source cannot be
built here until that exact build dependency is acquired. FastLanes, Blosc2,
fpzip, Gorilla, and the generic controls still need reviewed adapters even
where compilers or CLIs are already present.

Expected next-stage compute is modest for builds but material for the Python
candidate. Allow roughly 30–90 build minutes and 5–10 GiB scratch per host for
all baseline adapters, then approximately 1–6 CPU-hours per GiB of float64
input for the current 19-scale integer-rational search. That range is a static
planning estimate, not a measurement. A native/vectorized recast kernel should
be completed before a multi-GiB training sweep. The first training smoke test
should be capped at 64–256 MiB on an isolated host; only a clean exactness and
resource receipt should unlock the larger frozen training run.
