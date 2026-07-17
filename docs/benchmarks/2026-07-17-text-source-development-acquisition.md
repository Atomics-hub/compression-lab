# Text and source development acquisition

## Result

The seven declared development sources were acquired and converted under the
pre-acquisition protocol at commit
`b54283c5b80bfd98adebb1bb5766e15d3d1deda4`. The independent verifier passed
all 730,760,746 derived bytes and wrote
`runs/text-source-development-acquisition-v1.json`. Public validation was not
listed, downloaded, checksummed, parsed, or otherwise accessed.

This is development-corpus evidence, not compression evidence. No codec has
been run on these bytes, no standard has been tested, and neither category has
a ratio, speed, memory, validation, holdout, or state-of-the-art result.

| Development family | Format | Archive bytes | Derived bytes | Retained records | Selection note |
| --- | --- | ---: | ---: | ---: | --- |
| CPython 3.14.6 | `source-bundle-v1` | 23,921,184 | 44,506,231 | 2,032 files | complete selected set |
| TypeScript 6.0.3 | `source-bundle-v1` | 33,864,358 | 25,693,307 | 819 files | commit-pinned; complete selected set |
| Rust 1.97.1 | `source-bundle-v1` | 242,787,896 | 190,921,859 | 16,445 files | complete selected set |
| LLVM 22.1.8 | `source-bundle-v1` | 167,061,596 | 268,328,176 | 20,660 of 27,356 files | longest whole-file prefix below 256 MiB |
| English Wikibooks 2026-07-01 | `wikimedia-revision-text-v1` | 207,098,222 | 67,107,953 | 9,813 revisions | longest whole-page prefix below 64 MiB |
| English Wikinews 2026-07-01 | `wikimedia-revision-text-v1` | 54,157,210 | 67,105,968 | 18,698 revisions | longest whole-page prefix below 64 MiB |
| English Wikiversity 2026-07-01 | `wikimedia-revision-text-v1` | 119,592,609 | 67,097,252 | 12,904 revisions | longest whole-page prefix below 64 MiB |

The receipt freezes every archive SHA-256, derived SHA-256, item-manifest
SHA-256, terminal ordered-manifest SHA-256, byte count, record count, publisher
checksum source, tool digest, and the exact protocol/rule commit. The protocol
is synchronized with the derived identities; all seven validation entries
remain `sealed_unacquired` with null observed digests and sizes.

## Interrupted attempts

Four non-scoring attempts were retained in the receipt before the successful
fifth construction:

1. Rust exposed a case-only collision inside an excluded rustfmt fixture.
2. Rust exposed a link inside excluded vendored LLVM LLDB tests.
3. The run was manually interrupted after compressed XZ seeking was diagnosed
   as effectively quadratic; the builder was replaced with one-pass opaque
   spooling.
4. LLVM exposed three Python symlink aliases whose regular target modules were
   already selected; the aliases were audited and explicitly excluded rather
   than dereferenced or double-counted.

Every stopped attempt removed its staging directory and promoted no output.
Cached archives were rechecked against their frozen publisher sizes and digests
on every resume.

## Comparison status

| Track | Standards tested on this corpus | Current result | Claim ceiling |
| --- | --- | --- | --- |
| Multi-language source bundles | none | acquisition verified; baseline census not started | development corpus only |
| English Wikimedia wikitext | none | acquisition verified; baseline census not started | development corpus only |

The next gate is the complete practical baseline census declared in
`config/text-source-gates-v1.json`. Missing or unavailable baselines remain
visible and cannot be counted as wins. Representation work begins only after
the census identifies each family leader and the ratio/speed frontier.
