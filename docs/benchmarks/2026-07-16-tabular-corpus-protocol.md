# Delimited-tabular corpus and product protocol

## Decision question

Can a byte-exact delimited-table specialist expose column structure well enough
to beat the strongest complete lossless byte-stream baseline by at least 5%
without giving up practical compression, decompression, memory, integrity, or
portability?

This is a separate category from JSON logs. A win here must restore the exact
source bytes, including header spelling, delimiters, quoting, empty fields,
number spelling, record order, line endings, and final-terminator state.

## Frozen corpus split

`config/tabular-corpus-v1.json` freezes four development and four public
validation families from the UCI Machine Learning Repository. Every cited UCI
dataset page declares CC BY 4.0, names the creator, exposes a DOI, and lists the
selected file. The split deliberately spans:

- comma and semicolon delimiters;
- headerless and header-bearing inputs;
- categorical, integer, binary, decimal, timestamp, and string columns;
- narrow, wide, dense, sparse, event, and time-series layouts;
- selected byte streams large enough for meaningful throughput measurement.

Every item is capped at a frozen 64 MiB record-aligned prefix. The cap keeps
repeated dense-codec validation operational while preserving enough bytes for
stable speed and memory measurements. No parsing or canonical reserialization
is allowed when building corpus items.

The publisher pages do not expose file checksums. Development URLs may be
acquired only after this split is committed; their archive and derived-item
SHA-256 values must be committed before a scored development decision. Public
validation archives remain unopened until the candidate implementation,
baseline runner, evaluator, and gates are frozen. Their first acquisition
creates the immutable digest record and first score.

The private holdout remains sealed and unnamed.

## Rejected corpus candidates

The 18 PMLB datasets whose checked-in metadata explicitly says CC BY 4.0 are
useful correctness fixtures but are too small for throughput evidence: the
largest Git LFS object is only 46,773 compressed bytes. They are not a
performance corpus.

The Public BI benchmark is highly relevant competitor research, but its
workbook-derived table collection does not expose a single sufficiently clear
license for claim-bearing redistribution. Its published results and code may
inform baseline selection; its table bytes are excluded from this corpus.

## Representation research order

The first specialist probe is `TBL1`, with independently removable channels:

1. A byte-exact row skeleton records delimiters, quoting, escapes, line endings,
   malformed rows, and literal fallback regions.
2. Constant and null-like columns use constant tags and presence bitmaps.
3. Low-cardinality strings compare dictionary indexes, RLE, and direct bytes.
4. Integers compare delta, frame-of-reference, zigzag, bit packing, and direct
   textual bytes.
5. Decimal text compares exact sign, digit, scale, exponent, and spelling
   channels; binary floating-point conversion is not allowed to lose spelling.
6. The complete frame compares the specialist with an equally framed direct
   backend and store fallback. The selector emits the smallest complete frame.

Multi-column dependency coding is deferred until single-column channels have a
measured retained result. No validation family may influence channel design,
thresholds, or selector policy.

## Standards and comparability

The exact-byte baseline roster is frozen in `config/tabular-gates-v1.json` and
includes store, LZ4, gzip, bzip2, Zstandard levels 3/9/19, Brotli-11,
xz/LZMA2-9, and 7-Zip/LZMA2-9.

Modern column encodings are required context, including Apache Parquet's
[dictionary, RLE, delta, and byte-stream-split encodings](https://arrow.apache.org/rust/parquet/basic/enum.Encoding.html),
[FSST](https://www.vldb.org/pvldb/vol13/p2649-boncz.pdf),
[BtrBlocks](https://github.com/maxi-k/btrblocks), and
[FastLanes](https://github.com/cwida/FastLanes). However, a semantic Parquet,
BtrBlocks, or FastLanes artifact is not automatically comparable to exact-byte
CSV compression. It counts toward the primary gate only when the complete
artifact and all reconstruction metadata restore the original byte stream.

## Frozen product gates

The ratio-oriented dense mode must be at least 5% smaller in aggregate than the
strongest complete exact-byte baseline, achieve that margin on at least three
of four public-validation families, compress at 50 MB/s or more, decompress at
250 MB/s or more, and remain within 512 MiB peak RSS.

The balanced mode must be at least 5% smaller than zstd-9, remain within 2% of
dense-mode size, compress at 100 MB/s or more, decompress at 500 MB/s or more,
and remain within 384 MiB peak RSS.

Both modes require exact round trips, deterministic output, complete archive
accounting, bounded streaming memory, corruption rejection, a portable
reference decoder, and no material expansion versus the equally framed direct
fallback. Five repetitions are required for every candidate operation.

### Frozen streaming contract

The development streaming candidate is `TBS1` version 1: a segmented outer
stream containing complete, independently verified TBL1 frames. It reads a
32 MiB target chunk and may extend at most 1 MiB to finish a record; a longer
record is split losslessly at that hard bound. Each segment runs the bounded
dense selector independently, so neither delimiter detection nor candidate
generation sees more than one bounded segment.

The outer stream declares the segment target, record-alignment slack, original
size, complete payload size, segment count, source SHA-256, and payload
SHA-256. The decoder must enforce all declared bounds before allocation,
verify every inner TBL1 frame and both outer digests, reject truncation,
corruption, count/size inconsistencies, and trailing bytes, and never clobber
an existing destination after failure. Because every column candidate is
compared concurrently with a complete direct zstd-9 fallback, a selected
segment cannot exceed that fallback; the decoder therefore also rejects any
frame larger than the direct-frame allocation bound before reading it.

The streaming development gate allows at most 2% aggregate size regression
relative to whole-file TBL1-dense. It retains the 50 MB/s compression,
250 MB/s decompression, and 512 MiB memory limits, and additionally requires
the minimum—not merely median—five-run repetition aggregate to clear both
speed thresholds. A deterministic exact round trip of at least 1 GiB must
demonstrate that peak memory is bounded independently of total file size.

## Required scorecard

At every development or validation decision, publish one chart with:

- complete compressed bytes and byte-weighted ratio;
- compression and decompression MB/s and timing basis;
- peak RSS;
- exactness, determinism, corruption, streaming, and portability status;
- per-standard win, loss, mixed, or untested status;
- runner and semantic-versus-byte-exact comparability;
- corpus license, split, digests, commit, evidence stage, and claim ceiling.

A public-validation pass is still not a world-best claim. That language
requires a fresh private holdout and independent reproduction.
