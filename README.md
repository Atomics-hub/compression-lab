# Compression Lab

Compression Lab is an open, evidence-driven lossless compression project. It
combines category specialists, a deterministic content selector, exact
fallback, and a self-describing `.clab` container instead of forcing one
transform onto every kind of file.

The stable general-file CLI is alpha. DMS2, TBS1, and JLS2 are experimental
specialists and are promoted only when frozen evidence supports them.

## Latest result: DMS2 did not pass public validation

On **71,104,540 previously unopened Gisette and Madelon bytes**, DMS2 produced
11,937,137 bytes. Brotli-11 produced 8,315,469 bytes, so DMS2 was **43.55%
larger than the strongest two-item baseline**. The frozen gate did not pass.

| Codec | Complete bytes | DMS2 size vs codec | Compress MB/s | Decompress MB/s | Cold RSS C/D MiB | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **DMS2** | **11,937,137** | candidate | **33.45** | **313.99** | **630.5 / 86.9** | ✅ |
| store | 71,104,540 | 83.21% smaller | 1,594.70 | 815.60 | 26.1 / 26.1 | ✅ |
| LZ4-1 | 18,918,739 | 36.90% smaller | 810.42 | 433.22 | 35.2 / 30.7 | ✅ |
| gzip-9 | 10,371,868 | 15.09% larger | 3.18 | 382.82 | 106.9 / 170.8 | ✅ |
| bzip2-9 | 8,627,565 | 38.36% larger | 1.47 | 22.71 | 115.4 / 163.9 | ✅ |
| zstd-3 | 11,741,186 | 1.67% larger | 255.16 | 316.92 | 228.5 / 163.2 | ✅ |
| zstd-9 | 10,772,378 | 10.81% larger | 45.53 | 359.80 | 228.2 / 162.2 | ✅ |
| zstd-19 | 8,524,178 | 40.04% larger | 1.48 | 398.58 | 241.2 / 160.4 | ✅ |
| Brotli-11 | **8,315,469** | **43.55% larger** | 0.40 | 248.06 | 218.2 / 25.2 | ✅ |
| LZMA-9 | 8,444,740 | 41.36% larger | 0.47 | 39.77 | 749.1 / 224.4 | ✅ |
| 7-Zip-9 | 8,476,984 | 40.82% larger | 1.45 | 119.63 | 648.5 / 74.6 | ✅ |

The family results were also decisive: DMS2 was 46.57% larger than Brotli-11
on Gisette and 41.03% larger than bzip2-9 on Madelon. Compression speed, minimum
repetition speed, and cold compression memory missed their gates. Exactness,
determinism, corruption rejection, decompression speed, bounded fallback,
complete accounting, portability, and cross-platform wheels passed.

Full transparency: the acquisition wrapper downloaded four validation items,
and the baseline runner opened that four-item manifest while DMS2 used the
locked two-item projection. That independently invalidated the frozen aggregate
corpus gate. The table above is a two-item diagnostic reconstructed only from
the retained first attempt's exact per-item medians; speed is contextual because
the baseline schedule contained the two extra unscored items. The complete raw
results, manifests, decision, chart, and checksums are in the
[immutable evidence bundle](runs/dms2-public-validation-v1/README.md).

## Evidence portfolio

| Category | Evidence stage | Strongest result | Honest status |
| --- | --- | --- | --- |
| Dense numeric matrices | Public validation | No win: DMS2 was 43.55% larger than Brotli-11 on the locked two-item diagnostic | Frozen gate did not pass; both validation families are consumed |
| Delimited record tables | Public validation | TBS1 won 3/4 families by 7.35%–16.50% | Aggregate remained 3.48% behind 7-Zip-9 |
| JSON and machine logs | Public validation | JLS2 28.77% smaller than zstd-9 | Mixed against Brotli-11; decode gate missed |
| General binary, source, archives | Development | Exact fallback | No category win established |

Read the [portfolio scorecard](docs/benchmarks/2026-07-16-category-portfolio-status.md),
[TBS1 public-validation decision](docs/benchmarks/2026-07-17-tbl1-public-validation-decision.md),
and [JLS2 public-validation decision](docs/benchmarks/2026-07-16-jls2-public-validation-decision.md)
for the full receipts. Consumed validation families are never reused as fresh
evidence.

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
