# TBL1-dense development decision

## Decision

Retain native `TBL1-dense` and move next to bounded streaming and performance
stability work. On the frozen licensed development corpus, the candidate passed
every predeclared **point metric**. It did not pass the complete category gate,
and this result is not public validation or a state-of-the-art claim.

## Transparent comparison

Corpus: four CC-BY-4.0 UCI development families, 187,321,615 original bytes.
Compressed sizes include the complete candidate or baseline frame.

| Candidate or standard | Complete bytes | TBL1-dense improvement | Compress MB/s | Decompress MB/s | Peak compression RSS | Integrity / portability | Evidence basis | Size outcome |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| **TBL1-dense** | **12,012,933** | reference | **51.30** | **250.41** | **402.55 MiB** | 20/20 exact; current decision runner only | clean 5-repetition point run; isolated cold memory run | — |
| Brotli-11 | 13,425,698 | **10.52% smaller** | 0.33 | 293.21 | 254.47 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| LZMA-9 | 14,275,744 | **15.85% smaller** | 0.78 | 38.91 | 801.78 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| 7-Zip-9 | 14,301,453 | **16.00% smaller** | 2.69 | 133.13 | 648.53 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| zstd-19 | 14,570,801 | **17.55% smaller** | 2.07 | 424.88 | 240.38 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| bzip2-9 | 17,627,845 | **31.85% smaller** | 1.43 | 20.86 | 255.45 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| zstd-9 | 18,038,379 | **33.40% smaller** | 61.91 | 380.94 | 233.70 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| gzip-9 | 19,811,936 | **39.37% smaller** | 8.03 | 362.97 | 269.00 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| zstd-3 | 22,715,433 | **47.12% smaller** | 185.13 | 333.23 | 327.27 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| LZ4-1 | 38,164,405 | **68.52% smaller** | 765.00 | 393.48 | 37.17 MiB | exact on this runner | single-trial contextual census | TBL1 win |
| store | 187,321,615 | **93.59% smaller** | 1,242.40 | 719.78 | 25.03 MiB | exact on this runner | single-trial contextual census | TBL1 win |

The size comparison is exact. The speed and memory columns are transparent
context, not a controlled cross-codec speed victory: TBL1 used repeated and
isolated decision runs, while the baseline census used one measured trial.

## Family result

| Development family | TBL1-dense bytes | Strongest exact baseline | Baseline bytes | Improvement | Selector path | Family gate |
| --- | ---: | --- | ---: | ---: | --- | --- |
| AutoUniv mixed | 2,115,607 | 7-Zip-9 | 2,285,071 | **7.42% smaller** | column, zstd-9 | Pass |
| Covertype | 4,489,331 | Brotli-11 | 6,588,546 | **31.86% smaller** | column, zstd-9 | Pass |
| Facebook comment volume | 1,318,003 | Brotli-11 | 1,446,175 | **8.86% smaller** | column, zstd-16, 2 threads | Pass |
| Gas sensor | 4,089,992 | LZMA-9 | 2,922,704 | 39.94% larger | direct zstd-9 | Fail |

The Gas family selected the equally framed direct zstd-9 path and did not
regress relative to that fallback. Across all four families, no selected TBL1
frame was larger than its equally framed chosen direct backend.

## Frozen gate

| Requirement | Measured result | Status |
| --- | --- | --- |
| At least 5% below Brotli-11 aggregate | 10.52% smaller | Pass |
| At least three family wins of 5% vs strongest exact baseline | 3 of 4 | Pass |
| Compression at least 50 MB/s | 51.30 MB/s aggregate of family medians | Pass point; fragile |
| Decompression at least 250 MB/s | 250.41 MB/s aggregate of family medians | Pass point; fragile |
| Peak compression RSS at most 512 MiB | 402.55 MiB isolated | Pass |
| Five repetitions, exact, deterministic, clean commit | 20/20 exact; 5 repetitions; commit `89577e8` | Pass |
| Stable operational margin | compression 47.17-53.91 MB/s; decompression 238.45-346.94 MB/s across repetition aggregates | Not passed |
| Bounded streaming and large-file behavior | whole-file implementation with O(input) memory | Not passed |
| Fresh public validation | validation families unopened | Not run |
| Independent reproduction | none | Not run |

## Evidence

- Candidate commit: `89577e8258ed781cea540eadcddec72f285375f8`
- Corpus manifest SHA-256:
  `bac7f9bb94bac38dc621d927ff8cca70a8c2fde92c3689525a1de2d87d098f61`
- Five-repetition result SHA-256:
  `269fd8c777ef775fca048df0da4b5912908ef9709ce1fc3135ea09d570a54f07`
- Isolated memory result SHA-256:
  `d01f6c6c7ba51224c9516b06384285c62022c2bccbfd99bc400d09bed6051cbf`
- Machine-readable decision: `runs/tbl1-dense-development-decision-v1.json`

## Claim ceiling

Allowed: on the frozen licensed four-family **development** corpus,
TBL1-dense was 10.52% smaller than Brotli-11, achieved at least 5% per-family
wins on three of four families, and passed the predeclared point thresholds.

Not allowed: category win, validated win, world best, market leading, or
state of the art.

## Next gate

Implement bounded-memory streaming and large-file frames, then create enough
compression and decompression margin that repeated-run ranges stay above the
frozen thresholds. Public validation remains sealed until that development
gate is robust.
