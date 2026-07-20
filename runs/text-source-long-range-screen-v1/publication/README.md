# Long-range factorization screen: rejected

![Long-range diagnostics and every practical standard](comparison.svg)

> **Claim ceiling:** Training-split Kanzi pipeline decomposition only. These custom Kanzi archives are exact competitor diagnostics, not Axiom artifacts, Axiom wins, validation results, private-holdout results, novel-algorithm results, or state-of-the-art evidence.

The screen tested whether explicit single-reference LZP factorization improves Kanzi's TPAQX path. It did not. No Axiom codec was built, admitted, or credited with a win.

## Source-code screen: CPython + TypeScript

| Codec / diagnostic | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 70,199,538 | 1.00x | 100.00% | 393.03 | 551.60 | 2.14 / 2.14 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| LZ4-1 | 21,727,947 | 3.23x | 30.95% | 390.67 | 394.08 | 42.62 / 29.42 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| gzip-9 | 13,116,118 | 5.35x | 18.68% | 9.43 | 380.73 | 1.59 / 1.38 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| bzip2-9 | 10,300,995 | 6.81x | 14.67% | 9.32 | 35.57 | 8.47 / 4.72 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| bzip3-max | 8,126,940 | 8.64x | 11.58% | 7.10 | 10.47 | 2170.34 / 2170.81 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-3 | 13,219,757 | 5.31x | 18.83% | 193.17 | 383.70 | 39.45 / 7.81 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-9 | 10,995,786 | 6.38x | 15.66% | 50.85 | 295.06 | 60.20 / 9.78 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-19 | 9,279,147 | 7.57x | 13.22% | 1.92 | 391.96 | 132.66 / 13.77 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-22 ultra | 8,777,012 | 8.00x | 12.50% | 1.60 | 380.53 | 693.81 / 47.95 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| Brotli-11 | 8,659,166 | 8.11x | 12.34% | 0.41 | 278.91 | 291.98 / 19.83 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| XZ LZMA2-9e | 8,546,816 | 8.21x | 12.18% | 1.62 | 93.54 | 448.23 / 44.06 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| 7-Zip LZMA2-9 | 8,638,516 | 8.13x | 12.31% | 1.60 | 124.92 | 449.62 / 51.80 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| 7-Zip PPMd-9 | 8,224,267 | 8.54x | 11.72% | 6.33 | 6.47 | 261.06 / 261.14 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| Kanzi-max | 6,221,486 | 11.28x | 8.86% | 3.71 | 3.29 | 1465.14 / 1465.45 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| libbsc-max | 8,161,150 | 8.60x | 11.63% | 22.86 | 19.13 | 231.77 / 232.81 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| K1 custom Kanzi: LZP + level-9 transforms + TPAQX | 6,322,746 | 11.10x | 9.01% | 3.41 | 2.89 | 1459.44 / 1457.23 | ✅ / ✅ | custom Kanzi, same-host evidence only | not applicable: competitor diagnostic | rejected: -1.63% vs Kanzi max |
| K2 custom Kanzi: LZP + TEXT + UTF + TPAQX | 6,512,148 | 10.78x | 9.28% | 3.02 | 2.71 | 1461.64 / 1465.88 | ✅ / ✅ | custom Kanzi, same-host evidence only | not applicable: competitor diagnostic | rejected: -4.67% vs Kanzi max |
| K3 custom Kanzi: LZP + TPAQX | 6,630,029 | 10.59x | 9.44% | 2.66 | 2.36 | 1466.94 / 1466.81 | ✅ / ✅ | custom Kanzi, same-host evidence only | not applicable: competitor diagnostic | rejected: -6.57% vs Kanzi max |
| Axiom long-range prototype (not built) | — | — | — | — | — | — / — | — / — | no artifact | no artifact; no win | prototype not admitted; direction rejected |

## Wikimedia screen: English Wikibooks + Wikinews

