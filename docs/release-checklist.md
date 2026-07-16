# Public release checklist

## Code and compatibility

- [x] Full Python matrix passes on Linux, macOS, and Windows.
- [x] Rust formatting, debug tests, and release tests pass.
- [x] Version-1, version-2, and version-3 decode fixtures pass.
- [x] Malformed, truncated, oversized, checksum, and allocation-limit tests pass.
- [x] Wheel-installed native library is exercised on every release platform.
- [x] Source distribution builds in a clean environment with Rust stable.

## Evidence and claims

- [x] Public corpus licenses, upstream commits, and SHA-256 digests verify.
- [x] Controlling benchmark is rerun from a clean candidate commit on a hosted host.
- [x] gzip-9, zstd-3, zstd-9, Brotli-6/11, LZMA-9, and 7-Zip-9 are reported.
- [x] README claims match the controlling artifact and include corpus/hardware scope.
- [x] No private holdout bytes, paths, or results enter the repository.

## Distribution

- [x] `python -m build` and `twine check dist/*` pass.
- [x] Clean wheel installs pass native compression and decompression smoke tests.
- [x] Version agrees in Python, PyPI metadata, Cargo, and changelog.
- [ ] PyPI project name and trusted publisher are configured by the owner.
- [ ] The `pypi` GitHub environment requires owner approval.
- [ ] SHA-256 sums are attached to the GitHub release.

## Public launch actions requiring owner approval

- [ ] Change repository visibility from private to public.
- [ ] Confirm branch protection and private vulnerability reporting.
- [ ] Create signed tag `v0.1.0` and approve the GitHub release.
- [ ] Approve the protected PyPI publishing environment.

An npm package is intentionally not a 0.1.0 requirement. There is no supported
JavaScript or WebAssembly API yet; a wrapper that merely shells out to Python
would create a second distribution promise without improving usability.
