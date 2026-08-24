# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Git-history-bound evidence tests now degrade to explanatory skips on
  shallow or archive checkouts that do not retain the referenced commits
  instead of erroring, with an offline audit script for
  the public-checkout verification gate.
- Reproducible alternating JLS2 decode-kernel A/B evidence with raw samples,
  exact fixture and source hashes, a complete-product gate, and a public chart.
- Exact `--manifest` benchmark selection, results-schema-v5 corpus identity
  receipts, and release gates that reject missing or inconsistent manifest and
  runner provenance.
- Stable Python byte and file APIs for version-3 compression and version-1 to
  version-3 decompression.
- `clab` and `compression-lab` commands with `compress`, `decompress`, and
  `info` operations.
- Atomic no-clobber file writes and a configurable decompression output limit.
- Platform-wheel build hooks for the Rust transform library and a portable
  `python-zstandard` backend.
- Cross-platform Python/Rust CI and gated wheel/sdist release automation.
- Public format, security, contribution, and release documentation.
- A frozen eight-codec release benchmark and machine-verifiable evidence gate.
- Pull-request and scheduled hostile-frame mutation fuzzing.
- Dependency provenance, licensing notices, and automated update monitoring.
- An experimental JLS2 JSON-log codec with record-aligned streaming,
  integrity-checked nested frames, exact direct-Zstandard fallback, metadata
  inspection, safe file APIs, and `json-compress`, `json-decompress`, and
  `json-info` commands.
- Bounded two-segment compression and decompression pipelines, concurrent
  JSON-column stream compression, a single-segment decode fast path, and a
  checksummed hosted complete-product benchmark workflow.

### Changed

- Production CI now audits the resolved Python runtime graph and both Rust
  dependency graphs, while active CI, fuzz, and release actions are pinned to
  immutable commits.
- Python wheels, source builds, standalone decoders, CI, and native tests now
  share one repository-pinned Rust toolchain.
- JLS2 decode now bulk-copies JSON literal spans and lets the outer frame own
  restored-byte authentication, preserving exact encoded bytes while improving
  the development byte-API paired median by 21.66%.
- The project README now leads with a concise category-scoped standards table
  and links detailed caveats to immutable evidence bundles.

### Security

- Incompatible or stale native-library overrides now degrade to the documented
  portable backend instead of breaking import or availability checks.
- Legacy gzip, LZ4, and command-line Zstandard decoders now cap expansion at
  the frame's declared output size instead of checking only after the payload
  has been fully expanded.
- Tag-triggered releases now fail before building or publishing when the tag
  does not exactly match the Python and Rust package versions.
- The public decoder rejects frames whose declared output exceeds its 2 GiB
  default limit before allocating the output buffer.
- Portable backend and legacy gzip corruption errors are normalized at the
  public API boundary instead of leaking backend-specific exceptions.
- Native C-ABI entry points reject null pointers even for zero-length buffers.

## [0.1.0] - 2026-07-16

Initial public alpha release. The signed `v0.1.0` tag was published to PyPI and
GitHub with five platform wheels, one source distribution, a SHA-256 manifest,
and the controlling benchmark-evidence bundle.

[Unreleased]: https://github.com/Atomics-hub/compression-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Atomics-hub/compression-lab/releases/tag/v0.1.0
