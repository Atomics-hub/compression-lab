# Official PBC competitor reproduction protocol

## Status

This protocol was frozen before the first comparative score was produced. The
successful result is recorded in
`2026-07-16-pbc-competitor-development-decision.md`. It is development-corpus
evidence only.

PBC is directly relevant because its official scope is high-ratio lossless
compression for machine-generated data. Its source is Apache-2.0 licensed and
its SIGMOD artifact has independent reproducibility badges.

## Pinned artifact

- repository: <https://github.com/antgroup/pbc>
- commit: `bac1f86d29624cb585bb4475235d22a28e60ffea`
- license: Apache-2.0
- license SHA-256:
  `bacacee63139034e9acba4de0c513eeb93cc6277ae52054a30eebf4be644e7ed`
- environment: Ubuntu 22.04, as recommended by the official README

The benchmark clones and builds this pinned external repository. PBC source,
dependencies, and binaries are not vendored into Compression Lab.

### Build dependency repair

The first frozen hosted attempt failed before producing any score because two
historical dependency URLs no longer reproduce their pinned archives:

- Boost retired the JFrog download URL after December 2024. The workflow uses
  Boost's official archive host for the same 1.67.0 tarball and preserves PBC's
  original MD5.
- Colm's repository was renamed to `colm-suite`, and GitHub regenerated the
  tag archive. The workflow pins tag `0.14.7` to immutable commit
  `e88bda068d4a25f2afa7f48821e0f539405c8c6a` and verifies archive SHA-256
  `6f11b349722797165f5b71bac5dd71a2ade3cff1c45a9c0ae5522f0f71902ee1`.

The workflow records the exact build-only patch and dependency digests, builds
the artifact, then restores the PBC checkout and requires clean tracked source
before official tests and measurement. No PBC compression, training, CLI, or
test code is modified.

### Named-output compatibility

The release build's unit suite passes, but the first official integration
attempt exposed an upstream CLI defect: named compression and decompression
outputs are opened with `O_CREAT` without the required mode argument. Fresh
output paths can therefore fail nondeterministically.

The workflow and benchmark pre-create every named output with mode `0600`.
They then run the unmodified PBC CLI and official integration script. The
integration script's original byte-for-byte `cmp` checks must still pass. The
complete upstream `testresult` tree is retained in the evidence artifact.

## Official settings

The reproduction tests all four methods exposed by the official CLI:

- `pbc_only`
- `pbc_fse`
- `pbc_fsst`
- `pbc_zstd`

Pattern training uses the settings in PBC's official integration test:

- pattern size: 100
- training records: 2,000
- training threads: 64
- input type: newline-delimited records

The workflow builds PBC in release mode and runs its official unit and
integration tests before measuring the LogTrie development corpus.

## Exact-file contract

Each method and family must:

1. receive the same source path whose size and SHA-256 are fixed by the
   LogTrie manifest;
2. accept every record under PBC's documented 1 MiB record limit;
3. reconstruct the exact source size and SHA-256;
4. use at least two pattern-training repetitions and five online compression
   and decompression repetitions;
5. report the full pattern-file size and compressed-payload size;
6. count `pattern bytes + payload bytes` as the complete archive;
7. report pattern training, online compression, complete compression, and
   decompression wall times separately;
8. retain a pinned, clean tracked PBC source tree.

The complete compression rate includes the median pattern-training time plus
the median online file-compression time. Online compression is also reported
because PBC explicitly separates offline pattern extraction from per-record
compression.

PBC's hosted rates characterize this Ubuntu runner. They are not treated as a
direct speed comparison against JLS2 rates measured on a different runner.

## Ranking and claims

The primary PBC score is the smallest aggregate complete-archive size achieved
by one fixed official method across all five families. This is compared with
the accepted JLS2 frame bytes and zstd-9 bytes for the identical inputs.

A best-method-per-family oracle is reported only as diagnostic context. It is
not eligible for the primary comparison because it selects a codec after
observing each family.

Passing this gate means the PBC artifact was reproduced with complete,
byte-exact accounting. It does not itself mean Compression Lab beat PBC, nor
does it authorize a world-best or state-of-the-art claim.
