# Text/source long-range factorization decomposition screen

Status: frozen training-split protocol. No screen result existed when
`config/text-source-long-range-screen-v1.json` was written.

## Decision being purchased

Kanzi-max is already a compound `EXE+RLT+TEXT+UTF+DNA` transform followed by
the TPAQX context-mixing entropy coder. The rejected TS-P1/WK-P1 experiment
showed that a counted token dictionary materially improves a weak model but
does not approach TPAQX. Reimplementing another low-order predictor or word
dictionary would therefore ignore the strongest evidence.

The remaining inexpensive question is whether explicit long-range repetition
factoring adds information that TPAQX does not already encode. Recent work on
[approximate LZ77 text precompression](https://doi.org/10.4230/LIPIcs.SEA.2026.16)
reports that local-window standard compressors can miss far-apart repetition
and that a long-range prepass can assist a standard backend. Prior LZ77 work
specifically identifies [software repositories and versioned document
collections](https://arxiv.org/abs/1101.4065) as highly repetitive inputs.
[LZRR](https://arxiv.org/abs/1812.04261) also demonstrates that practical
multi-reference parsing can use fewer phrases than ordinary left-only LZ77,
although this screen remains strictly backward-decodable.

This is a decomposition screen, not an Axiom codec experiment. It uses Kanzi's
own exact LZP transform to ask whether the factorization signal survives a
strong backend. A passing result would authorize implementation of a separate,
bounded Axiom multi-reference implicit factorizer; it would not authorize any
compression claim.

## Frozen information boundary

Only the prior predictor-training split is screened:

| Track | Screened now | Reserved and not accessed by this screen |
| --- | --- | --- |
| Source-code bundles | CPython 3.14.6, TypeScript 6.0.3 | Rust 1.97.1, LLVM 22.1.8 |
| English Wikimedia wikitext | Wikibooks, Wikinews | Wikiversity |

The corpus manifest, immutable practical census, exact Kanzi binary, and
rejected predictor result are SHA-256-bound in the executable config. Public
validation and private holdout remain sealed and unaccessed.

## Comparable artifacts and ablations

The immutable practical-census `kanzi-max` bytes are the baseline. The runner
creates complete Kanzi archives for three custom pipelines using the identical
input bytes, 1 GiB maximum block, one job, and TPAQX:

1. `K1`: prepend LZP to the complete level-9 transform chain;
2. `K2`: LZP followed only by TEXT and UTF; and
3. `K3`: LZP alone, attributing generic factorization without text transforms.

Each custom item is compressed twice. Both archives must be byte-identical and
both decodes must exactly reproduce the source SHA-256. Every complete archive
byte, process time, and peak RSS is recorded. The prior baseline is not rerun
or silently replaced.

## Admission and rejection

A shared Axiom factorizer prototype is admitted only when one identical custom
variant satisfies all of these conditions on both tracks:

- at least 2% smaller aggregate complete bytes than `kanzi-max`;
- no screened item more than 0.5% larger;
- two byte-identical archives per item; and
- exact restoration for every run.

The 2% threshold funds a prototype; it is not the product gate. Any later Axiom
artifact must still be at least 5% smaller than the strongest complete baseline,
regress no item by more than 0.5%, count every byte, restore exactly, be
deterministic, and pass speed, memory, corruption, streaming, and portability
gates. If no one variant passes both tracks, the shared long-range direction is
rejected. A signal on only one track can motivate a separately frozen
track-specific successor but cannot pass this gate.

## Claim ceiling

These are training-split custom Kanzi diagnostics. They are not Axiom artifacts,
Axiom wins, validation results, private-holdout results, novel algorithms, or
state-of-the-art evidence.
