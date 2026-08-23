# Version 0.1 release record

## Engineering state

The repository contains the complete 0.1 alpha implementation: stable bytes
and file APIs, `clab` and `compression-lab` commands, versioned `.clab` frames,
legacy decoding, atomic no-clobber writes, allocation limits, a portable
Zstandard fallback, packaged Rust acceleration, reproducible benchmarks, and
cross-platform CI.

The automated gates cover Python 3.9 through 3.14; Linux, macOS, and Windows;
Rust debug and release tests; native wheel installation; malformed and hostile
frames; 5,000-case pull-request fuzzing; 100,000-case scheduled fuzzing; sdist
installation; five native platform wheels; Twine metadata; and SHA-256 release
manifests. The controlling workflow calls the same release workflow used by a
tag, so a private branch run can prove the full artifact set without publishing.

PyPI is the 0.1 distribution target. npm is deliberately deferred because the
project has no JavaScript or WebAssembly API; a shell wrapper would add a second
compatibility promise without making the compressor more useful.

## Release outcome

Version 0.1.0 was released on **2026-07-16**. The durable public record is:

1. The valid signed tag [`v0.1.0`](https://github.com/Atomics-hub/compression-lab/releases/tag/v0.1.0)
   points to commit `3b17b7b7978aa392dfaee2d053925c3565ebb58e`.
2. Release workflow run
   [`29509611019`](https://github.com/Atomics-hub/compression-lab/actions/runs/29509611019)
   built the source distribution and five platform wheels, verified the complete
   set, and published it to
   [PyPI](https://pypi.org/project/compression-lab/0.1.0/).
3. The GitHub release retains the same five wheels and source distribution plus
   `SHA256SUMS` and the controlling benchmark-evidence bundle.
4. The `pypi` environment requires owner review. The public repository has
   private vulnerability reporting enabled, and `main` protection requires the
   cross-platform Python, package, and native-wheel checks while refusing force
   pushes and deletion.

Those repository settings were rechecked on **2026-08-23**. They are current
operational state, not immutable benchmark evidence, and must be checked again
before a future release.

## Future release gates

Every later release still requires an owner-created signed tag and explicit
approval at the protected `pypi` environment. The workflow may build and verify
artifacts before that approval, but it cannot turn an ordinary branch run into
a public upload.

Do not replace these steps with a broad “best compression” claim. The frozen
release benchmark explicitly rejects that positioning; the permitted claims
are recorded in `docs/benchmarks/2026-07-16-release-candidate.md`.
