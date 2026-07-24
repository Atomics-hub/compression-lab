# CLUE-LDS JLS2 public championship screen — frozen protocol (v1)

Status date: 2026-07-25. **Frozen prospective protocol. No corpus data is read
in this freeze PR; acquisition and scoring are a separate, owner-dispatched
one-way door.** This document, `config/clue-jls2-championship-screen-v1-gates.json`,
`config/clue-json-log-corpus-championship-v1.json`, the acquisition/benchmark/
evaluator/verifier scripts, the reducer, and the workflow are frozen together and
pinned by `config/clue-jls2-championship-screen-v1-lock.json` at readiness.

This screen is an owner dispatch (2026-07-25). It answers exactly one question:

> On two fresh, previously unopened CLUE-LDS temporal ranges, is JLS2 a public
> championship contender against **Kanzi 2.5.3 max** and **ZPAQ 7.15 -method 54**,
> alongside the strongest eligible standard roster (Brotli-11, zstd --ultra -22,
> xz 9e, 7-Zip mx=9) and the PBC specialist?

It does **not** authorize the sealed private holdout, does not change the immutable
v1 `not_passed` or v2 `passed` scores, and reads no corpus data before it merges.

## Claim ceiling (the only permitted claim)

The best possible outcome is a **public championship contender on the two named
previously unopened CLUE-LDS temporal ranges** (`clue-championship-e` and
`clue-championship-f`). This is **not** world-best, **not** state-of-the-art,
**not** market-leading, **not** a private-holdout result, and **not** independently
reproduced. Unavailable tools are **unavailable, never beaten**. A not-contender
or interrupted screen is published under the same boundary. This screen does not
change the immutable v1 `not_passed` or v2 `passed` scores.

**Moonshot ledger:** this is the JLS2 **product** lane, not the Lane 2 moonshot
prescreen lane. It is **not charged against the moon 160-run cycle ledger.**

## Frozen championship ranges

Both ranges are inclusive; the record id equals the NDJSON line number, enforced
through the v2 fetcher discipline that verified `id == line_number` on this archive
through 45,250,000.

| id | family | first id | last id | expected records |
|----|--------|----------|---------|------------------|
| `clue-championship-e` | `clue_championship_e` | 15,000,001 | 15,250,000 | 250,000 |
| `clue-championship-f` | `clue_championship_f` | 32,000,001 | 32,250,000 | 250,000 |

Both ranges are fully **disjoint from and non-overlapping with** all seven consumed
ranges and with each other, and lie in distinct temporal neighborhoods.
`clue-championship-e` sits at least 4,750,001 records from every consumed boundary.
`clue-championship-f` sits at least 2,750,001 records from every consumed boundary
(its nearest neighbor is the consumed v1 validation range starting at 35,000,001).
**Correction to the dispatch:** the dispatch described both ranges as ≥ 3.7M
records from every consumed boundary; that holds for `clue-championship-e`
(4.75M) but `clue-championship-f` is 2.75M records below the 35,000,001 range. The
separation is still a clean, non-overlapping, distinct temporal neighborhood, so
the owner-dispatched range identities are frozen unchanged and the true minimum
gaps are recorded here instead.
The seven already-consumed ranges — development `1–250,000`, `10,000,001–10,250,000`,
`20,000,001–20,250,000`; v1 validation `35,000,001–35,250,000`, `45,000,001–45,250,000`;
v2 validation `28,000,001–28,250,000`, `40,000,001–40,250,000` — and both
championship ranges are **mutually refused** for any future acquisition by the
fetcher's `DECLARED_RANGE_CONFIGS` (all three corpus configs).

## Acquisition method and source license

Source: Zenodo record 7119953 (DOI `10.5281/zenodo.7119953`), member `clue.json`
inside `clue.zip` (sha256 `0c9eadb104acf1da6de738ba9babe957c83cd8602a01fa6d846a6ea4a6611d96`,
635,105,552 bytes, publisher md5 `9e318370f96b68077667e9cdc05f26a5`). License:
**CC-BY-4.0**. The Cloud-based User Entity Behavior Analytics Log Data Set
(Landauer, Skopik, Höld, Wurzenberger, 2022-09-28). The fetcher opens the single
archive member, selects the complete original NDJSON records whose id is within
each inclusive frozen range, verifies `id == line_number` per record, and refuses
any range overlapping a consumed range or the other championship range. The
public-validation split is refused without `--allow-public-validation` and without
a valid final readiness lock over a clean worktree. One acquisition, one score.

