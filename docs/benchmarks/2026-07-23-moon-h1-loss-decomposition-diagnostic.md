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
