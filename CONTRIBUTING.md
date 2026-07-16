# Contributing

Compression changes need stronger evidence than ordinary application changes.
Start with an issue describing the hypothesis, expected trade-off, corpus, and
failure gate. Do not tune against the private holdout or add unlicensed corpus
material.

## Development setup

Requirements are Python 3.9 or newer, Rust stable, and a C-compatible
Zstandard implementation supplied by the `zstandard` Python dependency or the
host system.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cargo test --manifest-path native/Cargo.toml --locked
python -m unittest discover -s tests -v
```

Run `cargo fmt --manifest-path native/Cargo.toml --all -- --check` and
`python -m compileall -q src tests` before opening a pull request.

## Compression experiments

Every ratio or throughput experiment must freeze its corpus identities,
digests, model family, and pass/fail gates before validation. Report complete
payload sizes, round-trip failures, host and codec versions, and negative
results. A validation failure consumes that split for the tested hypothesis.

Changes to the current encoder must retain decoding compatibility or introduce
a new frame version. Decoder changes need malformed, truncated, oversized,
corrupt, and legacy-frame tests.
