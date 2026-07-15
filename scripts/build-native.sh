#!/bin/sh
set -eu

repository=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec cargo build --manifest-path "$repository/native/Cargo.toml" --release --locked
