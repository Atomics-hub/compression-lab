# Axiom Q1 record-neighborhood screen: rejected

![Axiom Q1 compared with every practical standard](comparison.svg)

> **Claim ceiling:** Training-split record-neighborhood representation experiment only. A passing result admits an Axiom prototype but is not validation, private-holdout, independent-reproduction, category-win, market-leading, world-best, or state-of-the-art evidence.

Q1 was exact and deterministic, but every measured item became larger than the strongest control. It is rejected and earns no category win. The tables retain all 15 practical standards and the prior TS-H1 attribution control.

## Source-code screen: CPython + TypeScript

| Codec / candidate | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Q1 beat it? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 70,199,538 | 1.00x | 100.00% | 393.03 | 551.60 | 2.14 / 2.14 | ✅ / ✅ | same-host evidence only | yes | Q1 91.01% smaller |
| LZ4-1 | 21,727,947 | 3.23x | 30.95% | 390.67 | 394.08 | 42.62 / 29.42 | ✅ / ✅ | same-host evidence only | yes | Q1 70.96% smaller |
| gzip-9 | 13,116,118 | 5.35x | 18.68% | 9.43 | 380.73 | 1.59 / 1.38 | ✅ / ✅ | same-host evidence only | yes | Q1 51.89% smaller |
| bzip2-9 | 10,300,995 | 6.81x | 14.67% | 9.32 | 35.57 | 8.47 / 4.72 | ✅ / ✅ | same-host evidence only | yes | Q1 38.74% smaller |
| bzip3-max | 8,126,940 | 8.64x | 11.58% | 7.10 | 10.47 | 2170.34 / 2170.81 | ✅ / ✅ | same-host evidence only | yes | Q1 22.36% smaller |
| zstd-3 | 13,219,757 | 5.31x | 18.83% | 193.17 | 383.70 | 39.45 / 7.81 | ✅ / ✅ | same-host evidence only | yes | Q1 52.27% smaller |
| zstd-9 | 10,995,786 | 6.38x | 15.66% | 50.85 | 295.06 | 60.20 / 9.78 | ✅ / ✅ | same-host evidence only | yes | Q1 42.61% smaller |
| zstd-19 | 9,279,147 | 7.57x | 13.22% | 1.92 | 391.96 | 132.66 / 13.77 | ✅ / ✅ | same-host evidence only | yes | Q1 32.00% smaller |
| zstd-22 ultra | 8,777,012 | 8.00x | 12.50% | 1.60 | 380.53 | 693.81 / 47.95 | ✅ / ✅ | same-host evidence only | yes | Q1 28.11% smaller |
| Brotli-11 | 8,659,166 | 8.11x | 12.34% | 0.41 | 278.91 | 291.98 / 19.83 | ✅ / ✅ | same-host evidence only | yes | Q1 27.13% smaller |
| XZ LZMA2-9e | 8,546,816 | 8.21x | 12.18% | 1.62 | 93.54 | 448.23 / 44.06 | ✅ / ✅ | same-host evidence only | yes | Q1 26.17% smaller |
| 7-Zip LZMA2-9 | 8,638,516 | 8.13x | 12.31% | 1.60 | 124.92 | 449.62 / 51.80 | ✅ / ✅ | same-host evidence only | yes | Q1 26.95% smaller |
| 7-Zip PPMd-9 | 8,224,267 | 8.54x | 11.72% | 6.33 | 6.47 | 261.06 / 261.14 | ✅ / ✅ | same-host evidence only | yes | Q1 23.27% smaller |
| Kanzi-max | 6,221,486 | 11.28x | 8.86% | 3.71 | 3.29 | 1465.14 / 1465.45 | ✅ / ✅ | same-host evidence only | no | Q1 1.42% larger |
| libbsc-max | 8,161,150 | 8.60x | 11.63% | 22.86 | 19.13 | 231.77 / 232.81 | ✅ / ✅ | same-host evidence only | yes | Q1 22.68% smaller |
| TS-H1 exact demux control | 6,216,920 | 11.29x | 8.86% | 2.60 | 2.20 | 1464.94 / 1465.30 | ✅ / ✅ | experimental Python transform + Kanzi; same-host evidence | no | Q1 1.50% larger |
| Axiom Q1 bounded record-neighborhood | 6,310,078 | 11.12x | 8.99% | 0.39 | 0.47 | 1465.02 / 1465.36 | ✅ / ✅ | experimental Python transform + Kanzi; same-host evidence | candidate | rejected: -1.42% vs Kanzi max; -1.50% vs TS-H1 |

## Wikimedia screen: English Wikibooks + Wikinews

