# Sampled token-channel probe decision

## Decision

**Reject sampled token-channel routing and do not integrate it.**

The first predeclared sampled-compression learner failed training because its
100 Mbps byte-equivalent objective selected `never` in every family-level
fold. A separate, parameter-free fixed-sign rule perfectly separated all ten
training families, so it was frozen before the six-family public validation
set was opened. On that blind set it skipped every family, including both
small channel winners, and captured 0% of the available savings. The required
capture gate was 75%.

This validation set is now consumed for this hypothesis. No threshold, sample
budget, or predicate will be tuned on it. The private holdout remains sealed,
and adaptive-v3 retains its existing exact full-payload comparison.

## Frozen evidence chain

- sampled learner protocol:
  `docs/benchmarks/2026-07-15-sampled-channel-probe-protocol.md`;
- deterministic training implementation:
  `scripts/train-sampled-channel-probe.py`, SHA-256
  `71c1dbdede22e4baacb872cbf05e8d93facc8a2243ced0ed0003a71492b220a9`;
- fixed-sign follow-up protocol:
  `docs/benchmarks/2026-07-15-fixed-sign-sampled-probe-protocol.md`, SHA-256
  `022a8b80d9c7d214dc2fd5a158e66eb99bf98d66315b9e26378b1f748c861169`;
- serialized pre-validation model:
  `config/fixed-sign-sampled-channel-probe-v1.json`, SHA-256
  `a5f172d628fab5ed856d0bd1d21188f6ad18e01a6fb5e587b212437c5d3d3b33`;
- blind evaluator: `scripts/evaluate-fixed-sign-sampled-probe.py`;
- first training run: `runs/sampled-channel-probe-training.json`, SHA-256
  `ae73a67655ac5ce9a290e11fe05bcada6c3a8cbde75fefd92e16c6a2e0637205`;
- independent training repeat:
  `runs/sampled-channel-probe-training-repeat.json`, SHA-256
  `a2fee0497a1f786f2e4c044e890c123425b17fc187b877a1b8f5649235b776f7`;
- one-time blind validation:
  `runs/fixed-sign-sampled-probe-validation.json`, SHA-256
  `5643ab345e7e2e78ec141f7ce2f61ebbff2634b6681bfb4404612d9812778f8c`.

The validation config SHA-256 was
`625c7286f6a990624b40dede8e80812813c8af7c504c0d50b3b82f26df412433`.
The evaluator verified the frozen protocol, sampler, training artifacts,
training config, validation config, corpus files, and model before measuring a
validation payload.

## Training outcomes

The economic model's leave-one-family-out result was:

| Metric | Result | Gate |
| --- | ---: | ---: |
| Available savings | 14,159 bytes | report |
| Savings captured | 0% | at least 75% |
| Losing attempts avoided | 100% | at least 50% |
| Payload regret | 1.247% of STX1 | at most 0.50% |
| Route-time improvement | 100% | at least 10% |

It failed savings capture and regret, so that learner was rejected.

The follow-up fixed exactly one rule: use a 24,576-byte first/center/last STX1
body sample and attempt the complete token channel only when its complete
sampled Zstandard-3 representation is strictly smaller than the complete
sampled interleaved representation. This rule attempted exactly the two
training winners and skipped all eight losers. It captured 100% of savings
with zero regret and improved routed time by 73.62% in the first run and 62.60%
in the repeat. Exact sample hashes, sizes, scores, labels, decisions, and gates
reproduced; only timing varied.

## Blind result

| Family | Sample delta | Complete delta | Truth | Decision |
| --- | ---: | ---: | --- | --- |
| AWS SDK JS | +238 | +4,201 | lose | skip |
| Countries | +192 | +6,550 | lose | skip |
| gemoji | +39 | **-341** | win | **skip** |
| Jupyter Notebook | +26 | +2,183 | lose | skip |
| MDN browser data | +140 | +1,450 | lose | skip |
| OpenFootball | +10 | **-79** | win | **skip** |

Every sample delta was positive. The sign rule therefore made no complete
channel attempts. It correctly skipped all four losers but missed both
winners.

| Blind metric | Result | Gate | Status |
| --- | ---: | ---: | --- |
| Available savings | 420 bytes | report | — |
| Savings captured | **0%** | at least 75% | **fail** |
| Winner-family capture | 0 of 2 | gate applies at 3+ winners | pass by definition |
| Losing attempts avoided | 100% | at least 50% | pass |
| Payload regret | 0.0508% of STX1 | at most 0.25% | pass |
| Route-time improvement | 88.55% | at least 10% | pass |
| Bounds, determinism, fallback | all pass | all required | pass |

The regret is numerically small only because the two blind wins total 420
bytes across 826,958 interleaved bytes. It does not override the failed capture
gate: this probe does not preserve the available ratio gains out of family.

## What this rules out

The evidence rejects both tested cheap-routing families for this STX1 channel:

1. zero-order token statistics do not generalize by repository family;
2. the sign of a 24 KiB representative sample does not preserve the sign of
   small whole-file channel gains.

Continuing to tune thresholds or sample layouts would spend the consumed
validation set and optimize a routing layer around a representation whose six
blind files offer only 420 bytes of total upside. That is not a credible route
to a market-leading compressor.

## Next admissible direction

Stop optimizing whether to try the current STX1 side channel. Keep its exact
fallback for the already-demonstrated files, but move new ratio work to a new
representation or entropy-coding hypothesis with materially larger potential
than a few hundred bytes per family. Any successor needs a fresh public
training/validation split and must compete against zstd-9, Brotli-11, LZMA-9,
and 7-Zip-9 before the private holdout is opened.
