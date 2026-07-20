# Text/source structural transform development result

![Axiom structural variants compared with every practical standard](comparison.svg)

> **Claim ceiling:** Development structural-representation evidence only. Public validation and private holdout remain sealed, research-ceiling codecs remain pending, and this result cannot support a category-win, market-leading, world-best, or state-of-the-art claim.

Axiom rows are development hypotheses. A green ratio alone is not a category win.

## Source-code bundles

Practical ratio leader: **Kanzi-max**.

| Codec / candidate | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 529,449,573 | 1.00x | 100.00% | 598.62 | 936.29 | 2.14 / 2.16 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| LZ4-1 | 165,015,213 | 3.21x | 31.17% | 782.35 | 524.13 | 62.25 / 33.06 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| gzip-9 | 98,332,593 | 5.38x | 18.57% | 11.76 | 386.81 | 1.61 / 1.38 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| bzip2-9 | 75,279,437 | 7.03x | 14.22% | 11.39 | 41.83 | 8.47 / 4.72 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| bzip3-max | 59,840,101 | 8.85x | 11.30% | 7.65 | 11.16 | 2595.77 / 2596.20 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-3 | 95,618,572 | 5.54x | 18.06% | 119.38 | 370.16 | 41.62 / 7.81 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-9 | 79,715,660 | 6.64x | 15.06% | 34.77 | 355.19 | 82.97 / 9.83 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-19 | 66,615,701 | 7.95x | 12.58% | 1.63 | 479.46 | 219.28 / 13.81 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-22 ultra | 63,584,273 | 8.33x | 12.01% | 1.35 | 415.26 | 1017.45 / 133.81 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| Brotli-11 | 63,728,402 | 8.31x | 12.04% | 0.48 | 269.85 | 291.98 / 20.77 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| XZ LZMA2-9e | 62,145,332 | 8.52x | 11.74% | 1.16 | 89.34 | 674.75 / 65.62 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| 7-Zip LZMA2-9 | 62,545,755 | 8.46x | 11.81% | 1.24 | 133.48 | 2562.62 / 297.02 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| 7-Zip PPMd-9 | 59,457,949 | 8.90x | 11.23% | 5.68 | 4.91 | 261.06 / 261.14 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| Kanzi-max | 45,550,471 | 11.62x | 8.60% | 3.47 | 2.95 | 1890.55 / 1909.70 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| libbsc-max | 59,077,676 | 8.96x | 11.16% | 20.31 | 21.27 | 1377.30 / 1399.02 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| Axiom TS-H1 demux | 45,453,564 | 11.65x | 8.59% | 3.09 | 2.20 | 1889.00 / 1908.05 | ✅ / ✅ | untested | candidate | development hypothesis rejected |
| Axiom TS-H2 extension lanes | 45,725,000 | 11.58x | 8.64% | 1.72 | 1.91 | 1888.56 / 1907.45 | ✅ / ✅ | untested | candidate | development hypothesis rejected |

## English Wikimedia wikitext

Practical ratio leader: **Kanzi-max**.

| Codec / candidate | Complete bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 201,311,173 | 1.00x | 100.00% | 399.61 | 1139.30 | 2.16 / 2.14 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| LZ4-1 | 103,846,482 | 1.94x | 51.59% | 587.85 | 360.58 | 67.42 / 31.98 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| gzip-9 | 66,397,616 | 3.03x | 32.98% | 14.49 | 283.19 | 1.59 / 1.38 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| bzip2-9 | 52,961,853 | 3.80x | 26.31% | 10.23 | 26.56 | 7.59 / 4.72 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| bzip3-max | 39,246,217 | 5.13x | 19.50% | 5.09 | 6.79 | 2215.39 / 2215.89 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-3 | 63,392,884 | 3.18x | 31.49% | 91.31 | 305.06 | 43.36 / 7.81 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-9 | 55,470,795 | 3.63x | 27.55% | 30.46 | 390.69 | 87.86 / 9.80 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-19 | 48,105,758 | 4.18x | 23.90% | 0.97 | 304.51 | 165.77 / 13.92 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| zstd-22 ultra | 46,240,875 | 4.35x | 22.97% | 0.90 | 399.75 | 725.19 / 69.52 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| Brotli-11 | 46,260,763 | 4.35x | 22.98% | 0.33 | 216.51 | 348.11 / 19.94 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| XZ LZMA2-9e | 45,264,200 | 4.45x | 22.48% | 0.93 | 63.72 | 642.23 / 65.61 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| 7-Zip LZMA2-9 | 45,368,850 | 4.44x | 22.54% | 0.94 | 94.58 | 643.61 / 83.53 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| 7-Zip PPMd-9 | 41,682,047 | 4.83x | 20.71% | 3.54 | 3.46 | 261.05 / 260.12 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| Kanzi-max | 35,081,062 | 5.74x | 17.43% | 2.37 | 2.30 | 1529.48 / 1525.77 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| libbsc-max | 39,476,840 | 5.10x | 19.61% | 13.71 | 16.61 | 394.36 / 396.44 | ✅ / ✅ | same-host evidence only | no | tested practical baseline |
| Axiom TS-H1 demux | 35,078,683 | 5.74x | 17.43% | 1.83 | 1.65 | 1529.00 / 1525.12 | ✅ / ✅ | untested | candidate | development hypothesis rejected |

## Evidence boundary

- Structural results SHA-256: `92a29a1e184a04293ce04bfdd05f5e7ba7dd0d7f12873edce3d2926c1628db93`
- Structural receipt-manifest SHA-256: `d2839e05af5d1186b4264c09ddcc1fc63adeb5f899ac793091c0071d85a55ed4`
- Baseline results SHA-256: `08b66858cc5b7438c3aa134545642a54c8ea434b9c16d86db3ce8cc46122a5bc`
- Baseline receipt-manifest SHA-256: `a41eea623b86dd0382bf9d3136d1294864c5e63935e165fee1b19c8e83d3babf`
- Structural public recalculation evidence: [`evidence.json`](evidence.json), SHA-256 `e7b25f117866983214192183d076ed1cbac74490569653e302308c87ddeb3e97`.
- Bound baseline public-evidence SHA-256: `b28429e3d12542eda21d03d981b9452cba2d4a329252e4876803b62852f1299f`.
- Structural public trial-receipt manifest SHA-256: `362548cbbb6a85e2e7c2e8792dd70343a2f76be525b7b1d5628965b3b9413e4b`.
- Public evidence retains every decision-bearing field from all 33 structural trials; process streams are replaced by byte counts and SHA-256 commitments.
- Failed structural trials: **0**; all required item/variant gates complete: **true**.
- Corruption preflight: AXTP2 authenticates the complete backend payload with SHA-256 before backend decoding and deletes a rejected extraction; all 696 possible one-bit mutations and all 87 truncated lengths of its fixed header are rejected. Truncated or appended payloads are rejected without retaining stale/partial output.
- Runner comparability (size): Fully comparable: identical declared source bytes and complete self-contained artifact bytes are used for every row.
- Runner comparability (speed/memory): Contextual rather than paired: all rows use the same host and one codec thread, but candidate subprocess-chain measurements occur in the later structural run while baseline measurements come from the separately checksummed census.
- Public validation and private holdout remain sealed.
- Research-ceiling rows remain pending: ZPAQ, paq8px, cmix, and NNCP.
