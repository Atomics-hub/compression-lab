# Compression Lab

Compression Lab is an open, evidence-driven lossless compression project. It
combines category specialists, a deterministic content selector, exact
fallback, and a self-describing `.clab` container instead of forcing one
transform onto every kind of file.

The stable general-file CLI is alpha. DMS2, TBS1, and JLS2 are experimental
specialists and are promoted only when frozen evidence supports them.

## Measured standings

These are category-scoped results, not one blended leaderboard. Positive size
values mean our specialist is smaller; every row used exact round trips and
complete container bytes.

| Category and comparison | Size result | Compress MB/s: ours / standard | Decompress MB/s: ours / standard | Verdict |
| --- | ---: | ---: | ---: | --- |
| JSON logs: JLS2 vs zstd-9 | **28.77% smaller** | 155.83 / 222.03 | 165.88 / 1,547.88 | Ratio win; frozen speed gate failed |
| JSON logs: JLS2 vs Brotli-11 | **4.58% smaller aggregate**; won 1/3 families | 155.83 / 0.49 | 165.88 / 1,168.58 | Mixed; frozen gate failed |
| JSON logs: JLS2 vs PBC-only | **83.82% smaller** | 155.83 / 0.56 complete | 165.88 / 94.63 | Ratio and decode win; overall gate still failed |
| Delimited tables: TBS1 vs 7-Zip-9 | 3.48% larger aggregate; won 3/4 families against each family's strongest standard | 107.67 / 1.93 | 403.39 / 141.44 | Strong family signal; frozen gate failed |
| Dense matrices: DMS2 vs Brotli-11 | 43.55% larger | 33.45 / 0.40 | 313.99 / 248.06 | Frozen gate failed |
| General files | No strongest-standard win established | — | — | Exact fallback only |

The full 10-standard TBS1 chart, 11-codec DMS2 chart, JLS2 standards chart,
raw samples, memory measurements, manifests, and checksums are linked below.

## Latest engineering result

The JLS2 decoder now bulk-copies literal spans and avoids redundant nested
restored-byte hashing. Compressed bytes did not change.

| Development measurement | Before | After | Change | Result |
| --- | ---: | ---: | ---: | --- |
| Alternating byte API, seven-round median | 277.05 MB/s | 333.46 MB/s | **+21.66% paired median** | 7/7 candidate rounds above 250 MB/s |
| Complete file product, aggregate | 245.14 MB/s | 366.71 MB/s | +49.59% contextual | Candidate development gate passed |
| Complete encoded bytes | 2,693,313 | 2,693,313 | unchanged | Exact |

This is development evidence on existing families, so it does not rewrite the
retained public-validation result. See the
[reproducible A/B bundle and family chart](runs/jls2-decode-kernel-development-v1/README.md).

## Evidence portfolio

- [Category scorecard](docs/benchmarks/2026-07-16-category-portfolio-status.md)
- [JLS2 public-validation standards chart](docs/benchmarks/2026-07-16-jls2-public-validation-decision.md)
- [TBS1 public-validation 10-standard chart](docs/benchmarks/2026-07-17-tbl1-public-validation-decision.md)
- [DMS2 public-validation 11-codec chart and immutable bundle](runs/dms2-public-validation-v1/README.md)

Consumed validation families are never reused as fresh evidence.

## Quick start

Python 3.9 or newer is required. Native builds also require Rust stable.

```bash
git clone https://github.com/Atomics-hub/compression-lab.git
cd compression-lab
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
scripts/build-native.sh
```

Compress, inspect, and restore any file:

```bash
clab compress report.json
clab info report.json.clab
clab decompress report.json.clab -o restored.json
```

Standard input and output use `-`. Compression refuses to overwrite a file
unless `--force` is supplied. The decoder rejects declared output above 2 GiB
by default; use `--max-output-size` to set a different explicit bound.

## Python API

```python
import compresslab

frame = compresslab.compress(b"lossless data" * 1000)
original = compresslab.decompress(frame, max_output_size=10_000_000)
```

Experimental specialists remain separate from the stable API while their
formats and gates are still moving.

## Reproduce the research

Run the complete local verification suite:

```bash
scripts/build-native.sh
python3 -m unittest discover -s tests -v
```

Run the deterministic benchmark harness on a corpus:

```bash
python3 -m compresslab run \
  --corpus corpora/smoke \
  --output runs/smoke \
  --repetitions 3 \
  --warmups 1
```

For a frozen or projected corpus, name the exact manifest explicitly. The
runner records that file's SHA-256 and selected item IDs in `results.json`:

```bash
python3 -m compresslab run \
  --corpus corpora/public-validation \
  --manifest corpora/public-validation/scoring-manifest.json \
  --output runs/public-validation
```

Every promoted result declares corpus licenses and hashes, candidate commit,
codec versions, runner, repetitions, exact round trips, complete archive bytes,
and its claim ceiling. Private holdout data stays outside the repository.

Key documents:

- [JLS2 decode-kernel A/B gate and family chart](runs/jls2-decode-kernel-development-v1/README.md)
- [Benchmark manifest-binding gate and control chart](runs/benchmark-manifest-binding-v1/README.md)
- [DMS2 public-validation decision and complete chart](runs/dms2-public-validation-v1/README.md)
- [DMS2 immutable first-score bundle index](runs/dms2-public-validation-v1/bundle.json)
- [DMS2 acquisition deviation](docs/benchmarks/2026-07-17-dms2-acquisition-deviation.md)
- [DMS2 native development gate](docs/benchmarks/2026-07-17-dms2-native-development-gate.md)
- [Dense-matrix frozen protocol](docs/benchmarks/2026-07-17-dense-matrix-representation-protocol.md)
- [Fresh successor corpus protocol](docs/benchmarks/2026-07-17-tabular-successor-corpus-protocol.md)
- [File-format contract](docs/file-format.md)
- [Release readiness](docs/release-readiness.md)
- [Security policy](SECURITY.md)
- [Complete benchmark and rejected-hypothesis archive](docs/benchmarks/)

## License

Compression Lab is released under the [MIT License](LICENSE).
