# JSON-log LWS1 splice development protocol

## Motivation

The first real-family run rejected LWX2 as the validation candidate. It beat
direct Zstandard 9 by 16.84% to 57.83% on Apache, HealthApp, HPC, and
ZooKeeper, but selected direct fallback on Mac and therefore missed the
predeclared all-family gain gate. The blind validation files remain unopened.

Inspection of development telemetry showed the likely mechanism: exact-length
XOR performs well when neighboring records align byte-for-byte, but a changed
field length shifts every later JSON byte. LWS1 tests a materially different
delta representation that remains aligned across insertions and deletions.

The representation and gates below are frozen before measuring LWS1 on any
development family.

## Frozen representation

LWS1:

- splits only at byte `0x0a` and preserves all bytes and final-record state;
- keeps only the immediately previous record as a reference;
- references records no larger than 1 MiB;
- finds the longest common prefix;
- finds the longest common suffix without overlapping the prefix;
- emits the unmatched middle bytes plus prefix and suffix lengths;
- emits the record raw when the complete splice command is not smaller;
- uses deterministic unsigned varints and a versioned `LWS1` stream header;
- uses no JSON parser, source identity, field name, event template, dictionary,
  training, or family-specific exception.

The decoder must validate magic, varints, record count, reference
availability, prefix/suffix bounds, complete input consumption, exact output
size, and trailing data.

## Frozen backend question

Measure `LWS1 + Zstandard 3` against direct Zstandard 3 and 9 and Brotli 11.
The point of level 3 is operational: LWX2's honest complete selector was
aggregate 30.08% smaller than Zstandard 9 but only 26.28 MB/s on a highly
contended host because it performed two level-9 compressions. LWS1 discovery
asks whether a stronger representation can retain the ratio win with a much
faster backend.

This phase measures the transformed route directly. It does not yet authorize
a production selector or frame. If the representation gates pass, a separate
protocol must freeze the selector, direct fallback, complete byte accounting,
and native implementation before blind validation.

## Development data

Use only the already-opened, checksum-pinned LogTrie development families:

- Apache
- HealthApp
- HPC
- Mac
- ZooKeeper

The Hadoop, OpenSSH, and OpenStack validation files must not be downloaded or
scored.

## Predeclared representation gates

Advance LWS1 to native implementation and selector design only if:

1. every family round-trips exactly;
2. `LWS1 + zstd-3` is at least 5% smaller than direct zstd-9 on all five
   families;
3. aggregate `LWS1 + zstd-3` bytes are at least 15% smaller than direct
   zstd-9;
4. it is smaller than Brotli-11 on at least four of five families;
5. aggregate bytes are smaller than Brotli-11;
6. at least 75% of records use splice references on every family;
7. raw fallback prevents any splice command from exceeding its corresponding
   raw-record command on random, already compressed, non-line-oriented, and
   over-1-MiB-record inputs;
8. malformed streams, truncation, trailing bytes, impossible references, and
   output-size mismatches are rejected;
9. the existing Python and Rust suites remain green.

Pure-Python throughput is diagnostic only. A pass authorizes a separately
frozen native speed gate of at least 250 MB/s transform, 100 MB/s complete
compression, and 250 MB/s complete decompression on a quiet host.

If any ratio gate fails, retain LWS1 as rejected development evidence and do
not tune it on validation.
