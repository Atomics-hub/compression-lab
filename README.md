# Compression Lab

Compression Lab is an open, evidence-driven lossless compression project. It
combines category specialists, a deterministic content selector, exact
fallback, and a self-describing `.clab` container instead of forcing one
transform onto every kind of file.

The stable general-file CLI is alpha. DMS2, TBS1, and JLS2 are experimental
specialists and are promoted only when frozen evidence supports them.

## Latest result: dense numeric matrices

On 4,895,341 fresh development bytes from three UCI matrix families, native
DMS2 produced 189,738 bytes: **5.28% smaller than bzip2-9**, the strongest of
ten tested standards. Seven measured complete-frame trials after one warmup
ran at **54.85 MB/s compression and 268.18 MB/s decompression**.

| Codec | Complete bytes | DMS2 size result | Compress MB/s | Decompress MB/s | Peak RSS C/D MiB | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **DMS2 native** | **189,738** | candidate | **54.85** | **268.18** | **51.9 / 39.2** | ✅ |
| bzip2-9 | 200,311 | **5.28% smaller** | 1.71 | 27.18 | — | ✅ |
| Brotli-11 | 238,019 | **20.28% smaller** | 0.34 | 202.81 | — | ✅ |
| zstd-19 | 244,177 | **22.29% smaller** | 2.59 | 829.70 | — | ✅ |
| 7-Zip-9 | 244,868 | **22.51% smaller** | 5.19 | 124.55 | — | ✅ |
| LZMA-9 | 245,200 | **22.62% smaller** | 1.04 | 74.93 | — | ✅ |
| gzip-9 | 270,595 | **29.88% smaller** | 2.68 | 911.03 | — | ✅ |
| TBS1 stream-dense | 320,264 | **40.76% smaller** | 44.38 | 220.66 | — | ✅ |
| zstd-9 | 324,779 | **41.58% smaller** | 64.56 | 327.78 | — | ✅ |
| zstd-3 | 383,836 | **50.57% smaller** | 321.72 | 565.71 | — | ✅ |
| LZ4-1 | 971,749 | **80.47% smaller** | 166.92 | 199.39 | — | ✅ |
| store | 4,895,341 | **96.12% smaller** | 986.33 | 1,364.52 | — | ✅ |

Full transparency: this is development evidence, not a world-best claim or
public validation. Ratio, speed, memory, bounded streaming, selector,
direct-fallback, regression, exactness, determinism, and corruption gates all
passed locally. Native-wheel and full-suite reproduction also passed on Linux,
macOS, and Windows for commit `4e816ca`. Candidate lock remains before the
one-time unseen validation. See the [complete decision and raw evidence](docs/benchmarks/2026-07-17-dms2-native-development-gate.md).

Baseline speeds are same-machine contextual measurements from the preceding
fresh census; DMS2 used repeated trials. Baseline peak RSS was not rerun, so no
comparative memory win is claimed. Complete bytes include every frame header
and checksum.

## Evidence portfolio

| Category | Evidence stage | Strongest result | Honest status |
| --- | --- | --- | --- |
| Dense numeric matrices | Fresh development | DMS2 5.28% smaller than bzip2-9 at 54.85/268.18 MB/s | Local and cross-platform gates passed; candidate lock next; validation unopened |
| Delimited record tables | Public validation | TBS1 won 3/4 families by 7.35%–16.50% | Aggregate remained 3.48% behind 7-Zip-9 |
| JSON and machine logs | Public validation | JLS2 28.77% smaller than zstd-9 | Mixed against Brotli-11; decode gate missed |
| General binary, source, archives | Development | Exact fallback | No category win established |

The TBS1 public run covered **268,432,956 previously unseen UCI table bytes**.
It won three families, but the overall frozen gate was **not passed** because
aggregate output remained behind 7-Zip-9 and one decode repetition missed its
floor.

### Fresh successor development checkpoint

Before DMS2, unchanged TBS1 was 2.87% larger than bzip2 on the six-family
successor corpus and 59.88% larger on its dense-matrix track. That checkpoint
was development guidance, not validation; DMS2 is the direct response to the
dense-matrix gap.

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

Every promoted result declares corpus licenses and hashes, candidate commit,
codec versions, runner, repetitions, exact round trips, complete archive bytes,
and its claim ceiling. Private holdout data stays outside the repository.

Key documents:

- [DMS2 native development gate](docs/benchmarks/2026-07-17-dms2-native-development-gate.md)
- [Dense-matrix frozen protocol](docs/benchmarks/2026-07-17-dense-matrix-representation-protocol.md)
- [Fresh successor corpus protocol](docs/benchmarks/2026-07-17-tabular-successor-corpus-protocol.md)
- [File-format contract](docs/file-format.md)
- [Release readiness](docs/release-readiness.md)
- [Security policy](SECURITY.md)
- [Complete benchmark and rejected-hypothesis archive](docs/benchmarks/)

## License

Compression Lab is released under the [MIT License](LICENSE).
