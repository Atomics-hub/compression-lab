# Text and source-code category protocol

## Decision

“Plain text and source code” is no longer one benchmark category. It is now two
independent tracks:

1. deterministic multi-language source-code bundles; and
2. English Wikimedia revision text with its wikitext markup retained.

A win on one track says nothing about the other. Neither track has a benchmark
result yet. The committed declarations in
`config/text-source-category-protocol-v1.json` and
`config/text-source-gates-v1.json` are an unacquired protocol, not evidence that
Compression Lab is better than another compressor.

## Why the old evidence is insufficient

The public starter contains four source files from one SQLite release. That is
one C project family, not a representative source-code corpus. The existing
adaptive-v3 candidate was 1.81% smaller than zstd-3 on the expanded public
study, but 5.56% larger than zstd-9 and much slower. Its structured-text side
channel helped one JSON item and lost on every C/source item. Those are useful
development results, but they do not support a source-code or natural-language
claim.

The famous enwik8/enwik9 data is also not unseen evidence. The [Large Text
Compression Benchmark](https://mattmahoney.net/dc/text.html) has driven years
of direct optimization. We will retain enwik9 only as a diagnostic and as a
bridge to published research results.

## Source-code split

The development split freezes current official releases of CPython, TypeScript,
Rust, and LLVM. Public validation freezes different project lineages in the
same main language strata: Django, VS Code, Tokio, and {fmt}. All eight projects
have explicit software licenses and official release sources. As of the
declaration date, upstream identifies [Python 3.14.6](https://www.python.org/downloads/)
as the latest stable source release, [TypeScript
6.0.3](https://github.com/microsoft/TypeScript/releases/tag/v6.0.3), [Rust
1.97.1](https://github.com/rust-lang/rust/releases/tag/1.97.1), and [LLVM
22.1.8](https://github.com/llvm/llvm-project/releases/tag/llvmorg-22.1.8).
The validation releases are declared now but remain unopened.

Each corpus item is a deterministic `source-bundle-v1` byte stream. It keeps
source-file bytes unchanged, sorts paths bytewise, excludes frozen generated
and vendored trees, and frames paths and contents without timestamps, owners,
permissions, archive padding, or host-dependent metadata. This measures source
content rather than the accidental metadata of a tar implementation while
still preserving every selected source file exactly. The exact exclusions are
frozen in `config/text-source-path-rules-v1.json`. Both category formats include
an explicit record count and a terminal manifest digest whose input bytes are
defined in the machine-readable protocol, so a decoder never has to guess where
records stop.

## Natural-language split

This first natural-language wedge is deliberately narrow: English Wikimedia
revision text, including wikitext markup. It is not a claim about books, email,
chat, OCR, other languages, or arbitrary UTF-8.

Development uses English Wikibooks, Wikinews, and Wikiversity from the frozen
2026-07-01 dumps. Public validation uses different projects: English Wikipedia,
Simple English Wikipedia, and English Wikivoyage from the same dump date. The
[Wikimedia dump legal page](https://dumps.wikimedia.org/legal.html) explains
that textual content is generally available under CC BY-SA 4.0 and the GFDL,
subject to page-specific exceptions and third-party material. Every retained
manifest must therefore preserve project, revision, attribution, license,
publisher checksum evidence, and exact acquired and derived digests.

The first declaration named `20260620`, but all three development checksum URLs
returned HTTP 404 before any archive was acquired. The protocol was therefore
amended to the completed common monthly dump `20260701`. Only the three
development project indexes were inspected to make that correction; no
public-validation archive, checksum file, listing, byte, or statistic was
opened.

The first development acquisition stopped before LLVM or Wikimedia when the
official Rust source tarball exposed a case-only name collision inside an
excluded rustfmt test fixture (`ABCD` versus `abcd`). A second attempt stopped
on a symlink inside excluded vendored LLVM LLDB tests. Since the builder streams
members directly and never extracts an archive to host paths, the rule was
narrowed completely: exact duplicates, case-fold collisions, links, and
non-regular types are rejected among post-exclusion candidate source paths.
Every path still receives global lexical/root/encoding validation. Interrupted
staging directories were removed; cached archives remained subject to the same
publisher size and digest checks on resume.

A third attempt was manually interrupted when the original sorted writer was
observed repeatedly seeking through Rust's compressed XZ stream. The builder
now makes one streaming content pass into opaque, index-named temporary blobs,
then replays those blobs in bytewise path order. Archive member names are never
created on disk, the final bytes are unchanged, and the repeated decompression
cost is eliminated.

The deterministic extractor keeps namespace-zero, non-redirect latest revision
text in publisher order, performs only XML decoding, and applies no Unicode,
whitespace, case, markup, or line-ending normalization. A frozen 4 KiB exact
chunk rule removes cross-project page reuse from validation before its one-time
score and reports every rejection.

## Competitor tiers

The practical gate is much stronger than the old gzip/zstd/Brotli/LZMA roster.
It adds zstd ultra, bzip3, 7-Zip PPMd, Kanzi, and libbsc. The candidate must be
at least 5% smaller than the strongest same-run complete practical artifact,
not merely zstd-9, and must also meet speed, memory, exactness, determinism,
integrity, streaming, portability, and fallback-safety gates.

Maximum-ratio research compressors remain visible in a separate ceiling tier:
ZPAQ 7.15, PAQ8PX v216, cmix v21, and NNCP 3.2. cmix explicitly recommends at
least 32 GiB RAM, while PAQ8PX describes its highest modes as extremely slow
and memory-heavy. The protocol therefore caps each research run at 12 hours
per family and 32 GiB RSS. Failure to run, timeout, or lack of portability is
not a win. Passing the practical product gate cannot support “world-best
ratio” language unless every eligible completed research-ceiling result is
also beaten with all decoder assets counted.

## Frozen pass boundary

For each track, ratio mode must be at least 5% smaller in aggregate than the
strongest reproduced practical baseline, clear that margin on the required
family majority, never regress more than 1% against its equally framed direct
fallback on any family, compress at 25 MB/s or more, decompress at 200 MB/s or
more, and remain within 1 GiB peak RSS.

Balanced mode must be at least 5% smaller than zstd-9, remain within 3% of ratio
mode size, compress at 100 MB/s or more, decompress at 500 MB/s or more, and
remain within 512 MiB peak RSS. Both modes require exact deterministic round
trips, complete accounting, corruption rejection, bounded input-only
selection, cross-platform wheels, and a portable reference decoder.

Public validation remains sealed until the corpus builder, candidate, runner,
baseline commands, evaluator, gates, and publication path are frozen at a
clean commit. Its first authorized acquisition and score is immutable. A pass
is category-scoped; private-holdout success and independent reproduction are
still required before state-of-the-art wording.

## Next action

Commit and verify this declaration, then acquire only the seven declared
development sources (four source-code releases and three Wikimedia projects;
enwik9 is diagnostic-only), record all exact digests before probing a codec,
and run the complete practical baseline census. No new representation work is
justified until that census identifies the actual per-family leaders and the
ratio/speed frontier.