## Codec identities

### JLS2 / Axiom (candidate) — byte-identical to v2, zero tuning

JLS2 version 1 containing JLF2 version 1 segments; product lineage
`native/src/jls2.rs` from PR #74 (200c74b). Frozen implementation commit
`69e9ea6a974c24c9a0f99a364cca5e8cd9d36145`. Settings are **identical to v2**:
16 MiB segment target, internal Zstandard level 6, 2 compression segment workers,
3 standalone decode segment workers. The frozen source SHA-256 set is reused
verbatim from the v2 gates file
(`config/clue-jls2-public-validation-v2-gates.json`, sha256
`376354fb60eacb7cc6c7b7cda4fdde37ffd25b2aaa0ce41792a4ede0627d6c9a`); the built
binary is produced at execution from that pinned source. No tuning is permitted.

### Kanzi-max (research)

Kanzi 2.5.3, `https://github.com/flanglet/kanzi-cpp`, commit
`6eea1658897019ab3107df2806d5e534ef0798df`, source tarball sha256
`0f34944b0ea77843b34ae461d5207bacd3a9839436182d8df244c6c190a1e30d`. Settings
`--compress --level=9 --block=1g --jobs=1`. Build
`cmake -DCMAKE_BUILD_TYPE=Release -DKANZI_ENABLE_NATIVE_OPTIMIZATIONS=ON ;
cmake --build --target kanzi_static`. The Linux x86_64 binary sha256 is captured
into the run receipt **at execution**.

### ZPAQ (research), -method 54 eligible

ZPAQ 7.15, source `https://mattmahoney.net/dc/zpaq715.zip`, source zip sha256
`e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418`. Eligible
config: `add ARCHIVE input.bin -method 54 -threads 1 -noattributes -until
20000101000000` (level 5, 16 MiB block). x86_64 Linux build; binary sha256 captured
**at execution**. Per the E1 toolchain receipt
(`config/frontier-headroom-e1-toolchain-v1.json`) the frozen build is compiled
`-DNOJIT`; **ZPAQ JIT and NOJIT builds produce byte-identical archives** — the
ZPAQL model and the emitted archive are independent of the x86 JIT execution path,
so the complete-archive byte count is build-independent. If that E1 JIT/NOJIT
byte-identity cannot be re-cited at execution, it is enforced as **build-identity
policy**: the archive bytes must match across the two build modes or the run is
voided.

`-method 54` is the strongest ZPAQ config within the 512 MiB decode gate: it peaks
at **343.3 MiB decode RSS** and 358.3 MiB compress RSS
(`runs/json-context-ceiling-e2-a-v1/`).

### ZPAQ -method 510 — CONTEXTUAL research ceiling only, never eligible

`-method 510` (level 5, 1 GiB block) is ZPAQ's research ceiling. The frozen E2-A
evidence measures its decode RSS at **1272.1 MiB**, far over the 512 MiB product
decode gate, so it is **never eligible** under the product gates. It is reported
alongside as a contextual ratio ceiling; its results are contextual, **never
losses or wins**. Same treatment as `zstd --long=31`.

### Standard roster (the v2 / #109 standard roster)

- **Brotli-11** 1.2.0, `github.com/google/brotli` commit
  `028fb5a23661f123017c060daa546b55cf4bde29`, quality 11 single thread. Strongest
  eligible standard on the JLS2 v2 score.
- **zstd-22** 1.5.7, `github.com/facebook/zstd` commit
  `f8745da6ff1ad1e7bab384bd1f9d742439278e99`, `--ultra -22 -T1` (128 MiB window,
  in-gate). The `--long=31` variant (`zstd-22-long31`) is contextual only.
- **xz 9e** (`xz-lzma2-9e`) 5.8.3, `--format=xz --check=crc64 --lzma2=preset=9e
  --threads=1`, source tarball sha256
  `fff1ffcf2b0da84d308a14de513a1aa23d4e9aa3464d17e64b9714bfdd0bbfb6`.
