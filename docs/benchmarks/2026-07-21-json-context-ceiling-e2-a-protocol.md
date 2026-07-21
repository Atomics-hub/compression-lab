# E2-A JSON context-ceiling memory sweep

Status: frozen before measurement. Evidence class: development-only diagnostic.

E1 found 21.32% complete-byte JSON/log headroom between Kanzi-max and ZPAQ
level 5. E2-A asks the narrower question that must be answered before building a
new context mixer: does a meaningful part of that advantage survive Axiom's
460 MiB development memory target?

## Boundary

Only the three licensed CLUE development files named in
`config/json-context-ceiling-e2-a-v1.json` may be opened. Both earlier
public-validation families have been consumed. No fresh public-validation set
is currently frozen, and the private holdout remains sealed. This experiment
therefore cannot create a new candidate, validation, product, world-best, or
state-of-the-art claim.

The workflow reuses the exact E1 GitHub tools and training artifacts from run
29846879040. It verifies the live GitHub artifact roster against the pinned
recovery receipt before downloading either artifact, then verifies the exact
manifest, item roster, item bytes, and ZPAQ executable before compression.

## Matrix

The only independent variable is ZPAQ level-5 maximum block size:

| Method | Maximum block | Purpose |
|---|---:|---|
| `54` | 16 MiB | likely bounded-memory point |
| `55` | 32 MiB | target boundary point |
| `56` | 64 MiB | intermediate attribution point |
| `57` | 128 MiB | one-block curve point for 62-71 MiB inputs |
| `510` | 1 GiB | explicit cross-run E1 archive-byte anchor |

ZPAQ 7.15 documents numeric method `LB` as compression level `L` and maximum
block size `2^B` MiB. Its source expands the level-5 model from the actual
block size. Since every input is below 128 MiB, `57` and `510` should occupy
the same one-block regime. We still rerun `510` because matching every pinned
E1 archive digest is the fail-closed proof that E1 ratio references transport
to this run.

Every stage-one method/item pair runs once, sequentially with one ZPAQ thread.
The smallest complete method satisfying both 460 MiB compression and decode
RSS limits is selected deterministically. That method and `510` (if different)
receive one confirmation repetition. A confirmation mismatch fails the run;
the runner may not substitute the next method.

## Accounting and decision

Every trial uses a fresh `.zpaq` archive, fixed input name and mtime,
`-noattributes`, a fixed cutoff timestamp, and exact byte-for-byte decode.
Physical archive bytes and all AXE2O framing bytes count. `wait4` records the
direct process peak RSS for both phases. Timing is contextual only.
Level 5 is adaptive and journaling block packing also changes, so this is not a
pure context-window ablation; it measures the frozen ZPAQ-class lane as a whole.

The fixed E1 complete Kanzi reference is 1,712,149 bytes. For candidate bytes
`C`, gain is `floor((1712149 - C) * 10000 / 1712149)` basis points.

- Advance at 1,540,934 bytes or smaller (at least 1000 bp), after confirmation.
- Permit one separately frozen refinement from 1,540,935 through 1,592,298.
- Kill at 1,592,299 bytes or larger (below 700 bp), or when no method meets
  both memory limits.

A winner at or above 458,227,712 bytes peak RSS (95% of the development cap)
is marked fragile and must be reconfirmed in a later frozen stage.

An advance authorizes component attribution and a bounded native prototype. It
does not authorize an Axiom performance claim. Any later unseen score requires
a newly acquired, lineage-distinct, licensed, frozen corpus.
A kill applies only to this ZPAQ-class level-5 lane on these consumed items; it
does not disprove all bounded-memory context modeling.
