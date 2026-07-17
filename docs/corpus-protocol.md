# Corpus and holdout protocol

The benchmark accepts only files whose manifest records a dataset name, source
URL, license identifier, byte size, and SHA-256. Corpus bytes remain ignored by
Git; the manifest and download recipe establish provenance and reproducibility.

## Public starter corpus

`scripts/fetch-public-starter.py` reconstructs the local
`corpora/public-starter-v1` corpus from `config/public-starter-v1.json`. Downloads
are digest-pinned before extraction or import. The current starter contains:

- SQLite 3.53.3 amalgamation source and its ZIP archive, from the official
  SQLite download page. SQLite states that its deliverable code and
  documentation are in the public domain.
- Chinook 1.4.5 SQLite and JSON release assets under the repository's MIT
  license.
- NOAA's Data Access Procedural Directive PDF, whose repository record marks it
  CC0-1.0.

This is an engineering starter, not a representative corpus. It lacks enough
independent examples, size strata, numeric/scientific arrays, executables,
logs, backups, office documents, and media to support a market claim.

Rebuild it with:

    scripts/fetch-public-starter.py

## Expanded public JSON corpus

`config/public-json-v1.json` freezes four independent, license-compatible JSON
families at upstream commits: Kubernetes OpenAPI, Unicode CLDR, Vega records,
and Natural Earth GeoJSON. It is reconstructed with the same digest-checking
fetcher while keeping the original starter corpus unchanged:

    PYTHONPATH="$PWD/src" python3 scripts/fetch-public-starter.py \
      --config config/public-json-v1.json \
      --output corpora/public-json-v1 \
      --cache corpora/_download-cache/public-json-v1

The expanded set is engineering validation evidence for JSON selector
external validity. It does not replace the sealed private holdout or support a
general market-lead claim. Its frozen decision protocol is documented in
`docs/benchmarks/2026-07-15-expanded-json-protocol.md`.

## JSON estimator train and validation corpora

`config/public-json-estimator-train-v1.json` freezes ten repository-separated
training families. `config/public-json-estimator-validation-v1.json` freezes
six additional families with no repository overlap. Rebuild either with the
generic digest-checking fetcher and the matching cache/output names.

The training corpus may be compression-labeled freely. The estimator
validation corpus is public but blind: integrity and JSON syntax may be checked
beforehand, but transforms, features, compression labels, and benchmarks must
wait until a complete estimator is serialized. A failed training gate does not
consume that validation set. Neither corpus replaces the private holdout.

The six-family validation set was opened once on 2026-07-15 only after the
fixed-sign sampled model and protocol were serialized. That model failed its
predeclared savings-capture gate, so this validation set is now consumed for
STX1 channel-routing hypotheses and may not be used to tune a successor. See
`docs/benchmarks/2026-07-15-fixed-sign-sampled-probe-decision.md`. The private
holdout remains sealed.

## Importing additional licensed data

    PYTHONPATH="$PWD/src" python3 -m compresslab import-corpus \
      --source /path/to/files \
      --output corpora/public-v2 \
      --category database \
      --split validation \
      --dataset example-dataset-version \
      --license-spdx CC0-1.0 \
      --source-url https://owner.example/dataset

Do not infer a license from public accessibility. Use an SPDX identifier when
one applies; otherwise use a narrowly named `LicenseRef-*` and retain the
owner's license page in the research record.

## Private holdout

The holdout corpus must live outside this repository. Freeze it before selector
or predictor tuning:

    PYTHONPATH="$PWD/src" python3 -m compresslab freeze-holdout \
      --corpus /private/compression-holdout-v1 \
      --output /private/compression-holdout-v1.lock.json

At a decision gate, verify the commitment before running:

    PYTHONPATH="$PWD/src" python3 -m compresslab verify-holdout \
      --corpus /private/compression-holdout-v1 \
      --lock /private/compression-holdout-v1.lock.json

A mismatch invalidates the gate. Never tune thresholds on holdout results.

## Manifest-bound scoring

Any frozen, projected, public-validation, or holdout score must pass the exact
manifest filename with `--manifest`; providing only `--corpus` is reserved for
ordinary development runs that intentionally use `manifest.json`. Results
schema version 5 records the resolved manifest path, its SHA-256, the selected
item IDs, and source digests for the manifest-bound runner, frozen version-4
engine, and corpus loader. Release evidence is rejected when those identities
are absent or disagree with the result corpus.

This rule prevents a projected manifest from being silently replaced by a
sibling `manifest.json`. It proves corpus selection and integrity, not
benchmark representativeness or compression performance.
