# Compression Lab

**Category-specialized lossless compression, backed by reproducible evidence.**

Compression Lab is building a practical compressor that detects what a file is,
routes it to a specialist codec, and falls back safely when specialization will
not help. Every result is gated by exact byte restoration, complete archive
accounting, frozen datasets, and checked-in benchmark receipts.

## 18.08% smaller than the closest tested standard on JSON event logs

JLS2 compressed a fresh 203.6 MB CLUE-LDS development slice to **3.52 MB**.
Brotli-11, the next-smallest of 10 tested alternatives, produced **4.30 MB**.
JLS2 was also smallest on all three frozen ranges and restored the exact input
in all **99 of 99** measured round trips.

![JLS2 complete archive size, compression speed, and decompression speed compared with nine established codecs](docs/assets/clue-json-log-scorecard.svg)

This remains a **category-scoped development result**, not a public-validation
win. The frozen first public-validation gate completed as a valid **no-pass**
in [GitHub Actions run 29606109504](https://github.com/Atomics-hub/compression-lab/actions/runs/29606109504);
its retained artifact is awaiting checksum-verified repository import, so no
numeric public-validation claim is made here yet. The result is also not
private-holdout, independent, general-file, or world-best evidence. In the
original same-run development census, JLS2 won size and compression speed
against Brotli-11 but decoded 54.1% slower. A separately frozen
product-delivery gate passes with the standalone decoder at
**585.43 MB/s median**, a **398.40 MB/s minimum**, and all
**7/7 rounds above 250 MB/s**.

![Standalone JLS2 delivery gate and immutable 11-codec size census](runs/jls2-native-decoder-v1/native-decoder-scorecard.svg)

The delivery A/B did not rerun standard codecs, so its speed numbers are kept
separate from the immutable same-run standards table below.

<details>
<summary><strong>Open the full same-run scorecard</strong></summary>

Lower archive size is better. Positive `JLS2 smaller by` values are JLS2 wins.
All speed and memory values came from the same cold-process runner on the same
machine; `Store` is included as the no-compression control.

<!-- clue-scorecard:start -->

| Codec | Complete bytes | Ratio | JLS2 smaller by | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| **JLS2** | **3,523,721** | **57.77x** | — | 109.90 | 116.43 | 416.5 / 186.3 | yes |
| Brotli-11 | 4,301,558 | 47.33x | **18.08%** | 0.37 | 253.86 | 186.8 / 25.2 | yes |
| zstd-19 | 4,900,286 | 41.54x | **28.09%** | 1.05 | 268.83 | 244.1 / 163.1 | yes |
| bzip2-9 | 5,379,654 | 37.84x | **34.50%** | 1.37 | 25.26 | 104.1 / 166.8 | yes |
| LZMA-9 | 5,572,968 | 36.53x | **36.77%** | 1.59 | 82.29 | 743.9 / 227.7 | yes |
| 7-Zip-9 | 5,574,110 | 36.52x | **36.78%** | 6.44 | 164.58 | 750.0 / 73.4 | yes |
| zstd-9 | 5,684,983 | 35.81x | **38.02%** | 124.70 | 300.48 | 242.3 / 163.4 | yes |
| zstd-3 | 7,538,545 | 27.00x | **53.26%** | 313.60 | 248.62 | 233.7 / 164.3 | yes |
| gzip-9 | 8,272,033 | 24.61x | **57.40%** | 49.19 | 288.08 | 99.2 / 167.4 | yes |
| LZ4-1 | 14,061,683 | 14.48x | **74.94%** | 387.73 | 278.96 | 25.2 / 25.3 | yes |
| Store | 203,578,132 | 1.00x | **98.27%** | 416.08 | 479.03 | 26.0 / 26.0 | yes |

<!-- clue-scorecard:end -->

</details>

The [complete standards bundle](runs/clue-json-log-development-census-v1/README.md)
contains corpus ranges, licenses, codec versions, raw trials, and the original
failed delivery gate. The separate [standalone decoder bundle](runs/jls2-native-decoder-v1/README.md)
contains its frozen protocol, 48 exact trials, portability checks, chart, and
claim boundary. Its optimization lineage remains independently inspectable:
[decode kernel A/B](runs/jls2-decode-kernel-development-v1/README.md),
[scheduling A/B](runs/clue-jls2-decode-scheduling-v1/README.md), and
[cold-start A/B](runs/jls2-cold-start-v1/README.md).

## Measured standings

| Category | Best measured result | Gate status and evidence |
| --- | --- | --- |
| JSON and machine logs | JLS2 is 18.08% smaller than the strongest tested standard in development | Development ratio lead and standalone decode gate passed; the frozen first public-validation gate completed as a no-pass and its exact artifact is pending checksum-verified import ([result status](docs/benchmarks/2026-07-17-clue-jls2-public-validation-result-status.md), [readiness protocol](docs/benchmarks/2026-07-17-clue-jls2-public-validation-readiness.md)) |
| Delimited tables | TBS1 vs 7-Zip-9: 3.48% larger aggregate | Frozen gate failed ([decision](docs/benchmarks/2026-07-17-tbl1-public-validation-decision.md), [Fresh successor corpus protocol](docs/benchmarks/2026-07-17-tabular-successor-corpus-protocol.md)) |
| Dense matrices | DMS2 vs Brotli-11: 43.55% larger; 33.45 / 313.99 MB/s compression / decompression | Frozen gate failed ([evidence](runs/dms2-public-validation-v1/README.md)) |
| General files | Exact `.clab` fallback; no strongest-standard lead established | Alpha |

Consumed validation families are never reused as fresh evidence. The benchmark
runner also has a checked-in [manifest-binding gate](runs/benchmark-manifest-binding-v1/README.md).

## Try it

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

Decode an existing JLS2 JSON-log stream without Python:

```bash
native/target/release/clab-jls2 decompress events.jls2 \
  -o events.jsonl --max-output-size 1000000000
```

Tagged releases build verified standalone archives for Linux, macOS, and
Windows alongside the Python packages.

Standard input and output use `-`. Compression refuses to overwrite a file
unless `--force` is supplied. The decoder rejects declared output above 2 GiB
by default; set a different explicit bound with `--max-output-size`.

### Python API

```python
import compresslab

frame = compresslab.compress(b"lossless data" * 1000)
original = compresslab.decompress(frame, max_output_size=10_000_000)
```

The general `.clab` format is currently alpha. Research specialists stay
separate from the stable API until their formats and evidence gates are frozen.

## What is in the repository

- A self-describing `.clab` container with deterministic selection and an exact
  direct/store fallback for arbitrary files.
- JLS2 for structured JSON event logs, including a self-contained verified
  decoder, plus gated tabular and matrix research.
- Reproducible runners, manifests, receipts, fuzz tests, integrity checks,
  native acceleration, and cross-platform Python packaging.

## Reproduce the work

Run the complete verification suite:

```bash
scripts/build-native.sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run the manifest-bound benchmark harness:

```bash
PYTHONPATH=src python3 -m compresslab run \
  --corpus corpora/public-validation \
  --manifest corpora/public-validation/scoring-manifest.json \
  --output runs/public-validation \
  --repetitions 3 \
  --warmups 1
```

Every result records licenses, corpus and manifest hashes, item IDs, candidate
commit, codec versions, runner scope, repetitions, exact round trips, complete
archive bytes, and its claim ceiling. Private holdout data stays outside the
repository.

Start with the [category portfolio](docs/benchmarks/2026-07-16-category-portfolio-status.md),
[benchmark archive](docs/benchmarks/), [file-format contract](docs/file-format.md),
[release-readiness checklist](docs/release-readiness.md), and [security policy](SECURITY.md).

## License

Compression Lab is released under the [MIT License](LICENSE).
