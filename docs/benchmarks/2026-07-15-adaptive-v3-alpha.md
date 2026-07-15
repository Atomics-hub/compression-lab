# Adaptive-v3 segmented alpha

## Purpose

Adaptive-v2 was rejected on the isolated hosted decision run because wrapping
Zstandard could not improve on Zstandard. Adaptive-v3 tests the first genuine
segment-level alternative: independently transform heterogeneous regions while
retaining a whole-stream fallback.

This is an alpha discovery experiment, not a product-gate or private-holdout
run. The private holdout remained sealed.

## Implementation under test

- Version-3 self-describing frame with a segmented backend.
- 1 MiB candidate segments and a representative 32 KiB sample per segment.
- Per-segment recipes: store, Zstandard level 3, or native 32-bit
  delta-transpose plus Zstandard level 3.
- A transform is selected only when its sampled output is at least 3% smaller
  than raw sampled Zstandard.
- The encoder compares the complete segmented frame with a complete
  whole-stream Zstandard-or-store frame and emits the smaller result.
- Every segment carries its original size and CRC32; the complete frame carries
  original size and SHA-256.
- Benchmark schema version 4 records selected and candidate segment counts,
  transformed-segment counts, and stored-segment counts.

The tested revision was clean commit
`bd05b6b23a8d70871aad5c9a49cff39671a27b1e`.

## Method

Both runs used persistent workers, deterministic shuffled order seed
`20260715`, one warmup, two measured repetitions, a 25 ms minimum operation
batch, and 1,000 deterministic bootstrap samples. Every measured round trip
was checked by SHA-256.

The two canonical local evidence files are:

- `runs/adaptive-v3-alpha-smoke-clean/results.json`
- `runs/adaptive-v3-alpha-public-clean/results.json`

## Synthetic smoke result

All 80 measured round trips passed.

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s |
| --- | ---: | ---: | ---: | ---: |
| adaptive-v2 | 1,682,985 | 28.6422 | 94.14 | 158.80 |
| adaptive-v3 | 1,682,931 | 28.6413 | 94.18 | 156.80 |
| zstd-3 | 2,352,723 | 40.0403 | 126.72 | 137.61 |
| zstd-9 | 2,350,856 | 40.0085 | 93.94 | 207.71 |

Adaptive-v3 was 669,792 bytes, or 28.47%, smaller than Zstandard level 3. It
was also 54 bytes smaller than adaptive-v2. The gain came from the numeric-f32
and mixed-regions items selecting delta-transpose plus Zstandard. The
source-tree TAR also selected two raw-Zstandard segments and finished 127 bytes
smaller than its whole Zstandard level-3 stream after frame overhead.

This proves the segmented frame and routing mechanism can preserve a local
transform win. It does not establish a general-purpose advantage because the
corpus is synthetic and adaptive-v2 already captured nearly all of the same
numeric-transform gain.

## Licensed public-corpus result

All 64 measured round trips passed.

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s |
| --- | ---: | ---: | ---: | ---: |
| adaptive-v2 | 6,866,648 | 38.5939 | 64.52 | 211.75 |
| adaptive-v3 | 6,866,784 | 38.5946 | 46.72 | 212.71 |
| zstd-3 | 6,866,359 | 38.5922 | 89.84 | 306.65 |
| zstd-9 | 6,386,970 | 35.8978 | 21.35 | 203.00 |

Adaptive-v3 selected the whole-stream fallback on all eight licensed files.
Seven files used Zstandard level 3 and the already-compressed ZIP used store.
No segment used the numeric transform. Relative to direct Zstandard level 3,
adaptive-v3 was 425 bytes larger from framing, 48.00% slower to compress, and
30.63% slower to decompress. It was also 136 bytes larger than adaptive-v2.

## Decision

Keep the version-3 frame as an experimental substrate, but reject this recipe
set as a general-purpose candidate. Do not promote adaptive-v3, open the private
holdout, weaken the gates, or tune the 3% selector threshold against these
validation files.

The experiment isolates the missing ingredient: segmentation alone is not the
advantage. A segment must expose structure that Zstandard cannot already model.
The next alpha should add one independently reversible, file-family-specific
transform with a falsifiable public-corpus target. The best current target is a
structured-text transform for JSON and source code because the licensed corpus
contains both families, the transform can be tested without changing the frame,
and success requires beating the whole-stream fallback after all metadata.

Only if that transform produces repeatable real-file gains should adaptive-v3
return to an isolated hosted decision run.