| Codec / diagnostic | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 134,213,921 | 1.00x | 100.00% | 381.41 | 1093.71 | 2.16 / 2.14 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| LZ4-1 | 71,853,822 | 1.87x | 53.54% | 563.32 | 326.22 | 67.42 / 31.98 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| gzip-9 | 45,874,934 | 2.93x | 34.18% | 12.34 | 234.54 | 1.59 / 1.38 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| bzip2-9 | 36,382,414 | 3.69x | 27.11% | 9.65 | 27.14 | 7.59 / 4.72 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| bzip3-max | 26,785,430 | 5.01x | 19.96% | 4.29 | 5.91 | 2215.39 / 2215.89 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-3 | 43,915,339 | 3.06x | 32.72% | 82.58 | 260.10 | 43.36 / 7.80 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-9 | 38,388,753 | 3.50x | 28.60% | 31.67 | 364.51 | 87.86 / 9.80 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-19 | 33,217,736 | 4.04x | 24.75% | 0.88 | 259.29 | 165.77 / 13.92 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| zstd-22 ultra | 31,933,325 | 4.20x | 23.79% | 0.80 | 381.04 | 725.19 / 69.52 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| Brotli-11 | 31,960,330 | 4.20x | 23.81% | 0.30 | 196.08 | 348.11 / 19.88 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| XZ LZMA2-9e | 31,282,084 | 4.29x | 23.31% | 0.84 | 58.93 | 642.23 / 65.61 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| 7-Zip LZMA2-9 | 31,347,798 | 4.28x | 23.36% | 0.85 | 86.89 | 643.61 / 83.53 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| 7-Zip PPMd-9 | 28,649,879 | 4.68x | 21.35% | 3.57 | 3.50 | 261.05 / 260.09 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| Kanzi-max | 24,156,788 | 5.56x | 18.00% | 2.38 | 2.15 | 1529.48 / 1525.77 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| libbsc-max | 26,890,194 | 4.99x | 20.04% | 13.30 | 15.27 | 394.36 / 396.44 | ✅ / ✅ | same-host evidence only | no Axiom artifact | tested practical standard |
| K1 custom Kanzi: LZP + level-9 transforms + TPAQX | 24,207,040 | 5.54x | 18.04% | 2.95 | 2.37 | 1527.38 / 1523.14 | ✅ / ✅ | custom Kanzi, same-host evidence only | not applicable: competitor diagnostic | rejected: -0.21% vs Kanzi max |
| K2 custom Kanzi: LZP + TEXT + UTF + TPAQX | 24,219,706 | 5.54x | 18.05% | 2.22 | 1.96 | 1527.41 / 1526.00 | ✅ / ✅ | custom Kanzi, same-host evidence only | not applicable: competitor diagnostic | rejected: -0.26% vs Kanzi max |
| K3 custom Kanzi: LZP + TPAQX | 24,928,938 | 5.38x | 18.57% | 1.79 | 1.61 | 1523.48 / 1523.42 | ✅ / ✅ | custom Kanzi, same-host evidence only | not applicable: competitor diagnostic | rejected: -3.20% vs Kanzi max |
| Axiom long-range prototype (not built) | — | — | — | — | — | — / — | — / — | no artifact | no artifact; no win | prototype not admitted; direction rejected |

## Evidence boundary

- Frozen result SHA-256: `faad7b7736685a30e451cd7fc94f4fde9898b16afa102a0291e418f86a544d12`.
- Trial-receipt manifest SHA-256: `4129c6d96b0e7fbfd51221bfa983265c42de6cecd5ff0a9f83e9c28bb7b5afa9`.
- Public evidence SHA-256: `b4ecb32cc7bd241ca2c7f415a58ef151838eb179ac5f6bb9db9bc0bce0ff7e87`.
- Runner comparability (size): All rows with bytes are complete decodable archives over the identical track subset. The Axiom row is intentionally empty because no prototype was admitted.
- Runner comparability (speed/memory): Practical and custom Kanzi rows retain measured same-host medians and peak RSS; cross-runner timings are directional, not controlled hardware-independent rankings.
- Public validation and private holdout were not opened.
