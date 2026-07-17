# DMS2 native development gate

## Decision

**DMS2 passes the frozen ratio, compression-speed, and decompression-speed
development gates together. It is not yet locked for public validation.**

DMS2 combines a bounded 64 KiB content selector, parallel DMA2 adaptive
contexts for broader numeric alphabets, and DMP1 bit planes for alphabets of
four lexemes or fewer. The selector uses current-file bytes only. It does not
use a filename, family identity, known shape, source ID, digest, DOI, or track
label.

On the three fresh development matrices, seven measured complete-frame trials
after one warmup produced 189,738 aggregate bytes, 51.03 MB/s compression, and
255.55 MB/s decompression. Every frame was deterministic, restored the exact
source bytes, and rejected a corrupted payload.

## Full standards chart

The standards are the unchanged dense-matrix subset of the fresh 11-codec
census. DMS2 timings are medians from seven repetitions; baseline timings were
one local trial per codec and family, so speed comparisons are contextual.

| Codec | Complete bytes | DMS2 size result | Compress MB/s | Decompress MB/s | Exact |
| --- | ---: | ---: | ---: | ---: | --- |
| **DMS2 native** | **189,738** | candidate | **51.03** | **255.55** | ✅ |
| bzip2-9 | 200,311 | **5.28% smaller** | 1.71 | 27.18 | ✅ |
| Brotli-11 | 238,019 | **20.28% smaller** | 0.34 | 202.81 | ✅ |
| zstd-19 | 244,177 | **22.29% smaller** | 2.59 | 829.70 | ✅ |
| 7-Zip-9 | 244,868 | **22.51% smaller** | 5.19 | 124.55 | ✅ |
| LZMA-9 | 245,200 | **22.62% smaller** | 1.04 | 74.93 | ✅ |
| gzip-9 | 270,595 | **29.88% smaller** | 2.68 | 911.03 | ✅ |
| TBS1 stream-dense | 320,264 | **40.76% smaller** | 44.38 | 220.66 | ✅ |
| zstd-9 | 324,779 | **41.58% smaller** | 64.56 | 327.78 | ✅ |
| zstd-3 | 383,836 | **50.57% smaller** | 321.72 | 565.71 | ✅ |
| LZ4-1 | 971,749 | **80.47% smaller** | 166.92 | 199.39 | ✅ |
| store | 4,895,341 | **96.12% smaller** | 986.33 | 1,364.52 | ✅ |

## Family chart

| Family | Source bytes | Route | DMS2 bytes | bzip2-9 bytes | Result | Encode / decode MB/s |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Multiple Features pixels | 1,442,000 | DMA2 parallel | 79,561 | 77,935 | 2.09% larger | 38.79 / 230.27 |
| Optical Digits | 563,639 | DMA2 parallel | **79,638** | 89,361 | **10.88% smaller** | 28.37 / 153.65 |
| Semeion digits | 2,889,702 | DMP1 planes | **30,539** | 33,015 | **7.50% smaller** | 74.32 / 313.22 |
| **Aggregate** | **4,895,341** | **DMS2** | **189,738** | **200,311** | **5.28% smaller** | **51.03 / 255.55** |

## Frozen gate status

| Gate | Status |
| --- | --- |
| At most 190,295 bytes aggregate | ✅ 189,738 |
| At least two 5% family wins | ✅ 2 of 3 |
| At least 50 MB/s compression | ✅ 51.03 MB/s |
| At least 250 MB/s decompression | ✅ 255.55 MB/s |
| Exact deterministic frames and corruption rejection | ✅ |
| Peak RSS at most 512 MiB | Pending measured receipt |
| Bounded streaming memory | Pending |
| Record-table regression at most 0.25% | Pending |
| Leave-one-family-out selector evaluation | Pending |
| Linux and Windows native-wheel reproduction | Pending CI evidence |
| Public validation remains unopened | ✅ |

## Reproduction

Build the native library, acquire the pinned development corpus under the
authorized protocol, then run:

```bash
scripts/probe-dense-matrix-native.py \
  --corpus /path/to/tabular-successor-development-v1 \
  --gates config/dense-matrix-development-gates-v1.json \
  --baseline-results runs/tabular-successor-development-census-v1/results.json \
  --output runs/dms2-native-development-gate-v1.json \
  --repetitions 7 \
  --warmups 1
```

The checked-in JSON retains every measured duration, corpus and evidence hash,
standard aggregate, route, exactness result, corruption result, and gate.

## Claim ceiling and next action

This is fresh development evidence. It supports no public-validation,
category-best, market-leading, or state-of-the-art claim. Measure peak RSS,
prove record-table non-regression, run the selector audit, and reproduce native
wheels in CI before freezing a candidate. Only then may the still-unopened
public-validation matrices be acquired once.
