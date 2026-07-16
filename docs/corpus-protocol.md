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
