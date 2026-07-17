#!/bin/sh
set -eu

repository=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cargo build --manifest-path "$repository/native/Cargo.toml" --release --locked
cargo build --manifest-path "$repository/native-dense/Cargo.toml" --release --locked
