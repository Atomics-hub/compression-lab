# Adaptive-v3 streaming structured-text decode

## Purpose

The sampled structured-text candidate decoded in two complete stages: first
materialize the transformed token stream with Zstandard, then expand that
stream into the final output. This experiment replaces that path with a
stateful native token decoder fed incrementally by `ZSTD_decompressStream`.

This is a local public-validation result, not an isolated product gate. The
private holdout remained sealed.

## Design

- The Rust decoder parses the structured-text header and dictionary across
  arbitrary input boundaries.
- Literal runs, marker escapes, and dictionary references may all span chunks.
- Zstandard writes into one reusable 256 KiB buffer, which is fed directly to
  the decoder.
- The decoder writes into the final expected-size output allocation; it never
  materializes the complete transformed stream.
- Declared transformed size, declared output size, truncated input, trailing
  input, dictionary validity, marker validity, and final decoder state are all
  checked before returning output.
- Native-library or Zstandard-library absence retains the previous portable
  two-stage fallback.

The tested clean revision was
`d2a99de553e42ff054b356bc355f867ebfa0b96f`.

## Correctness

All 30 Python tests and all three Rust tests passed. New coverage includes a
single-byte native input schedule, seven-byte Zstandard output chunks,
truncated compressed data, a false transformed-size declaration, trailing
compressed data, marker bytes in source data, and exact byte-for-byte output.

The clean public benchmark completed all 64 measured round trips without a
failure. Encoded output is unchanged at 6,753,811 aggregate bytes, 37.9597% of
the 17,792,077-byte corpus.

## Paired decode measurement

The complete public benchmark was heavily contended: recorded one-minute load
rose from 5.62 at run start to 9.87 at run end, and every codec was roughly
three to four times slower than the immediately preceding run. Its absolute
throughput is therefore not used to attribute a streaming-code change.

To isolate the decode path, both implementations decoded the same 9,514,279-byte
SQLite source from the same 2,349,083-byte compressed payload in one process,
with alternating order across 24 measured decodes:

| Decoder | Median time | Throughput |
| --- | ---: | ---: |
| Complete transformed buffer | 47.646 ms | 199.687 MB/s |
| Streaming, 256 KiB chunks | 50.184 ms | 189.589 MB/s |

Streaming was 5.1% slower in this paired measurement. This is a real cost, not
a claimed speed improvement.

Forked children starting from the same prepared input measured the decode-time
high-water increase:

| Decoder | Incremental peak RSS |
| --- | ---: |
| Complete transformed buffer | 41,418,752 bytes |
| Streaming, 256 KiB chunks | 27,213,824 bytes |

The streaming path reduced the observed incremental peak by 14,204,928 bytes,
or 34.3%, and by construction removed the complete 8,466,924-byte transformed
allocation. These forked deltas are more informative for this change than the
benchmark's persistent-worker high-water field, which retains earlier peaks.

## Clean public result

Canonical local evidence:

- `runs/adaptive-v3-streaming-decode-public-clean/results.json`

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | ---: | --- |
| adaptive-v2 | 6,866,648 | 38.5939 | 26.97 | 66.19 | no |
| adaptive-v3 | 6,753,811 | 37.9597 | 15.81 | 78.71 | yes |
| zstd-3 | 6,866,359 | 38.5922 | 45.05 | 122.45 | yes |
| zstd-9 | 6,386,970 | 35.8978 | 14.91 | 144.64 | yes |

The deterministic size and within-run Pareto result survived. Absolute speeds
from this run are recorded for reproducibility but rejected as comparative
evidence because the unchanged baselines suffered the same host slowdown.

## Decision

Keep the streaming decoder as the bounded-memory architecture. It closes a
necessary scaling gap and preserves format compatibility, exact output, size,
and the measured public frontier. Do not describe it as a speed win.

The next performance target is to fuse the Zstandard stream loop and token
state machine behind one native call. The current Python-to-native call per
chunk and separate library boundary are the most plausible sources of the 5.1%
tax. Promotion, the private holdout, and a market claim remain blocked on a
broader corpus, fuzzing, isolated repetitions, and materially faster decode.

That target was completed in
`docs/benchmarks/2026-07-15-fused-decode.md`; the fused 4 MiB path removed the
paired speed tax while retaining a lower-memory decode profile.
