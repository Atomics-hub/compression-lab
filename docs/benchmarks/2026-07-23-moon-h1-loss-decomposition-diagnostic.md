# H1 loss-decomposition diagnostic — design and counted-run procedure

- Evidence stage: `development_only_prescreen`
- Claim ceiling: development-only diagnostic instrument. It is not an exact
  codec result, candidate score, unseen-validation number, or SOTA evidence. It
  measures *where the H1 floor arm spends its coding loss*, nothing more.
- Scope: moon-code only. No frozen-surface (`s0`) edits, no S0 behavioral
  change, and no change to any existing arm encode/decode path that could alter
  a tape.

## What it is

`clab-moon-kernel diagnose-h1 --item-index N --input PATH --report-out PATH
[--sse-bucket-bits 17|18] [--top-regions N] [--force]` emits a deterministic
JSON report (`schema: clab-moon-h1-loss-decomposition-v1`) that buckets the H1
arm's exact fixed-point Q24 coding loss — the same `modeled_loss_q24` the frozen
`Ledger` tracks — along the dimensions the ratio sprint asked for.

The measurement runs `moon::h1::encode_h1_item_traced`, a **read-only parallel
encode** that reuses every tape-affecting primitive of the canonical arm
(`resolve`, `predict_byte_bit`, `update_byte_bit`, `advance_byte`, `event_id`,
and the same `LossTable` / `observed_probability` arithmetic). Its only
additions are (1) capturing the per-bit Q24 loss the canonical path already
computes and discards, and (2) *reading* — never mutating — the resolved
context cells' confidence for the context-miss proxy. The existing
`encode_byte` / `encode_continuation_bit` / `encode_h1_item_with_bits` functions
are untouched.

## Byte-identity guarantee

The observer must be transparent. Two independent proofs:

1. **Unit test** `traced_observer_reproduces_the_arm_tape_and_ledger_byte_for_byte`
   (in `native/src/moon/h1.rs`) asserts, across every H1 regime snippet, that
   `encode_h1_item_traced` yields the exact same tape bytes and the exact same
   `Ledger` as `encode_h1_item`. `traced_losses_close_exactly_against_the_ledger`
   asserts the summed per-bit Q24 losses and event counts equal the ledger with
   no rounding slack.
2. **Runtime fail-closed guard.** `decompose_h1` re-runs the canonical
   `encode_h1_item_with_bits` on the same input and refuses
   (`DiagnoseError::ObserverDivergedFromArm`) if the tape or ledger differs by a
   single byte, and again if the buckets do not sum to `modeled_loss_q24`.

Field validation (synthetic 4 MiB slices, off-ledger): the report's
`tape_sha256` and full `ledger` match an independent `clab-moon-kernel encode
--arm h1-floor` of the same input exactly.

## Bucketing dimensions

**Primary partition (every source byte gets exactly one class; the eight
modeled bit-losses per byte are attributed to it; the class losses plus the
framing continuation loss sum to `modeled_loss_q24`):**

- `structural` — JSON punctuation and string delimiters `{ } [ ] , : "`.
- `field_name` — bytes inside an object key string.
- `string_value` — bytes inside a string value.
- `number_value` — numeric literal bytes.
- `literal_value` — `true` / `false` / `null` bytes.
- `whitespace` — space, tab, CR, and the newline record boundary.
- `unclassified` — bytes the classifier could not place (the coverage gap).

The classifier is a small deterministic streaming state machine over NDJSON. It
does **not** fully parse JSON; it decides key-vs-value from object/array context
and a key/value-position flag, and **resets its state at every newline** (the
NDJSON record boundary) so a malformed line cannot desync later lines. Coverage
is reported as `classifier.coverage_ppm` (fraction of bytes not `unclassified`).

**Framing vs modeled.** Every byte is preceded by one continuation(`true`)
framing bit and the stream ends with one continuation(`false`) bit; those framing
losses are pooled into `framing_continuation_loss_q24` (with the terminal bit
broken out). `record_boundary_loss_q24` is the cost of the `\n` bytes plus their
framing bits.

