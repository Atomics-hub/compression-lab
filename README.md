# Compression Lab

Compression Lab is an open, evidence-driven lossless compression project. It
combines category specialists with a deterministic selector, exact fallback,
and a self-describing `.clab` container rather than forcing one transform onto
every kind of file.

The project is currently alpha. The stable CLI can compress arbitrary files;
the strongest verified specialist result is `JLS2` for newline-delimited flat
JSON logs.

## Best verified result

On a frozen one-time public validation over 214,372,886 previously unseen bytes
from Hadoop, OpenSSH, and OpenStack logs, JLS2 produced the smallest aggregate
output of every tested standard.

| Standard | Bytes: JLS2 / standard | JLS2 size result | Compress MB/s: JLS2 / standard | Decompress MB/s: JLS2 / standard | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| zstd level 9 | 3,999,168 / 5,614,733 | **28.77% smaller** | 155.83 / 222.03 | 165.88 / 1,547.88 | Size win; speed loss |
| Brotli quality 11 | 3,999,168 / 4,191,238 | **4.58% smaller aggregate** | 155.83 / 0.49 | 165.88 / 1,168.58 | Mixed: size win in 1 of 3 families |
| official PBC-only | 3,999,168 / 24,718,693 | **83.82% smaller** | 155.83 / 0.56 complete | 165.88 / 94.63 | Size and speed win |

All candidates restored the original bytes exactly. JLS2 also passed its
determinism, no-expansion, provenance, and complete-accounting gates.

