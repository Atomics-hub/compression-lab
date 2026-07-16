# JSON token-channel estimator training decision

## Decision

**Reject the bounded threshold estimator before blind validation.**

The best final two-predicate rule perfectly separates the two winning files
from eight losing files in-sample, but family-level leave-one-out captures 0%
of available channel savings and has 1.247% payload regret versus the exact
oracle. The predeclared gates require at least 75% savings capture and no more
than 0.50% regret. This is direct evidence of overfit, not a candidate for
native integration.

The six-family validation corpus remains compression-unscored. Its URLs,
licenses, commits, byte sizes, and SHA-256 digests are frozen in
`config/public-json-estimator-validation-v1.json`, but no STX1 transform,
feature extraction, channel label, or codec benchmark has been run on it. It
can be preserved for a genuinely different predeclared model family. The
private holdout also remains sealed.

## Frozen evidence

The protocol was written before new compression labels were measured:

- `docs/benchmarks/2026-07-15-json-estimator-protocol.md`
- training config SHA-256:
  `9522b0219b003fd39a7289c43c0b5bdfe77c7fa12dd10b0522dca37d905ce7ca`
- sealed validation config SHA-256:
  `625c7286f6a990624b40dede8e80812813c8af7c504c0d50b3b82f26df412433`
- reproducible trainer: `scripts/train-token-channel-estimator.py`
- canonical local training evidence:
  `runs/token-channel-estimator-training-repeat.json`

The 10 training repositories total 12,636,148 source bytes. Five were already
exposed by earlier work; five new families were pinned before labeling:
Chrome DevTools Protocol under BSD-3-Clause, SchemaStore under Apache-2.0,
simdjson under Apache-2.0, TypeScript under Apache-2.0, and webpack under MIT.

Primary repository records:

- https://github.com/ChromeDevTools/devtools-protocol
- https://github.com/SchemaStore/schemastore
- https://github.com/simdjson/simdjson
- https://github.com/microsoft/TypeScript
- https://github.com/webpack/webpack

The sealed validation families are GitHub gemoji, Countries, OpenFootball,
MDN browser compatibility data, Jupyter Notebook, and AWS SDK for JavaScript.
Their repository licenses are MIT, ODbL-1.0, CC0-1.0, CC0-1.0,
BSD-3-Clause, and Apache-2.0 respectively.

## Training labels

Complete STX1 and channel sizes charge transformed-size metadata, both channel
frames, and the channel header.

| Family | Input bytes | STX1 bytes | Channel bytes | Channel minus STX1 |
| --- | ---: | ---: | ---: | ---: |
| Chinook | 1,897,482 | 170,430 | **164,515** | **-5,915** |
| Chrome DevTools Protocol | 1,426,498 | **156,537** | 163,828 | +7,291 |
| Kubernetes | 4,066,190 | **236,305** | 251,665 | +15,360 |
| Natural Earth | 838,726 | 184,134 | **175,890** | **-8,244** |
| SchemaStore | 452,258 | **70,225** | 72,407 | +2,182 |
| simdjson CITM | 1,727,204 | **15,671** | 17,221 | +1,550 |
| TypeScript lockfile | 369,177 | **49,226** | 51,140 | +1,914 |
| Unicode CLDR | 220,093 | **44,471** | 45,040 | +569 |
| Vega movies | 1,399,981 | **171,915** | 186,576 | +14,661 |
| webpack options | 238,539 | **36,099** | 37,330 | +1,231 |
| **Total** | **12,636,148** | **1,135,013** | **1,165,612** | **+30,599** |

Only Chinook and Natural Earth win. An exact oracle would attempt those two and
save 14,159 bytes while skipping eight losing channel encodes.

## Bounded learner

The frozen feature family uses only scale-free statistics available from an
STX1 marker scan: side density, dictionary utilization, normalized mean token
code, normalized zero-order entropy, top-one and top-four code share, and
adjacent repeat rate. No compressor output, filename, repository identity, or
semantic JSON field is a feature.

The exhaustive learner considered always-never baselines, one threshold, and
an AND of two thresholds. False-positive attempt time was converted to
byte-equivalent cost at 100 Mbps, with the predeclared complexity penalty. The
final all-training rule was:

```text
try channel if side_density > 0.04364382441897608
            and top1_share > 0.12262735066763303
```

That rule selects exactly Chinook and Natural Earth in-sample. It is not stable
when either source family is omitted.

## Controlling leave-one-family-out result

| Gate | Required | Measured | Result |
| --- | ---: | ---: | --- |
| Available channel savings captured | at least 75% | **0%** | fail |
| Losing attempts avoided | at least 50% | **50%** | pass |
| Payload regret versus oracle | at most 0.50% of STX1 | **1.247%** | fail |

Both winning holdouts were skipped. Four losing holdouts were unnecessarily
attempted. A second complete training run reproduced the same exact sizes,
features, final model, fold decisions, and gate result despite different local
timings.

## Implementation audit

The trainer verifies every imported corpus SHA-256 before labeling. It derives
thresholds only from the active training fold, enumerates the entire permitted
model family, charges false-positive attempt cost and predicate complexity,
and reports every holdout model and decision. An independent repeat confirmed
deterministic features, labels, final predicates, and leave-one-out metrics.

No production codec or decoder changed. Because training robustness already
fails, native feature extraction, blind validation, integrated market
benchmarking, and private-holdout scoring were correctly not performed.

## Next admissible direction

Do not add predicates to rescue these two points. The next model must be
architecturally different and predeclared before it touches the sealed public
validation corpus. The strongest remaining option is a tiny sampled
compression probe: compress fixed-size samples of the interleaved and separated
layouts, then estimate whole-file benefit. It spends bounded real codec work
but directly measures the context effect that zero-order token statistics fail
to predict. Its sampling budget and extrapolation rule must be frozen before
the six validation families are scored.
