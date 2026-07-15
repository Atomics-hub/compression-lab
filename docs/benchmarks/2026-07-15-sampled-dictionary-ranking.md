# Adaptive-v3 sampled dictionary ranking

## Purpose

The first structured-text performance pass removed duplicate Python work but
still counted identifiers across the complete file. This experiment tests a
bounded selector: rank dictionary tokens from deterministic first, middle, and
tail samples, then transform and compare the complete file exactly as before.

This is a local public-validation run, not an isolated hosted product gate. The
private holdout remained sealed.

## Design

- A 1 MiB total dictionary sample split deterministically across the beginning,
  middle, and end of larger files.
- Sample boundaries are moved off partial identifiers so native and Python
  tokenization remain byte-equivalent.
- Files at or below 1 MiB still use their complete content for ranking.
- The selected dictionary still transforms the complete file.
- The complete transformed frame must still beat raw Zstandard or store after
  every header, dictionary, checksum, and size field.
- Native and Python sampled-ranking implementations have a large-input
  byte-equivalence test.

The tested clean revision was
`1bf51c5342ac94d48f2803943006c49529f72816`.

## Budget sweep

On the 9.5 MB SQLite source file, the native transform sweep was:

| Ranking budget | Transform MB/s | Transformed zstd-3 bytes |
| ---: | ---: | ---: |
| 256 KiB | 130.80 | 2,360,182 |
| 512 KiB | 128.88 | 2,354,190 |
| 1 MiB | 122.07 | 2,349,083 |
| 2 MiB | 96.51 | 2,344,542 |
| 4 MiB | 93.72 | 2,341,183 |
| Full file | 72.67 | 2,337,767 |

One MiB was selected as the balanced knee. Relative to full ranking across the
complete licensed corpus, it gives back 11,571 bytes, or 0.17%, while preserving
the aggregate win over direct Zstandard level 3.

## Clean public result

The benchmark used one warmup, two measured repetitions, deterministic shuffle
seed `20260715`, persistent workers, a 25 ms minimum operation batch, and 1,000
bootstrap samples.

Canonical evidence:

- `runs/adaptive-v3-sampled-ranking-public-clean/results.json`

All 64 measured round trips passed.

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | ---: | --- |
| adaptive-v2 | 6,866,648 | 38.5939 | 140.90 | 328.30 | no |
| adaptive-v3 | 6,753,811 | 37.9597 | 54.03 | 229.43 | yes |
| zstd-3 | 6,866,359 | 38.5922 | 206.71 | 456.89 | yes |
| zstd-9 | 6,386,970 | 35.8978 | 40.23 | 429.33 | yes |

Adaptive-v3 saved 112,548 bytes, or 1.64%, versus Zstandard level 3. Against
Zstandard level 9 it used 5.74% more bytes but compressed 34.3% faster. No codec
in this run was simultaneously smaller and faster in both directions, so the
harness marked adaptive-v3 as Pareto-optimal for the first time on the licensed
public corpus.

Absolute throughput changed materially from the preceding clean run for every
codec, so the cross-run increase is not treated as an isolated algorithm-speed
claim. The within-run tradeoff and deterministic encoded sizes are the reliable
result.

## Decision

Keep 1 MiB sampled dictionary ranking as the balanced adaptive-v3 policy. This
is the strongest result so far: a real-file size win over Zstandard level 3 and
a compression-speed win over Zstandard level 9 in the same clean run.

Do not yet promote the codec, open the private holdout, or make a market claim.
Decode remains substantially slower than both Zstandard baselines, the public
corpus is still narrow, and the timing result needs the full repeated isolated
hosted gate. The next engineering target is fused or streaming structured-text
decode so the intermediate token stream is not materialized and copied.
