# Adaptive-v3 whole-frame decode profile

## Purpose

The fused structured-text decoder removed the per-chunk FFI penalty, but the
full benchmark still showed a large aggregate decode gap to direct Zstandard.
This experiment profiles the complete version-3 frame path, rejects attractive
but losing alternatives, and removes avoidable frame-assembly copies without
weakening CRC32 or SHA-256 verification.

This is a local public-validation result, not an isolated product gate. The
private holdout remained sealed.

## Profile

Thirty complete decodes of the 9,514,279-byte SQLite source attributed time as
follows:

| Component | Total time | Share |
| --- | ---: | ---: |
| Fused Zstandard plus token decode | 0.889 s | 78.6% |
| Frame SHA-256 | 0.185 s | 16.4% |
| Frame output extension | 0.015 s | 1.3% |
| Segment CRC32 | 0.014 s | 1.2% |
| Parsing, validation, and metadata | 0.028 s | 2.5% |

A separate rotating-order split measured 24.626 ms for Zstandard inflation,
25.880 ms for token expansion, and 48.937 ms for their fused path. The core
cost is therefore divided approximately evenly between the proven backend and
318,206 dictionary-token expansions. Python frame parsing is not the dominant
cost.

The benchmark's post-decode proof hash is computed outside the timed worker
operation. Adaptive-v3's timed SHA-256 is the frame's own integrity guarantee,
not accidental double-counting. It remains enabled.

## Rejected experiments

### Steady-state branch specialization

Moving completed header and dictionary checks out of the per-token loop looked
plausible in cross-run measurements. A same-process A/B loaded the old and new
Rust libraries simultaneously and alternated 100 decodes:

| Native decoder | Median time | Throughput |
| --- | ---: | ---: |
| Existing fused decoder | 40.445 ms | 235.242 MB/s |
| Specialized body loop | 40.538 ms | 234.701 MB/s |

The specialization was 0.23% slower and was discarded.

### Raw per-file Zstandard dictionary

The ranked identifier list was also tested as raw Zstandard dictionary content
so decode could bypass token expansion. The candidate included the dictionary
serialization required for independent decode. It lost to STX1 on every
structured file:

| File | Dictionary candidate minus STX1 |
| --- | ---: |
| Chinook JSON | +8,673 bytes |
| sqlite3.h | +14,663 bytes |
| sqlite3.c | +92,773 bytes |
| sqlite3ext.h | +2,602 bytes |
| shell.c | +16,608 bytes |

It was rejected before any frame-format change.

## Accepted zero-copy assembly

The native wrapper now accepts a mutable destination and offset. The fused
decoder writes structured-text output directly into the preallocated final
adaptive-v3 frame buffer. This removes:

- the compressed-input `ctypes` copy;
- the standalone decoded-segment allocation and immutable copy;
- the segment-to-frame copy.

CRC32 still covers each completed segment. SHA-256 now verifies the mutable
whole-frame buffer before its single final conversion to immutable bytes, so a
corrupt frame is rejected before that allocation.

An alternating 100-decode A/B on the same frame measured:

| Assembly path | Median time | Throughput |
| --- | ---: | ---: |
| Copied segment | 64.662 ms | 147.140 MB/s |
| Direct final-buffer write | 64.434 ms | 147.659 MB/s |

The 0.35% speed improvement is small and should be treated as near-neutral.
Forked children starting from the same prepared frame showed the material win:

| Assembly path | Incremental peak RSS |
| --- | ---: |
| Copied segment | 43,171,840 bytes |
| Direct final-buffer write | 33,636,352 bytes |

Direct assembly reduced observed peak growth by 9,535,488 bytes, or 22.1%,
approximately one complete source-sized segment.

The tested clean revision was
`f36bfa9143360ea2c5a573d4f19a56f2b3c0b3d0`.

## Correctness and clean public result

All 30 Python tests and all three optimized Rust tests passed. New coverage
writes into a non-zero output offset, verifies untouched prefix and suffix
sentinels, and rejects an undersized destination. Existing size, CRC, SHA,
truncation, trailing-data, and token-stream checks remain active.

Canonical local evidence:

- `runs/adaptive-v3-zero-copy-frame-public-clean/results.json`

All 64 measured round trips passed. Encoded output is unchanged at 6,753,811
bytes, 37.9597% of the 17,792,077-byte corpus.

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | ---: | --- |
| adaptive-v2 | 6,866,648 | 38.5939 | 57.76 | 159.66 | yes |
| adaptive-v3 | 6,753,811 | 37.9597 | 21.62 | 109.34 | yes |
| zstd-3 | 6,866,359 | 38.5922 | 31.57 | 103.71 | yes |
| zstd-9 | 6,386,970 | 35.8978 | 17.55 | 198.87 | yes |

The run began at a one-minute load average of 48.62 on a ten-core machine and
showed extreme throughput variance. Absolute speeds and this run's unusually
broad frontier are rejected as performance evidence. The clean commit, exact
sizes, and round-trip results remain reproducible evidence.

## Decision

Keep direct final-buffer assembly for its 22.1% large-frame memory reduction
and neutral-to-positive paired speed. Do not weaken SHA-256 or CRC32 to improve
a benchmark number, and do not adopt raw per-file Zstandard dictionaries.

The next codec experiment must attack representation rather than Python
bookkeeping: a separately benchmarked STX2 literal-run/token bytecode can test
whether one-byte token commands and length-delimited literal copies remove the
318,206-reference expansion floor without surrendering STX1's compression
advantage. It must beat STX1 on complete-frame bytes before integration.
