# Text/source record-neighborhood representation screen

Status: frozen training-split protocol. No record-neighborhood screen result
existed when `config/text-source-record-neighborhood-screen-v1.json` was
written.

## Decision being purchased

The previous exact structural demultiplexing experiment tied Kanzi-max, and the
subsequent explicit LZP-before-TPAQX decomposition screen lost on both tracks.
Those results reject another small token model or another equivalent left-only
factorization pass. They do not answer whether semantically related records are
too far apart for the strongest backend to exploit.

Q1 tests that missing piece. It parses the existing exact record containers,
front-codes record metadata, derives at most 64 evenly sampled 48-byte window
hashes per record, removes track-common hashes, and applies four fixed-seed
minhash projections inside source-extension or Wikimedia-namespace classes.
The resulting canonical order is stored as a delta-zigzag permutation and all
payload, metadata, permutation, outer-frame, and backend bytes are charged.
The decoder recomputes the order, rejects alternate encodings, restores the
original container byte-for-byte, and checks its SHA-256.

This design is informed by work on [relative Lempel-Ziv compression for related
collections](https://arxiv.org/abs/1106.2587) and [repetitive software and
document collections](https://arxiv.org/abs/1101.4065). The experiment is an
Axiom representation screen, not a category result.

## Frozen information boundary

Only four training items are accessed:

| Track | Screened now | Reserved and not accessed by this screen |
| --- | --- | --- |
| Source-code bundles | CPython 3.14.6, TypeScript 6.0.3 | Rust 1.97.1, LLVM 22.1.8 |
| English Wikimedia wikitext | Wikibooks, Wikinews | Wikiversity |

Reserved paths need not exist for the screen verifier to succeed. Public
validation and private holdout remain sealed. The corpus, practical-census
baseline, prior structural evidence, rejected long-range result, Kanzi binary,
and exact Q1 transform script are SHA-256-bound in the config.

## Complete artifacts and attribution controls

Each candidate is a complete Axiom experimental frame containing an identity,
original size and SHA-256, backend-payload size and SHA-256, and the complete
Kanzi level-9 payload of the AXRN1 transform. Compression and decompression run
as separate measured processes. The recorded cost is the sum of transform,
backend, frame, unframe, backend-decode, and inverse-transform process time; RSS
is the largest observed process peak. The exact Kanzi-max census bytes are the
direct baseline. The prior complete TS-H1 demux bytes are a second attribution
control, proving whether similarity ordering adds value beyond metadata/payload
separation alone.

Every item is measured twice in a frozen randomized order. Both complete frames
must be byte-identical and both decodes must exactly reproduce the original
SHA-256.

## Admission and rejection

The one identical Q1 variant is admitted only if both tracks independently:

- are at least 2% smaller in aggregate than complete `kanzi-max`;
- are at least 1% smaller in aggregate than the complete TS-H1 control;
- regress no screened item by more than 0.5% versus `kanzi-max`;
- produce two byte-identical complete frames per item; and
- restore every input exactly.

Passing funds a separately frozen Axiom specialist prototype. It does not pass
the final product gate. A final specialist must still be at least 5% smaller
than the strongest complete baseline on unseen data, count every byte, regress
no item by more than 0.5%, restore exactly, be deterministic, and pass speed,
memory, corruption, streaming, portability, packaging, and independent
reproduction gates.

If Q1 fails either track, this exact bounded-minhash ordering is rejected as the
shared successor. A different signature, class, or ordering scheme requires a
new frozen protocol; it may not be tuned against the reserved evaluation set.

## Claim ceiling

This is training-split representation evidence only. It is not validation,
private-holdout, independent-reproduction, category-win, market-leading,
world-best, or state-of-the-art evidence.
