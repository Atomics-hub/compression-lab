# JLS2 reusable Zstandard decode-context protocol

## Purpose

Test whether repeated construction of one-shot Zstandard decompression contexts
is a material cause of JLS2 cold-process peak RSS. The standalone decoder
currently calls `zstd::bulk::decompress` independently for the skeleton and
every column stream. Zstandard 0.13.3 documents that reusing a
`zstd::bulk::Decompressor` reduces memory relative to repeated free-function
calls.

This is a development-only operational experiment. The retained CLUE-LDS
public-validation no-pass is immutable, its two ranges are consumed, and they
must not be acquired, reconstructed, decoded, or rescored. The private holdout
remains sealed.

## Frozen change

The candidate may change only `native/src/jls2.rs` as follows:

- create one `zstd::bulk::Decompressor` inside each existing stream worker;
- reuse that context for every stream assigned to the worker; and
- retain the current segment workers, channel-worker limits, byte format,
  payload validation, output validation, corruption behavior, and CLI.

No inline single-worker path, adaptive segment scheduling, streaming
reassembly, format change, encoder change, or selector change belongs to this
screen. Those require separate protocols if this isolated hypothesis fails.

The unchanged baseline implementation is commit
`7b081f6f11c2561c36289cfc57f7d3715ab8c594`.

## Frozen inputs

Run on GitHub-hosted `ubuntu-22.04`, where cold-child RSS is measured with
`wait4` and Linux KiB values are converted to bytes.

1. The three licensed CLUE-LDS development ranges pinned in
   `config/clue-json-log-corpus-v1.json`. Their source sizes and hashes must
   match the frozen corpus manifest. Generate each complete JLS2 fixture twice
   on the Linux measurement host with the unchanged encoder; both generated
   archives must have identical size and SHA-256. Retain one and supply it
   byte-identically to both decoder binaries. Do not compare the Linux archive
   hash with an archive generated on a different operating system: the first
   protocol attempt stopped before measurement after detecting that this was
   not a valid cross-platform invariant.
2. A generated `jls2-context-stress-256` development fixture. It contains
   exactly 21,800 compact NDJSON records. Every record has the 256 keys
   `k000` through `k255` in that order and a one-digit integer value
   `(record_index + key_index) mod 10`, followed by LF. It is encoded once with
   the unchanged 16 MiB JLS2 encoder and supplied byte-identically to both
   binaries. This fixture is operational stress evidence, not corpus or ratio
   evidence. Generate it twice and require identical complete JLS2 size and
   SHA-256 before measurement.

Record source/frame SHA-256, complete bytes, command, parent wall time,
cold-child peak RSS, output identity, host, compiler, binary hashes, source
hashes, and execution order.

## Schedule

- one discarded warmup for every input and binary;
- seven measured rounds;
- alternating baseline/candidate order per input and round;
- a fresh process and fresh destination for every decode;
- primary speed is parent wall time including process startup, complete file
  I/O, integrity verification, and atomic output publication; and
- every restored output is checked for exact size and SHA-256 outside the
  timed interval.

## Selection gates

The reusable-context candidate passes only if all are true:

1. all 64 scheduled round trips are exact;
2. both binaries receive byte-identical complete JLS2 frames;
3. corruption and malformed-input unit tests remain green;
4. candidate peak RSS is at most 448 MiB on every input, reserving 64 MiB of
   headroom below the product boundary;
5. candidate peak RSS on `jls2-context-stress-256` is at least 20% below the
   baseline;
6. candidate peak RSS is no higher than the baseline on any CLUE development
   family;
7. candidate median aggregate throughput is at least 95% of the paired
   baseline;
8. every candidate family median is at least 250 MB/s and every aggregate
   measured round is at least 225 MB/s; and
9. candidate aggregate coefficient of variation is at most 20%.

Failure of the stress-memory gate rejects the hypothesis even if speed
improves. Failure caused solely by a noisy hosted-speed gate may be repeated
once on a different clean hosted runner with the exact same candidate and
protocol; inputs and thresholds may not change.

## Decision boundary

A pass authorizes retaining context reuse and designing a different untouched
public-validation memory gate. It does not retroactively pass or rewrite the
consumed score. A failure retains the current product and makes the next
eligible experiment the separately frozen inline-single-worker ablation,
followed only if necessary by declared-size-aware native batching.

Claim ceiling: **development-only decoder-memory evidence.** It cannot support
public-validation, private-holdout, independent-reproduction, universal,
market-leading, world-best, or state-of-the-art language.
