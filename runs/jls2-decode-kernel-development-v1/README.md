# JLS2 decode-kernel development gate

**Result: passed.** The optimized decoder preserved every compressed byte and exact round trip. In seven alternating A/B rounds, median aggregate byte-API decode speed improved **21.66%**, and the candidate exceeded 250 MB/s in **7/7** rounds.

## Before and after

| Measurement | Baseline | Candidate | Change | Result |
| --- | ---: | ---: | ---: | --- |
| Alternating byte API, median aggregate | 277.05 MB/s | 333.46 MB/s | +21.66% paired median | ✅ 7/7 candidate rounds ≥250 MB/s |
| Complete file product, aggregate | 245.14 MB/s | 366.71 MB/s | +49.59% | ✅ candidate gate passed |
| Complete encoded bytes | 2,693,313 | 2,693,313 | unchanged | ✅ exact accepted frames |

The alternating benchmark isolates the in-memory decoder and alternates which build runs first. The complete-product benchmark separately includes file I/O and the public experimental API.

## Family A/B chart

| Development family | Baseline median | Candidate median | Median paired change | Paired range | Encoded bytes | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| apache | 384.69 MB/s | 475.00 MB/s | +22.03% | -2.33% to +69.68% | 178,101 | ✅ |
| healthapp | 264.70 MB/s | 333.37 MB/s | +24.19% | +7.09% to +47.35% | 1,005,536 | ✅ |
| hpc | 257.93 MB/s | 312.82 MB/s | +18.43% | +7.89% to +26.02% | 624,163 | ✅ |
| mac | 297.88 MB/s | 382.74 MB/s | +27.58% | +3.32% to +45.27% | 687,763 | ✅ |
| zookeeper | 338.09 MB/s | 441.27 MB/s | +34.09% | +15.17% to +55.18% | 197,750 | ✅ |

## Complete-product gate

| Gate | Baseline | Candidate |
| --- | --- | --- |
| clean commit | ✅ | ✅ |
| compression aggregate | ❌ | ✅ |
| compression per family | ❌ | ✅ |
| decompression per family | ❌ | ✅ |
| deterministic frames | ✅ | ✅ |
| exact accepted bytes | ✅ | ✅ |
| preflight load | ✅ | ✅ |
| repetitions | ✅ | ✅ |
| roundtrip | ✅ | ✅ |

Compression code was unchanged. The compression-gate differences above are retained host-timing context and are not attributed to this decoder optimization.

## Evidence boundary

- Base commit: `493f6ac5a2ea32c1d870698e38cb1732b6423c20`
- Candidate commit: `ae28430b55fa27755e9cce3fcb7cc5abb30c593c`
- Manifest SHA-256: `d6c71d91cd2995e3efae46353d5d8d94c00f8ee988cc74bdb5c2e45c4d6cbe9f`
- Source bytes: 124,614,865
- Schedule: 7 alternating rounds × 5 timed decodes per family per build
- Timing: in-memory JLS2 byte API; internal payload and restored-byte SHA-256 checks included
- Raw samples, fixture hashes, source hashes, native-library hashes, runtime, and exactness checks: [`ab-result.json`](ab-result.json)
- Complete-product raw results: [`product-baseline.json`](product-baseline.json) and [`product-candidate.json`](product-candidate.json)

Claim ceiling: **development-only decoder evidence on the existing Apache, HealthApp, HPC, Mac, and ZooKeeper families.** It is not a fresh unseen-corpus score and does not change the retained JLS2 public-validation failure. The public validation still shows JLS2 28.77% smaller than zstd-9 in aggregate, mixed against Brotli-11, with the old decoder missing its 250 MB/s gate. A fresh independently sourced corpus is required before claiming that the speed gate is solved out of sample.
