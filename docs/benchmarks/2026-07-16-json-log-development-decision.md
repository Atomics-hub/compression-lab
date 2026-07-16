# JSON-log development decision

## Decision

Promote JLC2 to native implementation and selector design. Do not open blind
validation yet.

LWX2, LWS1, and JLC1 remain valuable rejected development artifacts. None is
eligible for a market or state-of-the-art claim.

## Corpus integrity

The opened development corpus contains 124,614,865 bytes across five distinct
LogTrie families: Apache, HealthApp, HPC, Mac, and ZooKeeper. The files come
from the CC BY 4.0 LogTrie dataset record:

`https://doi.org/10.5281/zenodo.18522101`

Every file matched the MD5 published by Zenodo and is pinned by SHA-256 in the
local manifest. One initial ZooKeeper response returned a valid-looking but
wrong object; the fetcher rejected it before scoring. A clean response matched
both the Zenodo HTTP checksum and record checksum.

The Hadoop, OpenSSH, and OpenStack validation identities were frozen in
configuration but their files have not been downloaded or inspected.

## Baseline caveat

The resumable core benchmark recorded complete sizes for zstd-3, zstd-9,
Brotli-11, and CLG1. Host load was severe, so absolute throughput from that
run is not claimable. Brotli decompression was not run; the first artifact
encoded its absent timing as a synthetic high rate, a reporting bug now fixed
in the harness. No decision below uses that field.

## LWX2 complete-frame result

CLG1 wrapped LWX2 with a version, mode, sizes, SHA-256, and exact direct
fallback.

| Family | CLG1 | zstd-9 | Gain vs zstd-9 | Brotli-11 | Route |
| --- | ---: | ---: | ---: | ---: | --- |
| Apache | 202,364 | 243,342 | 16.84% | 189,311 | transformed |
| HealthApp | 1,041,927 | 1,363,620 | 23.59% | 983,579 | transformed |
| HPC | 469,457 | 1,113,188 | 57.83% | 902,430 | transformed |
| Mac | 798,574 | 798,518 | -0.01% | 584,191 | direct |
| ZooKeeper | 136,275 | 269,207 | 49.38% | 219,618 | transformed |

Aggregate CLG1 was 30.08% smaller than zstd-9 and 8.01% smaller than
Brotli-11. It nevertheless failed the frozen all-family zstd gate, beat
Brotli on only two families, and paid for both level-9 candidates during
compression. Reject LWX2 as the validation candidate.

## LWS1 splice result

LWS1 used the immediately previous record's longest common prefix and suffix
and a zstd-3 backend. It spliced more than 99.99% of records, but output was
10.97% larger than zstd-9 on HealthApp and 11.06% larger on Mac. This shows
that record alignment alone is not the missing representation. Reject LWS1.

## JLC1 result

JLC1 losslessly separated flat top-level JSON values into per-key channels and
compressed every stream at zstd level 3. It extracted 100% of records. It won
against zstd-9 on HealthApp, HPC, and ZooKeeper, but missed Apache by 1.03%
and Mac by 2.56%. Reject JLC1 under its frozen gates.

## JLC2 result

JLC2 retained the exact JLC representation and changed every backend stream to
zstd level 6. Complete frame sizes include the channel table, stream sizes,
original size, and SHA-256.

| Family | JLC2 | zstd-9 | Gain vs zstd-9 | Brotli-11 | Gain vs Brotli |
| --- | ---: | ---: | ---: | ---: | ---: |
| Apache | 177,913 | 243,342 | 26.89% | 189,311 | 6.02% |
| HealthApp | 1,006,264 | 1,363,620 | 26.21% | 983,579 | -2.31% |
| HPC | 588,800 | 1,113,188 | 47.11% | 902,430 | 34.75% |
| Mac | 652,784 | 798,518 | 18.25% | 584,191 | -11.74% |
| ZooKeeper | 197,562 | 269,207 | 26.61% | 219,618 | 10.04% |

Totals:

- JLC2: 2,623,323 bytes
- zstd-9: 3,787,875 bytes
- Brotli-11: 2,879,129 bytes
- JLC2 gain versus zstd-9: 30.74%
- JLC2 gain versus Brotli-11: 8.88%
- JLC2 families smaller than Brotli-11: 3 of 5
- extracted records: 100% on every family

JLC2 passes every frozen development ratio gate. Its Python reference is
intentionally slow and is not product evidence.

## Next gate

Implement byte-identical native extraction and reassembly, then measure on a
quiet host. The native candidate must meet the frozen extraction, complete
compression, decompression, memory, corruption, fallback, and streaming gates
before the validation files may be downloaded.

Competitive validation must also include CLP, LogLite, DeLog, and other
reproducible log-specific systems where their artifacts and licenses permit.
The strongest current research claim found during this phase is DeLog's 2026
paper claim of state-of-the-art ratio and speed on public and production logs:

`https://arxiv.org/abs/2601.15084`
