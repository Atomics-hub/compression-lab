# JLS2 cold-start delivery protocol

## Purpose

Determine whether reducing eager Python imports makes the real JLS2 product and
benchmark entry points reliably clear the existing 250 MB/s cold-process decode
gate. The candidate may change package, CLI, codec-registry, and worker import
delivery only. It must not change JLS2/JLF2/JCT1 bytes, decode scheduling,
reconstruction, integrity checks, selector decisions, or output bytes.

This is a development experiment. The two frozen CLUE-LDS public-validation
ranges remain unmaterialized and unopened.

## Frozen comparison

- Baseline source: merge commit `5778b86c1bb9d9b842afd17afb3b3456f02b0cf1`.
- Candidate source: the first clean commit that implements the import-delivery
  change after this protocol.
- Python executable, native release library, environment, frames, destinations,
  filesystem, and host are shared by both source trees.
- Inputs are the three licensed development ranges pinned in
  `config/clue-json-log-corpus-v1.json`.
- JLS2 frame sizes must remain 1,382,653, 738,259, and 1,402,809 bytes and each
  frame SHA-256 must be identical between baseline and candidate trials.

## Product paths

Measure both public cold-process paths:

1. `python -m compresslab json-decompress`, including interpreter/package/CLI
   startup, complete file decode, integrity verification, atomic output, and CLI
   completion.
2. `python -m compresslab.worker --codec jls2 --operation decompress`, including
   interpreter/package/worker startup, complete file decode, integrity
   verification, output, and telemetry publication.

Also characterize `python -c 'pass'`, `import compresslab`,
`python -m compresslab --version`, and `python -m compresslab.worker --help`.
These probes explain startup changes but do not decide the decode gate.

## Schedule and accounting

- one discarded warmup per source tree, product path, and family;
- seven measured rounds;
- a fresh process for every trial;
- deterministic rotation of baseline/candidate order, product-path order, and
  family order;
- primary timing is parent wall clock around the complete process;
- decimal MB/s from original source bytes;
- worker wall, CPU, high-water RSS, engines, segment count, and selected backend
  are retained as secondary evidence;
- the parent rechecks restored size and SHA-256 after timing;
- all commands, Python/platform metadata, source hashes, frame hashes, native
  library hash, load averages, raw trials, and exactness results are retained.

## Frozen gates

The candidate qualifies only if all of these are true:

1. all 96 total round trips are exact (84 measured plus 12 warmups);
2. frame sizes and SHA-256 values are identical for baseline and candidate;
3. the full test suite, formatter/linter checks, golden frames, hostile-frame
   tests, and cross-platform CI remain green;
4. public CLI output, exit codes, aliases, overwrite rules, allocation bounds,
   worker telemetry fields, and codec availability behavior remain compatible;
5. all seven candidate aggregate rounds reach at least 250 MB/s for both the CLI
   and benchmark-worker paths;
6. every family median reaches at least 250 MB/s for both paths;
7. aggregate round-rate coefficient of variation is at most 20% for both paths;
8. candidate worker peak RSS is at most 512 MiB;
9. median paired aggregate improvement over the baseline is at least 10% for
   both paths; and
10. compressed bytes, decode scheduling, and the JLS2 reconstruction kernel are
    unchanged.

If any gate fails, retain the existing product claim and use the evidence to
decide whether a standalone/native decoder is the next justified experiment.

## Claim ceiling

This experiment may support only a development claim about cold-process product
delivery on the three frozen CLUE-LDS development ranges. It cannot advance
JLS2 to public validation or support a market-leading, world-best, universal, or
state-of-the-art claim.
