# Compression category portfolio status

## Decision

Compression Lab is not yet on track to claim wins in every category. It now has
strong category-specific ratio signals in JSON/logs and delimited tables, but
both missed their complete frozen gates. The right architecture remains a
portfolio of specialists behind a deterministic selector with direct and store
fallbacks.

This chart is the control surface for future category work. A green ratio cell
does not make the complete category green when speed, memory, integrity,
portability, or independent-evidence cells remain red or untested.

| Category | Evidence stage | Ratio status | Speed status | Memory status | Complete category win? | Next gate |
| --- | --- | --- | --- | --- | --- | --- |
| JSON and machine logs | Public-validation partial | ✅ JLS2 beat zstd-9 on 3/3, PBC on 3/3, and Brotli-11 in aggregate; Brotli family gate was 1/3 | ⚠️ compression passed; Linux decompression failed 250 MB/s gate | ⚠️ development-only JLS2 measurement; no same-run baseline memory | ❌ No | Development-only Linux decode profile, then a fresh independent corpus |
| Plain text and source | Development | ❌ no win over the strongest tested ratio baselines | ⚠️ some Pareto development points, no category validation | ⚠️ partial development measurements | ❌ No | New representation or calibrated entropy-model hypothesis |
| Tabular CSV | Public-validation partial | ⚠️ TBS1 won 3/4 families by 7.35%–16.50%, but lost aggregate to 7-Zip-9 by 3.48% after a 32.15% OCRB loss | ⚠️ 107.67/403.39 MB/s average; minimum compression passed, one decompression repetition failed at 163.51 MB/s | ✅ cold 293.70/139.81 MiB | ❌ No | Preserve the three-family signal; split image-like matrices into a separate category and use only fresh families for a successor |
| Numeric and time series | Smoke only | ⚠️ synthetic delta-transpose signal | — | — | ❌ No | Licensed heterogeneous numeric corpus and specialist audit |
| General binary/archive | Development | ❌ current encoder loses to zstd-9 | ❌ not Pareto-optimal | ⚠️ bounded-frame evidence only | ❌ No | Keep safe fallback; wait for a materially new specialist hypothesis |
| Incompressible/already compressed | Development safety tests | ✅ bounded store/direct fallback behavior | — category throughput unvalidated | — large-file category gate unvalidated | ❌ No | Freeze expansion, selector-cost, speed, and memory gates |

The machine-readable portfolio and required chart fields are in
`config/compression-category-matrix.json`. Every completed category or product
gate must add a checksummed JSON summary and render the same size, speed,
memory, integrity, comparability, and claim-ceiling fields used by
`scripts/render-category-scorecard.py`.

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

## Universal-selector consequence

The selector may eventually route among JSON/log, text/source, tabular,
numeric, binary, and store/direct specialists. It must use bounded evidence
from the input itself, compare complete framed candidates where practical, and
never learn from a consumed validation or private-holdout family. A specialist
does not enter the universal product merely because it wins ratio: it must pass
its complete operational gate first.
