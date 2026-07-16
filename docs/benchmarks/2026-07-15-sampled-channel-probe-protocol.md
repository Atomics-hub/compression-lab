# Sampled token-channel probe protocol

## Question

Zero-order STX1 statistics failed to generalize across source families. This
experiment asks whether a small amount of real Zstandard work on representative
STX1 body samples can predict the sign of the complete token-channel benefit
without compressing both complete channel layouts.

The ten-family training corpus is already exposed. The six-family public
validation corpus remains compression-unscored, and the private holdout remains
sealed. This protocol freezes the sampling layouts, score family, learner, and
gates before any sampled-compression score is measured.

## Bounded representative sample

Start from the already-produced complete STX1 transform. Parse and retain its
dictionary header. Sample only the transformed body at three deterministic
positions: first, centered, and last.

Allowed total body budgets are exactly 24, 48, 96, and 192 KiB. Divide the
budget across the three positions, giving any remainder to the last window.
Windows must be adjusted inward by at most one byte so no STX1 marker/code pair
is split. Merge overlapping ranges, preserve source order, and use the full
body if it is smaller than the requested budget.

Construct one valid sampled STX1 stream from the original dictionary header
and concatenated aligned body ranges. Compare:

- interleaved sample: transformed-size metadata plus one zstd-3 frame;
- channel sample: the existing complete channel header plus independent
  zstd-3 skeleton and side frames.

Both representations charge every byte. Sampling may allocate only the fixed
budget plus the dictionary header; it may not allocate complete skeleton or
side buffers.

## Frozen score and model family

For each allowed budget, compute exactly two candidate scalar scores:

1. raw sampled channel bytes minus sampled interleaved bytes;
2. the same delta divided by sampled transformed bytes and multiplied by
   1,000,000.

The deployable model is either always skip, always try, or one predicate of the
form `score < threshold`. Thresholds are midpoints between distinct training
scores. No source identity, filename, semantic JSON feature, additional
statistic, multi-budget vote, second predicate, or validation-tuned adjustment
is allowed.

For every training fold, select the model using only the other nine families.
The objective at 100 Mbps is:

- missed full-channel savings;
- byte-equivalent median full-channel attempt time on false positives;
- byte-equivalent median sample-probe time on every sampled decision;
- a 0.05% aggregate-STX1 complexity penalty for a threshold model.

Time converts at `seconds * 12,500,000`. Each probe and full-channel attempt is
measured after one warmup with five repetitions; use the median. Ties prefer
always skip, then always try, then smaller sample budget, raw score, and lower
threshold in that order.

After family-level leave-one-out evaluation, refit once on all ten training
families. Serialize the chosen budget, score, threshold, source/config hashes,
and all training metrics before any blind validation transform or compression.

## Predeclared training gates

All must pass before blind validation is opened:

- capture at least 75% of available full-channel savings by bytes;
- avoid at least 50% of losing full-channel attempts;
- payload regret versus the complete exact oracle at most 0.50% of aggregate
  STX1 bytes;
- measured probe-plus-routed-channel time at least 10% lower than trying the
  full channel on every family;
- the selected sample budget is no more than 192 KiB and probe bytes never
  exceed the declared bound;
- two complete training runs reproduce exact sample bytes, scores, labels,
  final model, fold decisions, and gates. Timing may vary, but may not change
  the selected model or pass/fail decision.

## Predeclared blind gates

If and only if training passes, score the frozen six-family validation corpus
once. All must pass for native integration:

- capture at least 75% of available full-channel savings and at least 67% of
  winning families when there are at least three winners;
- avoid at least 50% of losing full-channel attempts;
- payload regret at most 0.25% of aggregate STX1 bytes;
- probe-plus-routed-channel time at least 10% below generic full-channel
  attempts;
- estimator-routed output never exceeds interleaved STX1 because a positive
  prediction still uses exact complete-payload fallback;
- the native bounded probe improves complete adaptive-v3 focused encode
  throughput by at least 10%, passes all Python, Rust, malformed-stream,
  corruption, and corpus round trips, does not increase aggregate output, and
  does not lose a Pareto position held by the generic exact route;
- compare and report zstd-3, zstd-9, Brotli-6, Brotli-11, LZMA-9, 7-Zip-9,
  gzip-9, generic adaptive-v3, and sampled-probe adaptive-v3.

If training fails, serialize and document the rejection without consuming the
blind corpus. If blind validation fails, do not tune on it or integrate the
probe.
