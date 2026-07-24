# JSON/log championship roster v1 (prospective, frozen, not executed)

**Date:** 2026-07-24
**Status:** frozen prospective roster; **not yet executed**. Execution is
owner-gated and comes only after independent dedicated-machine reproduction of
the JLS2 v2 public-validation pass.
**Evidence effect:** none. This is a protocol freeze, not a benchmark. It
contains no measurements, downloads no new binaries, and makes no claim beyond
the frozen JLS2 v2 claim ceiling.
**Machine-readable freeze:** `config/json-log-championship-roster-v1.json`.

This document freezes, before any execution, the complete championship
comparison roster, tool identities, framing, gates, and decision reducer for a
prospective JSON/log complete-byte championship. It extends the discipline of
the frozen JLS2 v2 public validation
(`config/clue-jls2-public-validation-v2-gates.json`,
`docs/benchmarks/2026-07-24-clue-jls2-public-validation-v2-results.md`) to a
research-tier roster by adding Kanzi and ZPAQ and pinning every identity in
advance.

## Claim ceiling

The only permitted claim, now and at execution, is a **category-scoped
public-validation product pass on the two named previously unopened CLUE-LDS
temporal ranges**. This roster and its future execution may not support
universal, state-of-the-art, market-leading, world-best, or "beats all
compressors" language. Tools that cannot be reproduced comparably are
**unavailable or contextual, never beaten**.

## Sequencing (one-way doors, in order)

1. Freeze this roster (this document; no measurements).
2. Independent dedicated-machine reproduction of the JLS2 v2 public-validation
   pass.
3. Owner dispatch of a championship execution on fresh sealed data.
4. Only after all of the above: private-holdout acquisition.

This roster must be frozen **before** any private-holdout acquisition. Private
holdout identities never enter this repository by design.

## Framing (inherited from JLS2 v2, unchanged)

- **Complete-byte comparison.** Every tool is scored on the complete archive
  bytes required to exactly restore the source, including any container, header,
  dictionary, pattern file, or framing wrapper. For PBC the complete archive is
  the pattern file plus the compressed payload.
- **Exactness.** Byte-exact roundtrip preserving record order and timezone text
  is required for every trial; non-exact tools are ineligible.
- **Determinism.** Output must be deterministic.
- **Runner class.** GitHub-hosted `ubuntu-22.04`, 4 vCPU, matching the JLS2 v1
  and v2 evidence class.
- **Timeout.** 1800 s per item. A tool that does not finish an item within the
  budget is recorded as a did-not-finish for that item and is not eligible for
  a championship comparison on it; it is never silently dropped.
- **Memory.** Every candidate compression and standalone decode resource row is
  measured through the clean-child instrument `scripts/measure-clean-rss.py`
  (SHA-256 `805ee3a20680d2afcf339f678d2e1292fb0ed72dc3ba2ccff261ba693bf41306`)
  with the v2 shim-floor eligibility (floor at most 64 MiB and at most 25% of
  the reading). A tool is eligible for the product claim only when its worst
  cold-process standalone decode peak RSS is at most **512 MiB**
  (536,870,912 bytes). Research-tier tools that exceed the decode gate are
  reported as **contextual**, not eligible.
- **Regression rules.** Each temporal family is scored individually; the
  aggregate and each family require at least 5% smaller complete exact bytes
  than the strongest eligible tool. Segment framing may not regress against an
  equally framed direct fallback (0-byte tolerance).
- **Speed tiers.** At least 100 MB/s aggregate compression and 250 MB/s
  aggregate standalone decompression, as in v2. Speed is reported for context on
  every tool; the championship decision is a ratio-and-eligibility decision.

## Frozen roster