- **7-Zip** (`7zip-9`) 26.02, release asset sha256
  `41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e`, LZMA2 `-mx=9`.
- **PBC** (`pbc-only`) `github.com/antgroup/pbc` commit
  `bac1f86d29624cb585bb4475235d22a28e60ffea`, license Apache-2.0 (sha256
  `bacacee63139034e9acba4de0c513eeb93cc6277ae52054a30eebf4be644e7ed`), method
  `pbc_only`, pattern_size 100, train_data_number 2000, train_thread_num 64.
  Complete archive = pattern file bytes plus compressed payload bytes. PBC is a
  **first-class attempted eligible opponent**: the benchmark runs the exact v2 PBC
  machinery (`scripts/benchmark-pbc-competitor.py`) from the pinned commit under
  `config/clue-pbc-championship-screen-v1-gates.json`, captures the built binary
  SHA-256 at execution, and classifies each family. If PBC cannot run comparably it
  is recorded as an **invalid-tool-failure**, never silently dropped and never
  counted as beaten.

Every built binary's SHA-256 is captured into the run receipt at execution. The
7-Zip pinned release asset sha256 is authoritative; the extracted `7zz` binary
sha256 is recorded at execution.

## Framing, accounting, and integrity requirements

- **Complete-byte accounting**, identical to v2: every tool is scored on the
  complete archive bytes required to exactly restore the source, including any
  container, header, dictionary, pattern file, or framing wrapper.
- **Exact byte roundtrip** preserving record order and timezone text; deterministic
  output; corruption rejection for JLS2. A byte-exact roundtrip that equals the
  source SHA-256 preserves record order and timezone text by construction.
- **Complete framed-byte accounting** for JLS2, identical to v2 (stream header +
  per-segment headers + selected frame bytes must equal the whole stream), with a
  bounded direct-fallback regression of 0 bytes per segment.
- **Clean RSS instrument**: JLS2 cold-process compression and standalone-decode
  peak RSS are measured through `scripts/measure-clean-rss.py` (sha256
  `805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306`), exactly as
  v2, with the shim-floor eligibility bound (≤ 64 MiB and ≤ 25% of the reading).
- **512 MiB decoder-RSS product cap FOR JLS2**: JLS2's worst cold-process
  standalone decode peak RSS must be ≤ 536,870,912 bytes; its compression peak RSS
  must be ≤ 536,870,912 bytes.
- **Eligibility framing (frozen NOW):** `kanzi-max` and `zpaq-5-m54` are eligible
  byte-comparison opponents **regardless of their own decode RSS or speed**; those
  are reported transparently. Only JLS2 carries the 512 MiB product decode-RSS cap.
  This is a deliberate, owner-frozen framing for this head-to-head screen (see
  Deviations). `-method 510` and `zstd --long=31` remain contextual only.
- **Speed** is reported for context on every tool. JLS2 carries the v2 speed gates
  (≥ 100 MB/s aggregate compression, ≥ 250 MB/s aggregate standalone decode, with
  the v2 per-repetition floors); the **championship decision is a ratio-and-
  eligibility decision, not a speed decision** between codecs.

## Per-item walls

- **Default per-item wall: 600 s.**
- **JLS2 keeps the v2 per-item wall exactly: 1800 s.**
- **ZPAQ ceiling: 1800 s** (both `-method 54` and the contextual `-method 510`).

**ZPAQ wall justification.** Local arm64 NOJIT `zpaq -method 54` measured 111.8 s
and 113.8 s per ~24 MiB GH Archive slice
(`runs/moon-cycle2-c1c2c8-prescreen-v1/local-references-s24.json`), i.e. ~4.7 s/MiB,
projecting to ~220 s per ~46.5 MiB CLUE family; a synthetic worst case reached
166.8 s per 24 MiB (~6.6 s/MiB, ~310 s per family). The 1800 s ZPAQ ceiling gives
roughly 6×–8× headroom over the projected family wall so that a slow runner cannot
silently kill ZPAQ as a tool failure, while keeping the bound explicit and frozen.
A ZPAQ item that still exceeds 1800 s is recorded as an invalid-tool-failure with
its reason, never quietly dropped.