**Value-subclass overlays (may overlap each other and the primary classes;
attribute the byte's eight modeled bits):**

- `digits` — ASCII digit bytes.
- `timestamp_span` — bytes inside an ISO-8601 `YYYY-MM-DDThh:mm:ss` span (a space
  in place of `T` accepted; optional `.d+` fraction and `Z`/`±hh:mm` zone).
- `hex_id_run` — bytes inside a maximal hex run ≥ 16, or a maximal alphanumeric
  run ≥ 20 containing at least one digit and one letter.

**Repeated-string candidacy overlay.** `repeat_candidate` marks bytes inside a
match of length ≥ 8 against the most recent prior occurrence of the current
8-gram within a 65 536-byte window (byte-verified to exclude hash collisions,
greedily extended). It is an OBSERVER-only proxy for how many expensive bytes lie
inside long repeats a copy/match model could capture — not an exhaustive matcher.

**Context-miss proxy.** A modeled bit is flagged when the *best-supported* of its
eight hashed contexts has confidence (observed count) below
`H1_LOW_CONFIDENCE_THRESHOLD = 4` at prediction — i.e. the bit was coded largely
from the mixer bias / base rate rather than a warmed context.
`context_miss.low_confidence_loss_q24` sums those specific bits' Q24 losses.

**Hot regions.** `top_regions` lists the N highest-loss 64-byte regions by
offset, each with its class byte-count mix and overlay byte-counts. No source
content is emitted — only byte offsets and single-byte class labels/counts.

All percentages are integer parts-per-million (`*_ppm`) computed from exact Q24
losses, so the report is byte-for-byte deterministic (proved by
`decomposition_is_deterministic_including_json`).

## Counted-run procedure (prepared, NOT executed here)

The two counted decomposition runs are on the two public 24 MiB slices. The
sweep runner (`scripts/moon-prescreen-runner.py`) only drives `encode`, so the
new `diagnose-h1` subcommand is driven by
`scripts/moon-h1-decomposition-run.py`, a thin wrapper that reuses that runner's
`read_budget` / `write_budget` **verbatim**, so `run-budget.json` is updated the
same way: schema `moon-prescreen-budget-v1`, `runs_consumed` incremented once per
diagnostic run, cap 160, and `BudgetExhausted` at the cap. It verifies each
slice's SHA-256 against the config (and the local-references source SHA/size when
supplied) before reading it, and makes no kill/nominate decision.

Two runs → `runs_consumed` 38 → 40. The exact config is delivered in the PR /
task report (kept out of the corpora tree by design); it is not run here and no
public slice is read by this change.

## Counted results (runs 38 → 40, `development_only_prescreen`)

The two counted runs are on the two pinned GH Archive slices. Both reports and
the sweep summary are published at `runs/moon-h1-loss-decomposition-v1/`
(`SHA256SUMS` included). Evidence stage: `development_only_prescreen` — this is a
loss-attribution map of the H1 floor arm, not a codec result, candidate score,
or unseen-validation number. No compression-ratio claim is made or implied by
any figure below; every number is a *share of the arm's own Q24 coding loss*.

Provenance of the two runs:

| snapshot | source_bytes | source_sha256 | tape_bytes | tape_sha256 | total_loss_q24 | records |
| --- | --- | --- | --- | --- | --- | --- |
| gharchive-2026-05-15-14-s24 | 25,165,377 | `a6873fde…802b4` | 28,311,104 | `c8e153b5…dff80` | 481,419,739,510,336 | 37,231 |
| gharchive-2026-06-15-14-s24 | 25,165,414 | `05220440…e50f79` | 28,311,145 | `65161fc7…e579b` | 469,125,813,093,030 | 35,854 |

Internal consistency holds on both reports (checked, not asserted): the primary
partition sums exactly to `modeled_bits_loss_q24`; `modeled_bits + framing ==
total_loss_q24`; and the per-bucket byte counts sum to `source_bytes` with zero
`unclassified` (coverage 1,000,000 ppm). Observer transparency is guaranteed by
the byte-identity unit test plus the runtime fail-closed guard documented above;
each report's `tape_sha256` is the byte-identical arm tape.

### Primary partition — share of total Q24 loss

