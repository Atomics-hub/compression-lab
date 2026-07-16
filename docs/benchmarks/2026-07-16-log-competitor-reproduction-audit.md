# Log-specific competitor reproduction audit

## Decision

Do not report a direct CLP, LogLite, or DeLog win yet. None is currently
eligible for the same byte-exact local benchmark, for different reasons.

This is an eligibility audit, not a comparative result. Blind validation
remains sealed.

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

## Next action

1. Preserve zstd-9 and Brotli-11 as the current exact, reproducible baselines.
2. Add CLP only as a separate semantic-log comparison if Docker becomes
   available.
3. Seek a licensed, byte-exact LogLite or DeLog execution path on suitable
   Linux hardware before opening validation.
4. Keep every unavailable or ineligible competitor visible; absence is not a
   win.