Full transparency: the overall frozen gate was **not passed**. JLS2 needed to
beat Brotli-11 on two of three families but beat it on one, and its 165.88 MB/s
Linux decode speed missed the predeclared 250 MB/s target. Baseline speeds were
same-host contextual measurements; JLS2 used repeated trials. See the
[complete scorecard](docs/benchmarks/2026-07-16-jls2-public-validation-decision.md)
and [immutable GitHub Actions run](https://github.com/Atomics-hub/compression-lab/actions/runs/29542804015).

## Newest verified result: delimited tables

On 268,432,956 previously unseen UCI table bytes, bounded `TBS1` beat the
strongest exact standard by 7.35%–16.50% on three of four families. OCRB pixel
tables were the exception, making TBS1 3.48% larger than the strongest
aggregate standard, 7-Zip-9.

| Standard | Complete bytes | TBS1 size result | Compress MB/s: TBS1 / standard | Decompress MB/s: TBS1 / standard | Exact | Size beaten? |
| --- | ---: | --- | ---: | ---: | --- | --- |
| **TBS1 stream-dense** | **27,985,887** | candidate | **107.67 / —** | **403.39 / —** | ✅ | — |
| store | 268,432,956 | **89.57% smaller** | 107.67 / 1,382.93 | 403.39 / 812.06 | ✅ | ✅ |
| LZ4-1 | 95,128,929 | **70.58% smaller** | 107.67 / 878.25 | 403.39 / 423.25 | ✅ | ✅ |
| gzip-9 | 49,933,695 | **43.95% smaller** | 107.67 / 6.26 | 403.39 / 333.42 | ✅ | ✅ |
| zstd-3 | 44,511,580 | **37.13% smaller** | 107.67 / 247.36 | 403.39 / 343.45 | ✅ | ✅ |
| bzip2-9 | 34,291,969 | **18.39% smaller** | 107.67 / 2.39 | 403.39 / 23.68 | ✅ | ✅ |
| zstd-9 | 36,047,298 | **22.36% smaller** | 107.67 / 51.20 | 403.39 / 344.36 | ✅ | ✅ |
| zstd-19 | 28,942,224 | **3.30% smaller** | 107.67 / 1.31 | 403.39 / 372.62 | ✅ | ✅ |
| Brotli-11 | 28,315,299 | **1.16% smaller** | 107.67 / 0.43 | 403.39 / 258.15 | ✅ | ✅ |
| LZMA-9 | 27,049,040 | **3.46% larger** | 107.67 / 0.54 | 403.39 / 45.23 | ✅ | ❌ |
| 7-Zip-9 | **27,044,234** | **3.48% larger** | 107.67 / 1.93 | 403.39 / 141.44 | ✅ | ❌ |

The overall frozen gate was **not passed**: aggregate ratio missed, and one of
five decompression repetitions fell below 250 MB/s. Average speed was
107.67/403.39 MB/s; cold encode/decode peaks were 293.70/139.81 MiB. Exactness,
determinism, fallback safety, complete accounting, portability, and the 3/4
family gate passed. See the [full scorecard and raw evidence](docs/benchmarks/2026-07-17-tbl1-public-validation-decision.md).

### Portfolio scorecard

| Category | Evidence stage | Ratio position | Speed position | Current verdict |
| --- | --- | --- | --- | --- |
| JSON and machine logs | Public validation | Beat zstd-9 and PBC; mixed against Brotli-11 | Mixed | Strong specialist result; full gate not passed |
| Plain text and source | Development | Behind strongest dense baselines | Not frontier-leading | Not won |
| CSV and delimited tables | Public validation | Won 3/4 families by 7.35%–16.50%; aggregate 3.48% behind 7-Zip-9 | 107.67/403.39 MB/s average; one decode repetition missed its floor | Strong specialist signal; full gate not passed |
| Numeric and time series | Smoke only | Synthetic signal only | Untested | Not validated |
| General binary and archives | Development | Behind zstd-9 | Behind zstd | Not won |
| Incompressible or precompressed | Safety tests | Store/direct fallback | Category benchmark pending | Expansion safety only |

The [portfolio matrix](docs/benchmarks/2026-07-16-category-portfolio-status.md)
is updated as each category reaches a real decision gate. “Best” and
“state-of-the-art” claims require fresh unseen evidence and independent
reproduction; development wins do not count.

## Quick start

Python 3.9 or newer is required. Native development builds also require Rust
stable.

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

`compression-lab` is an equivalent command. Compression refuses to overwrite
an output unless `--force` is supplied. Standard input and output use `-`:

```bash
printf 'hello\n' | clab compress - -o - > hello.clab
clab decompress hello.clab -o -
```

The decoder rejects a declared output above 2 GiB by default. Change the bound
with `--max-output-size 512MiB` or explicitly disable it with `unlimited`.

## JSON-log specialist

`JLS2` preserves original whitespace, key order, number spelling, line endings,
and non-JSON fallback bytes. Each record-aligned segment independently chooses
the smaller of direct Zstandard and a JSON-columnar representation.

```bash
clab json-compress events.jsonl
clab json-info events.jsonl.jls2
clab json-decompress events.jsonl.jls2 -o restored.jsonl
```

The JSON-log API is experimental and deliberately separate from the stable
general-file API. The consumed Hadoop, OpenSSH, and OpenStack validation
families will not be used for tuning or rerun as fresh evidence.

## Python API

```python
import compresslab

frame = compresslab.compress(b"lossless data" * 1000)
original = compresslab.decompress(frame, max_output_size=10_000_000)

compressed_path = compresslab.compress_file("report.json")
restored_path = compresslab.decompress_file(
    compressed_path,
    "report.copy.json",
)
```

Experimental JSON logs:

```python
from compresslab.experimental import compress_json_logs, decompress_json_logs

frame = compress_json_logs(jsonl_bytes)
restored = decompress_json_logs(frame)
```

## Research and reproduction

Every promoted result must declare its corpus, license, split, candidate commit,
codec versions, runner, repetitions, exact round trips, complete archive bytes,
and claim ceiling. Private holdout data stays outside the repository.

Run the local verification suite:

```bash
scripts/build-native.sh
python3 -m unittest discover -s tests -v
```

Generate a deterministic smoke corpus and compare registered codecs:

```bash
python3 -m compresslab init-corpus --output corpora/smoke
python3 -m compresslab run \
  --corpus corpora/smoke \
  --output runs/smoke \
  --repetitions 3 \
  --warmups 1
```

Render a category scorecard from a checksummed JSON result:

```bash
python3 scripts/render-category-scorecard.py \
  runs/jls2-public-validation-summary.json
```

The benchmark output includes canonical `results.json`, aggregate `summary.csv`,
and a human-readable `report.md`. Aggregate ratios are byte-weighted, measured
trials follow warmups, operation order is deterministically shuffled, and any
round-trip, provenance, stability, or completeness failure remains visible.

## Documentation

- [Current category portfolio](docs/benchmarks/2026-07-16-category-portfolio-status.md)
- [JLS2 public-validation decision](docs/benchmarks/2026-07-16-jls2-public-validation-decision.md)
- [Tabular development baseline census](docs/benchmarks/2026-07-16-tabular-baseline-census.md)
- [TBL1 bounded column-transpose probe](docs/benchmarks/2026-07-16-tbl1-column-transpose-probe.md)
- [TBL1 dense development decision](docs/benchmarks/2026-07-16-tbl1-dense-development-decision.md)
- [TBL1 streaming development decision](docs/benchmarks/2026-07-16-tbl1-streaming-development-decision.md)
- [TBL1 public-validation readiness decision](docs/benchmarks/2026-07-16-tbl1-public-validation-readiness.md)
- [TBL1 public-validation decision and full chart](docs/benchmarks/2026-07-17-tbl1-public-validation-decision.md)
- [TBL1 public-validation lock](config/tbl1-public-validation-lock.json)
- [File-format contract](docs/file-format.md)
- [Release readiness](docs/release-readiness.md)
- [Security policy](SECURITY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Complete benchmark and rejected-hypothesis archive](docs/benchmarks/)

## License

Compression Lab is released under the [MIT License](LICENSE).
