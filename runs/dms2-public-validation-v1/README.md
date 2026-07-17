# DMS2 public-validation first score

Status: **not passed**.

On 71,104,540 locked Gisette and Madelon bytes, DMS2 produced 11,937,137 bytes. The strongest two-item baseline was brotli-11 at 8,315,469 bytes, so DMS2 was 43.55% larger.

## Family decisions

| Family | DMS2 bytes | Strongest standard | Standard bytes | DMS2 delta | Passed |
| --- | ---: | --- | ---: | ---: | --- |
| `uci-gisette-train` | 10,621,702 | brotli-11 | 7,246,803 | 46.57% larger | no |
| `uci-madelon-train` | 1,315,435 | bz2-9 | 932,738 | 41.03% larger | no |

## Two-item diagnostic comparison

| Codec | Complete bytes | DMS2 delta | Compress MB/s | Decompress MB/s | Cold RSS C/D MiB | Exact | DMS2 smaller? |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| dms2-stream | 11,937,137 | candidate | 33.45 | 313.99 | 630.5 / 86.9 | yes | candidate |
| store | 71,104,540 | -83.21% | 1594.70 | 815.60 | 26.1 / 26.1 | yes | yes |
| lz4-1 | 18,918,739 | -36.90% | 810.42 | 433.22 | 35.2 / 30.7 | yes | yes |
| gzip-9 | 10,371,868 | +15.09% | 3.18 | 382.82 | 106.9 / 170.8 | yes | no |
| bz2-9 | 8,627,565 | +38.36% | 1.47 | 22.71 | 115.4 / 163.9 | yes | no |
| zstd-3 | 11,741,186 | +1.67% | 255.16 | 316.92 | 228.5 / 163.2 | yes | no |
| zstd-9 | 10,772,378 | +10.81% | 45.53 | 359.80 | 228.2 / 162.2 | yes | no |
| zstd-19 | 8,524,178 | +40.04% | 1.48 | 398.58 | 241.2 / 160.4 | yes | no |
| brotli-11 | 8,315,469 | +43.55% | 0.40 | 248.06 | 218.2 / 25.2 | yes | no |
| lzma-9 | 8,444,740 | +41.36% | 0.47 | 39.77 | 749.1 / 224.4 | yes | no |
| 7zip-9 | 8,476,984 | +40.82% | 1.45 | 119.63 | 648.5 / 74.6 | yes | no |

## Decision and comparability

Failed frozen gates: `aggregate_ratio`, `cold_compression_memory`, `compression_speed`, `family_ratio_count`, `frozen_corpus`, `manifest_identity`, `minimum_repetition_compression_speed`, `shared_corpus`.

The baseline runner opened the four-item acquisition manifest while the candidate used the two-item locked projection.
Contextual same-host medians. Baselines and candidate ran in adjacent batches, and the baseline schedule included two extra unscored items.
Same-host cold-process peak RSS restricted to the two predeclared IDs.

The frozen DMS2 public-validation gate did not pass. These rows disclose the retained first attempt and support no category-win or state-of-the-art claim.
