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

| Category | Evidence stage | Ratio status | Speed status | Memory status | Complete category win? | Next gate |
| --- | --- | --- | --- | --- | --- | --- |
| JSON and machine logs | Public-validation partial | ✅ JLS2 produced 489,591 bytes from 96,934,483 unseen source bytes, 52.97% smaller than Brotli-11; both families won by 48.31% and 54.50% | ✅ 109.58 MB/s compression and 431.36 MB/s standalone decode; every speed gate passed | ❌ standalone decode was 621.3 MiB versus the frozen 512 MiB cap; compression memory passed | ❌ No; valid no-pass on one memory gate | Preserve the imported first score; diagnose RSS only on fresh development families and use different untouched validation families |
| Source-code bundles | Unacquired protocol | — no score; four licensed development and four lineage-disjoint validation projects frozen | — untested | — untested | ❌ No | Acquire only declared development releases and run the expanded practical census before choosing a hypothesis |
| English Wikimedia wikitext | Unacquired protocol | — no score; three development and three validation projects frozen; enwik9 is diagnostic-only | — untested | — untested | ❌ No | Acquire only declared development dumps and run practical plus bounded research-ceiling baselines |
| Tabular CSV | Public-validation partial | ⚠️ TBS1 won 3/4 families by 7.35%–16.50%, but lost aggregate to 7-Zip-9 by 3.48% after a 32.15% OCRB loss | ⚠️ 107.67/403.39 MB/s average; minimum compression passed, one decompression repetition failed at 163.51 MB/s | ✅ cold 293.70/139.81 MiB | ❌ No | Preserve the three-family signal; split image-like matrices into a separate category and use only fresh families for a successor |
| Dense numeric matrices and time series | Public-validation partial | ❌ DMS2 was 46.57% larger than Brotli-11 on Gisette and 41.03% larger than bzip2-9 on Madelon; a baseline corpus-scope defect also invalidated the frozen aggregate | ❌ 33.45 MB/s aggregate and 27.77 MB/s minimum missed 50/45 MB/s gates; decompression passed | ❌ cold compression RSS was 630.45 MiB versus 512 MiB gate; decompression passed | ❌ No | Retain the first score, never tune on Gisette/Madelon, repair corpus plumbing, and require a materially new specialist on fresh development and validation families |
| General binary/archive | Development | ❌ current encoder loses to zstd-9 | ❌ not Pareto-optimal | ⚠️ bounded-frame evidence only | ❌ No | Keep safe fallback; wait for a materially new specialist hypothesis |
| Incompressible/already compressed | Development safety tests | ✅ bounded store/direct fallback behavior | — category throughput unvalidated | — large-file category gate unvalidated | ❌ No | Freeze expansion, selector-cost, speed, and memory gates |

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
No declared item has been acquired or scored.

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
