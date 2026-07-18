# Axiom Compression

**Category-specialized lossless compression, backed by reproducible evidence.**

Axiom is building a practical compressor that detects what a file is,
routes it to a specialist codec, and falls back safely when specialization will
not help. Every result is gated by exact byte restoration, complete archive
accounting, frozen datasets, and checked-in benchmark receipts.

## 52.97% smaller on previously unopened JSON event logs

Axiom's JLS2 codec compressed **96,934,483 source bytes to 489,591 bytes** on
the single authorized CLUE-LDS public-validation score. Brotli-11, the
smallest eligible complete standard, produced **1,040,990 bytes**. JLS2 was
therefore **52.97% smaller**, while compressing at **109.58 MB/s** and decoding
at **431.36 MB/s**. It won both previously unopened temporal families by
**48.31%** and **54.50%**, and every measured round trip was exact.

![Axiom JLS2 complete archive size compared with standards and eligible specialists on the frozen CLUE-LDS public-validation score](runs/clue-jls2-public-validation-v1/publication/comparison.svg)

The frozen overall product gate is still an honest **no-pass**. JLS2 passed the
aggregate and per-family ratio gates, compression and decompression speed,
compression memory, exactness, determinism, corruption rejection, fallback,
accounting, provenance, and roster gates. Its only miss was standalone decoder
peak RSS: **621.3 MiB** against the frozen **512 MiB** limit. Both validation
ranges are now consumed and will not be tuned or rerun.

The [immutable publication bundle](runs/clue-jls2-public-validation-v1/publication/README.md)
contains the complete chart, all tested standards, family rows, speed and
memory measurements, unavailable-specialist disclosures, gates, and exact
claim ceiling. The [import receipt](runs/clue-jls2-public-validation-v1-import.json)
binds it to GitHub artifact `8418445259`, workflow run `29606109504`, the
workflow commit, and GitHub's artifact SHA-256 digest.

This is strong **category-scoped public-validation ratio evidence**, but not a
complete category win, private-holdout result, independent reproduction,
general-file result, or world-best claim. LogFold, LogPrism, LogLite, and DeLog
remain unavailable or ineligible for exact reproduction; their absence is not
an Axiom win.

Brand note: the validation protocol was frozen under the earlier public label
**Atompress**, so the immutable evidence retains that label. The current
product name is **Axiom**; `JLS2` remains the technical on-disk format ID.

<details>
<summary><strong>Open the earlier development and standalone-decoder evidence</strong></summary>

Before public validation, JLS2 compressed a fresh 203.6 MB CLUE-LDS
development slice to **3.52 MB**, 18.08% smaller than Brotli-11. The separately
frozen product-delivery gate passed with the standalone decoder at
**585.43 MB/s median**, a **398.40 MB/s minimum**, and all **7/7 rounds above
250 MB/s**.

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

</details>

The [complete standards bundle](runs/clue-json-log-development-census-v1/README.md)
contains corpus ranges, licenses, codec versions, raw trials, and the original
failed delivery gate. The separate [standalone decoder bundle](runs/jls2-native-decoder-v1/README.md)
contains its frozen protocol, 48 exact trials, portability checks, chart, and
claim boundary. Its optimization lineage remains independently inspectable:
[decode kernel A/B](runs/jls2-decode-kernel-development-v1/README.md),
[scheduling A/B](runs/clue-jls2-decode-scheduling-v1/README.md), and
[cold-start A/B](runs/jls2-cold-start-v1/README.md).

## Text and source-code frontier

The frozen development census is complete: **630/630 exact trials** across 15
single-threaded practical codecs and seven licensed inputs. Kanzi-max is the
ratio leader on both tracks: **45,550,471 bytes from 529,449,573 source-code
bytes (8.60%)** and **35,081,062 bytes from 201,311,173 Wikimedia bytes
(17.43%)**. Those ratio points cost roughly 1.5–1.9 GiB peak RSS and 2.3–3.5
MB/s, so faster and lower-memory operating points remain visible in the chart.

The first frozen Axiom representation probe is also complete: **33/33 exact,
deterministic trials**. TS-H1 improved source-code size by only **0.213%** and
Wikimedia by **0.0068%** versus Kanzi-max, missing its 0.5% hypothesis gate.
TS-H2 made source-code size **0.383% worse** and included a **0.893% regression**
on LLVM, missing both its aggregate and per-item gates. Both hypotheses are
rejected; neither will be promoted into the product.

![Axiom structural variants and every practical text/source standard compared by complete size, speed, memory, exactness, and determinism](runs/text-source-structural-transform-development-v1/publication/comparison.svg)

