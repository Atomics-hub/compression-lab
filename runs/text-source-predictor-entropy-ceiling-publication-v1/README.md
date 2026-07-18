# TS-P1 / WK-P1 predictor entropy-ceiling result

![Predictor estimates and every practical standard](comparison.svg)

> **Claim ceiling:** Sampled development entropy-ceiling probe only. Estimated bytes are not a decodable artifact, codec result, baseline win, validation result, or state-of-the-art claim. Public validation and private holdout remain sealed and unaccessed.

The predictor rows are conservative ideal-code estimates, not decodable archives. They cannot beat a standard or support a codec claim.

Every tested practical standard remains visible on the identical evaluation subset.

## Source-code evaluation: Rust + LLVM

Dictionary: **129,838 bytes**, **8,192 entries**. P2 improvement over P1: **13.34%**. Full-codec admission: **no**.

| Codec / estimate | Complete or projected bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 459,250,035 | 1.00x | 100.00% | 613.32 | 986.19 | 2.14 / 2.16 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| LZ4-1 | 143,287,266 | 3.21x | 31.20% | 866.63 | 521.24 | 62.25 / 33.06 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| gzip-9 | 85,216,475 | 5.39x | 18.56% | 11.55 | 367.14 | 1.61 / 1.38 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| bzip2-9 | 64,978,442 | 7.07x | 14.15% | 11.14 | 40.64 | 8.47 / 4.72 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| bzip3-max | 51,713,161 | 8.88x | 11.26% | 7.32 | 10.67 | 2595.77 / 2596.20 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-3 | 82,398,815 | 5.57x | 17.94% | 107.12 | 348.75 | 41.62 / 7.81 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-9 | 68,719,874 | 6.68x | 14.96% | 31.48 | 346.58 | 82.97 / 9.83 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-19 | 57,336,554 | 8.01x | 12.48% | 1.51 | 469.19 | 219.28 / 13.81 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-22 ultra | 54,807,261 | 8.38x | 11.93% | 1.25 | 398.50 | 1017.45 / 133.81 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| Brotli-11 | 55,069,236 | 8.34x | 11.99% | 0.46 | 254.34 | 264.61 / 20.77 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| XZ LZMA2-9e | 53,598,516 | 8.57x | 11.67% | 1.05 | 84.06 | 674.75 / 65.62 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| 7-Zip LZMA2-9 | 53,907,239 | 8.52x | 11.74% | 1.13 | 127.67 | 2562.62 / 297.02 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| 7-Zip PPMd-9 | 51,233,682 | 8.96x | 11.16% | 5.30 | 4.49 | 261.06 / 261.12 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| Kanzi-max | 39,328,985 | 11.68x | 8.56% | 3.26 | 2.75 | 1890.55 / 1909.70 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| libbsc-max | 50,916,526 | 9.02x | 11.09% | 18.93 | 20.47 | 1377.30 / 1399.02 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| Axiom P0 byte unigram estimate | 297,278,159 | 1.54x | 64.73% | — | — | — / — | — / — | not an artifact | ineligible estimate | diagnostic ablation only |
| Axiom P1 byte/class estimate | 271,768,878 | 1.69x | 59.18% | — | — | — / — | — / — | not an artifact | ineligible estimate | diagnostic ablation only |
| Axiom P2 mixed token/class estimate | 235,513,209 | 1.95x | 51.28% | — | — | — / — | — / — | not an artifact | ineligible estimate | reject_predictor_family_below_entropy_headroom_gate |

## Wikimedia evaluation: English Wikiversity

Dictionary: **79,833 bytes**, **8,192 entries**. P2 improvement over P1: **25.41%**. Full-codec admission: **no**.

| Codec / estimate | Complete or projected bytes | Ratio | Size % | Compress MB/s | Decompress MB/s | Peak RSS C / D MiB | Exact / deterministic | Portability | Axiom beat? | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Store | 67,097,252 | 1.00x | 100.00% | 380.47 | 1072.42 | 2.14 / 2.14 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| LZ4-1 | 31,992,660 | 2.10x | 47.68% | 555.29 | 385.64 | 46.83 / 31.83 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| gzip-9 | 20,522,682 | 3.27x | 30.59% | 18.18 | 387.48 | 1.59 / 1.38 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| bzip2-9 | 16,579,439 | 4.05x | 24.71% | 9.99 | 22.36 | 7.59 / 4.72 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| bzip3-max | 12,460,787 | 5.38x | 18.57% | 6.56 | 8.02 | 2215.31 / 2215.80 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-3 | 19,477,545 | 3.44x | 29.03% | 97.72 | 381.33 | 40.77 / 7.81 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-9 | 17,082,042 | 3.93x | 25.46% | 24.93 | 389.88 | 87.56 / 9.78 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-19 | 14,888,022 | 4.51x | 22.19% | 1.01 | 382.14 | 156.66 / 13.78 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| zstd-22 ultra | 14,307,550 | 4.69x | 21.32% | 0.99 | 381.60 | 722.98 / 69.52 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| Brotli-11 | 14,300,433 | 4.69x | 21.31% | 0.34 | 230.98 | 334.00 / 19.94 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| XZ LZMA2-9e | 13,982,116 | 4.80x | 20.84% | 0.98 | 64.82 | 642.16 / 65.61 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| 7-Zip LZMA2-9 | 14,021,052 | 4.79x | 20.90% | 1.01 | 97.65 | 643.55 / 82.39 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| 7-Zip PPMd-9 | 13,032,168 | 5.15x | 19.42% | 3.04 | 2.96 | 261.03 / 260.12 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| Kanzi-max | 10,924,274 | 6.14x | 16.28% | 2.07 | 2.28 | 1527.73 / 1524.16 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| libbsc-max | 12,586,646 | 5.33x | 18.76% | 12.65 | 17.14 | 363.02 / 368.61 | ✅ / ✅ | same-host evidence only | not established | tested practical baseline |
| Axiom P0 byte unigram estimate | 43,235,525 | 1.55x | 64.44% | — | — | — / — | — / — | not an artifact | ineligible estimate | diagnostic ablation only |
| Axiom P1 byte/class estimate | 39,869,065 | 1.68x | 59.42% | — | — | — / — | — / — | not an artifact | ineligible estimate | diagnostic ablation only |
| Axiom P2 mixed token/class estimate | 29,738,777 | 2.26x | 44.32% | — | — | — / — | — / — | not an artifact | ineligible estimate | reject_predictor_family_below_entropy_headroom_gate |

## Evidence boundary

- Result SHA-256: `300a9cd657b0949b9b4af165d6e080ff3962afb1281a764bb5c894b508d2fa68`.
- Public evidence SHA-256: `ecbece60ba1f09956defef8fcbe04d27db299ccbde0aaf5c5e934f713596c2b4`.
- Runner comparability (size): Predictor rows are conservative sampled ideal-code projections and are not comparable as complete decodable artifacts; practical rows are exact complete bytes on the identical evaluation items.
- Runner comparability (speed/memory): No predictor speed or memory claim exists; practical rows retain measured same-host values.
- Public validation and private holdout remain sealed and unaccessed.
