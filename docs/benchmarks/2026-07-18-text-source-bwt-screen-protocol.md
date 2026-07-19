# Text/source BWT decomposition screen

Status: frozen training-split protocol. No BWT screen result existed when
`config/text-source-bwt-screen-v1.json` was written.

## Decision being purchased

The structural demultiplex, low-order predictor, explicit LZP, and bounded
record-neighborhood experiments failed their frozen gates. None answers whether
reversible suffix-context clustering exposes information that Kanzi level 9's
local byte contexts and match predictor miss. This screen buys that one answer
without implementing a new codec.

Kanzi 2.5.3 level 9 uses `EXE+RLT+TEXT+UTF+DNA&TPAQX`; it does not use BWT.
The pinned binary already contains a reversible BWT with primary indexes, the
SRT and ZRLT post-transforms, and both TPAQX and FPAQ entropy coders. The four
predeclared chains distinguish direct BWT-to-TPAQX prediction, conventional
rank/run shaping before TPAQX, the official level-6 BWT control, and raw BWT
without TEXT/UTF. These are custom Kanzi diagnostics, not Axiom artifacts.

## Frozen information boundary

Only the already-consumed training subset is screened:

| Track | Screened now | Reserved and not accessed by this screen |
| --- | --- | --- |
| Source-code bundles | CPython 3.14.6, TypeScript 6.0.3 | Rust 1.97.1, LLVM 22.1.8 |
| English Wikimedia wikitext | Wikibooks, Wikinews | Wikiversity |

The runner verifies the roster from the manifest but opens, stats, and hashes
only the four screened bundle paths. Reserved evaluation paths need not exist.
Public validation and private holdout remain sealed and unaccessed.

The corpus manifest, practical census, pinned Kanzi binary, and the four prior
negative results are SHA-256-bound before execution. The baseline complete
archives are reused and never rerun or replaced.

## Exact variants and commands

The decision-bearing variants, in fixed tie order, are:

1. `TEXT+UTF+BWT&TPAQX`;
2. `TEXT+UTF+BWT+SRT+ZRLT&TPAQX`;
3. `TEXT+UTF+BWT+SRT+ZRLT&FPAQ`, the explicit level-6 control; and
4. `BWT+SRT+ZRLT&TPAQX`.

Compression uses the explicit transform and entropy names, a 1 GiB maximum
block, and one job. It never supplies `--level`, which would override the
explicit chain, or `--skip`/`--checksum`, which would change framing relative
to the immutable baseline:

```text
kanzi --compress --input=SOURCE --output=ARTIFACT --force \
  --transform=TRANSFORM --entropy=ENTROPY --block=1g --jobs=1 --verbose=0
kanzi --decompress --input=ARTIFACT --output=RESTORED --force \
  --jobs=1 --verbose=0
```

Each item/variant is measured twice after zero warmups, in a schedule shuffled
with seed `20260718`. Compression and decompression each have a 7,200-second
limit. The four variants by four screened items by two repetitions produce
exactly 32 retained trial receipts. Runs are sequential and require a clean
tracked commit.

## Complete-byte accounting and exactness

The complete artifact is the `.knz` file itself. Its filesystem size counts the
Kanzi stream header, transform and entropy identities, per-block skip flags,
BWT mode and primary indexes, entropy payload, and all end framing. There is no
wrapper, external dictionary, model, or side asset. One complete artifact is
counted per item in an aggregate; the second identical artifact proves
determinism and is not added again.

Every measured decode must restore the manifest-bound size and SHA-256. Both
complete artifacts for an item/variant must have one identical byte size and one
identical SHA-256. Wall time, CPU time, and peak RSS are retained for both
directions. Complete encode and decode peak RSS must not exceed 4 GiB.

## Frozen integer gates

Percentages are explanatory only. Decisions use the following integer byte
comparisons and therefore cannot change through rounding:

| Track/item | Kanzi-max bytes | Signal maximum (1%) | Strong maximum (2%) | Per-item +0.5% guard |
| --- | ---: | ---: | ---: | ---: |
| Source aggregate | 6,221,486 | 6,159,271 | 6,097,056 | — |
| CPython | 4,511,714 | — | — | 4,534,272 |
| TypeScript | 1,709,772 | — | — | 1,718,320 |
| Wikimedia aggregate | 24,156,788 | 23,915,220 | 23,673,652 | — |
| Wikibooks | 12,622,786 | — | — | 12,685,899 |
| Wikinews | 11,534,002 | — | — | 11,591,672 |

Tracks are evaluated independently. A variant signals only when it is complete,
exact, deterministic, within both item guards and the 4 GiB limit, and no larger
than the track's 1% maximum. At least 2% under the identical conditions is a
strong signal. When several variants pass, the smallest aggregate wins; an
exact byte tie uses the fixed variant order above.

- No signal: reject raw BWT for that track and do not build token-BWT.
- Signal below 2%: retain diagnostic context and authorize only a cheap exact
  token/production-BWT ceiling.
- Strong signal: admit a separately frozen token-BWT representation prototype
  for that track.

A ratio signal that exceeds 4 GiB remains visible as resource-rejected evidence
and admits nothing. Shared passing variants are reported but are not required
for category specialists. A later Axiom artifact must still be at least 5%
smaller than the strongest complete baseline, count every decoder byte, restore
exactly, be deterministic, and pass corruption, streaming, speed, portability,
packaging, and independent-reproduction gates.

## Claim ceiling

This is training-split custom Kanzi pipeline decomposition only. Complete
archives are exact competitor diagnostics, not Axiom artifacts, Axiom wins,
validation results, private-holdout results, independent reproduction,
novel-algorithm results, or state-of-the-art evidence. `axiom_wins` is always
zero regardless of the screen decision.
