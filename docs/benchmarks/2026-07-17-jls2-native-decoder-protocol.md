# JLS2 standalone native decoder protocol

## Purpose

Determine whether a complete standalone JLS2 decoder can make the verified
JSON-log format operationally credible without changing a single compressed
byte. The experiment measures the real cold-process product path, including
argument parsing, file I/O, all JLS2/JLF2/JLC1 integrity checks, reconstruction,
atomic publication, and process exit.

This is a development experiment. The two frozen CLUE-LDS public-validation
ranges remain unmaterialized and unopened.

## Frozen comparison

- Baseline source: product commit
  `604271cbc89a11c739848f68a7739ed523fb9a1b`.
- Candidate source: the first clean commit implementing this protocol after the
  protocol commit.
- Baseline command: `python -m compresslab json-decompress INPUT -o OUTPUT
  --force` from a clean baseline source tree with its own release native
  library.
- Candidate command: `clab-jls2 decompress INPUT -o OUTPUT --force` from the
  candidate release build.
- Python, Rust, C toolchain, host, filesystem, inputs, frames, destinations, and
  parent timer are recorded. Both paths use the same input frame for a trial.
- Inputs are the three licensed development ranges pinned in
  `config/clue-json-log-corpus-v1.json`.
- JLS2 frame sizes must remain 1,382,653, 738,259, and 1,402,809 bytes, and the
  frame SHA-256 values must match the immutable development census.

## Frozen standalone interface

The candidate product is a release binary named `clab-jls2` with:

```text
clab-jls2 decompress INPUT -o OUTPUT [--force] [--max-output-size BYTES]
clab-jls2 --help
clab-jls2 --version
```

It must refuse an existing destination unless `--force` is present, write a
same-directory temporary file, atomically publish only after complete
verification, remove partial output on every failure, and emit diagnostics to
standard error with a nonzero exit status. It must not require Python or a
non-system shared library at runtime.

## Schedule and accounting

- one discarded warmup per variant and family;
- seven measured rounds;
- a fresh process for every trial;
- deterministic rotation of family and baseline/candidate order;
- primary timing is parent wall clock around the complete process;
- decimal MB/s from original source bytes;
- peak resident memory is captured by the platform process-accounting tool;
- the parent rechecks restored size and SHA-256 after timing;
- all commands, toolchain/platform metadata, source hashes, frame hashes,
  binary hashes/linkage, load averages, raw trials, exactness results, and
  hostile-frame results are retained.

This is 6 discarded warmups plus 42 measured round trips.

## Frozen compatibility and safety corpus

In addition to golden development frames, automated tests must cover:

1. empty and nonempty direct-mode streams;
2. columnar streams with zero, one, and many channels;
3. marker escaping, long varints, CRLF, non-JSON literal lines, and mixed
   extracted/literal records;
4. truncated stream, segment, frame, column-table, and zstd payloads;
5. wrong magic, unsupported version, nonzero flags/reserved bits, invalid mode,
   trailing data, and inconsistent declared sizes/counts;
6. stream encoded, frame payload, frame original, and stream original SHA-256
   mismatches, including mutations whose enclosing digest is recomputed;
7. excessive channel count/raw-size declarations, integer-overflow-shaped
   lengths, decompression-size mismatches, and output-limit rejection;
8. refusal to overwrite, forced replacement, atomic cleanup after failure, and
   input/output path collision; and
9. byte-for-byte agreement with the Python reference decoder for every valid
   fixture and rejection of every hostile fixture.

## Frozen gates

The candidate qualifies only if all of these are true:

1. all 48 scheduled round trips are exact;
2. every immutable development frame has its expected byte size and SHA-256;
3. every compatibility/safety fixture passes and no failure publishes a partial
   destination;
4. the full Python and Rust test suites, lint/format checks, golden frames,
   hostile-frame tests, and cross-platform CI remain green;
5. all seven candidate aggregate rounds reach at least 250 MB/s;
6. every candidate family median reaches at least 250 MB/s;
7. candidate aggregate round-rate coefficient of variation is at most 20%;
8. candidate peak RSS is at most 512 MiB;
9. median paired aggregate improvement over the lazy Python baseline is at
   least 10%;
10. compressed bytes, selector decisions, JLS2/JLF2/JLC1 format semantics, and
    restored bytes are unchanged; and
11. the release binary runs without Python and has no runtime dependency on a
    non-system shared library.

If a gate fails, retain the current decode claim and publish the failure. Tuning
may continue only against these same development inputs and gates; the protocol
and public-validation ranges remain frozen.

## Claim ceiling

This experiment may support only a development claim about cold-process JLS2
delivery on the three frozen CLUE-LDS development ranges. It cannot advance
JLS2 to public validation or support a market-leading, world-best, universal,
or state-of-the-art claim.
