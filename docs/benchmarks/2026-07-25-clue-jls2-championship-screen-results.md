# CLUE-LDS JLS2 public championship screen — results

**Status: not_contender.** On two fresh, previously unopened CLUE-LDS temporal
ranges, JLS2 is **not** a public championship contender against ZPAQ-class
compression. The frozen integer reducer decided `not_contender` (`contender: false`,
exit 2). This is the completing score under the frozen "one acquisition, one score,
first result final" contract; it is published plainly as a loss.

## Claim ceiling (verbatim)

> A contender screen may support only a public championship contender claim on the
> two named previously unopened CLUE-LDS temporal ranges (clue-championship-e and
> clue-championship-f). It is not world-best, not state-of-the-art, not
> market-leading, not a private-holdout result, and not independently reproduced.
> Unavailable tools are unavailable, never beaten. A not-contender or interrupted
> screen is published under the same boundary.

The **immutable v2 category-scoped public-validation pass is unchanged** by this
screen. v2 remains true within its own claim ceiling (a category-scoped pass against
the standard roster on the two v2 ranges); this screen answers a different,
specialist question — does JLS2 beat ZPAQ-class context mixing on fresh ranges — and
the answer is **no**. The immutable v1 `not_passed` is likewise unchanged.

## Provenance

- Workflow `.github/workflows/clue-jls2-championship-screen-v1.yml`, run
  **30080444891** (`workflow_dispatch`), head `850cb63`, hosted `ubuntu-22.04`.
- Completing dispatch = attempt 3 (see attempt log). Readiness lock verified over a
  clean tree before acquisition; receipt `readiness-lock-receipt.json`.
- Candidate JLS2 identity byte-identical to v2 (frozen source pins, zero tuning).
- Evidence sealed under `runs/clue-jls2-championship-screen-v1/`; all 14
  `SHA256SUMS` entries verify. `decision-recomputed.json` is an **independent
  recomputation receipt**: the frozen evaluator re-run offline on `bundle.json`
  reproduces `{"result":"not_contender","contender":false}` and every aggregate,
  ratio, family decision, and classification.

## Re-acquisition identity (byte-identical to attempt 2)

The fetcher is deterministic; attempt 3 re-acquired the identical ranges from the
same pinned archive (`clue.zip` sha256
`0c9eadb104acf1da6de738ba9babe957c83cd8602a01fa6d846a6ea4a6611d96`). Manifest
per-item SHA-256 equals attempt 2's:

| range | official IDs | records | source bytes | B/record | sha256 |
|---|---|---|---|---|---|
| clue-championship-e | 15,000,001–15,250,000 | 250,000 | 143,578,666 | 574.3 | `9197e1ae…` |
| clue-championship-f | 32,000,001–32,250,000 | 250,000 | 48,443,391 | 193.8 | `ff84d870…` |

