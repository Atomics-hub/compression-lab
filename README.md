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

## Newest development result: delimited tables

On the frozen, licensed 187,321,615-byte tabular development corpus, bounded
`TBS1` streaming produced **12,134,137 bytes**: 9.62% smaller than Brotli-11
and 32.73% smaller than zstd-9. It beat the strongest exact baseline by at
least 5% on three of four data families.

| Standard | Complete bytes | TBS1 size result | Compress MB/s | Decompress MB/s | Peak compression RSS | Integrity / portability | Size win? |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| **TBS1 stream-dense** | **12,134,137** | reference | **60.92** | **356.76** | **409.72 MiB** | 20/20 + 1 GiB exact; Python reference | — |
| TBL1-dense whole-file | 12,012,933 | 1.01% larger | 51.30 | 250.41 | 402.55 MiB | 20/20 exact | **No** |
| Brotli-11 | 13,425,698 | **9.62% smaller** | 0.33 | 293.21 | 254.47 MiB | Exact on this runner | **Yes** |
| LZMA-9 | 14,275,744 | **15.00% smaller** | 0.78 | 38.91 | 801.78 MiB | Exact on this runner | **Yes** |
| 7-Zip-9 | 14,301,453 | **15.15% smaller** | 2.69 | 133.13 | 648.53 MiB | Exact on this runner | **Yes** |
| zstd-19 | 14,570,801 | **16.72% smaller** | 2.07 | 424.88 | 240.38 MiB | Exact on this runner | **Yes** |
| bzip2-9 | 17,627,845 | **31.16% smaller** | 1.43 | 20.86 | 255.45 MiB | Exact on this runner | **Yes** |
| zstd-9 | 18,038,379 | **32.73% smaller** | 61.91 | 380.94 | 233.70 MiB | Exact on this runner | **Yes** |
| gzip-9 | 19,811,936 | **38.75% smaller** | 8.03 | 362.97 | 269.00 MiB | Exact on this runner | **Yes** |
| zstd-3 | 22,715,433 | **46.58% smaller** | 185.13 | 333.23 | 327.27 MiB | Exact on this runner | **Yes** |
| LZ4-1 | 38,164,405 | **68.21% smaller** | 765.00 | 393.48 | 37.17 MiB | Exact on this runner | **Yes** |
| store | 187,321,615 | **93.52% smaller** | 1,242.40 | 719.78 | 25.03 MiB | Exact on this runner | **Yes** |

TBS1 speed is a clean five-repetition result; every repetition cleared the
50/250 MB/s thresholds. Memory is from isolated cold processes, and a separate
1 GiB no-newline file used 155.34/101.56 MiB for encode/decode. Baseline speed
and memory remain single-trial context, so this is not a controlled speed-win
claim. The streaming development gate **passed**; the complete category is
**not passed** until unseen public validation and independent reproduction.
See the [transparent streaming decision](docs/benchmarks/2026-07-16-tbl1-streaming-development-decision.md).

### Portfolio scorecard

| Category | Evidence stage | Ratio position | Speed position | Current verdict |
| --- | --- | --- | --- | --- |
| JSON and machine logs | Public validation | Beat zstd-9 and PBC; mixed against Brotli-11 | Mixed | Strong specialist result; full gate not passed |
| Plain text and source | Development | Behind strongest dense baselines | Not frontier-leading | Not won |
| CSV and delimited tables | Development streaming pass | TBS1 beat Brotli-11 by 9.62% aggregate and the strongest exact baseline by >=5% on 3/4 families | 60.92/356.76 MB/s; all five repetition aggregates passed | Streaming gate passed; category not validated |
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
- [File-format contract](docs/file-format.md)
- [Release readiness](docs/release-readiness.md)
- [Security policy](SECURITY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Complete benchmark and rejected-hypothesis archive](docs/benchmarks/)

## License

Compression Lab is released under the [MIT License](LICENSE).
