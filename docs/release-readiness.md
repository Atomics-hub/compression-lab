# Version 0.1 release readiness

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

## Owner-only launch gates

These actions intentionally remain outside unattended automation:

1. Review and merge pull request 1 while the repository is still private.
2. Create a GitHub `pypi` environment with required-reviewer protection.
3. Configure PyPI trusted publishing for owner `Atomics-hub`, repository
   `compression-lab`, workflow `release.yml`, environment `pypi`. The project
   name was absent from PyPI when checked on 2026-07-15, but that is not a name
   reservation.
4. Add a `main` branch ruleset requiring the CI checks. No branch protection or
   repository ruleset was configured during the private readiness audit.
5. Set the repository description and topics, decide whether to disable the
   currently enabled wiki and projects, then make the repository public.
6. Enable private vulnerability reporting once GitHub exposes it for the public
   repository.
7. Create the signed `v0.1.0` tag. The tag builds and verifies the complete
   artifact set, then pauses at the protected `pypi` environment.
8. Review the SHA-256 manifest and approve PyPI publication. Create the GitHub
   release from the same tag and attach the verified artifacts, checksums, and
   controlling benchmark evidence.

Do not replace these steps with a broad “best compression” claim. The frozen
release benchmark explicitly rejects that positioning; the permitted claims
are recorded in `docs/benchmarks/2026-07-16-release-candidate.md`.
