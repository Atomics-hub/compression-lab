# CLUE-LDS JSON-log development census

**Outcome: ratio win; complete category gate not passed.** JLS2 is the
smallest complete archive on all three fresh development ranges and is
**18.08% smaller than brotli-11** aggregate. It clears the 100 MB/s aggregate
compression and 512 MiB memory gates, but its aggregate decode rate is
116.43 MB/s versus the frozen 250 MB/s gate.

## Full comparison

All rows are complete-file, cold-process measurements from the same
manifest-bound runner, with one discarded warmup and three scored trials.
Positive size values mean JLS2 is smaller.

| Codec | Complete bytes | Ratio | JLS2 size result | Compress MB/s | JLS2 compress result | Decompress MB/s | JLS2 decompress result | Peak RSS C/D MiB | Exact |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- | ---: | :---: |
| jls2 | 3,523,721 | 57.77x | candidate | 109.90 | candidate | 116.43 | candidate | 416.5/186.3 | yes |
| brotli-11 | 4,301,558 | 47.33x | 18.08% smaller | 0.37 | 297.46x faster | 253.86 | 54.1% slower | 186.8/25.2 | yes |
| zstd-19 | 4,900,286 | 41.54x | 28.09% smaller | 1.05 | 104.52x faster | 268.83 | 56.7% slower | 244.1/163.1 | yes |
| bz2-9 | 5,379,654 | 37.84x | 34.50% smaller | 1.37 | 80.13x faster | 25.26 | 4.61x faster | 104.1/166.8 | yes |
| lzma-9 | 5,572,968 | 36.53x | 36.77% smaller | 1.59 | 69.01x faster | 82.29 | 1.41x faster | 743.9/227.7 | yes |
| 7zip-9 | 5,574,110 | 36.52x | 36.78% smaller | 6.44 | 17.06x faster | 164.58 | 29.3% slower | 750.0/73.4 | yes |
| zstd-9 | 5,684,983 | 35.81x | 38.02% smaller | 124.70 | 11.9% slower | 300.48 | 61.3% slower | 242.3/163.4 | yes |
| zstd-3 | 7,538,545 | 27.00x | 53.26% smaller | 313.60 | 65.0% slower | 248.62 | 53.2% slower | 233.7/164.3 | yes |
| gzip-9 | 8,272,033 | 24.61x | 57.40% smaller | 49.19 | 2.23x faster | 288.08 | 59.6% slower | 99.2/167.4 | yes |
| lz4-1 | 14,061,683 | 14.48x | 74.94% smaller | 387.73 | 71.7% slower | 278.96 | 58.3% slower | 25.2/25.3 | yes |
| store | 203,578,132 | 1.00x | 98.27% smaller | 416.08 | 73.6% slower | 479.03 | 75.7% slower | 26.0/26.0 | yes |

## Family ratio result

| Development range | Source bytes | JLS2 bytes | Strongest standard | Standard bytes | JLS2 gain |
| --- | ---: | ---: | --- | ---: | ---: |
| clue-early-development | 62,267,473 | 1,382,653 | brotli-11 | 1,594,417 | 13.28% |
| clue-late-development | 71,463,332 | 1,402,809 | brotli-11 | 1,631,607 | 14.02% |
| clue-middle-development | 69,847,327 | 738,259 | brotli-11 | 1,075,534 | 31.36% |

## Frozen gates

| Gate | Result |
| --- | :---: |
| Complete 11-codec matrix | PASS |
| 99/99 scored round trips exact | PASS |
| JLS2 smallest aggregate | PASS |
| JLS2 smallest on every family | PASS |
| At least 5% smaller than strongest standard | PASS |
| At least 100 MB/s aggregate compression | PASS |
| At least 250 MB/s aggregate decompression | FAIL |
| At most 512 MiB compression RSS | PASS |
| At most 512 MiB decompression RSS | PASS |
| Deterministic JLS2 sizes | PASS |

## Decision and claim boundary

Retain JLS2 as the fresh structured-cloud-event-log ratio baseline. It wins complete bytes against every tested standard and clears the aggregate compression and memory gates, but it does not advance to public validation because the aggregate decompression gate failed.

Fresh licensed CLUE-LDS development evidence only; not public validation, private holdout, independent reproduction, universal, market-leading, world-best, or state-of-the-art evidence

Runner commit: `24d4a38d3b2c150db4d4018701fc93c640c94c15`. Timing scope: parent wall clock including worker process startup. Memory scope: worker high-water RSS.
