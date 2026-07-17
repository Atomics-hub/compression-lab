# DMS2 one-time public-validation readiness

## Decision

**Ready to lock; validation remains unopened.** The DMS2/DSS1 implementation,
two-family validation identities, complete fixed-baseline roster, evaluator,
speed and memory scopes, integrity proofs, pass thresholds, and acquisition
refusal path are now explicit. This readiness package does not authorize a
download until its exact merged commit is named by the separate lock file and
the lock verifier passes on a clean descendant.

## Frozen candidate

| Property | Frozen value |
| --- | --- |
| Complete format | DSS1 version 1 containing DMS2 version 1 segments |
| Segment target | 16 MiB, LF-aligned when available |
| Specialist entropy level | zstd-19 |
| Direct fallback | equally framed zstd-1 |
| Selector evidence | at most 64 KiB of current-file bytes; zero fitted parameters |
| Production metadata | no filename, source ID, family, DOI, shape, or validation identity |
| Candidate base | `5ff6f01d10960681b35cce5a53eff3e9e3d96ee8` |
| Development gate | 5.28% smaller than bzip2-9; 54.85 / 268.18 MB/s |
| Cross-platform package proof | Linux, macOS, and Windows full suite plus native wheel smoke |

The candidate digest map covers the Python selector and portable inverse,
both native Rust libraries and lockfiles, the zstd bridge, package metadata,
line-ending policy, and exact transform tests. The development ratio/speed,
operational, and cross-platform receipts are also digest-bound.

## Unopened validation identities

| Family | Declared publisher member | License | Acquisition state |
| --- | --- | --- | --- |
| Gisette | `GISETTE/gisette_train.data` | CC BY 4.0 | Unopened; archive and item digests remain `null` |
| Madelon | `MADELON/madelon_train.data` | CC BY 4.0 | Unopened; archive and item digests remain `null` |

The first authorized acquisition records the publisher archive digest, exact
selected-member digest, byte count, completeness, DOI, creator, source URL,
and selection rule. No archive listing, byte sample, header, shape, or derived
statistic may be inspected before the lock is merged.

## Frozen first-score gates

| Gate | Required first-score result |
| --- | --- |
| Aggregate ratio | at least 5% smaller than the strongest complete exact-byte baseline |
| Family ratio | both Gisette and Madelon at least 5% smaller than each strongest complete exact-byte baseline |
| Aggregate compression | at least 50 MB/s |
| Aggregate decompression | at least 250 MB/s |
| Every repetition | at least 45 MB/s compression and 225 MB/s decompression |
| Cold peak RSS | at most 512 MiB for compression and decompression |
| Exactness | every candidate, baseline, and cold-memory trial restores the exact SHA-256 |
| Determinism and integrity | byte-identical repeated frames and corrupted-frame rejection on both families |
| Fallback safety | every DSS1 segment no larger than its equally framed direct zstd-1 route |
| Complete accounting | all frame headers, segment lengths, trailers, and checksums counted |
| Baselines | store, LZ4-1, gzip-9, bzip2-9, zstd-3/9/19, Brotli-11, LZMA-9, and 7-Zip-9 all present |
| Portability | frozen Linux/macOS/Windows suite and native-wheel receipt remains valid |
| Private holdout | sealed |

The first eligible score is final even if it fails or is interrupted. No
candidate, representation, selector, threshold, baseline setting, corpus
slice, evaluator, or pass rule may change afterward.

## Standardized result chart contract

The evaluator emits one row for DMS2 and every baseline with:

- complete compressed bytes and DMS2 percentage difference;
- compression and decompression MB/s;
- cold compression and decompression peak RSS;
- exact-roundtrip failures and portability state;
- whether DMS2 is smaller;
- runner comparability and the exact claim ceiling.

Ratio, exactness, and cold memory use identical bytes on the same host and are
directly comparable. Candidate and baseline speed trials use the same host,
worker-wall timing scope, repetitions, and corpus, but separate adjacent
persistent-worker schedules; the published speed comparison is therefore
explicitly contextual rather than paired.

## Locked workflow

Only after the exact readiness commit is merged and the lock verifier passes:

```bash
python scripts/fetch-dms2-public-validation.py \
  --allow-public-validation \
  --output /path/to/dms2-public-validation-v1 \
  --cache /path/to/dms2-public-validation-cache-v1

python scripts/benchmark-dms2-public-validation.py \
  --manifest /path/to/dms2-public-validation-v1/manifest.json \
  --output /path/to/dms2-first-score-v1

python scripts/evaluate-dms2-public-validation.py \
  --receipt /path/to/dms2-first-score-v1/receipt.json \
  --gates config/dms2-public-validation-gates.json \
  --output /path/to/dms2-first-score-v1/decision.json
```

The acquisition wrapper refuses before explicit authorization and verifies the
merged digest lock before invoking any network-capable fetcher. The benchmark
also verifies that same lock before accepting a manifest or creating a scored
attempt directory.

## Claim ceiling

Readiness supports no new compression-performance claim. Even a passing first
score would support only a category-scoped public-validation result on these
two previously unseen licensed families. Private-holdout success and
independent reproduction remain mandatory before any state-of-the-art claim.
