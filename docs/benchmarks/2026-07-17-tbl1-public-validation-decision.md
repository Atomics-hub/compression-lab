# TBL1 delimited-table one-time public validation

## Decision

**Overall frozen gate: ❌ NOT PASSED**

`TBS1` produced decisive unseen size wins on three of four families and was
smaller than eight of ten standards in aggregate. The complete gate failed
because OCRB pixel tables made the aggregate output 3.48% larger than 7-Zip-9,
and one of five decompression repetitions missed the 250 MB/s floor.

The first score is final. These four families will not be tuned on or rerun as
fresh evidence.

## Complete standards comparison

All rows use the same 268,432,956 exact source bytes on the same host. Candidate
speed is the aggregate of five repetitions; each displayed standard speed is
its aggregate median on those repetitions. Worker RSS is persistent-worker
high water and is contextual rather than an isolated per-codec memory claim.

| Standard | Complete bytes | TBS1 size result | Compress MB/s: TBS1 / standard | Decompress MB/s: TBS1 / standard | Worker high-water RSS MiB | Exact | Size beaten? |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| **TBS1 stream-dense** | **27,985,887** | candidate | **107.67 / —** | **403.39 / —** | **415.16** | ✅ | — |
| store | 268,432,956 | **89.57% smaller** | 107.67 / 1,382.93 | 403.39 / 812.06 | 25.95 | ✅ | ✅ |
| LZ4-1 | 95,128,929 | **70.58% smaller** | 107.67 / 878.25 | 403.39 / 423.25 | 64.72 | ✅ | ✅ |
| gzip-9 | 49,933,695 | **43.95% smaller** | 107.67 / 6.26 | 403.39 / 333.42 | 251.69 | ✅ | ✅ |
| zstd-3 | 44,511,580 | **37.13% smaller** | 107.67 / 247.36 | 403.39 / 343.45 | 297.25 | ✅ | ✅ |
| bzip2-9 | 34,291,969 | **18.39% smaller** | 107.67 / 2.39 | 403.39 / 23.68 | 287.73 | ✅ | ✅ |
| zstd-9 | 36,047,298 | **22.36% smaller** | 107.67 / 51.20 | 403.39 / 344.36 | 301.88 | ✅ | ✅ |
| zstd-19 | 28,942,224 | **3.30% smaller** | 107.67 / 1.31 | 403.39 / 372.62 | 321.27 | ✅ | ✅ |
| Brotli-11 | 28,315,299 | **1.16% smaller** | 107.67 / 0.43 | 403.39 / 258.15 | 238.66 | ✅ | ✅ |
| LZMA-9 | 27,049,040 | **3.46% larger** | 107.67 / 0.54 | 403.39 / 45.23 | 879.75 | ✅ | ❌ |
| 7-Zip-9 | **27,044,234** | **3.48% larger** | 107.67 / 1.93 | 403.39 / 141.44 | 648.59 | ✅ | ❌ |

The candidate cold-process peaks were 293.70 MiB for compression and 139.81
MiB for decompression, both below the frozen 512 MiB limit. Baseline memory was
not rerun in isolated cold processes, so the table does not claim memory wins.

## Family results

Each family reference is its smallest complete exact-byte standard.

| Family | Source bytes | TBS1 bytes | Strongest standard | Standard bytes | TBS1 result | Gate |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| MetroPT sensor data | 67,108,801 | 4,316,507 | bzip2-9 | 5,169,178 | **16.50% smaller** | ✅ |
| Electricity load | 67,107,069 | 7,049,407 | LZMA-9 | 7,858,072 | **10.29% smaller** | ✅ |
| OULAD relational events | 67,108,841 | 3,804,890 | LZMA-9 | 4,106,572 | **7.35% smaller** | ✅ |
| OCRB mixed pixels | 67,108,245 | 12,815,083 | 7-Zip-9 | 9,697,061 | **32.15% larger** | ❌ |

## Frozen gates

| Gate | Result |
| --- | --- |
| at least 5% smaller than the strongest aggregate standard | ❌ 3.48% larger than 7-Zip-9 |
| at least three of four family wins by 5% | ✅ 3 / 4 |
| aggregate compression at least 50 MB/s | ✅ 107.67 MB/s |
| aggregate decompression at least 250 MB/s | ✅ 403.39 MB/s |
| every repetition compression at least 50 MB/s | ✅ minimum 64.36 MB/s |
| every repetition decompression at least 250 MB/s | ❌ minimum 163.51 MB/s |
| cold compression and decompression each at most 512 MiB | ✅ 293.70 / 139.81 MiB |
| exact roundtrip, deterministic output, complete accounting | ✅ |
| no selected segment larger than equally framed fallback | ✅ |
| all ten standards present with no benchmark failures | ✅ |
| frozen candidate, corpus, execution, digests, and clean commit | ✅ |
| portable reference decoder and cross-platform CI | ✅ |
| private holdout | ✅ sealed |

The five repetition aggregates were 102.08/400.15, 102.13/384.97,
108.62/410.61, 64.36/163.51, and 99.84/486.80 MB/s for
compression/decompression. The runner recorded host load throughout; the
fourth repetition is retained as measured and cannot be discarded.

## Evidence boundary

- Stage: first and only public-validation score
- Corpus: four previously unopened UCI CC-BY-4.0 delimited-table families
- Exact source bytes: 268,432,956
- Candidate base commit: `80b9f5f89f9ef3cf81fb4d6878ea65b6f8a9199e`
- Readiness commit: `74296886f003bcc7433665f91e8ee37f7f99a7d4`
- Scored repository commit: `002edea7d3299714afe00ec47a60d264bcd83a38`
- Runner: macOS 26.5.2 arm64, Python 3.12.12, 10 logical CPUs
- Decision SHA-256: `baf0cd9421e726bf0b51a29fbe3a57f84f109b0907d695b53f86ca0dbfe0b7a5`
- Receipt SHA-256: `16656332e6d5ecadaee3e555122a8540037e6b9dcefc91e5ef15fc0115bea5d8`
- Manifest SHA-256: `cf1c045f8c8ddbc19e2ca3d729a55e305263bc35eb03a4e2f2c8b7fc4e763f99`
- [Raw decision](../../runs/tbl1-public-validation-v1/decision.json)
- [Raw five-repetition results](../../runs/tbl1-public-validation-v1/performance/results.json)
- [Cold-memory results](../../runs/tbl1-public-validation-v1/memory/results.json)
- [Acquisition manifest](../../runs/tbl1-public-validation-v1/manifest.json)
- [Final receipt](../../runs/tbl1-public-validation-v1/receipt.json)

Claim ceiling: category-scoped one-time public-validation evidence on these
four families. It is not a complete category win, private-holdout result,
independent reproduction, universal win, market-leading claim, or
state-of-the-art claim.

## Next decision

Retain this failed first score. Do not tune or rerun TBS1 on MetroPT,
electricity, OULAD, or OCRB. Preserve the validated specialist signal on the
three winning families, treat image-like pixel matrices as a distinct category,
and develop the next selector or representation only on fresh development
families. Any successor claim requires a new untouched validation corpus.
