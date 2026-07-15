# Adaptive-v3 structured-text alpha

## Purpose

The first adaptive-v3 alpha proved that the segmented frame worked but found no
real-file recipe that beat its whole-stream fallback. This experiment adds one
new reversible hypothesis: replace repeated ASCII identifiers with compact
dictionary codes before Zstandard level 3.

This is a public validation experiment, not a product-gate or private-holdout
run. The private holdout remained sealed.

## Implementation under test

- A deterministic per-file dictionary ranked by estimated net identifier gain.
- 128 dictionary entries for JSON-like files, 16 for files below 64 KiB, and up
  to 254 for other structured text.
- A byte-exact transform that escapes its marker byte and retains the dictionary
  inside the transformed stream.
- Native Rust encode and decode with a byte-equivalent Python reference path.
- A bounded transformed-size prefix, per-segment CRC32, and whole-frame SHA-256.
- Exact complete-frame comparison against store and raw Zstandard level 3; the
  new recipe is emitted only when all transform and frame metadata still win.
- Structured-text route, dictionary-size, and candidate-count telemetry in the
  canonical benchmark result.

The tested revision was clean commit
`5360d825b12412d0fd3871e9b4065e064757d532`.

## Method

The clean smoke and licensed public runs used persistent workers, deterministic
shuffle seed `20260715`, one warmup, two measured repetitions, a 25 ms minimum
operation batch, and 1,000 deterministic bootstrap samples. Every measured
round trip was checked by SHA-256.

Canonical local evidence:

- `runs/adaptive-v3-structured-smoke-clean/results.json`
- `runs/adaptive-v3-structured-public-clean/results.json`

## Licensed public result

All 64 measured round trips passed.

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s |
| --- | ---: | ---: | ---: | ---: |
| adaptive-v2 | 6,866,648 | 38.5939 | 90.89 | 246.05 |
| adaptive-v3 | 6,742,240 | 37.8946 | 13.16 | 143.99 |
| zstd-3 | 6,866,359 | 38.5922 | 94.52 | 295.45 |
| zstd-9 | 6,386,970 | 35.8978 | 25.65 | 287.84 |

Adaptive-v3 saved 124,119 bytes, or 1.81%, versus direct Zstandard level 3.
All five licensed JSON/source-code files selected the structured-text recipe.
The database and PDF retained raw Zstandard level 3, and the already-compressed
ZIP retained store. This is the project's first clean aggregate real-file size
win over its direct Zstandard level-3 baseline.

The win is not a product pass. Adaptive-v3 was 86.07% slower to compress and
51.26% slower to decompress than Zstandard level 3. It was also 5.56% larger
than Zstandard level 9 while compressing more slowly. It is therefore not on the
measured Pareto frontier.

## Synthetic regression result

All 80 measured smoke round trips passed. Adaptive-v3 produced 1,680,074 bytes,
2,911 bytes fewer than the prior v3 recipe set and 672,649 bytes (28.59%) fewer
than direct Zstandard level 3. The structured JSON-log item joined the existing
numeric and mixed-region transform wins.

## Decision

Retain the structured-text recipe and native implementation as the first
validated real-file compression improvement. Do not promote adaptive-v3 as a
general-purpose default, open the private holdout, or make a market claim yet.

The next work is performance, not validation-threshold tuning: profile and
reduce token-counting and duplicate candidate-encode cost, expand the licensed
structured-text corpus beyond SQLite and Chinook, and test whether the transform
can approach Zstandard level-9 ratio without falling below its speed. Only a
repeatable Pareto improvement should advance to the isolated hosted gate.
