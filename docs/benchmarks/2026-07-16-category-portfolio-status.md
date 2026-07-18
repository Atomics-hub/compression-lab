# Compression category portfolio status

## Decision

Compression Lab is not yet on track to claim wins in every category. It now has
strong category-specific ratio signals in JSON/logs and delimited tables, but
both missed their complete frozen gates. DMS2's dense-matrix development win
also failed to generalize: both unseen families lost decisively. The right
architecture remains a portfolio of specialists behind a deterministic
selector with direct and store fallbacks.

This chart is the control surface for future category work. A green ratio cell
does not make the complete category green when speed, memory, integrity,
portability, or independent-evidence cells remain red or untested.

Objective completion uses ten equally weighted binary evidence gates from the
machine-readable portfolio. Partial, failed, planned, or development-only work
does not receive credit for a later-stage gate. A category reaches 100% only
after private-holdout success and independent reproduction. Across the seven
declared categories, strict category-evidence completion is currently
**22.86%**. This deliberately narrower number is not the broader engineering
readiness estimate: it withholds most credit until unseen and independent gates
actually pass.

| Category | Objective completion | Evidence stage | Ratio status | Speed status | Memory status | Complete category win? | Next gate |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| JSON and machine logs | **50%** | Public-validation partial | ✅ JLS2 produced 489,591 bytes from 96,934,483 unseen source bytes, 52.97% smaller than Brotli-11; both families won by 48.31% and 54.50% | ✅ 109.58 MB/s compression and 431.36 MB/s standalone decode; every speed gate passed | ❌ standalone decode was 621.3 MiB versus the frozen 512 MiB cap; compression memory passed | ❌ No; valid no-pass on one memory gate | Preserve the imported first score; diagnose RSS only on fresh development families and use different untouched validation families |
| Source-code bundles | **10%** | Practical baseline and structural probe complete | TS-H1 +0.213%; TS-H2 -0.383% vs Kanzi-max; both frozen gates failed | TS-H1 measured at 3.09/2.20 MB/s compression/decompression | TS-H1 measured at 1,889.0/1,908.1 MiB compression/decompression | ❌ No | Run the bounded research-ceiling tier; do not promote either rejected transform ([chart](../../runs/text-source-structural-transform-development-v1/publication/README.md)) |
| English Wikimedia wikitext | **10%** | Practical baseline and structural probe complete | TS-H1 +0.0068% vs Kanzi-max; frozen gate failed | TS-H1 measured at 1.83/1.65 MB/s compression/decompression | TS-H1 measured at 1,529.0/1,525.1 MiB compression/decompression | ❌ No | Run the bounded research-ceiling tier; keep enwik9 diagnostic-only ([chart](../../runs/text-source-structural-transform-development-v1/publication/README.md)) |
| Tabular CSV | **50%** | Public-validation partial | ⚠️ TBS1 won 3/4 families by 7.35%–16.50%, but lost aggregate to 7-Zip-9 by 3.48% after a 32.15% OCRB loss | ⚠️ 107.67/403.39 MB/s average; minimum compression passed, one decompression repetition failed at 163.51 MB/s | ✅ cold 293.70/139.81 MiB | ❌ No | Preserve the three-family signal; split image-like matrices into a separate category and use only fresh families for a successor |
| Dense numeric matrices and time series | **20%** | Public-validation partial | ❌ DMS2 was 46.57% larger than Brotli-11 on Gisette and 41.03% larger than bzip2-9 on Madelon; a baseline corpus-scope defect also invalidated the frozen aggregate | ❌ 33.45 MB/s aggregate and 27.77 MB/s minimum missed 50/45 MB/s gates; decompression passed | ❌ cold compression RSS was 630.45 MiB versus 512 MiB gate; decompression passed | ❌ No | Retain the first score, never tune on Gisette/Madelon, repair corpus plumbing, and require a materially new specialist on fresh development and validation families |
| General binary/archive | **10%** | Development | ❌ current encoder loses to zstd-9 | ❌ not Pareto-optimal | ⚠️ bounded-frame evidence only | ❌ No | Keep safe fallback; wait for a materially new specialist hypothesis |
| Incompressible/already compressed | **10%** | Frozen protocol; corpus pending | ✅ bounded store/direct fallback unit behavior; formal gate requires an exact equally framed store tie | — frozen 1,000/1,500 MB/s native encode/decode targets remain untested | — frozen 128 MiB RSS and 64 MiB window at 1/4 GiB remain untested | ❌ No | Construct and byte-verify the declared generated/licensed development corpus ([protocol](2026-07-17-incompressible-precompressed-protocol.md)) |

