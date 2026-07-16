# JLC2 native development decision

## Status

Keep JLC2/JLF2/JLS2 in development. Do not open blind validation yet.

The native representation, exact fallback, segmented file API, memory
revision, encoded-integrity checks, and fuzz gates have materially advanced.
The quiet-host speed gate is still unverified because unrelated Android,
Gradle, and Xcode builds kept normalized host load far above the frozen limit.

## Native equivalence and correctness

- Rust and Python emit byte-identical JCT1 on empty, flat JSON, nested JSON,
  CRLF, escaped strings, malformed numbers, binary marker bytes, final
  unterminated records, and the 257-key channel-limit case.
- Rust reassembly restores exact bytes and rejects invalid magic, truncation,
  trailing bytes, impossible references, and unconsumed channels.
- JLC2 output sizes remain byte-identical to the accepted Python-reference
  development artifact.
- Four-channel compression and decompression now run concurrently while
  preserving deterministic output order.

## Contended-host diagnostic

The initial native whole-frame run began at a one-minute load average above
300 on a 10-logical-CPU host. These rates are not claimable.

Even under that invalid load:

- sequential native aggregate compression: 12.08 MB/s;
- parallel-channel aggregate compression: 34.12 MB/s;
- sequential native aggregate decompression: 47.88 MB/s;
- parallel-channel aggregate decompression: 105.64 MB/s.

This establishes implementation direction only. It does not pass or fail the
frozen quiet-host speed gates.

## Exact fallback and segmentation

JLF2 computes direct zstd-6 and JLC2 concurrently, hashes the selected payload,
and selects the smaller complete frame. JLS2 hashes the complete encoded
segment stream and original bytes.

With the revised 16 MiB default:

| Family | JLS2 bytes | zstd-9 bytes | Gain |
| --- | ---: | ---: | ---: |
| Apache | 178,101 | 243,342 | 26.81% |
| HealthApp | 1,005,536 | 1,363,620 | 26.26% |
| HPC | 624,163 | 1,113,188 | 43.93% |
| Mac | 687,763 | 798,518 | 13.87% |
| ZooKeeper | 197,750 | 269,207 | 26.54% |

Aggregate JLS2 is:

- 2,693,313 bytes;
- 28.90% smaller than zstd-9;
- 6.45% smaller than Brotli-11;
- smaller than Brotli-11 on three of five families.

Random, already-compressed, non-JSON, and long-record adversarial inputs all
selected the exact direct route and never exceeded the equally framed direct
candidate.

## Streaming and memory

The bytes and file APIs emit identical JLS2 bytes for the same segment target.
The file API reads and writes one segment at a time, backfills the fixed
header, uses a temporary destination, and publishes output only after
integrity succeeds.

HPC memory diagnostics:

| Target | Maximum resident set | Encoded bytes | Decision |
| --- | ---: | ---: | --- |
| 64 MiB initial | 942,653,440 | 588,924 | reject |
| 64 MiB optimized | 620,216,320 | 588,924 | reject |
| 32 MiB optimized | 518,553,600 | 596,058 | insufficient headroom |
| 16 MiB optimized | 307,019,776 | 624,035 | accept as new default |

The 16 MiB target remains 43.94% smaller than zstd-9 on HPC while providing
substantial headroom under the 512 MiB gate.

Current-format per-family maximum resident set:

| Family | Maximum resident set |
| --- | ---: |
| Apache | 140,820,480 |
| HealthApp | 253,542,400 |
| HPC | 294,682,624 |
| Mac | 268,795,904 |
| ZooKeeper | 169,426,944 |

All five pass the 536,870,912-byte ceiling.

## Fuzz evidence

The deterministic JLS2 fuzz run passed:

- 17,080 exhaustive single-bit mutations rejected;
- 2,135 truncations rejected;
- 2,000 additional random mutations rejected;
- 2,000 random JLS frames rejected;
- 2,000 random JCT transforms rejected;
- 250 randomized binary/JSON round trips.

## Remaining development gates

Before validation:

1. obtain an eligible quiet-host five-repetition speed run;
2. add release-facing CLI/API integration and versioned format inspection;
3. run broader fuzzing and sanitizer/hosted CI;
4. reproduce CLP, LogLite, DeLog, and other log-specific baselines where
   licensing and hardware permit;
5. freeze the final validation artifact and thresholds.

No public superiority claim follows from this checkpoint.
