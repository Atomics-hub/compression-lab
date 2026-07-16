# JSON token-channel estimator protocol

## Question

JSON syntax alone did not predict whether separating STX1 token IDs helped.
This experiment asks whether cheap statistics from the already-produced STX1
stream can predict channel benefit before paying for two additional Zstandard
compressions. The private holdout remains sealed.

The source-family split, estimator family, feature budget, and decision gates
below are frozen before any new source is compression-labeled.

## Family-separated source split

Previously exposed files may be used only for training. No repository family
appears in both training and blind validation.

### Training families

The five previously measured families are Chinook 1.4.5 JSON, Kubernetes
OpenAPI at `1b4e48f52199bcfb28ef6efd60522a082c3e78d0`, Unicode CLDR at
`a79b499916d486dca4b0f74fe423ea457705fdd9`, Vega movies at
`cad85578e232704bb0453544742440038038c6a2`, and Natural Earth GeoJSON at
`ca96624a56bd078437bca8184e78163e5039ad19`.

Five additional training families are frozen without viewing compression
labels:

| Family | File | Commit | License |
| --- | --- | --- | --- |
| Chrome DevTools Protocol | `json/browser_protocol.json` | `2c7c583a5eb689b731fea6697b7b7b17d9ffedaa` | BSD-3-Clause |
| SchemaStore | `src/api/json/catalog.json` | `773fe876b57bb3d35693177b626164570a6bac49` | Apache-2.0 |
| simdjson examples | `jsonexamples/citm_catalog.json` | `8e6bac94877f2d3d026000d36ce81e0aaf38d26f` | Apache-2.0 |
| TypeScript | `package-lock.json` | `637d5746b70257028fb95aad32ddec6b26ab0a14` | Apache-2.0 |
| webpack | `schemas/WebpackOptions.json` | `805ae584b87f12e773d477e6984c60ccdd179975` | MIT |

### Blind validation families

These files must be downloaded, digest-pinned, and frozen before training
labels are inspected. They may be scored only after the final estimator and
all thresholds have been written to a versioned model artifact.

| Family | File | Commit | License |
| --- | --- | --- | --- |
| GitHub gemoji | `db/emoji.json` | `0eca75db9301421efc8710baf7a7576793ae452a` | MIT |
| Countries | `countries.json` | `09b28e3d03e6ca3fbbac996d716a50d929781e8c` | ODbL-1.0 |
| OpenFootball | `2023-24/en.2.json` | `a5dd38b3bcbe3aa2477cf400f569264253d51431` | CC0-1.0 |
| MDN browser compatibility data | `api/Element.json` | `cc0621335538f2d773b22e2242b2c3aa63908699` | CC0-1.0 |
| Jupyter Notebook | `binder/example.ipynb` | `113a7b062fc693dac71aae5c20992cfaf6cebe17` | BSD-3-Clause |
| AWS SDK for JavaScript | `apis/dynamodb-2012-08-10.normal.json` | `9d3c66eca8c4416a9d347d0703f27b65775d65ef` | Apache-2.0 |

## Labels and complete-byte accounting

For each source, the label is whether the complete raw-channel payload is
smaller than interleaved STX1. Both candidates use Zstandard level 3. Charge
the STX1 transformed-size field, both channel frames, the channel header, and
the adaptive-v3 recipe metadata. The exact selector that tries both
representations is the oracle upper bound for this experiment, not a deployable
estimator.

## Feature budget

Features may scan the transformed STX1 bytes once but may not invoke a
compressor, parse the original JSON semantically, allocate proportional
skeleton and side buffers, or inspect source identity or filename. Candidate
scale-free statistics are limited to:

- marker or side-byte density;
- dictionary utilization and normalized mean token code;
- zero-order side-code entropy;
- largest-code probability and top-four probability;
- adjacent equal-code rate.

The production extractor must compute the retained features in native code
with constant auxiliary memory. The feature scan is charged to selector time.

## Frozen estimator family

The learner may choose among:

1. always skip or always try;
2. one threshold predicate over one declared feature, in either direction;
3. an AND of two threshold predicates over at most two declared features.

Threshold candidates are midpoints between distinct training values. Model
selection uses family-level leave-one-out predictions. The objective is the
sum of missed channel savings plus the measured encode-time cost of false
positive channel attempts. Channel-attempt cost is the median of five warm
focused measurements and is converted to byte-equivalent cost at 100 Mbps
(`seconds * 12,500,000`). Add a complexity penalty equal to 0.05% of training
STX1 bytes per predicate. Ties prefer fewer predicates, then the declared
feature order, then the lower threshold. The final model is refit on all
training families and serialized before blind validation is opened.

No tree deeper than two predicates, source-specific exception, coefficient
sweep, semantic JSON rule, or validation-driven threshold change is allowed.

## Predeclared gates

The estimator can be integrated only if all gates pass.

### Training robustness

- Leave-one-family-out captures at least 75% of available channel savings by
  bytes.
- It avoids at least 50% of losing channel attempts.
- Its complete-payload regret versus the exact oracle is at most 0.50% of
  aggregate STX1 bytes.

### Blind validation

- Capture at least 75% of available channel savings by bytes and at least 67%
  of winning families when validation contains at least three winners.
- Avoid at least 50% of losing channel attempts.
- Complete-payload regret versus the exact oracle is at most 0.25% of
  aggregate STX1 bytes.
- Estimator-routed output is never larger than interleaved STX1 because exact
  complete-payload comparison remains mandatory after a positive prediction.
- The native feature scan sustains at least 500 MB/s and consumes at most 5%
  of total structured-text encode time.
- Estimator routing improves focused aggregate encode throughput by at least
  10% versus trying both channel candidates on every JSON document.

### Integrated system

- Every Python, Rust, malformed-stream, corruption, and corpus round trip
  passes.
- Adaptive-v3 does not lose a Pareto position held by the generic exact route
  and does not increase aggregate bytes.
- Report direct zstd-3, zstd-9, Brotli-6, Brotli-11, LZMA-9, 7-Zip-9, gzip-9,
  the generic exact route, and the estimator route on the blind corpus.
- Absolute throughput claims require the repository's quiet-host and
  repeatability gates; noisy runs may establish sizes, routing, correctness,
  and within-run comparisons only.

If any blind gate fails, retain the model and evidence as a rejected research
artifact, do not integrate the estimator, and do not tune it on validation.
