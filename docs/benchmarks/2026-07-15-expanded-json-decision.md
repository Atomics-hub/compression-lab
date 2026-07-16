# Expanded JSON token-channel decision

## Decision

**Reject broad JSON generalization. Keep the current exact-comparison recipe
bounded and make no post-hoc selector change from this validation set.**

The raw token side channel won only one of four independently sourced JSON
families. In aggregate it was 22,346 bytes, or 3.51%, larger than interleaved
STX1. The clean focused run also missed the 50 MB/s encode gate, and integrated
adaptive-v3 was not Pareto. The size, prevalence, throughput, and Pareto gates
therefore block broader promotion.

The integrated exact comparison still selected the channel on Natural Earth
GeoJSON and retained interleaved STX1 on the other three files. That produced a
5.52% aggregate size win over direct zstd-3, but it does not rescue the rejected
hypothesis that a JSON prefix predicts a channel win. The private holdout
remained sealed.

## Frozen corpus

The predeclared protocol is
`docs/benchmarks/2026-07-15-expanded-json-protocol.md`. The reconstruction
recipe is `config/public-json-v1.json`; every URL is pinned to an upstream
commit and a SHA-256 digest.

| Family | Input bytes | SHA-256 prefix | License |
| --- | ---: | --- | --- |
| Kubernetes OpenAPI | 4,066,190 | `6938670a70e2` | Apache-2.0 |
| Unicode CLDR likely subtags | 220,093 | `38345946ad45` | Unicode-3.0 |
| Vega movies | 1,399,981 | `e63c499759e3` | BSD-3-Clause |
| Natural Earth countries | 838,726 | `6866c877d39c` | public domain |
| **Total** | **6,524,990** | | |

Primary provenance and license records:

- Kubernetes repository and Apache-2.0 license:
  https://github.com/kubernetes/kubernetes
- Unicode CLDR JSON license:
  https://github.com/unicode-org/cldr-json/blob/a79b499916d486dca4b0f74fe423ea457705fdd9/LICENSE
- Vega datasets package license:
  https://github.com/vega/vega-datasets/blob/cad85578e232704bb0453544742440038038c6a2/package.json
- Natural Earth public-domain declaration:
  https://github.com/nvkelso/natural-earth-vector/blob/ca96624a56bd078437bca8184e78163e5039ad19/LICENSE.md

## Focused representation result

The clean controlling probe ran at implementation revision
`e54cf1ec279a8e8d6c04945481919861c7b1676e`. Complete sizes include both
Zstandard frames and token-channel boundary metadata. The STX1 column includes
its transformed-size metadata.

| Family | Direct zstd-3 | STX1 | Raw channel | Raw minus STX1 | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Unicode CLDR | 46,226 | 44,471 | 45,040 | +569 (+1.28%) | lose |
| Natural Earth GeoJSON | 185,240 | 184,134 | **175,890** | **-8,244 (-4.48%)** | win |
| Kubernetes OpenAPI | 250,315 | **236,305** | 251,665 | +15,360 (+6.50%) | lose |
| Vega movies | 183,804 | **171,915** | 186,576 | +14,661 (+8.53%) | lose |
| **Total** | **665,585** | **636,825** | **659,171** | **+22,346 (+3.51%)** | **reject** |

Raw-channel aggregate throughput in that run was 43.745 MB/s encode and
243.513 MB/s decode. Decode passed the 100 MB/s gate; encode failed the
50 MB/s gate. A nearby repeat reached 60.320 MB/s encode, so the focused timing
is visibly host-sensitive and cannot support a product-speed claim. Sizes were
identical across repeats.

Delta and move-to-front side representations remained rejected. They produced
665,838 and 703,009 aggregate bytes respectively, both larger than raw IDs and
interleaved STX1.

## Integrated market comparison

Canonical local evidence:

- `runs/adaptive-v3-expanded-json-clean/results.json`
- run `20260716T034250Z-3a172acb`
- one warmup, two measured repetitions, deterministic shuffled order;
- persistent workers and a 250 ms calibrated operation target;
- 64/64 measured round trips passed.

Brotli level 5 was predeclared, but the installed adapter exposes levels 1, 6,
and 11. Level 6 was used as the closest available middle setting, and 7-Zip
level 9 was added because it is a user-facing market baseline.

| Codec | Bytes | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | ---: | --- |
| Brotli-11 | **446,160** | **6.84%** | 0.47 | 118.72 | yes |
| LZMA-9 | 469,492 | 7.20% | 1.95 | 68.46 | yes |
| 7-Zip-9 | 471,315 | 7.22% | 3.80 | 67.54 | yes |
| Brotli-6 | 556,425 | 8.53% | 27.64 | 91.21 | yes |
| zstd-9 | 568,536 | 8.71% | 55.15 | 510.11 | yes |
| adaptive-v3 | 628,833 | 9.64% | 28.06 | 165.48 | **no** |
| zstd-3 | 665,585 | 10.20% | **236.33** | **542.85** | yes |
| gzip-9 | 733,072 | 11.23% | 16.09 | 133.45 | no |

Adaptive-v3 was 36,752 bytes or 5.52% smaller than zstd-3, but 60,297 bytes or
10.61% larger than zstd-9 and 182,673 bytes or 40.94% larger than Brotli-11.
It was dominated in the measured ratio/speed space and therefore failed the
integrated Pareto gate. Its two-repetition compression and decompression CVs
were 18.97% and 7.55%, also too noisy for an absolute throughput claim.

The adaptive routes were exact and explainable:

- Natural Earth selected `structured-text-channel+zstd-3` at 175,953 complete
  frame bytes;
- Kubernetes, Unicode CLDR, and Vega selected interleaved
  `structured-text+zstd-3`;
- all four files evaluated both representations, and complete-payload
  comparison prevented a selected size regression.

## Correctness finding and repair

The validation pass exposed an independent native debug-build bug. Rust's
eager `then_some` argument evaluated `gain - overhead` even for a dictionary
token that should be rejected, causing unsigned-underflow panics in three
native tests. The estimator now constructs the tuple only inside an explicit
passing branch. This preserves release dictionary choices and encoded sizes
while making debug arithmetic correct.

Final verification on the clean implementation:

- 32/32 Python tests passed;
- 4/4 Rust tests passed;
- malformed token channels, truncated streams, invalid codes, frame
  corruption, checksum tampering, and tiny-chunk streaming cases passed;
- the four-family, eight-codec integration completed 64/64 measured round
  trips with zero failures;
- corpus reconstruction reverified every pinned download digest and every
  imported SHA-256.

## What this means next

Do not tune a selector on these four validation files or open the private
holdout. The useful signal is narrower: channel separation can help specific
token distributions, but JSON syntax alone is not the predictor. The next
ratio experiment should train a cheap representation-benefit estimator on a
new public training corpus and validate it on a separately frozen corpus. It
must predict channel benefit before paying for the second compression path and
must compete against zstd-9 and Brotli, not only zstd-3.

