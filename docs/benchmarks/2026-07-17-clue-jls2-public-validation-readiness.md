# CLUE-LDS JLS2 public-validation readiness

## Decision

**Candidate and gates frozen; validation remains unopened and unauthorized.**

The development ratio and standalone-delivery gates now justify preparing one
unchanged score on the two sealed CLUE-LDS temporal ranges. They do not justify
opening those ranges yet. Acquisition remains disabled until a committed final
readiness lock pins the candidate, corpus, complete competitor roster, runner,
evaluator, publication surface, and one-attempt policy.

The intended public brand is **Atompress**. `JLS2` remains the technical codec
and on-disk stream identifier, so branding has no effect on the frozen bytes or
candidate implementation.

## Frozen candidate

The candidate is the exact JLS2 implementation in the publicly reachable merge
commit `e254c43458e2ae4f8088b7fcc22b665614e8f169`. The gate file pins SHA-256 for its
Python encoder, Rust transforms, standalone Rust decoder, Cargo lock, and build
metadata. Validation must build and run that implementation from a detached
worktree; later documentation, branding, harness, or packaging changes may not
alter the candidate.

Development evidence is immutable and checksummed:

- fresh CLUE-LDS ratio census: JLS2 was the smallest of all eleven same-run
  codecs, 18.08% smaller than Brotli-11 aggregate;
- local standalone decode gate: 585.43 MB/s median, 398.40 MB/s minimum, 7/7
  rounds above 250 MB/s, 146.5 MiB peak RSS, exact output; and
- hosted Apple ARM64 reproduction: 689.96 MB/s median, 623.52 MB/s minimum,
  7/7 rounds above 250 MB/s, 120,012,800 bytes peak RSS, exact output.

These are development results, not unseen validation.

## Sealed score

| Item | Inclusive official IDs | Records | Current size/SHA-256 |
| --- | ---: | ---: | --- |
| `clue-validation-a` | 35,000,001–35,250,000 | 250,000 | unknown; unopened |
| `clue-validation-b` | 45,000,001–45,250,000 | 250,000 | unknown; unopened |

The monolithic publisher ZIP has been cached and verified, but neither range
has been parsed or materialized. The acquisition command must still refuse
without an explicit flag and the final readiness lock. Maximum authorized
acquisitions and scored attempts are both one. Failed or interrupted attempts
are retained.

## Complete competitor contract

The same-run standard matrix is fixed at store, LZ4-1, gzip-9, bzip2-9,
zstd-3, zstd-9, zstd-19, Brotli-11, LZMA-9, and 7-Zip-9. External releases are
pinned to LZ4 1.10.0, zstd 1.5.7, Brotli 1.2.0, and 7-Zip 26.02. The three
source builds are pinned by commit, and the official 7-Zip Linux asset is
pinned by SHA-256.

PBC-only is the frozen eligible log specialist at commit
`bac1f86d29624cb585bb4475235d22a28e60ffea`. Its pattern bytes count in the
archive, and pattern training counts in complete compression time. The score
workflow must also retain the dependency-repair patch, third-party download
digests, and successful official PBC unit and integration tests.

LogFold, LogPrism, LogLite, and DeLog remain visible but unavailable or
ineligible for exact reproduction. Their rows must say untested/unavailable;
their absence is not a JLS2 win. The audit must be rechecked immediately before
the final lock.

## Pass gates

JLS2 must satisfy all of the following on the first score:

1. at least 5% smaller than the strongest complete exact-byte eligible result
   on each of the two families and aggregate;
2. at least 100 MB/s aggregate and 90 MB/s every-repetition compression;
3. at least 250 MB/s aggregate and 225 MB/s every-repetition standalone native
   decompression;
4. no more than 512 MiB cold-process peak RSS in either direction;
5. exact output on every trial, deterministic frames, corruption rejection,
   complete accounting, and no segment larger than its equally framed direct
   fallback;
6. every required standard and PBC-only present, with no benchmark failure;
7. clean tracked source, frozen candidate hashes, standalone delivery, and
   cross-platform product evidence; and
8. a complete chart that preserves same-run versus separate-run comparability
   and includes unavailable specialist markers.

The locked publisher writes an immutable Markdown report, a complete-byte SVG
chart, the bound raw decision and inputs, and a checksum manifest. It runs for
both pass and no-pass decisions; failure never suppresses publication.

The first eligible score is final. No threshold, family, candidate parameter,
baseline setting, runner, evaluator, or chart rule may change after acquisition.

## Claim ceiling

A pass would establish a category-scoped public-validation result for two
previously unseen temporal ranges from one licensed cloud-event dataset. It
would not be private-holdout or independently reproduced evidence. It would not
support universal, market-leading, world-best, or state-of-the-art language,
especially while newer paper-reported specialists cannot be reproduced.
