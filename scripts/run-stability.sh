#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/runs/adaptive-v2-public-stability}"

cd "$ROOT"
scripts/fetch-public-starter.py
scripts/build-native.sh

PYTHONPATH=src python3 -m compresslab run \
  --corpus corpora/public-starter-v1 \
  --output "$OUTPUT" \
  --codecs store,adaptive-v1,adaptive-v2,gzip-6,lzma-6,zstd-3,zstd-9,lz4-1,brotli-6,7zip-5 \
  --splits validation \
  --repetitions 7 \
  --warmups 1 \
  --bandwidths 10,100,1000 \
  --timeout 180 \
  --execution-mode persistent-worker \
  --order-seed 20260715 \
  --confidence-level 0.95 \
  --bootstrap-samples 5000

set +e
PYTHONPATH=src python3 -m compresslab evaluate \
  --results "$OUTPUT/results.json" \
  --gates config/initial-gates.json \
  --candidate adaptive-v2 \
  --bandwidth 100 \
  --output "$OUTPUT/gates-initial.json"
initial_status=$?

PYTHONPATH=src python3 -m compresslab evaluate \
  --results "$OUTPUT/results.json" \
  --gates config/stability-gates.json \
  --candidate adaptive-v2 \
  --bandwidth 100 \
  --output "$OUTPUT/gates-stability.json"
stability_status=$?
set -e

if (( initial_status != 0 )); then
  exit "$initial_status"
fi
exit "$stability_status"