**Did-not-finish rule.** A tool that does not finish an item within its frozen
per-item wall is recorded as a did-not-finish (invalid-tool-failure) for that item
and is not eligible for a byte comparison on it; it is never silently dropped, and
Kanzi and ZPAQ are never quietly omitted.

## Tool failure vs algorithmic failure

Every opponent execution is classified. A codec that **crashes, times out, or
mis-restores** (non-zero exit, wall exceeded, non-deterministic output, or a
restored file whose SHA-256 differs from the source) is recorded as an
**invalid-tool-failure**. An invalid-tool-failure is **excluded from the strongest
eligible minimum and is never counted as a JLS2 win or as beating JLS2**. This is
distinct from an **algorithmic** result — a valid execution that simply produces
larger or smaller bytes than JLS2. **Kanzi and ZPAQ may never be silently
downgraded or omitted**: if either is an invalid-tool-failure, the screen cannot be
a clean contender and the failure is recorded explicitly with its reason. A
championship claim that omits Kanzi or ZPAQ without a documented reason is invalid.

## The one-shot decision reducer

Reducer: `scripts/reduce-clue-jls2-championship-screen-v1.py`, integer arithmetic,
frozen now with unit tests, applied mechanically by the evaluator. JLS2 is a
**contender** if and only if:

1. **Aggregate margin.** `JLS2 aggregate complete bytes * 100 <= 95 * strongest`,
   where `strongest` is the minimum aggregate complete bytes among the eligible
   opponents (`kanzi-max`, `zpaq-5-m54`, `brotli-11`, `zstd-22`, `xz-lzma2-9e`,
   `7zip-9`, `pbc-only`) that produced a **valid** execution on **every** family.
2. **Per-family and per-item — outright win.** On each family (and item) JLS2's
   complete bytes are **strictly smaller** than every eligible opponent that
   produced a valid execution on that family. **Allowed regression is zero bytes;
   equality is not a win.** There is **no** separate per-family 5% margin.
3. **JLS2 gates.** Every JLS2 gate passes: exact roundtrip, deterministic output,
   corruption rejection, 512 MiB standalone-decode RSS, complete accounting,
   bounded direct fallback (0-byte segment-framing regression), frozen identity,
   and the v2 speed gates.
4. **Required research opponents.** `kanzi-max` and `zpaq-5-m54` both produce a
   valid execution on every family.

### Supersession of #109 (owner authority)

This screen's decision rule is governed by **Tom's 2026-07-25 owner dispatch**,
whose phrasing is that JLS2 "wins or stays within the frozen allowed regression on
every family/item". The only frozen regression numbers in #109 are (a) the 5%
margin requirement, which this dispatch reassigns to the **aggregate only**, and
(b) the 0-byte segment-framing rule, which is **kept**. No separate per-family
allowed-regression was ever frozen, so the conservative reading is **allowed
regression = 0 (win required)** on each family/item.

The dispatch therefore **supersedes the #109 prospective roster's decision reducer
FOR THIS SCREEN ONLY**. **#109 is not modified**: its stricter per-family-5%
"championship candidate" bar remains the frozen prospective holdout protocol. The
two produce **different labels** — "public championship contender" here vs #109's
"championship candidate" — and a contender under this screen **does not
automatically meet #109's bar**. The already-documented eligibility supersession
(kanzi-max and zpaq-5-m54 eligible byte opponents regardless of their own RSS;
`-method 510` contextual; RSS/speed reported transparently) rests on the same
owner authority.

### Equality semantics (explicit)

The aggregate operator is **`<=`**, so **aggregate equality passes**: when
`candidate_bytes * 100 == 95 * strongest_bytes` (JLS2 is exactly 95% of the
strongest = exactly 5% smaller), the aggregate condition is **satisfied**. One byte
above the line is **not** a contender. **Per family and per item, equality is NOT
a win** — JLS2 must be strictly smaller. Both sides of both boundaries are
unit-tested.