| Codec / candidate | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Q1 beat it? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 134,213,921 | 1.00x | 100.00% | 381.41 | 1093.71 | 2.16 / 2.14 | ✅ / ✅ | same-host evidence only | yes | Q1 81.67% smaller |
| LZ4-1 | 71,853,822 | 1.87x | 53.54% | 563.32 | 326.22 | 67.42 / 31.98 | ✅ / ✅ | same-host evidence only | yes | Q1 65.77% smaller |
| gzip-9 | 45,874,934 | 2.93x | 34.18% | 12.34 | 234.54 | 1.59 / 1.38 | ✅ / ✅ | same-host evidence only | yes | Q1 46.38% smaller |
| bzip2-9 | 36,382,414 | 3.69x | 27.11% | 9.65 | 27.14 | 7.59 / 4.72 | ✅ / ✅ | same-host evidence only | yes | Q1 32.39% smaller |
| bzip3-max | 26,785,430 | 5.01x | 19.96% | 4.29 | 5.91 | 2215.39 / 2215.89 | ✅ / ✅ | same-host evidence only | yes | Q1 8.17% smaller |
| zstd-3 | 43,915,339 | 3.06x | 32.72% | 82.58 | 260.10 | 43.36 / 7.80 | ✅ / ✅ | same-host evidence only | yes | Q1 43.99% smaller |
| zstd-9 | 38,388,753 | 3.50x | 28.60% | 31.67 | 364.51 | 87.86 / 9.80 | ✅ / ✅ | same-host evidence only | yes | Q1 35.92% smaller |
| zstd-19 | 33,217,736 | 4.04x | 24.75% | 0.88 | 259.29 | 165.77 / 13.92 | ✅ / ✅ | same-host evidence only | yes | Q1 25.95% smaller |
| zstd-22 ultra | 31,933,325 | 4.20x | 23.79% | 0.80 | 381.04 | 725.19 / 69.52 | ✅ / ✅ | same-host evidence only | yes | Q1 22.97% smaller |
| Brotli-11 | 31,960,330 | 4.20x | 23.81% | 0.30 | 196.08 | 348.11 / 19.88 | ✅ / ✅ | same-host evidence only | yes | Q1 23.04% smaller |
| XZ LZMA2-9e | 31,282,084 | 4.29x | 23.31% | 0.84 | 58.93 | 642.23 / 65.61 | ✅ / ✅ | same-host evidence only | yes | Q1 21.37% smaller |
| 7-Zip LZMA2-9 | 31,347,798 | 4.28x | 23.36% | 0.85 | 86.89 | 643.61 / 83.53 | ✅ / ✅ | same-host evidence only | yes | Q1 21.53% smaller |
| 7-Zip PPMd-9 | 28,649,879 | 4.68x | 21.35% | 3.57 | 3.50 | 261.05 / 260.09 | ✅ / ✅ | same-host evidence only | yes | Q1 14.14% smaller |
| Kanzi-max | 24,156,788 | 5.56x | 18.00% | 2.38 | 2.15 | 1529.48 / 1525.77 | ✅ / ✅ | same-host evidence only | no | Q1 1.83% larger |
| libbsc-max | 26,890,194 | 4.99x | 20.04% | 13.30 | 15.27 | 394.36 / 396.44 | ✅ / ✅ | same-host evidence only | yes | Q1 8.52% smaller |
| TS-H1 exact demux control | 24,155,142 | 5.56x | 18.00% | 1.51 | 1.42 | 1529.00 / 1525.12 | ✅ / ✅ | experimental Python transform + Kanzi; same-host evidence | no | Q1 1.83% larger |
| Axiom Q1 bounded record-neighborhood | 24,598,152 | 5.46x | 18.33% | 0.64 | 0.78 | 1529.09 / 1525.33 | ✅ / ✅ | experimental Python transform + Kanzi; same-host evidence | candidate | rejected: -1.83% vs Kanzi max; -1.83% vs TS-H1 |

## Evidence boundary

- Frozen result SHA-256: `724594043816e47fe3f0eabfe7870ee8f54a3fb75f1cdbd3a4b5696df297882a`.
- Trial-receipt manifest SHA-256: `85d2812521a5761eb0ad1ed8b50924be564c38321a41e76f90b1238c411884b1`.
- Public evidence SHA-256: `fe2681382da4ce24d721086b2b5b7ca5e7892373dd24cb5c4da2bcc2a82a9194`.
- Size comparability: Every byte row is a complete decodable artifact over the identical two-item track subset. Q1 includes transform metadata, permutation, backend payload, and outer frame.
- Speed/memory comparability: Practical, TS-H1, and Q1 rows retain measured same-host medians and peak RSS. Cross-run timings are directional because background load and runner overhead differ.
- Public validation and private holdout were not opened.
