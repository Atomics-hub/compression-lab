# JLC2 balanced columnar development protocol

## Prior result

JLC1 used independent Zstandard level-3 streams. It extracted 100% of records
and won against zstd-9 on HealthApp, HPC, and ZooKeeper, but missed by 1.03%
on Apache and 2.56% on Mac. It therefore failed its frozen all-family gate.

Development-only channel diagnostics then measured backend levels without
changing the JLC representation. Level 6 was the first balanced point that:

- produced smaller raw stream totals than direct zstd-9 on all five families;
- produced smaller totals than Brotli-11 on Apache, HPC, and ZooKeeper;
- kept Mac backend throughput near 100 MB/s on the noisy local host;
- avoided the severe level-9 and level-19 development-loop cost.

The complete JLC2 frame, results, and gates below are frozen before measuring
JLC2 as a framed candidate. Blind validation remains unopened.

## Frozen candidate

JLC2 is byte-for-byte the JLC1 flat-JSON columnar representation defined in
`2026-07-16-json-log-columnar-protocol.md`, with exactly one change:

- the skeleton and every channel use Zstandard level 6.

The frame still includes all headers, raw/compressed sizes, channel table,
original size, and SHA-256. No source rule, field-specific codec, channel
exception, semantic normalization, learned dictionary, or mixed backend level
is allowed.

## Development gates

Advance JLC2 to a portable native extractor only if the complete frame:

1. round-trips every development file exactly;
2. is at least 5% smaller than direct zstd-9 on all five families;
3. is at least 20% smaller than zstd-9 in aggregate;
4. beats Brotli-11 on at least three of five families;
5. is at least 5% smaller than Brotli-11 in aggregate;
6. extracts at least 95% of records on every family;
7. passes all JLC1 malformed, corruption, bound, and adversarial tests;
8. leaves the existing Python and Rust suites green.

Python throughput is diagnostic only. Native promotion will use separate
predeclared gates:

- at least 250 MB/s extraction;
- at least 75 MB/s complete compression on every family and 100 MB/s
  aggregate;
- at least 250 MB/s complete decompression;
- no more than 256 channels and bounded per-chunk memory;
- exact direct fallback and streaming before blind validation.

If the ratio gates fail, retain JLC2 as rejected development evidence and do
not inspect validation.