Contextual tools (`zpaq-5-m510`, `zstd-22-long31`) and unavailable tools
(`LogFold`, `LogPrism`, `LogLite`, `DeLog`) are reported alongside the decision but
are **never counted as beaten and never counted as beating JLS2**. The first
eligible score is final; no post-score tuning; no reruns; no post-hoc threshold or
setting changes.

## Evidence locations and SHA-256 bindings

- ZPAQ memory evidence (`-method 54` 343.3 MiB, `-method 510` 1272.1 MiB):
  `runs/json-context-ceiling-e2-a-v1/`.
- ZPAQ wall evidence: `runs/moon-cycle2-c1c2c8-prescreen-v1/local-references-s24.json`.
- JLS2 v2 score evidence: `runs/clue-jls2-public-validation-v2/`.
- v2 gates (reused frozen candidate pins): sha256
  `376354fb60eacb7cc6c7b7cda4fdde37ffd25b2aaa0ce41792a4ede0627d6c9a`.
- Clean-RSS instrument: sha256
  `805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306`.
- The corpus config and every frozen script are pinned by
  `config/clue-jls2-championship-screen-v1-lock.json` at readiness. The workflow
  (`.github/workflows/clue-jls2-championship-screen-v1.yml`) is `workflow_dispatch`
  only and verifies the lock before any acquisition.

## Sequencing and authorization

Freeze this protocol first (this PR, no measurements). Acquisition and scoring are
a separate, owner-dispatched one-way door that verifies the final readiness lock
over a clean worktree before opening either sealed range. This screen does not
authorize the sealed private holdout; private-holdout identities never enter this
repository by design. The screen publishes **contender OR not-contender** — failure
is publishable.

### Dispatch procedure and lock re-pin (post-merge)

The readiness lock's `readiness_commit` is pinned to the freeze branch commit, so
it deliberately **fails closed** after a squash-merge (the branch commit is not an
ancestor of the squashed mainline commit). The frozen dispatch sequence, following
the #105 precedent, is:

1. **Squash-merge** this freeze PR to `main`.
2. Open a **small re-pin PR** that updates only
   `config/clue-jls2-championship-screen-v1-lock.json`'s `readiness_commit` (and,
   if any byte drifted through the squash, the `locked_paths` digests) to the
   mainline merge commit. No other change.
3. On a **clean checkout** of the merged mainline, run
   `scripts/verify-clue-jls2-championship-screen-v1-lock.py` and confirm it passes
   (clean tree, readiness commit is an ancestor of HEAD, every locked blob matches).
4. Trigger the **single `workflow_dispatch`** run of
   `.github/workflows/clue-jls2-championship-screen-v1.yml`. One acquisition, one
   score, first result final.

### Attempt log

A dispatch attempt that dies **before** the acquisition step reads no CLUE data,
consumes no score, and does not enter the one-way door; it is a fail-closed setup
failure, and fixing the setup and re-dispatching is legitimate (the JLS2 v2
attempt-1 precedent). Every attempt is recorded here.

- **Attempt 1 — run 30073461614 at `29b07f7` — FAILED PRE-ACQUISITION (fail-closed).**
  The "Build strongest standard codecs" step failed the xz tarball SHA-256 check:
  the workflow downloaded `xz-5.8.3.tar.gz` while the pinned `XZ_TARBALL_SHA256`
  (`fff1ffcf2b0da84d308a14de513a1aa23d4e9aa3464d17e64b9714bfdd0bbfb6`) is the digest
  of the `xz-5.8.3.tar.xz` release asset (URL and hash referred to different
  assets; the hash was inherited correctly from the frozen E1 toolchain config).
  The "Acquire the two sealed championship ranges exactly once" step was **skipped**;
  **no CLUE data was touched and no score was consumed**; the one-way door was not
  entered. The retained first-attempt evidence was uploaded by the workflow. Fix
  (this PR): download the `.tar.xz` asset and extract with `tar -xJf`; no pinned
  hash string changed. The zpaq (`e85ec2529…`) and 7-Zip (`41aaba7b…`) asset
  download/hash pairs were re-verified against the live assets and match; brotli,
  zstd, and kanzi are git clones at pinned commits.

