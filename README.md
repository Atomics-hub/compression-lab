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

On the frozen, licensed 187,321,615-byte tabular development corpus,
`TBL1-dense` produced **12,012,933 bytes**: 10.52% smaller than Brotli-11 and
33.40% smaller than zstd-9. It beat the strongest exact baseline by at least 5%
on three of four data families.

| Standard | Complete bytes | TBL1-dense size result | Compress MB/s | Decompress MB/s | Peak compression RSS | Exact? | Size win? |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| **TBL1-dense** | **12,012,933** | reference | **51.30** | **250.41** | **402.55 MiB** | 20/20 | — |
| Brotli-11 | 13,425,698 | **10.52% smaller** | 0.33 | 293.21 | 254.47 MiB | Yes | **Yes** |
| LZMA-9 | 14,275,744 | **15.85% smaller** | 0.78 | 38.91 | 801.78 MiB | Yes | **Yes** |
| 7-Zip-9 | 14,301,453 | **16.00% smaller** | 2.69 | 133.13 | 648.53 MiB | Yes | **Yes** |
| zstd-19 | 14,570,801 | **17.55% smaller** | 2.07 | 424.88 | 240.38 MiB | Yes | **Yes** |
| bzip2-9 | 17,627,845 | **31.85% smaller** | 1.43 | 20.86 | 255.45 MiB | Yes | **Yes** |
| zstd-9 | 18,038,379 | **33.40% smaller** | 61.91 | 380.94 | 233.70 MiB | Yes | **Yes** |
| gzip-9 | 19,811,936 | **39.37% smaller** | 8.03 | 362.97 | 269.00 MiB | Yes | **Yes** |
| zstd-3 | 22,715,433 | **47.12% smaller** | 185.13 | 333.23 | 327.27 MiB | Yes | **Yes** |
| LZ4-1 | 38,164,405 | **68.52% smaller** | 765.00 | 393.48 | 37.17 MiB | Yes | **Yes** |
| store | 187,321,615 | **93.59% smaller** | 1,242.40 | 719.78 | 25.03 MiB | Yes | **Yes** |

TBL1 figures are a clean five-repetition point decision; its isolated memory
run was exact on all four families. Baseline throughput and memory are
single-trial contextual measurements from the same development corpus, so the
table does not claim a controlled speed win. The complete category is **not
passed**: TBL1 still needs bounded streaming, more stable speed margin, unseen
public validation, cross-platform portability evidence, and independent
reproduction. See the
[transparent decision record](docs/benchmarks/2026-07-16-tbl1-dense-development-decision.md).

### Portfolio scorecard

| Category | Evidence stage | Ratio position | Speed position | Current verdict |
| --- | --- | --- | --- | --- |
| JSON and machine logs | Public validation | Beat zstd-9 and PBC; mixed against Brotli-11 | Mixed | Strong specialist result; full gate not passed |
| Plain text and source | Development | Behind strongest dense baselines | Not frontier-leading | Not won |
| CSV and delimited tables | Development point decision | TBL1-dense beat Brotli-11 by 10.52% aggregate and the strongest exact baseline by >=5% on 3/4 families | 51.30/250.41 MB/s point metrics; margins remain fragile | Point metrics passed; category not validated |
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
- [File-format contract](docs/file-format.md)
- [Release readiness](docs/release-readiness.md)
- [Security policy](SECURITY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Complete benchmark and rejected-hypothesis archive](docs/benchmarks/)

## License

Compression Lab is released under the [MIT License](LICENSE).
