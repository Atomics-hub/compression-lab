#!/bin/sh
set -eu

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh" >&2
  exit 2
fi

exec brew install zstd lz4 brotli sevenzip
