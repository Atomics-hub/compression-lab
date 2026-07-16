# Public release checklist

## Code and compatibility

- [ ] Full Python matrix passes on Linux, macOS, and Windows.
- [ ] Rust formatting, debug tests, and release tests pass.
- [ ] Version-1, version-2, and version-3 decode fixtures pass.
- [ ] Malformed, truncated, oversized, checksum, and allocation-limit tests pass.
- [ ] Wheel-installed native library is exercised on every release platform.
- [ ] Source distribution builds in a clean environment with Rust stable.

## Evidence and claims

- [ ] Public corpus licenses, upstream commits, and SHA-256 digests verify.
- [ ] Controlling benchmark is rerun from the release commit on an isolated host.
- [ ] gzip-9, zstd-3, zstd-9, Brotli-6/11, LZMA-9, and 7-Zip-9 are reported.
- [ ] README claims match the controlling artifact and include corpus/hardware scope.
- [ ] No private holdout bytes, paths, or results enter the repository.

## Distribution

- [ ] `python -m build` and `twine check dist/*` pass.
- [ ] Clean wheel installs pass `compress`, `decompress`, and `info` smoke tests.
- [ ] Version agrees in Python, PyPI metadata, Cargo, changelog, and tag.
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