The next frozen entropy-ceiling probe trained counted dictionaries only on
CPython, TypeScript, Wikibooks, and Wikinews, then evaluated on separate Rust,
LLVM, and Wikiversity items. Its mixed token/class model improved on the weak
byte/class ablation by **13.34%** for source and **25.41%** for Wikimedia, but
remained **498.83% larger than Kanzi-max** on Rust + LLVM and **172.23% larger**
on Wikiversity. Both predictor successors are rejected, and neither merits an
exact codec build.

![Axiom predictor entropy estimates and all 15 practical standards on the identical evaluation subsets](runs/text-source-predictor-entropy-ceiling-publication-v1/comparison.svg)

This establishes the practical target and records clean negative Axiom
results; it is **not an Axiom win**. The predictor rows are conservative
estimates, not decodable artifacts, and carry no speed, memory, exactness, or
portability claim. ZPAQ, paq8px, cmix, and NNCP remain in a separate
research-ceiling tier. The [predictor publication
bundle](runs/text-source-predictor-entropy-ceiling-publication-v1/README.md)
shows every practical standard, all three estimates, and the exact claim
boundary. The earlier [structural publication
bundle](runs/text-source-structural-transform-development-v1/publication/README.md)
contains every practical standard and Axiom row, raw-receipt commitments,
per-item results, speed, memory, exactness, determinism, and the claim ceiling.
The earlier [practical census](runs/text-source-development-baseline-census-v1/publication/README.md)
remains independently reproducible.

## Measured standings

| Category | Objective completion | Best measured result | Gate status and evidence |
| --- | ---: | --- | --- |
| JSON and machine logs | **50%** | JLS2 is 52.97% smaller than the strongest eligible standard on the first frozen public-validation score | Ratio, both families, speed, exactness, integrity, and compression memory passed; overall gate failed only decoder RSS at 621.3 MiB vs 512 MiB ([immutable result](runs/clue-jls2-public-validation-v1/publication/README.md), [import receipt](runs/clue-jls2-public-validation-v1-import.json)) |
| Source-code bundles | **10%** | Tokenization improved the weak P1 estimate by 13.34%, but P2 was 498.83% larger than Kanzi-max on Rust + LLVM | Structural and low-order predictor families both failed frozen gates; pursue a materially stronger contextual or long-range successor while completing external research-ceiling hosts ([latest chart](runs/text-source-predictor-entropy-ceiling-publication-v1/README.md), [protocol](docs/benchmarks/2026-07-18-text-source-predictor-probe-protocol.md)) |
| English Wikimedia wikitext | **10%** | Tokenization improved the weak P1 estimate by 25.41%, but P2 was 172.23% larger than Kanzi-max on Wikiversity | Structural and low-order predictor families both failed frozen gates; pursue a materially stronger contextual successor and keep enwik9 diagnostic-only ([latest chart](runs/text-source-predictor-entropy-ceiling-publication-v1/README.md), [protocol](docs/benchmarks/2026-07-18-text-source-predictor-probe-protocol.md)) |
| Delimited tables | **50%** | TBS1 vs 7-Zip-9: 3.48% larger aggregate | Frozen gate failed ([decision](docs/benchmarks/2026-07-17-tbl1-public-validation-decision.md), [Fresh successor corpus protocol](docs/benchmarks/2026-07-17-tabular-successor-corpus-protocol.md)) |
| Dense matrices and time series | **20%** | DMS2 vs Brotli-11: 43.55% larger; 33.45 / 313.99 MB/s compression / decompression | Frozen gate failed ([evidence](runs/dms2-public-validation-v1/README.md)) |
| General binary/archive | **10%** | Exact `.clab` fallback; no strongest-standard lead established | Alpha |
| Incompressible/already compressed | **10%** | Exact fallback unit behavior; the honest target is an equally framed store-size tie, not an impossible random-data ratio win | No formal measurement yet; no-expansion, bounded selector, 1/4 GiB streaming, native speed/memory, corruption, and portability gates are frozen ([protocol](docs/benchmarks/2026-07-17-incompressible-precompressed-protocol.md)) |

The [category portfolio scorecard](docs/benchmarks/2026-07-16-category-portfolio-status.md)
tracks objective completion from 0% to 100% using ten equally weighted binary
evidence gates per category. Partial or failed validation does not receive
credit for a complete-validation gate; 100% requires private-holdout success
and independent reproduction.

Consumed validation families are never reused as fresh evidence. The benchmark
runner also has a checked-in [manifest-binding gate](runs/benchmark-manifest-binding-v1/README.md).

## Try it

Python 3.9 or newer is required. Install the published package from PyPI:

```bash
python -m pip install compression-lab
```

For a source checkout, native builds also require Rust stable:

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
