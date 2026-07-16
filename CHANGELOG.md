# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

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

### Security

- The public decoder rejects frames whose declared output exceeds its 2 GiB
  default limit before allocating the output buffer.
- Portable backend and legacy gzip corruption errors are normalized at the
  public API boundary instead of leaking backend-specific exceptions.
- Native C-ABI entry points reject null pointers even for zero-length buffers.

## [0.1.0] - Unreleased

Initial public release candidate. The date will be set only when the release is
approved and published.

[Unreleased]: https://github.com/Atomics-hub/compression-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Atomics-hub/compression-lab/releases/tag/v0.1.0
