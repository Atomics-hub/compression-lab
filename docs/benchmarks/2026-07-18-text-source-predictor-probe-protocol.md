# TS-P1 / WK-P1 predictor entropy-ceiling protocol

Status: frozen development protocol; no predictor-probe result existed when
`config/text-source-predictor-probe-v1.json` was written.

## Why this probe exists

The 33-trial TS-H1/TS-H2 structural experiment was exact and deterministic but
both hypotheses missed their predeclared gates. The checked successor router
therefore selected a mixed byte/token predictor with a counted static
dictionary for source bundles (`TS-P1`) and a markup-aware equivalent for
Wikimedia (`WK-P1`). Building a production range coder, decoder, streaming
format, and native implementation before proving entropy headroom would be an
expensive way to rediscover another sub-percent signal.

This experiment is a deliberately cheap ceiling test. It estimates ideal code
length under deterministic adaptive probability models. It cannot produce a
decodable archive and therefore cannot establish an Axiom win. Its only power
is to reject weak predictor families or admit one family to a later exact-codec
experiment.

## Frozen data separation

Dictionary fitting and evaluation use different development items:

| Track | Dictionary training | Evaluation |
| --- | --- | --- |
| Source-code bundles | CPython 3.14.6, TypeScript 6.0.3 | Rust 1.97.1, LLVM 22.1.8 |
| English Wikimedia wikitext | English Wikibooks and Wikinews 2026-07-01 | English Wikiversity 2026-07-01 |

The corpus manifest, practical baseline, structural successor decision, and
successor routing configuration are SHA-256-bound in the machine-readable
protocol. Public validation and private holdout remain sealed and unaccessed.

## Sampling and accounting

Training uses at most 32 evenly spaced 1 MiB chunks per training item.
Evaluation uses 12 evenly spaced 1 MiB chunks per evaluation item. Offsets are
computed from item length alone by the formula in the config; there is no
content-based selection. Predictor state resets at every chunk boundary so a
jump between nonadjacent bytes cannot create false context.

The learned model is serialized canonically as `AXPD1`, a track byte, 256 raw
byte prior weights, an entry count, and ranking-order length-prefixed token
bytes with one prior weight per token. A weight is one plus the integer square
root of its training-sample occurrence count; an absent raw byte receives one.
This compact prior is deterministic and every decoder-needed byte is charged
once to the aggregate projection. The complete model is also charged to every
per-item projection, which is intentionally conservative. Each item
additionally receives a 65,536-byte projected startup allowance. Context counts
still start from the fixed half-count and adapt only from evaluated bytes.

The conservative projected size uses the mean sampled ideal bits per byte plus
two population-standard-error units, multiplied by the complete source size,
then adds the declared startup and dictionary accounting. This remains an
estimate, not complete archive bytes.

## Attributable ablations

The same sampled bytes are evaluated under:

1. `P0`: adaptive raw-byte unigram;
2. `P1`: adaptive raw-byte mixture of global and previous-symbol-class models;
3. `P2`: the identical P1 probability family after reversible replacement of
   training-dictionary tokens with token symbols. WK-P1 additionally gives
   fixed markup tokens longest-match precedence.

P0 to P1 attributes class context. P1 to P2 attributes tokenization and the
counted dictionary. Unsupported syntax and all unmatched bytes remain raw, so
the proposed eventual representation has an exact escape path.

## Admission and rejection

P2 may advance to a real entropy-coded specialist only if all of the following
hold on the untouched development-evaluation items:

- conservative aggregate projection is at least 10% smaller than the exact
  Kanzi-max bytes for the same evaluation items;
- every evaluation item is at least 5% smaller after charging the complete
  dictionary and startup allowance;
- P2 improves at least 3% over P1, proving the counted dictionary contributes
  material signal; and
- the serialized dictionary is at most 524,288 bytes.

Failing any condition rejects this predictor family. Passing only authorizes a
later exact coder. That later artifact must still beat the strongest complete
baseline by at least 5%, regress no item by more than 0.5%, restore exact bytes,
produce two byte-identical measured artifacts, count every decoder byte, and
pass speed, memory, integrity, streaming, and portability gates before any
category claim.

## Claim ceiling

All output is sampled development entropy evidence. An estimated byte count is
not an archive, codec result, validation score, market lead, world-best result,
or state-of-the-art claim.
