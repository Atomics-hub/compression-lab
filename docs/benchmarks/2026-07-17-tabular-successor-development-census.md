# Fresh tabular-successor development census

## Decision

**Advance the record-table representation; replace the dense-matrix path.**

On six fresh development families, unchanged TBS1 produced 1,697,505 bytes.
It beat eight of ten exact standards in aggregate, including 7-Zip-9,
Brotli-11, and every tested Zstandard level. It remained 0.26% larger than
LZMA-9 and 2.87% larger than bzip2-9, so there is no aggregate ratio win.

The track split is more useful than the aggregate. TBS1 was 4.88% smaller than
the strongest record-table standard, but 59.88% larger than the strongest
dense-feature-matrix standard. Preserve the record-table path and focus the
next representation on repeated-space, binary, small-integer, and fixed-width
numeric matrices.

## Full standards chart

Positive values in “TBS1 size delta” mean TBS1 is smaller. Every one of the 66
candidate and baseline trials restored the exact source bytes.

| Codec | Complete bytes | Source % | TBS1 size delta | Compress MB/s | Decompress MB/s | Peak RSS MiB | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| bzip2-9 | **1,650,170** | **8.85%** | **2.87% larger** | 4.09 | 28.06 | 61.7 | ✅ |
| LZMA-9 | 1,693,160 | 9.09% | **0.26% larger** | 0.69 | 50.55 | 223.8 | ✅ |
| **TBS1 stream-dense** | **1,697,505** | **9.11%** | candidate | **45.52** | **278.26** | **118.6** | ✅ |
| 7-Zip-9 | 1,703,372 | 9.14% | **0.34% smaller** | 3.34 | 124.44 | 143.4 | ✅ |
| Brotli-11 | 1,755,288 | 9.42% | **3.29% smaller** | 0.43 | 239.36 | 152.9 | ✅ |
| zstd-19 | 1,802,591 | 9.67% | **5.83% smaller** | 1.81 | 720.14 | 196.3 | ✅ |
| gzip-9 | 2,298,691 | 12.33% | **26.15% smaller** | 3.60 | 695.15 | 61.4 | ✅ |
| zstd-9 | 2,307,534 | 12.38% | **26.44% smaller** | 57.32 | 595.30 | 85.0 | ✅ |
| zstd-3 | 2,795,608 | 15.00% | **39.28% smaller** | 154.90 | 542.01 | 65.2 | ✅ |
| LZ4-1 | 4,920,321 | 26.40% | **65.50% smaller** | 255.90 | 311.16 | 25.2 | ✅ |
| Store | 18,635,606 | 100.00% | **90.89% smaller** | 1,627.18 | 2,189.08 | 25.8 | ✅ |

## Track scorecard

| Track | Source bytes | TBS1 bytes | Strongest standard | Standard bytes | TBS1 result | Decision |
| --- | ---: | ---: | --- | ---: | --- | --- |
| Record tables | 13,740,265 | **1,377,241** | LZMA-9 | 1,447,960 | **4.88% smaller** | Keep and improve |
| Dense feature matrices | 4,895,341 | 320,264 | bzip2-9 | **200,311** | **59.88% larger** | Replace representation |

The record-table result narrowly misses the predeclared 5% target against its
strongest standard by 0.12 percentage points. It does beat bzip2-9 by 5.01%
and 7-Zip-9 by 5.57%. The dense-matrix loss is not hidden by the byte-weighted
aggregate.

## Family scorecard

| Family | TBS1 bytes | Strongest standard | Standard bytes | TBS1 result | Frozen TBS1 route |
| --- | ---: | --- | ---: | --- | --- |
| Appliances Energy | **1,143,533** | bzip2-9 | 1,176,461 | **2.80% smaller** | column |
| Bike Sharing | **155,877** | LZMA-9 | 171,600 | **9.16% smaller** | column |
| Seoul Bike | **77,831** | 7-Zip-9 | 94,490 | **17.63% smaller** | column |
| Multiple Features pixels | 130,296 | bzip2-9 | **77,935** | **67.19% larger** | direct fallback |
| Optical Digits | 117,259 | bzip2-9 | **89,361** | **31.22% larger** | column |
| Semeion digits | 72,709 | bzip2-9 | **33,015** | **120.23% larger** | direct fallback |

The two space-delimited matrix families were detected as comma-delimited by
the unchanged TBS1 auto-detector and selected direct fallback. This is a
diagnosis, not permission to special-case filenames or track labels. A
production selector may use only bounded current-file bytes and complete
framed candidate sizes.

## Evidence boundary

- Stage: single-trial clean development census
- Candidate: unchanged `tbl1-stream-dense`
- Corpus: six fresh CC BY 4.0 UCI families, 18,635,606 exact bytes
- Trials: 66; failures: 0; exact round trips: 66
- Commit: `7bb7ff4e68a385fb6a037bdf1e093593f093c23e`
- Git state at run start: clean
- Runner: macOS 26.5.2 arm64, 10 logical CPUs
- Execution: persistent worker, deterministic shuffled order, no warmup, one
  measured repetition
- Timing: worker startup excluded; IPC, file I/O, and native CLI startup
  included
- Public validation: four declared families remain unopened
- Private holdout: sealed
- Results SHA-256:
  `45722d28d272b4333ee29308d92c3cebbf6757af5c9d57b91d6a52591905c552`
- Summary CSV SHA-256:
  `e62ba89be8053a2728b55f580602eedee35a5f55a0d1373a4aa3010f924ca1e8`
- Generated report SHA-256:
  `45cd04bcda8764597777780da22768b3f9564facd7e5841666d70f2150ae9fac`

Raw evidence is retained in
[`runs/tabular-successor-development-census-v1`](../../runs/tabular-successor-development-census-v1/).

## Claim ceiling

This is one local development trial per pair. It can select research work and
reject representations; it cannot support a public-validation, private-
holdout, independent, category-best, market-leading, or state-of-the-art
claim. The current public README keeps that boundary visible beside the chart.

## Next experiment

Freeze a dense-matrix development protocol that tests:

1. whitespace-aware row and field framing that preserves repeated spaces;
2. compact token alphabets for binary and small non-negative integers;
3. column-major or bit-plane layouts selected only from bounded file bytes;
4. complete framed comparison against direct fallback; and
5. leave-one-family-out selection, with the record-table path protected from
   regression.
