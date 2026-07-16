# JLF1 exact fallback and JLS1 segmentation protocol

## Purpose

JLC2 passed the real-family development ratio gates and now has byte-identical
native extraction and reassembly. This protocol freezes the complete selector,
direct fallback, and bounded large-file container before measuring them.

Blind validation remains unopened.

## JLF1 exact fallback frame

For one segment, run these candidates concurrently:

1. direct Zstandard level 6 over the original bytes;
2. complete JLC2 over the original bytes.

Wrap both candidates in the same fixed JLF1 header containing:

- magic and version;
- selected mode;
- original size;
- payload size;
- SHA-256 of original bytes.

Select the smaller complete frame, with ties going to direct Zstandard. Since
both candidates pay the same outer header and are fully materialized before
selection, JLF1 can never exceed its equally framed direct route.

The selector uses no source identity, filename, schema exception, validation
identity, or estimated size. Direct and JLC work run concurrently so exact
fallback does not require serially adding both backend costs.

## JLS1 bounded container

The bytes API stores one or more JLF1 frames in a JLS1 container:

- target segment size: 64 MiB;
- split only immediately after byte `0x0a`;
- never split a record;
- a single record larger than 64 MiB forms one oversized segment;
- process segments in source order;
- outer header stores version, total original size, SHA-256, and segment count;
- each segment stores original size and complete JLF1 size.

The initial bytes API may retain the final encoded output, but codec working
state must be bounded to one source segment, its direct candidate, its JLC
candidate, and fixed channel metadata. A later file API must stream segments
without reading the complete source or destination into memory.

## Development gates

Before blind validation:

1. JLF1 round-trips every development and adversarial fixture exactly.
2. JLF1 never exceeds the equally framed direct route.
3. JLS1 round-trips LF, CRLF, final unterminated records, binary bytes, random
   bytes, already-compressed bytes, missing fields, reordered fields, nested
   values, malformed records, and records larger than the target segment.
4. Every truncation, trailing byte, invalid mode, impossible size, segment
   mismatch, nested-frame corruption, and SHA mismatch is rejected.
5. Output is deterministic across repeated and parallel runs.
6. Complete development sizes remain at least 5% smaller than raw zstd-9 on
   every LogTrie family.
7. Quiet-host complete compression is at least 75 MB/s per family and
   100 MB/s aggregate.
8. Quiet-host complete decompression is at least 250 MB/s per family.
9. Peak working memory for a 64 MiB segment remains below 512 MiB.
10. Python, Rust, malformed-input, corruption, and fuzz suites remain green.

A pass advances to a streaming file API and competitive log-specific
baselines. It still does not authorize validation or a public superiority
claim.
