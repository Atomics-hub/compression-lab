# Official PBC development decision

## Decision

Pass the independent competitor-reproduction gate. Freeze `pbc_only` as the
single PBC method for blind validation and allow the already-declared
three-family public validation split to open exactly once.

Do not make a public superiority, world-best, or state-of-the-art claim. This
is a large win on five exposed development families from one corpus
publication, not independent validation.

## Reproduction proof

The successful hosted run is
<https://github.com/Atomics-hub/compression-lab/actions/runs/29537587012>.
Its canonical result SHA-256 is
`7f88a0d98d17dc2c8b4fe9990544caac5dffb35cc6e218f3f9b138eee5d50dab`.
The durable summary is
`runs/pbc-competitor-hosted-development-summary.json`.

The run used:

- Compression Lab commit
  `921d858843afe35ac8b624164ddb70de147b6daa`;
- PBC commit `bac1f86d29624cb585bb4475235d22a28e60ffea`;
- Ubuntu 22.04.5 on a four-logical-CPU AMD EPYC hosted runner;
- all four official PBC methods;
- the official 100-pattern, 2,000-record, 64-thread training settings;
- two complete pattern-training repetitions;
- five fixed-pattern compression and decompression repetitions;
- pattern bytes plus payload bytes as the complete archive;
- full size and SHA-256 verification for every restored file.

Every frozen gate passed. PBC's official unit tests, integration tests, and
byte-for-byte integration comparisons also passed after pre-creating named
outputs to avoid the pinned CLI's missing `open` mode argument.

## Size result

Across 124,614,865 source bytes:

| Codec | Complete bytes | Notes |
| --- | ---: | --- |
| JLS2 | 2,693,313 | accepted frozen development frames |
| zstd-9 | 3,787,875 | identical source bytes |
| PBC-only | 35,380,846 | 79,654 pattern + 35,301,192 payload |
| PBC-FSE | 35,381,182 | fixed official method |
| PBC-Zstd | 35,524,438 | fixed official method |
| PBC-FSST | 44,087,556 | 8,786,364 pattern bytes |

`pbc_only` is the smallest fixed PBC method. JLS2 is 92.39% smaller than it;
the PBC archive is 13.14 times the JLS2 size. JLS2 is smaller on all five
families; its
per-family margin ranges from 82.34% to 96.76%.

Even the non-primary oracle that chooses a PBC method separately for each
family produces 35,380,239 bytes, effectively unchanged. It remains
context-only and cannot support the primary comparison.

## Operational result

PBC-only's hosted aggregate rates were:

- 0.239 MB/s complete compression, including 517.14 seconds of pattern
  training;
- 29.17 MB/s online compression with patterns already present;
- 36.38 MB/s file decompression.

These rates characterize the PBC Ubuntu runner only. They are not directly
compared with JLS2's macOS hosted rates. The 88-minute end-to-end workflow and
the separation between complete and online compression are retained because
they matter to product use.

## Frozen validation consequence

The competitor gate is now resolved. Before any validation byte is downloaded:

1. freeze the exact JLS2 implementation and 16 MiB segment target;
2. freeze `pbc_only`, pattern size 100, 2,000 training records, and 64 training
   threads;
3. freeze complete pattern-plus-payload accounting and the existing zstd-9 and
   Brotli-11 validation thresholds;
4. record the Compression Lab commit that contains the validation workflow;
5. open Hadoop, OpenSSH, and OpenStack once, with no post-score tuning.

The private holdout remains sealed.
