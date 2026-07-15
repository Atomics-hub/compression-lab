# Adaptive-v3 fused structured-text decode

## Purpose

The first bounded-memory decoder crossed the Python/native boundary once per
256 KiB Zstandard output chunk. It removed the complete transformed-stream
allocation but cost 5.1% throughput in the paired large-file measurement. This
follow-up tests whether the whole Zstandard stream loop and token state machine
can execute behind one native call without adding a build-time dependency on a
specific system-library path.

This is a local public-validation result, not an isolated product gate. The
private holdout remained sealed.

## Design

- Python loads the same `libzstd` used by every other in-process baseline and
  caches pointers to its stream create, initialize, decompress, free, and error
  functions.
- One FFI call passes that function table, the compressed input, declared
  transformed size, final output allocation, and expected output size to Rust.
- Rust owns the complete stream lifecycle and token-decoder state until either
  exact completion or a validated failure.
- The native loop rejects Zstandard errors, no-progress states, integer
  overflow, transformed-size mismatches, output-size mismatches, invalid token
  data, incomplete frames, and trailing compressed data.
- The default reusable buffer is 4 MiB, capped to the declared transformed
  size so smaller inputs never allocate the full default.
- Passing function pointers avoids hard-linking the Rust library to a
  platform-specific Zstandard installation while removing all per-chunk Python
  calls and buffer descriptors.

The tested clean revision was
`ac3548251123fb96d73c69e69880e252b3f85e15`.

## Correctness

All 30 Python tests and all three optimized Rust tests passed. The fused path
retains the earlier single-byte and seven-byte boundary schedules and adds a
valid-Zstandard frame containing an invalid structured-text token stream. It
also rejects truncation, false transformed sizes, trailing data, invalid
markers, and output-size violations.

The clean public benchmark completed all 64 measured round trips without a
failure. Encoded output remains byte-stable at 6,753,811 aggregate bytes,
37.9597% of the 17,792,077-byte corpus.

## Chunk-size selection

Removing the Python crossings changed the streaming-size knee. A rotating-order
paired sweep on the 9,514,279-byte SQLite source produced:

| Decoder | Median throughput |
| --- | ---: |
| Complete transformed buffer | 140.094 MB/s |
| Fused, 64 KiB | 146.867 MB/s |
| Fused, 256 KiB | 130.945 MB/s |
| Fused, 1 MiB | 144.681 MB/s |
| Fused, 4 MiB | 162.269 MB/s |

The host was variable, so this sweep is used to select a local knee rather than
as a general throughput claim. Four MiB was retained and then tested again in a
separate 60-decode alternating-order pair.

## Paired decode result

Both paths decoded the same 2,349,083-byte payload representing an
8,466,924-byte transformed stream and reproduced the same 9,514,279-byte source:

| Decoder | Median time | Throughput |
| --- | ---: | ---: |
| Complete transformed buffer | 47.975 ms | 198.317 MB/s |
| Fused streaming, 4 MiB | 46.872 ms | 202.986 MB/s |

Fused streaming was 2.4% faster in this paired measurement. The previous
per-chunk implementation was 5.1% slower than two-stage decode, so the native
fusion removed the measured speed tax rather than merely moving it.

Forked children starting from the same prepared input measured the decode-time
high-water increase:

| Decoder | Incremental peak RSS |
| --- | ---: |
| Complete transformed buffer | 41,418,752 bytes |
| Fused streaming, 4 MiB | 31,145,984 bytes |

The fused default reduced the observed incremental peak by 10,272,768 bytes,
or 24.8%, while also winning the paired throughput comparison. Applications
that prioritize memory over speed may still request a smaller chunk.

## Clean public result

Canonical local evidence:

- `runs/adaptive-v3-fused-decode-public-clean/results.json`

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | ---: | --- |
| adaptive-v2 | 6,866,648 | 38.5939 | 60.06 | 204.37 | no |
| adaptive-v3 | 6,753,811 | 37.9597 | 26.68 | 118.93 | yes |
| zstd-3 | 6,866,359 | 38.5922 | 82.91 | 217.96 | yes |
| zstd-9 | 6,386,970 | 35.8978 | 21.87 | 245.99 | yes |

The run began with a one-minute load average of 10.56 on a ten-core machine.
Its absolute throughputs are retained for reproducibility but rejected as an
isolated speed claim. The deterministic size, exact round trips, clean commit,
and within-run Pareto classification remain valid.

## Decision

Keep the fused 4 MiB streaming path. It is both faster and lower-memory than
the original two-stage decode in the controlled large-file pair, preserves
encoded compatibility, and keeps system Zstandard discovery portable.

This closes the per-chunk FFI bottleneck but does not make adaptive-v3 the
default market winner. In the full harness, version-3 frame parsing, integrity
checks, allocation, and Python orchestration still leave aggregate decode well
behind direct Zstandard. The next engineering target is a measured whole-frame
decode profile followed by native movement of only the dominant remaining
cost. Broader corpora, fuzzing, isolated repetitions, and the private holdout
remain promotion gates.
