# Compression category portfolio status

## Decision

Compression Lab is not yet on track to claim wins in every category. It now has
one strong category-specific ratio result, but even that JSON/log result missed
its complete frozen gate. The right architecture remains a portfolio of
specialists behind a deterministic selector with direct and store fallbacks.

This chart is the control surface for future category work. A green ratio cell
does not make the complete category green when speed, memory, integrity,
portability, or independent-evidence cells remain red or untested.

| Category | Evidence stage | Ratio status | Speed status | Memory status | Complete category win? | Next gate |
| --- | --- | --- | --- | --- | --- | --- |
| JSON and machine logs | Public-validation partial | ✅ JLS2 beat zstd-9 on 3/3, PBC on 3/3, and Brotli-11 in aggregate; Brotli family gate was 1/3 | ⚠️ compression passed; Linux decompression failed 250 MB/s gate | ⚠️ development-only JLS2 measurement; no same-run baseline memory | ❌ No | Development-only Linux decode profile, then a fresh independent corpus |
| Plain text and source | Development | ❌ no win over the strongest tested ratio baselines | ⚠️ some Pareto development points, no category validation | ⚠️ partial development measurements | ❌ No | New representation or calibrated entropy-model hypothesis |
| Tabular CSV | Untested | — | — | — | ❌ No | Licensed corpus and specialist-baseline reproduction |
| Numeric and time series | Smoke only | ⚠️ synthetic delta-transpose signal | — | — | ❌ No | Licensed heterogeneous numeric corpus and specialist audit |
| General binary/archive | Development | ❌ current encoder loses to zstd-9 | ❌ not Pareto-optimal | ⚠️ bounded-frame evidence only | ❌ No | Keep safe fallback; wait for a materially new specialist hypothesis |
| Incompressible/already compressed | Development safety tests | ✅ bounded store/direct fallback behavior | — category throughput unvalidated | — large-file category gate unvalidated | ❌ No | Freeze expansion, selector-cost, speed, and memory gates |

The machine-readable portfolio and required chart fields are in
`config/compression-category-matrix.json`. Every completed category or product
gate must add a checksummed JSON summary and render the same size, speed,
memory, integrity, comparability, and claim-ceiling fields used by
`scripts/render-category-scorecard.py`.

## Universal-selector consequence

The selector may eventually route among JSON/log, text/source, tabular,
numeric, binary, and store/direct specialists. It must use bounded evidence
from the input itself, compare complete framed candidates where practical, and
never learn from a consumed validation or private-holdout family. A specialist
does not enter the universal product merely because it wins ratio: it must pass
its complete operational gate first.
