# CLUE-LDS JSON/log successor corpus protocol

## Decision

Use CLUE-LDS as the fresh independent corpus for the next JLS2 successor gate.
Freeze the ranges below before acquisition, open only the development ranges,
and retain the validation ranges for one candidate-frozen score.

CLUE-LDS is materially different from the consumed LogTrie families. It
contains about 50 million real, anonymized cloud-storage user events collected
over more than five years. The publisher supplies the records as nested JSON
with stable top-level event fields and variable `params` and `location`
objects. The dataset is CC-BY-4.0 and has DOI
[`10.5281/zenodo.7119953`](https://doi.org/10.5281/zenodo.7119953).

## Frozen source

| Field | Value |
| --- | --- |
| Zenodo record | `7119953` |
| Archive | `clue.zip` |
| Archive bytes | `635,105,552` |
| Publisher MD5 | `9e318370f96b68077667e9cdc05f26a5` |
| Member | `clue.json` |
| License | `CC-BY-4.0` |
| Record boundary | one original JSON object per line |

The acquisition script verifies the published byte count and MD5 before
opening the archive, computes SHA-256, rejects unexpected ZIP members or path
traversal, validates every selected JSON object, and preserves each selected
line byte-for-byte.

## Frozen split

| Split | Family | Inclusive official IDs | Records | Status |
| --- | --- | ---: | ---: | --- |
| development | `clue_early` | 1–250,000 | 250,000 | authorized |
| development | `clue_middle` | 10,000,001–10,250,000 | 250,000 | authorized |
| development | `clue_late` | 20,000,001–20,250,000 | 250,000 | authorized |
| public validation | `clue_validation_a` | 35,000,001–35,250,000 | 250,000 | sealed |
| public validation | `clue_validation_b` | 45,000,001–45,250,000 | 250,000 | sealed |

The temporal spacing is fixed to expose the selector and representation to
schema and event-distribution drift. Ranges may not be moved after seeing size,
speed, event-type, or codec results. Validation acquisition requires the
explicit `--allow-public-validation` flag and is prohibited until the
candidate, competitors, gates, runner, and maximum scored attempts are locked.

## Development gate

The first development census must compare complete exact bytes for JLS2,
zstd-3, zstd-9, zstd-19, Brotli-11, gzip-9, bzip2-9, LZMA-9, 7-Zip-9, LZ4-1,
and store. It must report each temporal family plus aggregate size,
compression/decompression speed, determinism, exactness, and peak memory.

No representation change is promoted unless it beats the current JLS2 frame
on aggregate complete bytes without regressing any family by more than 1%, and
the complete product passes at least 100 MB/s compression, 250 MB/s
decompression, and 512 MiB cold-process memory in both directions. The direct
fallback remains mandatory.

## Claim boundary

Development results from the first three ranges are tuning evidence only. The
two validation ranges remain one-time public evidence and are not a private
holdout. A pass would support only the structured cloud-event-log category; it
would not establish universal, market-leading, world-best, or state-of-the-art
compression.

## Sources

- [Zenodo dataset record](https://zenodo.org/records/7119953)
- [Official Zenodo API record](https://zenodo.org/api/records/7119953)
- [Dataset methodology paper](https://doi.org/10.1109/BigData55660.2022.10020672)
