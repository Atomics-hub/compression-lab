# Log-specific competitor reproduction audit

## Decision

Audit refreshed on 2026-07-17. Do not report a direct CLP, LogLite, DeLog,
LogFold, or LogPrism win yet. None is currently
eligible for the same byte-exact local benchmark, for different reasons.

PBC was found after the initial audit and passed the frozen hosted
reproduction. JLS2 was 92.39% smaller than the best fixed PBC method on the
five exposed development families.

The PBC result is a comparative development result. The remaining entries are
eligibility findings. No public superiority claim follows from either.

The general-purpose roster is not stale: the CLUE development census used
zstd 1.5.7, Brotli 1.2.0, LZ4 1.10.0, and 7-Zip 26.02, alongside the pinned
in-process gzip, bzip2, and LZMA implementations. Version freshness does not
make unlike runners comparable, and it does not replace the specialist audit.

The machine-readable record is
`config/log-competitor-reproduction-v1.json`.

## Direct-comparison contract

A compressor enters the primary leaderboard only when it:

1. receives the identical input bytes;
2. reconstructs the identical bytes by SHA-256;
3. preserves record order and exact textual values;
4. reports the total size of every required archive, dictionary, index, and
   metadata file;
5. measures complete compression and decompression wall time;
6. uses a pinned source commit or immutable container digest;
7. has a software license that permits a reproducible benchmark workflow.

Semantically transformed or non-order-preserving systems may be reported
separately, but never as if they satisfy the exact-file contract.

## PBC

Pinned source:

- repository: <https://github.com/antgroup/pbc>;
- commit: `bac1f86d29624cb585bb4475235d22a28e60ffea`;
- license: Apache-2.0;
- paper: <https://doi.org/10.1145/3626732>.

PBC directly targets high-ratio compression for machine-generated data and
has an official SIGMOD reproducibility artifact. It exposes four lossless
methods: PBC-only, PBC-FSE, PBC-FSST, and PBC-Zstd.

The frozen hosted protocol builds the unmodified pinned source on Ubuntu 22.04,
runs the official unit and integration tests, and compares all four methods on
the identical LogTrie development bytes. Pattern files are required decoder
artifacts, so their bytes are included in every complete archive. Pattern
training time is reported separately and included in complete compression
time.

The reproduction passed every exactness and accounting gate. PBC-only was the
best fixed method at 35,380,846 complete bytes versus 2,693,313 for JLS2 and
3,787,875 for zstd-9. See
`docs/benchmarks/2026-07-16-pbc-competitor-development-decision.md`.

## CLP JSON

Pinned source:

- repository: <https://github.com/y-scope/clp>;
- release: `v0.12.0`;
- commit: `d3daf16517c51f8e6fc09960be821a93a3efe06b`;
- license: Apache-2.0.

The official `clp-s` interface accepts newline-delimited JSON and can produce
single-file archives. However, the current official documentation states that
timezone information and event order are not preserved during JSON
decompression:

<https://docs.yscope.com/clp/main/user-docs/core-clp-s.html#current-limitations>

That makes CLP JSON ineligible for the byte-exact leaderboard. Its ratio may
later be reported in a clearly separated semantic-log context.

The official quick-start container is x86 Ubuntu:

`ghcr.io/y-scope/clp/clp-core-x86-ubuntu-jammy`

The local Docker CLI is installed, but its daemon was not running during this
audit.

## LogLite

Pinned source:

- repository: <https://github.com/benzhaotang/LogLite>;
- commit: `68f851ef673ac6fa45f26513df08613151624bd2`;
- paper: <https://www.vldb.org/pvldb/vol18/p3757-yang.pdf>.

The artifact describes line-wise lossless compression for both text and JSON
logs. Its official build uses:

`g++-9 -Ofast -march=native -mavx512f`

The source includes x86 intrinsic headers. It therefore cannot be reproduced
faithfully on this Apple ARM64 host. In addition, the repository contains
`LogLite-B` and `LogLite-b`, which collide on the default case-insensitive
macOS filesystem.

No top-level software license was present and GitHub reported no repository
license. The repository is not vendored, patched, or redistributed. A direct
result requires an appropriate x86-64 AVX-512 Linux host and license
clarification.

## DeLog

Pinned source:

- repository: <https://github.com/gaiusyu/Delog>;
- commit: `64a074f6b6559fbfcd809f201fc3540442151749`;
- paper: <https://arxiv.org/abs/2601.15084>.

The authors document whole-file SHA-256 verification and support arbitrary log
names without predefined benchmark regexes. That makes DeLog conceptually
eligible for the exact-file contract.

The current local reproduction blockers are:

- the Docker daemon is not running;
- bundled binaries are Linux x86-64 ELF files;
- a source build requires PCRE2 and libarchive, and local libarchive headers
  are absent;
- the official Docker tags are mutable and must be resolved to image digests;
- no top-level software license was present and GitHub reported no repository
  license.

Do not vendor or modify DeLog. Reproduction may proceed only through a pinned
external environment after license clarification.

## LogFold

Pinned observed state:

- repository: <https://github.com/shanshw/LogFold>;
- commit: `1832f4f380e360dd12d098d987e8c0f6dcc1f3cf`;
- license: Apache-2.0;
- paper: <https://arxiv.org/abs/2603.20618>.

The paper reports experiments over 16 public log datasets and an average ratio
improvement over its chosen baselines. That makes LogFold important specialist
context. However, the official repository contained only `LICENSE` and
`README.md` when rechecked on 2026-07-17. It exposed no runnable source,
release, corpus manifest, or benchmark artifact. LogFold is therefore visible
but unavailable for reproduction. It cannot enter the primary leaderboard,
and its absence cannot be labeled a JLS2 win.

## LogPrism

Observed state:

- repository: <https://github.com/Lycc42/LogPrism>;
- paper: <https://arxiv.org/abs/2601.17482>;
- commit and software license: unavailable because the repository is empty.

The paper reports the best ratio on 13 of 16 benchmark datasets and strong
throughput. The official GitHub repository was still empty when rechecked on
2026-07-17: it exposed no commit, source, release, license, or benchmark
artifact. LogPrism is important paper-reported context but is not yet
reproducible or eligible. Its absence is not a JLS2 win.

## Next action

1. Freeze JLS2, the complete eleven-codec standard roster, and PBC-only before
   opening the two sealed CLUE-LDS validation ranges exactly once.
2. Recheck LogFold, LogPrism, LogLite, and DeLog immediately before that lock;
   retain unavailable entries in the result with explicit untested markers.
3. Preserve all ten exact standard baselines, not only zstd-9 and Brotli-11.
4. Add CLP only as a separate semantic-log comparison if Docker becomes
   available.
5. Seek a licensed, byte-exact LogLite or DeLog execution path on suitable
   Linux hardware before opening validation.
6. Keep every unavailable or ineligible competitor visible; absence is not a
   win.