| Tool | Role | Status | Identity (version / source / settings) | Binary SHA-256 |
| --- | --- | --- | --- | --- |
| **JLS2 / Axiom** | candidate | candidate | JLS2 v1 / JLF2 v1 segments; lineage `native/src/jls2.rs` PR #74 (`200c74b`), frozen impl commit `69e9ea6a974c24c9a0f99a364cca5e8cd9d36145`; 16 MiB segments, internal Zstandard level 6, 2 compress / 3 decode workers | `jls2.rs` `2868d54d8379cdc45608f96a219d49fe6dc406d2d63a0596cdae7a4c7b9779b2`; source set pinned in v2 gates, binary built at execution |
| **Brotli-11** | standard | eligible | 1.2.0, github.com/google/brotli commit `028fb5a23661f123017c060daa546b55cf4bde29`; quality 11, single thread | Linux build from pinned commit; captured at execution |
| **Zstandard (high-ratio)** | standard | eligible | 1.5.7, github.com/facebook/zstd commit `f8745da6ff1ad1e7bab384bd1f9d742439278e99`; eligible `--ultra -22 -T1` (128 MiB window, in-gate) | Prior macOS receipt `9b5676aae3cb048cf68e2b40c543d9523db3b4cb911b31861bd5f4fcb050c4b6`; Linux binary captured at execution |
| **XZ / LZMA** | standard | eligible | 5.8.3, xz v5.8.3; `--format=xz --check=crc64 --lzma2=preset=9e --threads=1` (preset 9 extreme); v2-equivalent to lzma-9 | `16b9994cca884ed2a66ba63736f1450049cbc6fd1d93076c51e5f0e7f7a71381` (prior macOS receipt); Linux binary captured at execution |
| **7-Zip** | standard | eligible | 26.02, ip7z/7zip release `7z2602-linux-x64.tar.xz`; LZMA2 `-mx=9` | release asset `41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e`; extracted `7zz` captured at execution |
| **Kanzi-max** | research | eligible (pending Linux build) | 2.5.3, github.com/flanglet/kanzi-cpp commit `6eea1658897019ab3107df2806d5e534ef0798df`; `--compress --level=9 --block=1g --jobs=1` | prior macOS receipts `1518708ef729b2520ac706997721eb90c024266d72e97cc3a1db25a3a1afcbdd`, `3c93e96fb108ebf8152e187ef0f830b03952200dc94b449fcec8d158e7474618`; Linux binary captured at execution |
| **ZPAQ** | research | eligible (pending Linux build) | 7.15, mattmahoney.net zpaq715.zip (source zip SHA-256 `e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418`); `add ARCHIVE input.bin -method 54 -threads 1 -noattributes -until 20000101000000` (level 5, 16 MiB block) | prior macOS NOJIT receipts `fecbedd1fe9ee9bfe8308ad61d223635dc65fc853f18b79dcabd854e5e341ac0`, `3030bfef86efe97cc63ca6f47b0c362ae83fa2ec55e05095d6b190f463f28d37`; Linux binary captured at execution |
| **ZPAQ (research ceiling)** | research | contextual | 7.15, same source zip; `add ARCHIVE input.bin -method 510 -threads 1 -noattributes -until 20000101000000` (level 5, 1 GiB block) | same build as the eligible ZPAQ row; Linux binary captured at execution |
| **PBC** | specialist | eligible | github.com/antgroup/pbc commit `bac1f86d29624cb585bb4475235d22a28e60ffea`, Apache-2.0; `pbc_only`, pattern_size 100, train_data_number 2000, train_thread_num 64; complete archive = pattern file + payload | `c96e0dbf5268899314a51238d5bed8bfa58c00bc032e196a2a1dddbff0bfc720` (v2 hosted-run receipt, head `b187308`); re-captured at execution |

Standards `store`, `lz4-1`, `gzip-9`, `bz2-9`, `zstd-3`, `zstd-9`, and
`zstd-19` from the JLS2 v2 baseline set remain part of the complete-byte matrix
and are carried unchanged; the strongest of them (Brotli-11) is the reference
already reported in v2. External standard versions are pinned by the v2 gates
(`lz4 1.10.0` commit `ebb370ca83af193212df4dcbadcc5d87bc0de2f0`,
`zstd 1.5.7` commit `f8745da6ff1ad1e7bab384bd1f9d742439278e99`,
`brotli 1.2.0` commit `028fb5a23661f123017c060daa546b55cf4bde29`,
`7zip 26.02`).

