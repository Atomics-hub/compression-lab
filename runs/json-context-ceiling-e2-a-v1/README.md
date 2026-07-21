# E2-A JSON context-ceiling result

![Complete-byte and memory comparison](comparison.svg)

Evidence stage: **development-only diagnostic**. Decision: **kill_bounded_level5_lane**.
Best memory-eligible method: **zpaq-5-m54** at 1,613,165 complete bytes.

| Method | Max block | Complete bytes | Gain vs E1 Kanzi | Compress RSS | Decode RSS | <=460 MiB both |
|---|---:|---:|---:|---:|---:|:---:|
| E1 Kanzi-max | 1 GiB | 1,712,149 | reference | 1,526.7 MiB* | 1,526.7 MiB* | no* |
| zpaq-5-m54 | 16 MiB | 1,613,165 | 5.78% | 358.3 MiB | 343.3 MiB | yes |
| zpaq-5-m55 | 32 MiB | 1,502,978 | 12.21% | 622.9 MiB | 592.2 MiB | no |
| zpaq-5-m56 | 64 MiB | 1,384,350 | 19.14% | 951.1 MiB | 936.3 MiB | no |
| zpaq-5-m57 | 128 MiB | 1,347,061 | 21.32% | 1269.2 MiB | 1272.1 MiB | no |
| zpaq-5-m510 | 1024 MiB | 1,347,064 | 21.32% | 1270.3 MiB | 1272.1 MiB | no |

`*` E1's published peak is a cross-phase same-run context value, not a same-run E2 speed/RSS comparison. E2 timing is contextual only.

This result used only the three previously consumed CLUE development items. It is not an unseen score, candidate win, private holdout, independent reproduction, practical-speed result, or state-of-the-art claim. Both prior public-validation families remain consumed; a future candidate requires a newly frozen lineage-distinct corpus.

Result SHA-256: `20ff8e78d1738aa72f0b114e18e586213c6c69a34b49250d93fee5110aa4b0da`.
