# Delimited-tabular development baseline census

## Decision

**Evidence stage: discovery only — no candidate and no category gate**

All 40 exact round trips passed. Brotli-11 is the smallest fixed baseline on
the four-family development corpus, while zstd-9 and zstd-3 define the useful
balanced speed frontier. The next candidate must create a new Pareto point; it
is not enough to beat one convenient Zstandard level.

## Aggregate standards comparison

| Standard | Complete bytes | Source % | Compress MB/s | Decompress MB/s | Peak RSS MiB | Exact | Position |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Brotli-11 | **13,425,698** | **7.17%** | 0.33 | 293.21 | 254.5 | ✅ | Best fixed ratio |
| LZMA-9 | 14,275,744 | 7.62% | 0.78 | 38.91 | 801.8 | ✅ | Dense frontier |
| 7-Zip-9 | 14,301,453 | 7.63% | 2.69 | 133.13 | 648.5 | ✅ | Dense frontier |
| zstd-19 | 14,570,801 | 7.78% | 2.07 | **424.88** | 240.4 | ✅ | Dense decode frontier |
| bzip2-9 | 17,627,845 | 9.41% | 1.43 | 20.86 | 255.5 | ✅ | Dominated |
| zstd-9 | 18,038,379 | 9.63% | **61.91** | 380.94 | 233.7 | ✅ | Balanced frontier |
| gzip-9 | 19,811,936 | 10.58% | 8.03 | 362.97 | 269.0 | ✅ | Dominated |
| zstd-3 | 22,715,433 | 12.13% | **185.13** | 333.23 | 327.3 | ✅ | Fast balanced frontier |
| LZ4-1 | 38,164,405 | 20.37% | **765.00** | 393.48 | 37.2 | ✅ | Fast frontier |
| Store | 187,321,615 | 100.00% | 1,242.40 | 719.78 | 25.0 | ✅ | Copy frontier |

## Family ratio leaders

| Family | Source bytes | Best standard | Best bytes |
| --- | ---: | --- | ---: |
| AutoUniv mixed | 11,238,737 | 7-Zip-9 | 2,285,071 |
| Covertype integer/binary | 67,108,763 | Brotli-11 | 6,588,546 |
| Facebook dense numeric | 53,242,583 | Brotli-11 | 1,446,175 |
| Gas-sensor wide float | 55,731,532 | LZMA-9 | 2,922,704 |

No one baseline wins every family. The zero-cost per-family size oracle is
13,242,496 bytes, only 1.36% smaller than fixed Brotli-11. The representation
must therefore improve the data, not merely select among existing codecs.

## Candidate targets

| Mode | Ratio target | Compression target | Decompression target |
| --- | --- | ---: | ---: |
| Dense | At most 12,754,413 bytes: 5% below Brotli-11 | ≥50 MB/s | ≥250 MB/s |
| Balanced | At most 17,136,460 bytes: 5% below zstd-9 | ≥100 MB/s | ≥500 MB/s |

## Evidence boundary

- Category: byte-exact CSV and delimited tables
- Stage: single-trial local development baseline discovery
- Corpus: 4 CC-BY-4.0 UCI families, 187,321,615 bytes
- Public validation: unopened
- Private holdout: sealed
- Runner: macOS 26.5.2 arm64, 10 logical CPUs
- Timing: one complete trial; persistent worker per codec; Python startup
  excluded; IPC, file I/O, and native CLI startup included
- Round-trip failures: 0
- Benchmark commit: `0ea040f0484f99795687c9563de36e75b0596509`
- Git state: dirty because the corpus-manifest compatibility change was not yet
  committed
- Source results SHA-256:
  `1bebda79d6bb38152b8fd11731a0f3040229594f8ea70ed01bb4fba5216fad15`
- Corpus manifest SHA-256:
  `bac7f9bb94bac38dc621d927ff8cca70a8c2fde92c3689525a1de2d87d098f61`

This run cannot support a Compression Lab performance claim. It exists to
choose honest targets and reject dominated baseline work before candidate
development.

## Next decision

Retain Brotli-11 as the fixed aggregate ratio target, per-family best bytes as
the family targets, zstd-9 and zstd-3 as balanced speed references, and LZ4-1
as the fast reference. Implement and reject TBL1 channels on development data
only, then run the surviving candidate and frontier baselines repeatedly from
a clean frozen commit.