### Why these Zstandard and ZPAQ configurations

- **Zstandard.** The JLS2 v2 eligible roster froze zstd at levels 3/9/19. This
  championship freezes the strongest in-gate level, `--ultra -22 -T1`
  (default 128 MiB window, decode RSS within the 512 MiB gate). The stronger
  `--ultra -22 --long=31 -T1` recovers additional ratio but its roughly 2 GiB
  decode window exceeds the 512 MiB decode gate, so it is reported as
  **contextual**, not eligible.
- **ZPAQ.** The eligible championship config is level 5 at a 16 MiB block
  (`-method 54`), the strongest practical ZPAQ configuration that the frozen
  E2-A memory evidence shows stays within the 512 MiB decode gate: `zpaq-5-m54`
  peaks at **343.3 MiB** decode RSS (358.3 MiB compress) and is memory-eligible
  (`runs/json-context-ceiling-e2-a-v1/`). The larger-block variants recover up
  to the full 21.32% ratio gap but exceed the gate on decode: `zpaq-5-m57`
  (128 MiB block) and `zpaq-5-m510` (1 GiB block) both measure **1272.1 MiB**
  decode RSS. The 1 GiB-block config (`-method 510`) is carried as the
  **contextual research-ceiling** ZPAQ row: reported alongside, never eligible
  under the 512 MiB decode gate, and its results are contextual, never losses or
  wins under the product gates. This is the same treatment as zstd `--long=31`
  below.

## Unavailable and contextual tools (absence is never a win)

| Tool | Status | Reason |
| --- | --- | --- |
| **LogFold** | unavailable | Official repository (`shanshw/LogFold`, commit `1832f4f380e360dd12d098d987e8c0f6dcc1f3cf`) contains only LICENSE and README.md; no runnable source, release, or benchmark artifact. |
| **LogPrism** | unavailable | Official repository (`Lycc42/LogPrism`) is empty; no commit, source, release, license, or benchmark artifact. |
| **LogLite** | unavailable | No top-level software license found (do not vendor or patch); build blocked on Apple ARM64, an AVX-512 requirement, and case-colliding paths; pending a licensed x86-64 AVX-512 host. |
| **DeLog** | unavailable | No top-level software license found (do not vendor or patch); Docker daemon unavailable, source build lacks libarchive headers, bundled binaries are Linux x86-64; pending license clarification and pinned container digests. |
| **CLP JSON** | contextual | Official JSON documentation states timezone information and event order are not preserved, so it is ineligible for a byte-exact comparison. |

**Kanzi and ZPAQ may not be quietly omitted from any championship claim.** If
either cannot run comparably on the frozen runner, the exact reason is
documented and it is classified unavailable or contextual, never beaten. A
championship claim that omits either without a documented reason is invalid.

## Mechanical decision reducer

- **Eligible tool.** An available tool that produces a byte-exact roundtrip
  preserving record order and timezone text, finishes every item within the
  timeout, and whose worst cold-process standalone decode peak RSS is at most
  512 MiB under the clean-child instrument.
- **Championship candidate requirement.** JLS2 is a championship candidate only
  if, on fresh sealed data under these frozen gates, it produces the **smallest
  complete exact-byte archive against every eligible available tool** on every
  family and in aggregate (at least 5% smaller than the strongest eligible
  complete exact-byte result per family and aggregate), while passing all
  exactness, determinism, corruption-rejection, accounting, memory, and speed
  gates.
- **Contextual and unavailable tools** are reported alongside the decision but
  are never counted as beaten and never counted as beating JLS2 for the product
  claim.
- **First eligible score is final; no post-score tuning.** One acquisition and
  one scored attempt, retained whether it passes, fails, or is interrupted.

## What this roster does not do

It downloads no new binaries, records no measurements, changes no immutable v1
or v2 artifact, and asserts nothing beyond the frozen v2 claim ceiling.
Execution, tool acquisition, and any private-holdout step remain separately
owner-dispatched.
