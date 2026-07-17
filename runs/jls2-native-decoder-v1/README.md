# JLS2 standalone native decoder development gate

**Outcome: the standalone native decoder passed the frozen development product gate.**

The complete cold-process product path reached
**585.43 MB/s** median aggregate throughput and never fell below
**398.40 MB/s** in any aggregate round. It cleared 250 MB/s in
**7/7** rounds, restored all 48 scheduled outputs exactly, and used
**146.5 MiB** peak RSS.

![Standalone JLS2 delivery gate and immutable standards size census](native-decoder-scorecard.svg)

## Product-path comparison

| Path | Median | Minimum | CV | Rounds ≥250 | Paired vs Python | Peak RSS | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Pinned lazy Python CLI | 339.47 MB/s | 290.81 MB/s | 9.65% | 7/7 | — | 196.0 MiB | yes |
| Standalone native | 585.43 MB/s | 398.40 MB/s | 14.63% | 7/7 | +69.98% | 146.5 MiB | yes |

Every standalone family median cleared the target:

| Frozen range | Median | Minimum |
| --- | ---: | ---: |
| `clue-early-development` | 575.11 MB/s | 407.86 MB/s |
| `clue-late-development` | 597.90 MB/s | 346.28 MB/s |
| `clue-middle-development` | 617.65 MB/s | 397.01 MB/s |

## Safety, portability, and packaging

- complete JLS2/JLF2/JLC1 parsing and nested SHA-256 checks;
- direct, columnar, empty, truncated, corrupt, oversized, trailing-data,
  overwrite, forced-replacement, cleanup, and path-collision coverage;
- same-directory temporary output and atomic publication after full verification;
- bounded segment parallelism and explicit maximum-output enforcement;
- self-contained release binary with bundled zstd and no Python dependency;
- local macOS binary links only to the system `libSystem`;
- cross-platform CI run [`29597215089`](https://github.com/Atomics-hub/compression-lab/actions/runs/29597215089) passed on Linux, macOS, and Windows; and
- release-artifact run [`29597540285`](https://github.com/Atomics-hub/compression-lab/actions/runs/29597540285) verified the distribution workflow.

## Standards context

JLS2 compressed the immutable 203.6 MB census to
**3,523,721 bytes** (57.77x),
18.08% smaller than Brotli-11 and smaller than every tested standard.
No standard codec was rerun in this delivery experiment. The standalone
585.43 MB/s result therefore clears the absolute product gate but is not
inserted into the immutable same-run standards speed table.

- [Full immutable 11-codec scorecard](../clue-json-log-development-census-v1/README.md)
- [Raw paired trials and machine-readable performance gates](results.json)
- [Frozen protocol](../../docs/benchmarks/2026-07-17-jls2-native-decoder-protocol.md)
- [Artifact receipt](receipt.json)
- [Verified hosted release checksums](release-SHA256SUMS)

## Evidence boundary

- Baseline commit: `604271cbc89a11c739848f68a7739ed523fb9a1b`
- Candidate implementation commit: `86d86f80dad86735e53829c6009eb29cee0ea324`
- Candidate binary SHA-256: `906ec3d722c90c2412d03e7af819423ada43ff0efd1399941bea8305a8c1f0fd`
- Schedule: 1 discarded warmup + 7 measured rounds × 3 families × 2 paths
- Exactness: 48/48 scheduled round trips; 42/42 measured
- JLS2 frames: byte-identical to the immutable development census
- Public-validation ranges: unmaterialized and unopened

Claim ceiling: **Development-only cold-process delivery evidence on the three frozen CLUE-LDS development ranges; not public validation, private holdout, independent reproduction, universal, market-leading, world-best, or state-of-the-art evidence.**
