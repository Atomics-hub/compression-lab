#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/runs/release-benchmark-v0.1.0}"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"

cd "$ROOT"
scripts/wait-for-quiet-host.py \
  --gates config/stability-gates.json \
  --timeout "${COMPRESSION_LAB_PREFLIGHT_TIMEOUT:-600}"
scripts/fetch-public-starter.py
scripts/build-native.sh

PYTHONPATH=src python3 -m compresslab run \
  --corpus corpora/public-starter-v1 \
  --manifest corpora/public-starter-v1/manifest.json \
  --output "$OUTPUT" \
  --codecs adaptive-v3,gzip-9,zstd-3,zstd-9,brotli-6,brotli-11,lzma-9,7zip-9 \
  --splits validation \
  --repetitions 7 \
  --warmups 1 \
  --bandwidths 10,100,1000 \
  --timeout 300 \
  --execution-mode persistent-worker \
  --order-seed 20260716 \
  --confidence-level 0.95 \
  --bootstrap-samples 5000 \
  --minimum-trial-time-ms 250 \
  --max-batch-iterations 4096

PYTHONPATH=src python3 -m compresslab.release_evidence \
  "$OUTPUT/results.json" \
  --expected-commit "$COMMIT"