Percentages are `bucket loss_q24 / total_loss_q24`; every source byte is in
exactly one class. `framing` is the pooled continuation-bit loss (separate from
the byte classes).

| class | 05-15 loss share | 05-15 bytes | 06-15 loss share | 06-15 bytes |
| --- | --- | --- | --- | --- |
| string_value | 77.78% | 13,976,500 | 77.95% | 14,280,539 |
| number_value | 10.92% | 1,399,775 | 10.74% | 1,346,656 |
| structural | 6.43% | 4,558,262 | 6.32% | 4,436,329 |
| field_name | 4.54% | 5,029,771 | 4.65% | 4,904,322 |
| literal_value | 0.095% | 163,838 | 0.107% | 161,714 |
| whitespace | 0.006% | 37,231 | 0.006% | 35,854 |
| framing (continuation) | 0.217% | — | 0.223% | — |

The two snapshots agree closely. The headline is stable: **~78% of the H1 floor
arm's coding loss is spent inside string values**, a further ~11% on numeric
literals, and structural punctuation + field names together account for ~11%.
Whitespace, JSON literals (`true`/`false`/`null`), and record framing are jointly
under 0.4% of loss — measured immaterial.

### Value-subclass and structural overlays — share of total Q24 loss

Overlays may overlap each other and the primary classes; each marks a byte and
attributes that byte's eight modeled bits. These are OBSERVER proxies, not codec
components.

| overlay | 05-15 loss share | 05-15 bytes | 06-15 loss share | 06-15 bytes |
| --- | --- | --- | --- | --- |
| repeat_candidate (≥8 B match, 64 KiB window) | 42.95% | 21,110,001 | 43.76% | 21,158,512 |
| digits | 40.37% | 4,565,754 | 40.11% | 4,500,730 |
| hex_id_run | 37.60% | 2,656,187 | 36.08% | 2,487,235 |
| timestamp_span | 0.62% | 759,637 | 0.89% | 818,560 |
| context_miss (best context <4 confidence) | 0.10% | — | 0.10% | — |

Two large, overlapping pools stand out. **~43% of loss sits inside bytes that lie
within a long repeat** a copy/match model could in principle capture, and the
digit + hex-id-run overlays (which live predominantly inside the string_value and
number_value pots) carry ~40% and ~37% respectively. `timestamp_span` is a small
slice (<1%), and the context-miss / cold-start proxy is ~0.1% — the arm is almost
never coding from an un-warmed context. Hot 64-byte regions (`top_regions`) are
overwhelmingly pure `string_value` runs dominated by `hex_id` overlays,
consistent with the partition.

### Tape bytes vs. cycle-1 projected complete bytes (not the same quantity)

The report's `tape_bytes` (28,311,104 / 28,311,145) is the raw s0 accounting-tape
byte count — the internal per-event modeling tape the observer walks and is
byte-identical against. It is intentionally **different** from the cycle-1 H1
receipts' `projected_complete_bytes` (3,609,680 / 3,517,625 in
`runs/moon-prescreen-cycle1-h1-v1/`), which is the compression **projection**
metric (the arm's estimated coded output size). These measure different things:
one is the modeling/accounting tape used to attribute loss, the other is the
scoreboard output-size projection. They are not expected to match and no identity
between them is claimed. The lineage that *does* hold is the byte-identity of the
arm tape itself, enforced by the fail-closed guard.

### Funding consequences (helm decisions, already made)

These are attribution-driven allocation calls; none is a survival prediction and
none reads a development item.

- **C1 match-mixer arm — FUNDED** to attack the ~43% `repeat_candidate` mass:
  the largest single addressable pool is loss inside long repeats a copy/match
  model could capture.
- **C2 value-context arm — FUNDED** to attack the ~78% `string_value` pot (with
  its `hex_id_run` / `digits` sub-structure): the dominant loss class by a wide
  margin.
- **C8 expert-mixture arm — FUNDED** (new id). The 0.93× H1 kill line is to be
  frozen pre-measurement, before any counted run.
- **NOT priority targets** (measured immaterial): `timestamp_span`, `framing`,
  and context cold-start each carry ≤ ~0.9% of loss and are explicitly deprioritized.
