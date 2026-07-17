# TBL1 bounded-streaming development decision

## Decision

Advance `TBS1` to a frozen public-validation readiness audit. The bounded
streaming development gate passed. The complete tabular category has not
passed because public validation and independent reproduction have not occurred.

## Full comparison

The licensed development corpus contains four UCI families and 187,321,615
source bytes. Sizes are complete artifacts. TBS1 speed uses five measured
repetitions after one warmup; TBS1 memory uses isolated cold processes.
Baseline speed and memory are single-trial context, not controlled speed claims.

| Candidate or standard | Complete bytes | TBS1 size result | Compress MB/s | Decompress MB/s | Peak compression RSS | Integrity / portability | Evidence basis | Size outcome |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| **TBS1 stream-dense** | **12,134,137** | reference | **60.92** | **356.76** | **409.72 MiB** | 20/20 + 1 GiB exact; deterministic; Python reference decoder | clean five-run + isolated memory | — |
| TBL1-dense whole-file | 12,012,933 | 1.01% larger | 51.30 | 250.41 | 402.55 MiB | 20/20 exact; native/reference equivalence | earlier clean five-run point decision | TBS1 loss |
| Brotli-11 | 13,425,698 | **9.62% smaller** | 0.33 | 293.21 | 254.47 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| LZMA-9 | 14,275,744 | **15.00% smaller** | 0.78 | 38.91 | 801.78 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| 7-Zip-9 | 14,301,453 | **15.15% smaller** | 2.69 | 133.13 | 648.53 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| zstd-19 | 14,570,801 | **16.72% smaller** | 2.07 | 424.88 | 240.38 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| bzip2-9 | 17,627,845 | **31.16% smaller** | 1.43 | 20.86 | 255.45 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| zstd-9 | 18,038,379 | **32.73% smaller** | 61.91 | 380.94 | 233.70 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| gzip-9 | 19,811,936 | **38.75% smaller** | 8.03 | 362.97 | 269.00 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| zstd-3 | 22,715,433 | **46.58% smaller** | 185.13 | 333.23 | 327.27 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| LZ4-1 | 38,164,405 | **68.21% smaller** | 765.00 | 393.48 | 37.17 MiB | exact on this runner | single-trial contextual census | TBS1 win |
| store | 187,321,615 | **93.52% smaller** | 1,242.40 | 719.78 | 25.03 MiB | exact on this runner | single-trial contextual census | TBS1 win |

## Per-family result

| Development family | TBS1 bytes | Strongest exact baseline | Baseline bytes | Improvement | Segments | Path | Family gate |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| AutoUniv mixed | 2,115,731 | 7-Zip-9 | 2,285,071 | **7.41% smaller** | 1 | column | Pass |
| Covertype | 4,588,527 | Brotli-11 | 6,588,546 | **30.36% smaller** | 4 | column | Pass |
| Facebook comment volume | 1,344,651 | Brotli-11 | 1,446,175 | **7.02% smaller** | 4 | column | Pass |
| Gas sensor | 4,085,228 | LZMA-9 | 2,922,704 | 39.78% larger | 4 | direct zstd-9 | Fail |

Nine column segments compared their complete result with an equally framed
zstd-3/store fallback; none selected fallback. Four Gas segments selected
direct zstd-9. Every path has raw-store protection.

## Frozen streaming gate

| Requirement | Measured result | Status |
| --- | --- | --- |
| Aggregate ratio at least 5% below Brotli-11 | 9.62% smaller | Pass |
| Three family wins of at least 5% | 3 of 4 | Pass |
| At most 2% larger than whole-file dense | 1.01% larger | Pass |
| Compression at least 50 MB/s | 60.92 MB/s | Pass |
| Decompression at least 250 MB/s | 356.76 MB/s | Pass |
| Every repetition above 50/250 MB/s | minima 56.94/335.57 MB/s | Pass |
| Cold compression/decompression RSS at most 512 MiB | 409.72/120.22 MiB | Pass |
| Exact and deterministic | 20/20 exact; identical size/output policy | Pass |
| Enforced direct/store fallback | complete per-segment comparison or direct/store path | Pass |
| Corruption, truncation, bounds, trailing data, atomic failure | regression tests pass | Pass |
| Portable reference decoder | native-created column stream decoded with Python transform | Pass |
| 1 GiB bounded large-file behavior | 155.34/101.56 MiB RSS; exact SHA-256 | Pass |
| Public validation | four families remain unopened | Not run |
| Independent reproduction | none | Not run |

Persistent-worker RSS rose across repeated trials because the allocator retains
freed arenas; it reached 786.86 MiB after the fifth repetition. The predeclared
memory gate is therefore taken from cold isolated processes, while the separate
1 GiB process proves memory does not grow with total file size. Both numbers are
reported rather than substituting one for the other.

## Evidence

- Candidate commit: `d3e4e2c7555aa43131bee759260589a75bd60587`
- Corpus manifest SHA-256:
  `bac7f9bb94bac38dc621d927ff8cca70a8c2fde92c3689525a1de2d87d098f61`
- Five-run result SHA-256:
  `076e92972684b47f97b2aca19ff68305067d1e8555f72036f21585729029493c`
- Cold-memory result SHA-256:
  `6ab60c750ddcfb136c8523aef50170568332faa38d76ab6433eff8b120c3ac37`
- 1 GiB source/restored SHA-256:
  `49bc20df15e412a64472421e13fe86ff1c5165e18b2afccf160d4dc19fe68a14`
- 1 GiB TBS1 frame SHA-256:
  `02d89e997e29e35566528d2c1cfe6c153bbde281f15dd6386a38032a52bb8182`
- Machine-readable decision: `runs/tbl1-streaming-development-decision-v1.json`

## Claim ceiling

Allowed: bounded TBS1 passed its frozen streaming **development** gate and was
9.62% smaller than Brotli-11 on the licensed four-family development corpus.

Not allowed: validated category win, world best, market leading, or state of
the art.

## Next gate

Require the full cross-platform wheel matrix to pass, freeze the candidate,
runner, evaluator, and claim text, then acquire and score all four unopened
public-validation families once. No development parameter may change after
that acquisition.
