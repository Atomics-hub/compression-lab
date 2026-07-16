# JLS1 bounded-memory v2 protocol

## Prior decision

The original JLS1 protocol froze a 64 MiB target and a peak working-memory
gate below 512 MiB. On the 49,307,346-byte HPC development file:

- initial implementation: 942,653,440-byte maximum resident set;
- after removing redundant ctypes source copies and reducing transform
  preallocation: 620,216,320 bytes.

The 64 MiB target therefore failed its frozen memory gate.

A 32 MiB diagnostic produced:

- 518,553,600-byte maximum resident set;
- 596,058 encoded bytes;
- two segments.

Although 518,553,600 bytes is technically below 512 MiB, the margin is too
small to be robust across allocators and platforms.

A 16 MiB diagnostic produced:

- 307,019,776-byte maximum resident set;
- 624,035 encoded bytes;
- three segments.

This gives substantial memory headroom while remaining 43.94% smaller than
the 1,113,188-byte zstd-9 HPC baseline.

## Frozen revision

Keep the JLS1 wire format and JLF1 exact selector unchanged. Change only the
default target segment size:

- old target: 64 MiB;
- new target: 16 MiB.

All record-boundary, oversized-record, exact-fallback, SHA, corruption, and
determinism requirements from the original JLF1/JLS1 protocol remain in
force.

## Promotion gates

Before validation:

1. maximum resident set remains below 512 MiB on every development family;
2. every development family remains at least 5% smaller than raw zstd-9;
3. aggregate bytes remain at least 20% smaller than zstd-9;
4. exact fallback remains no larger than the equally framed direct route;
5. file and bytes APIs emit identical JLS1 bytes for the same segment target;
6. quiet-host compression and decompression gates pass;
7. all existing correctness and corruption tests pass.

The 16 MiB target is a development revision, not a public performance claim.
Blind validation remains unopened.