The machine-readable portfolio and required chart fields are in
`config/compression-category-matrix.json`. Every completed category or product
gate must add a checksummed JSON summary and render the same size, speed,
memory, integrity, comparability, and claim-ceiling fields used by
`scripts/render-category-scorecard.py`.

The fresh CLUE-LDS development ratio census and standalone delivery gate are in
[`runs/clue-json-log-development-census-v1`](../../runs/clue-json-log-development-census-v1/README.md)
and [`runs/jls2-native-decoder-v1`](../../runs/jls2-native-decoder-v1/README.md).
The latter passed locally and on a GitHub-hosted Apple ARM64 runner. The single
authorized CLUE acquisition and score subsequently completed as a valid
no-pass in
[GitHub Actions run 29606109504](https://github.com/Atomics-hub/compression-lab/actions/runs/29606109504).
The checksum-verified
[imported publication](../../runs/clue-jls2-public-validation-v1/publication/README.md)
shows a 52.97% aggregate gain over Brotli-11 and wins on both families, with
every gate passing except decoder RSS at 621.3 MiB versus 512 MiB. Both
validation ranges are now consumed and may not be reused. The category has not
achieved a complete public-validation pass.

The new source-code and English Wikimedia wikitext splits, extraction rules,
expanded practical baselines, bounded research-ceiling roster, and claim
boundaries are frozen in
[`docs/benchmarks/2026-07-17-text-source-category-protocol.md`](2026-07-17-text-source-category-protocol.md).
All seven development items were acquired and byte-verified in the separate
[`development acquisition`](2026-07-17-text-source-development-acquisition.md).
The frozen 15-codec practical census is complete: all 630 trials round-tripped
exactly and deterministically, with Kanzi-max leading both tracks. The
[offline-verifiable publication](../../runs/text-source-development-baseline-census-v1/publication/README.md)
contains the complete chart and public recalculation evidence. Exact upstream
identities and self-contained accounting rules are frozen for the still-pending
ZPAQ, paq8px, cmix, and NNCP research-ceiling tier. A codec's shipped parameter
profile may be reproduced on the declared same-input corpus, but the famous
enwik9 corpus and its published scores remain diagnostic-only. Both category
rows remain at 10% until the complete required baseline gate is reproduced.

The tabular split, exact-byte boundary, baseline roster, and first product gates
are frozen in
`docs/benchmarks/2026-07-16-tabular-corpus-protocol.md`. The first single-trial
baseline census is in
`docs/benchmarks/2026-07-16-tabular-baseline-census.md`; the native TBL1 point
decision is in
`docs/benchmarks/2026-07-16-tbl1-dense-development-decision.md`.
The bounded streaming decision is in
`docs/benchmarks/2026-07-16-tbl1-streaming-development-decision.md`.
The frozen setup is recorded in the
[TBL1 public-validation readiness decision](2026-07-16-tbl1-public-validation-readiness.md).
The first score, complete ten-standard chart, family results, failed gates, and
raw evidence are in the
[TBL1 public-validation decision](2026-07-17-tbl1-public-validation-decision.md).
The DMS2 first score, full two-item diagnostic chart, manifest-scope deviation,
and checksummed raw bundle are in
[`runs/dms2-public-validation-v1`](../../runs/dms2-public-validation-v1/README.md).

## Universal-selector consequence

The selector may eventually route among JSON/log, source-code, natural-language, tabular,
numeric, binary, and store/direct specialists. It must use bounded evidence
from the input itself, compare complete framed candidates where practical, and
never learn from a consumed validation or private-holdout family. A specialist
does not enter the universal product merely because it wins ratio: it must pass
its complete operational gate first.
