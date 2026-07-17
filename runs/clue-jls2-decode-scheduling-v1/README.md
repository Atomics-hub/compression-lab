# CLUE-LDS JLS2 decode-scheduling development gate

**Outcome: scheduling hypothesis rejected; product unchanged.** The current two-segment-worker, auto-channel topology remained the fastest measured option at **330.40 MB/s** median cold-process throughput. None of the three bounded alternatives passed the frozen selection gates.

The current decode kernel itself reached **604.37 MB/s** median and never fell below **380.60 MB/s** in aggregate worker timing. The primary parent-wall result missed 250 MB/s in one of seven rounds because cold-process overhead ranged up to 267.04 ms. The next experiment should target startup/native product delivery, not reduce decode parallelism.

## Full topology chart

All variants decoded identical JLS2 bytes in fresh worker processes. Parent wall is the frozen primary timing and includes interpreter startup plus complete atomic file decode.

| Variant | Segment / channel workers | Parent median | Parent minimum | Parent CV | Parent rounds ≥250 | Worker median | Worker minimum | Cold-process overhead median / max | Peak RSS | Paired vs current | Exact | Selected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| outer2-innerauto | 2 / auto | 330.40 MB/s | 184.34 MB/s | 20.60% | 6/7 | 604.37 MB/s | 380.60 MB/s | 93.03 / 267.04 ms | 195.1 MiB | +0.00% | yes | no |
| outer1-innerauto | 1 / auto | 242.47 MB/s | 154.64 MB/s | 17.12% | 3/7 | 367.87 MB/s | 245.30 MB/s | 94.76 / 235.01 ms | 177.9 MiB | -17.57% | yes | no |
| outer2-inner1 | 2 / 1 | 222.23 MB/s | 145.75 MB/s | 27.58% | 2/7 | 310.27 MB/s | 221.77 MB/s | 99.32 / 235.45 ms | 204.4 MiB | -20.94% | yes | no |
| outer2-inner2 | 2 / 2 | 275.94 MB/s | 130.88 MB/s | 30.26% | 4/7 | 482.65 MB/s | 214.84 MB/s | 108.46 / 242.68 ms | 201.0 MiB | -10.88% | yes | no |

## Family parent-wall medians

| Variant | Early | Middle | Late |
| --- | ---: | ---: | ---: |
| outer2-innerauto | 310.39 MB/s | 351.44 MB/s | 345.63 MB/s |
| outer1-innerauto | 251.55 MB/s | 230.01 MB/s | 289.77 MB/s |
| outer2-inner1 | 285.43 MB/s | 327.29 MB/s | 134.37 MB/s |
| outer2-inner2 | 248.15 MB/s | 323.12 MB/s | 317.61 MB/s |

## Decision

Retain `outer2-innerauto`. Do not change JLS2 compressed bytes or decode scheduling. The byte-identical worker kernel already has substantial headroom above 250 MB/s; the remaining failed gate is cold-process delivery reliability under variable host scheduling.

## Evidence boundary

- Clean benchmark commit: `9fa2e9f2c80b857e729728f53f2f88e25eaa7c9f`
- Platform: `macOS-26.5.2-arm64-arm-64bit`; Python `3.12.12`; 10 logical CPUs
- Schedule: 1 discarded warmup + 7 measured rounds × 3 families × 4 topologies
- Exactness: 96/96 total round trips exact; 84/84 measured
- Complete frames: 3,523,721 bytes aggregate, identical for every topology
- Raw trials, order, worker CPU, RSS, source/frame hashes, load averages, source hashes, and native-library hash: [`results.json`](results.json)
- Frozen protocol: [`2026-07-17-clue-jls2-decode-scheduling-protocol.md`](../../docs/benchmarks/2026-07-17-clue-jls2-decode-scheduling-protocol.md)

Claim ceiling: **development-only decode-scheduling evidence on the three frozen CLUE-LDS development ranges.** The CLUE public-validation ranges remain unmaterialized and unopened. This result is not public validation, private holdout, independent reproduction, universal, market-leading, world-best, or state-of-the-art evidence.