- **Attempt 2 — run 30075201539 at `ac79380` — ENTERED THE DOOR, then CRASHED
  mid-score (no scoreable result).** Acquisition **succeeded** and is immutable and
  complete: `clue-championship-e` sha256 `9197e1ae…`, 143,578,666 source bytes (a
  heavier temporal region, roughly 3x v2's record density); `clue-championship-f`
  sha256 `ff84d870…`, 48,443,391 source bytes (manifest + hashes retained). The
  benchmark then crashed with an `IsADirectoryError` at
  `scripts/benchmark-clue-jls2-championship-screen-v1.py:439`,
  `run_opponent_item` `scratch.unlink` on `zpaq-5-m54.clue_championship_e.restored`:
  zpaq `extract -to` recreates the full stored source path as a **directory tree**
  (the documented E1 zpaq behavior), and the harness assumed a file. **No score
  JSON, no reducer input, and no opponent byte counts exist.** Two harness defects
  are fixed in this PR: (1) restore handling now restores every opponent into a
  fresh per-item directory, resolves the single restored payload under it (handling
  path-recreating extractors generically), and cleans up files AND directory trees;
  (2) the workflow score step now captures the benchmark exit code from `$?` on a
  plain redirect (not `PIPESTATUS` through a `tee` pipe), always records it and
  whether a bundle was produced, exits with the real code so a crash fails the step
  visibly, the reducer step runs whenever a score bundle exists, and enforce reads
  the real codes and reports each failure mode explicitly. A local synthetic
  end-to-end dry-run of `run_opponent_item` for all eight opponents (brotli-11,
  zstd-22, xz-9e, 7-Zip, kanzi-max, zpaq-54, zpaq-510, zstd-long31) verified
  compress + restore + hash + cleanup; that dry-run additionally caught and fixed
  two more latent template bugs (brotli 1.2.0 and kanzi 2.5.3 long-option forms).
  PBC is not locally buildable (boost 1.67 / colm toolchain); a line-by-line review
  of its path confirms it writes to a single named output file via `-o` and unlinks
  a file, so it is unaffected by the directory-recreation/cleanup defect.
  **Retained attempt-2 partials, all disclosed:** JLS2 clean-RSS receipts only —
  compression peak RSS family e **610,725,888 B (582.4 MiB), OVER the frozen 512 MiB
  compression cap**; compression peak RSS family f 316,547,072 B; standalone decode
  peak RSS family e 143,806,464 B and family f 91,836,416 B (both decode readings
  in-gate); plus the existence of zpaq's family-e roundtrip. No opponent byte counts
  and no JLS2 archive sizes were produced.

  **Helm ruling (recorded verbatim):** "the one-way door was entered once; the
  acquisition is immutable and complete (manifest + hashes retained); NO scoreable
  result was produced, so under the frozen 'one acquisition, one score, first
  result final' the COMPLETING run is THE one score, not a second one. Nothing is
  replaced-by-selection: attempt 2 produced no scoreable bundle; all attempt-2
  partials are retained and disclosed side-by-side with the completed score's fresh
  measurements; JLS2's identity is hash-pinned and untunable; the only
  decision-relevant partial seen (582.4 MiB compress RSS on family e) is ADVERSE to
  the candidate, so completion cannot flatter JLS2. The completing dispatch (attempt
  3) must acquire byte-identical ranges (fetcher determinism enforces: same archive
  sha 0c9eadb1..., same selection; verify manifest hashes match attempt 2's and
  record that check in the attempt log)."

  **Attempt 3 (the completing run) — byte-identical re-acquisition requirement:**
  the fetcher is deterministic (same pinned archive sha256
  `0c9eadb104acf1da6de738ba9babe957c83cd8602a01fa6d846a6ea4a6611d96`, same frozen
  inclusive ranges and selection rule), so attempt 3 re-acquires the identical
  ranges. Before scoring, the attempt-3 manifest per-item SHA-256 MUST equal
  attempt 2's (`clue-championship-e` `9197e1ae…`, `clue-championship-f`
  `ff84d870…`); that equality check is recorded here as part of the attempt-3 entry.
  Because the sole decision-relevant partial already observed (582.4 MiB family-e
  compression peak RSS) exceeds the 512 MiB compression cap and is adverse to the
  candidate, completing the score cannot flatter JLS2.
