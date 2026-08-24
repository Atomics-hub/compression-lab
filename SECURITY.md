# Security policy

## Supported versions

Until the first stable release, security fixes are provided only for the most
recent published 0.x release. Frame versions 1 through 3 remain decodeable,
but old package releases are not maintained indefinitely.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting flow under the repository
Security tab. Do not open a public issue for a decompression bomb, memory-safety
problem, path-handling flaw, crafted-frame crash, or integrity bypass.

Include the affected version, operating system and architecture, a minimal
reproducer or malformed frame when possible, and the impact you observed. We
will acknowledge a complete report within five business days and coordinate a
fix and disclosure timeline with the reporter.

## Security boundaries

Compression Lab validates frame structure, declared output length, per-segment
CRC32, and whole-file SHA-256. The public decoder defaults to a 2 GiB declared
output limit to prevent unbounded allocation from untrusted frames. Callers
may lower that limit and should do so when their application has a smaller
expected object size.

The current 0.x file API reads complete files into memory. Do not use it as an
archive extractor or assume that it sanitizes paths inside another container.
The format provides integrity detection, not encryption or authenticity.

Every pull request runs deterministic truncation, bit-mutation, plausible-frame,
and allocation-limit tests plus a 5,000-case mutational fuzz smoke. A scheduled
workflow expands that to 100,000 hostile frames against valid version 1, 2, and
3 seeds. CI also resolves and audits the local project's Python runtime
dependency graph with `pip-audit 2.10.1` and both Rust lockfiles with
`cargo-audit 0.22.2`. GitHub's extended CodeQL default setup scans Python and
Actions; Rust is covered by RustSec dependency auditing, `clippy -D warnings`,
cross-platform tests, and hostile-input fuzzing because CodeQL does not
currently analyze Rust. These checks reduce risk but are not a security proof.
