# DMS2 native development gate

## Decision

**DMS2 passes every local frozen development gate: ratio, speed, memory,
streaming, selector, integrity, and record-table preservation. Full-suite and
native-wheel reproduction passed on Linux, macOS, and Windows. Candidate lock
remains before one-time public validation.**

DMS2 combines a bounded 64 KiB content selector, parallel DMA2 adaptive
contexts for broader numeric alphabets, and DMP1 bit planes for alphabets of
four lexemes or fewer. The selector uses current-file bytes only. It does not
use a filename, family identity, known shape, source ID, digest, DOI, or track
label.
It materializes an equally framed zstd-1 fallback beside valid numeric
specialists, chooses the smaller complete frame, and uses that fallback for
arbitrary nonnumeric input.

On the three fresh development matrices, seven measured complete-frame trials
after one warmup produced 189,738 aggregate bytes, 54.85 MB/s compression, and
268.18 MB/s decompression. Every frame was deterministic, restored the exact
source bytes, and rejected a corrupted payload.

## Full standards chart

The standards are the unchanged dense-matrix subset of the fresh 11-codec
census. DMS2 timings are medians from seven repetitions; baseline timings were
one local trial per codec and family, so speed comparisons are contextual.

| Codec | Complete bytes | DMS2 size result | Compress MB/s | Decompress MB/s | Peak RSS C/D MiB | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **DMS2 native** | **189,738** | candidate | **54.85** | **268.18** | **51.9 / 39.2** | ✅ |
| bzip2-9 | 200,311 | **5.28% smaller** | 1.71 | 27.18 | — | ✅ |
| Brotli-11 | 238,019 | **20.28% smaller** | 0.34 | 202.81 | — | ✅ |
| zstd-19 | 244,177 | **22.29% smaller** | 2.59 | 829.70 | — | ✅ |
| 7-Zip-9 | 244,868 | **22.51% smaller** | 5.19 | 124.55 | — | ✅ |
| LZMA-9 | 245,200 | **22.62% smaller** | 1.04 | 74.93 | — | ✅ |
| gzip-9 | 270,595 | **29.88% smaller** | 2.68 | 911.03 | — | ✅ |
| TBS1 stream-dense | 320,264 | **40.76% smaller** | 44.38 | 220.66 | — | ✅ |
| zstd-9 | 324,779 | **41.58% smaller** | 64.56 | 327.78 | — | ✅ |
| zstd-3 | 383,836 | **50.57% smaller** | 321.72 | 565.71 | — | ✅ |
| LZ4-1 | 971,749 | **80.47% smaller** | 166.92 | 199.39 | — | ✅ |
| store | 4,895,341 | **96.12% smaller** | 986.33 | 1,364.52 | — | ✅ |

DMS2 memory is from isolated cold processes. Baseline RSS was not rerun in
isolated processes, so this chart makes no comparative memory claim.

## Family chart

| Family | Source bytes | Route | DMS2 bytes | bzip2-9 bytes | Result | Encode / decode MB/s |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Multiple Features pixels | 1,442,000 | DMA2 parallel | 79,561 | 77,935 | 2.09% larger | 45.63 / 263.35 |
| Optical Digits | 563,639 | DMA2 parallel | **79,638** | 89,361 | **10.88% smaller** | 28.37 / 155.02 |
| Semeion digits | 2,889,702 | DMP1 planes | **30,539** | 33,015 | **7.50% smaller** | 76.49 / 316.07 |
| **Aggregate** | **4,895,341** | **DMS2** | **189,738** | **200,311** | **5.28% smaller** | **54.85 / 268.18** |

## Frozen gate status

| Gate | Status |
| --- | --- |
| At most 190,295 bytes aggregate | ✅ 189,738 |
| At least two 5% family wins | ✅ 2 of 3 |
| At least 50 MB/s compression | ✅ 54.85 MB/s |
| At least 250 MB/s decompression | ✅ 268.18 MB/s |
| Exact deterministic frames and corruption rejection | ✅ |
| Peak RSS at most 512 MiB | ✅ 51.9 / 39.2 MiB cold frame encode/decode |
| Bounded streaming memory | ✅ 208.6 / 114.8 MiB on 184.9 MB; no growth vs 92.5 MB |
| Record-table regression at most 0.25% | ✅ 0.00%; 1,377,241 bytes unchanged |
| Leave-one-family-out selector evaluation | ✅ oracle route on 3/3; 64 KiB sample; zero fitted parameters |
| Never exceed equally framed direct fallback | ✅ 3/3 dense families plus arbitrary-input tests |
| Linux, macOS, and Windows full-suite and native-wheel reproduction | ✅ commit `4e816ca`; push and PR CI passed |
| Public validation remains unopened | ✅ |

## Reproduction

Build the native library, acquire the pinned development corpus under the
authorized protocol, then run:

```bash
scripts/probe-dense-matrix-native.py \
  --corpus /path/to/tabular-successor-development-v1 \
  --gates config/dense-matrix-development-gates-v1.json \
  --baseline-results runs/tabular-successor-development-census-v1/results.json \
  --operational-evidence runs/dms2-operational-development-gate-v1.json \
  --output runs/dms2-safe-selector-development-gate-v2.json \
  --repetitions 7 \
  --warmups 1
```

The checked-in [speed and ratio evidence](../../runs/dms2-safe-selector-development-gate-v2.json)
retains every measured duration, corpus and evidence hash, standard aggregate,
route, exactness result, corruption result, and gate. The separate
[operational receipt](../../runs/dms2-operational-development-gate-v1.json)
retains cold RSS, bounded-stream, selector, direct-fallback, and record-table
regression evidence. The separate [cross-platform CI receipt](../../runs/dms2-cross-platform-ci-receipt-v1.json)
binds the DMS2 source hashes to the successful public GitHub runs and individual
full-suite and specialist/direct/DSS1 wheel jobs on all three operating systems.

## Claim ceiling and next action

This is fresh development evidence, not a world-best claim. It supports no
public-validation, category-best, market-leading, or state-of-the-art claim.
The cross-platform runs reproduce correctness and packaging, not the local
performance numbers in the chart. Freeze the exact candidate, evaluator, and
acquisition receipt next. Only then may the
still-unopened public-validation matrices be acquired once.
