# Fixed-sign sampled token-channel probe protocol

## Status and rationale

The predeclared economic learner in
`2026-07-15-sampled-channel-probe-protocol.md` rejected every sampled model.
At the assumed 100 Mbps exchange rate, its measured probe cost was greater
than the 14,159 bytes available to save in the ten-family training corpus, so
all leave-one-family-out folds selected `never` and captured no savings.

That rejection stands. A separate inspection of its already-exposed training
artifact found a simpler physical invariant: at the smallest allowed sample,
the sign of the complete sampled payload delta exactly matched the sign of the
complete payload delta for every training family. This follow-up freezes that
fixed-sign rule and its blind gates before the first transform or compression
measurement on the six-family public validation corpus.

The purpose is ratio preservation and practical routing, not optimization at
an assumed network exchange rate. The private holdout remains sealed.

## Frozen model

Use the deterministic representative sampler already specified by the sampled
probe protocol:

- retain the complete STX1 dictionary header;
- sample aligned first, centered, and last body windows;
- use exactly 24,576 bytes as the total body budget;
- merge overlaps, preserve source order, and never split an STX1 marker/code
  pair.

Compress the resulting valid sample exactly twice with Zstandard level 3:

1. complete interleaved representation: transformed-size metadata and frame;
2. complete channel representation: channel header, skeleton frame, side
   frame, and all metadata.

Let `delta = sampled_channel_bytes - sampled_interleaved_bytes`. Attempt the
complete channel representation if and only if `delta < 0`. A predicted
attempt still compares the complete channel payload to the already-produced
complete interleaved payload and keeps the smaller one. There is no learned
threshold, fitting step, source identity, semantic feature, alternate budget,
normalized score, tie adjustment, or validation-dependent change.

## Training evidence

The frozen rule attempts exactly the two winning families and skips all eight
losing families in both completed training runs:

- savings capture: 100%;
- avoided losing attempts: 100%;
- payload regret: 0 bytes;
- routed time improvement versus trying the complete channel for every family:
  73.62% in the first run and 62.60% in the repeat run;
- smallest winner score: -356 bytes; largest winner score: -26 bytes;
- smallest loser score: +36 bytes; largest loser score: +413 bytes;
- sample bytes, sample hashes, compressed sizes, scores, labels, decisions,
  and gates reproduced exactly. Timing varied without changing a decision.

The fixed model, training and validation config digests, sampler digest, and
this protocol digest are serialized in
`config/fixed-sign-sampled-channel-probe-v1.json` before validation is opened.

## Predeclared blind validation

Score the frozen six-family public validation corpus once. Measure only the
24,576-byte fixed-sign probe; do not inspect an alternate sample budget or tune
the rule after seeing a validation label. All of these gates must pass:

- capture at least 75% of available full-channel savings by bytes;
- when there are at least three winning families, attempt at least 67% of them;
- avoid at least 50% of losing full-channel attempts;
- payload regret versus the complete exact oracle at most 0.25% of aggregate
  interleaved STX1 bytes;
- measured probe-plus-routed-channel time at least 10% below attempting the
  complete channel on every family;
- the selected output never exceeds interleaved STX1 because every positive
  decision retains the exact complete-payload fallback;
- every sample respects the body budget and deterministically reproduces its
  bytes and compressed sizes within the run.

If blind validation fails, publish the rejection, do not tune on the consumed
validation set, and do not integrate the probe.

## Integration gates

Only after every blind gate passes may the fixed probe enter adaptive-v3. A
native bounded implementation must then:

- improve focused complete adaptive-v3 encode throughput by at least 10%
  versus the generic exact channel attempt;
- pass all Python, Rust, malformed-stream, corruption, and corpus round trips;
- never increase aggregate output because exact fallback remains active;
- retain any Pareto position held by the generic route;
- be compared against zstd-3, zstd-9, Brotli-6, Brotli-11, LZMA-9, 7-Zip-9,
  gzip-9, generic adaptive-v3, and sampled-probe adaptive-v3.

Failure at integration leaves the fixed-sign model documented but disabled.