Family e is a **heavy-record regime** (~574 B/record, ~3× v2's density); family f
is a **v2-like regime** (~194 B/record).

## Phase-4 transparent chart — complete bytes (aggregate and both families)

Ratio is JLS2 ÷ codec (× > 1 means JLS2 is larger/worse). "Beat?" is the frozen
outright-win rule (JLS2 strictly smaller; equality is not a win), reported per family
and aggregate. Opponent peak RSS was not measured through the clean-child instrument
(only JLS2 carries the product RSS gate); opponent speed is a single-run wall for
context. The championship decision is a byte-ratio-and-eligibility decision, not a
speed decision.

| codec | class | aggregate B | JLS2÷agg | family e B | JLS2÷e | family f B | JLS2÷f | comp MB/s | decomp MB/s | exact | JLS2 beat? (e / f / agg) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **JLS2 (candidate)** | candidate | **4,323,039** | 1.000 | **4,107,254** | 1.000 | **215,785** | 1.000 | 169.1 | 468.5 | yes | — |
| zpaq-5-m54 | eligible (research) | 1,540,588 | **2.806** | 1,456,116 | **2.821** | 84,472 | **2.555** | ~0.3 | ~0.2 | yes | **no / no / no** |
| brotli-11 | eligible (standard) | 3,883,989 | 1.113 | 3,403,445 | 1.207 | 480,544 | 0.449 | ~0.7 | ~997 | yes | no / **yes** / no |
| zstd-22 | eligible (standard) | 2,652,086 | 1.630 | 1,974,291 | 2.080 | 677,795 | 0.318 | ~0.6 | ~1316 | yes | no / **yes** / no |
| 7zip-9 | eligible (standard) | 2,987,593 | 1.447 | 2,392,384 | 1.717 | 595,209 | 0.363 | ~19.7 | ~478 | yes | no / **yes** / no |
| pbc-only | eligible (specialist) | 45,182,993 | 0.096 | 37,628,261 | 0.109 | 7,554,732 | 0.029 | ~0.06 | ~82.8 | yes | **yes / yes / yes** |
| kanzi-max | eligible — **invalid-tool-failure** | — | — | — | — | — | — | n/a | n/a | no | not comparable |
| xz-lzma2-9e | eligible — **invalid-tool-failure** | — | — | — | — | — | — | n/a | n/a | no | not comparable |
| zpaq-5-m510 | **contextual** (over decode gate) | 995,384 | 4.343 | 927,943 | 4.426 | 67,441 | 3.200 | ~0.2 | ~0.3 | yes | never counted |
| zstd-22-long31 | **contextual** (over decode gate) | 2,651,305 | 1.630 | 1,974,128 | 2.081 | 677,177 | 0.319 | ~0.6 | ~1359 | yes | never counted |

**Strongest eligible valid opponent = zpaq-5-m54** (smallest aggregate and smallest
on both families). JLS2 loses to it by **2.81×** aggregate (2.82× family e, 2.55×
family f). JLS2 aggregate is 4,323,039 B vs zpaq-m54's 1,540,588 B — **+2,782,451 B
larger**.

**What JLS2 beat:** the PBC specialist (far smaller on both families and aggregate),
and the LZMA/Brotli-class standards on **family f only** (brotli-11, zstd-22, 7zip-9;
JLS2 215,785 B vs 480,544 / 677,795 / 595,209). **What JLS2 lost:** zpaq-5-m54
everywhere; brotli-11, zstd-22, and 7zip-9 on aggregate and family e. On **family e
JLS2 is the largest of every valid eligible codec.**

## Invalid-tool-failures (recorded per protocol; never a win or a loss)

Per the frozen tool-failure discipline, a codec that crashes, times out, or
mis-restores is an `invalid-tool-failure`: excluded from the strongest-eligible
minimum and **never counted as beaten or as beating JLS2**.

- **kanzi-max — infrastructure failure, NOT a kanzi result.** Compression returned
  exit code **127 in ~1.0 ms** on both families — an instant spawn/loader failure of
  the runner-built binary (sha256 `0521c487…`, captured in
  `opponent-binary-sha256.txt`), not an algorithmic outcome. Because kanzi-max is a
  required research opponent that did not produce a valid execution, the screen
  **could never have been a clean contender** regardless of the byte results. Kanzi
  remains **unmeasured in this screen**; the only kanzi signal is the local
  development-tier GH-Archive prescreen references in the research lane.
- **xz-lzma2-9e — harness restore-path defect, NOT an xz result.** Compression
  returned exit code 0 but the restored-output resolution failed for xz's output
  semantics (`exact_roundtrip` false, no bytes recorded). This is a harness limitation
  for xz's restore path, recorded honestly rather than scored.

Neither invalid tool is counted as beaten or beating JLS2.

## Why not_contender — independently overdetermined

The `not_contender` decision does not hinge on any single fact. It is
**overdetermined** by three independent conditions, any one of which is sufficient:

1. **JLS2's own compression-memory product gate FAILS.** Family-e compression peak
   RSS through the clean-child instrument is **645,296,128 B (615.4 MiB), over the
   frozen 512 MiB (536,870,912 B) compression cap.** (Family-f compression RSS
   309,952,512 B / 295.6 MiB is in-gate. Standalone decode RSS is in-gate on both
   families: e 143,798,272 B / 137.1 MiB, f 91,226,112 B / 87.0 MiB. Speed gates
   passed: 169.1 MB/s compression, 468.5 MB/s standalone decode.)
2. **JLS2 loses the outright-win requirement** on both families and in aggregate to
   the strongest eligible valid opponent (zpaq-5-m54), and loses aggregate + family e
   to brotli-11, zstd-22, and 7zip-9.
3. **A required research opponent (kanzi-max) was not valid**, so a clean contender
   claim was impossible by construction.

## Loss localization

- **Family e (heavy-record regime) both collapses the ratio and breaches the memory
  gate.** At ~574 B/record, family e is 95.0% of JLS2's total complete bytes
  (4,107,254 of 4,323,039), and its compression peaks at 615.4 MiB — over the cap.
  JLS2's model does not hold on this denser regime.
- **But the ZPAQ gap is not regime-specific — it is structural and ratio-dominant.**
  On the v2-like family f (~194 B/record), where JLS2 actually beats the LZMA/Brotli
  standards, JLS2 is still **2.55× larger than zpaq-5-m54** (215,785 vs 84,472). The
  gap to ZPAQ-class context mixing is a compression-ratio gap that persists in the
  regime JLS2 was tuned for, plus — on the heavy regime — one resource breach.

## Attempt log

- **Attempt 1** (run 30073461614 at `29b07f7`) — failed pre-acquisition, fail-closed,
  on an xz asset/hash mixup; acquisition skipped; one-way door not entered.
- **Attempt 2** (run 30075201539 at `ac79380`) — entered the door; acquisition
  succeeded (identical ranges) but the benchmark crashed mid-score on a zpaq
  directory-recreation restore defect; no scoreable bundle. Helm ruling (recorded in
  the protocol doc verbatim): the completing run is THE one score; all attempt-2
  partials retained and disclosed; the only decision-relevant partial seen (family-e
  compression RSS over the 512 MiB cap) was adverse to JLS2, so completion could not
  flatter the candidate.
- **Attempt 3** (run 30080444891 at `850cb63`) — **the completing score. Result:
  not_contender.** Re-acquisition byte-identical to attempt 2 (verified above).

Full protocol, gates, reducer semantics, walls, tool identities, and the verbatim
helm ruling are in
`docs/benchmarks/2026-07-25-clue-jls2-championship-screen-protocol.md`.

## Disposition

The v2 category-scoped public-validation pass against the standard roster is
**unchanged and immutable**, scoped to its claim ceiling. This screen answers the
specialist question and the answer is that **JLS2 does not beat ZPAQ-class
compression on fresh CLUE ranges**. Kanzi remains unmeasured here (infrastructure
failure). No experiment is reopened and no roadmap is implied; the JSON/log lane's
next algorithmic work moves to the private laboratory per the owner's authorization.
