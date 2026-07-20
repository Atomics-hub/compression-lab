# E1 frontier-headroom and oracle-routing census

Status: frozen training-only protocol. No E1 codec invocation, sample, segment,
or result existed when
`config/frontier-headroom-oracle-census-e1-v1.json` was committed.

## Decision being purchased

E1 asks a deliberately narrower question than “which new codec should we
build?” It measures whether the remaining opportunity in each corpus-ready
category is mostly:

1. choosing an existing ratio codec per item;
2. choosing an existing codec per bounded consecutive segment; or
3. closing a genuine modeling gap between practical codecs and a feasible
   research ceiling.

The answer determines whether the next experiment should be a bounded
selector, a segmented container, or a materially new representation/model.
Hindsight oracles are upper bounds, not shippable selectors. No E1 outcome is an Axiom win.

## Frozen information boundary

Only the 17 exact licensed development items in the config may be opened.
Their sizes and SHA-256 values reconstruct from four tracked acquisition or
corpus declarations. CLUE validation ranges; Rust, LLVM, and Wikiversity;
every tabular public-validation family; consumed validation families; all
private holdouts; and every unlisted path are forbidden. The runner must not
stat, list, sample, hash, or open them.

The general-binary, incompressible/precompressed, and media categories remain
excluded because their required licensed development corpora are not yet
constructed and byte-verified. E1 cannot silently substitute generated or
convenient local files.

Before the first allowed item is opened, a clean pre-execution lock must bind:

- the canonical config, protocol, runner, verifier, and clean commit;
- the four tracked manifest hashes;
- host/OS/CPU/RAM identity and the process sampler;
- the physical executable size and SHA-256 for all four codecs;
- exact version output and the exact command vectors from the config; and
- an empty result directory and sealed-split declaration.

Any mismatch stops before corpus access. A first promoted result is immutable;
partial or interrupted attempts remain recorded and cannot be overwritten.

## Codecs and complete artifacts

The whole-item census runs pinned Kanzi 2.5.3 level 9, zstd 1.5.7 level 19
with `--long=31`, xz 5.8.3 LZMA2 preset 9e, and ZPAQ 7.15 method 510. Every
command is single-threaded. ZPAQ uses a fixed `input.bin` name, fixed UTC mtime,
`-noattributes`, fixed `-until`, and complete journaling-archive accounting.
Each ZPAQ repetition targets a fresh nonexistent path ending in `.zpaq`;
reusing an archive is invalid because `add` appends.
The exact command arrays and executable hashes live in the config; shell
aliases, implicit flags, pipes, renamed archive members, or payload-only
counts are invalid.

Each physical self-contained artifact file is counted. Every measured decode
must restore the manifest-bound length and SHA-256. The practical codecs run
one warmup and three measured repetitions. ZPAQ runs two measured repetitions
without a warmup because it is a research-ceiling path. All measured artifacts
for an item/codec must have the same SHA-256. Each subprocess records wall and
CPU nanoseconds, peak RSS from POSIX `wait4`, exit status, timeout state, and
sanitized commands. A timeout kills its whole process group.

Ratio comparisons require identical item and binary identities. Speed and RSS
comparisons require one otherwise-idle host and identical measurement code;
cross-host numbers are contextual. For each category/codec/repetition,
throughput is the sum of decoded source bytes divided by the sum of primary
process wall time. The published category scalar is the slowest complete
repetition aggregate; peak RSS is the maximum direct-process `wait4` value
over every item and repetition. A tier requires exact deterministic output and
all three compression, decompression, and RSS thresholds. The host receipt
requires AC/battery, low-power, and thermal-pressure telemetry. Governor,
frequency, and turbo state are recorded when the platform exposes them; their
platform-level absence alone does not refuse a tier. Changed AC/battery or
thermal state, low-power mode, or unavailable required telemetry refuses tier
classification while preserving admissible ratio evidence. E1 reports
interactive, balanced, and archival commercial speed tiers exactly as frozen
in the config.

## Five-percent stratified ceiling sample

For every item of size `N`, the sample budget is
`B = floor(N * 500 / 10000)`, never more than 5%. `B` is split into five
lengths differing by at most one byte. For stratum `i` from zero through four,
the offset is `floor((N - length_i) * i / 4)`. Ranges must be ordered,
nonoverlapping, and in bounds.

All AXE1S integers are unsigned little-endian; strings are a `u16` byte length
plus canonical UTF-8 and digests are 32 raw SHA-256 bytes. Its exact order is
`AXE1S` magic[5], version `u8=1`, category string, item string, original size
`u64`, original digest, stratum count `u8=5`, five `(offset u64, length u64)`
pairs, sampled-payload length `u64`, sampled-payload digest, then sampled bytes
in stratum order. The complete frame—not an uncounted raw concatenation—is the
codec input.

ZPAQ method 510 is the strongest presently feasible pinned self-contained
ceiling on this host. The pinned paq8px `-11L` build is unavailable; paq8px
`-12L` and cmix v21 require a larger isolated host. This limitation must be
published. E1 may not swap in a later ceiling after measurement begins; doing
so requires a separately frozen E2. Therefore E1’s ceiling row is a feasible
local diagnostic, not an absolute frontier.

## Whole-item and bounded-segment oracles

The category single-codec controls and per-item oracle use the exact AXE1O
layout in the config. This equal framing prevents the oracle from receiving a
free container. The single-codec controls put every item’s complete artifact
behind the same headers used by the per-item oracle. The oracle chooses the
smallest successful artifact per item after the fact.

The optional segment screen runs only if the per-item oracle saves at least
0.50% or at least two items in the category choose different codecs. It splits
each item into consecutive 16 MiB segments, with only the final segment
shorter. All four codecs operate independently on each segment. AXE1G counts
magic/version, original identity, segment policy, every codec choice, decoded
and artifact length/digest, every complete codec frame, and all payload bytes.
No dictionary or state crosses a segment unless a future protocol counts and
freezes it.

The equally framed whole fallback is AXE1G with `segment-count u32=1`, segment
size equal to the full item, and one complete whole-item artifact, followed by
the same outer AXE1O category framing as the segmented route.

For every item, the reported safe selector upper bound is the smaller of the
equally framed whole-item fallback and complete AXE1G route. Raw segment losses
remain visible even when this safe minimum clamps net selector gain to zero.
This is hindsight information unavailable to a production selector; any real
selector must later use only bounded bytes from its current input and pay all
decision metadata.

## Frozen calculations

All gates use integer bytes and basis points:

- best single practical: smallest complete category AXE1O bytes among Kanzi,
  zstd-long, and xz;
- best single ratio: smallest complete category AXE1O bytes among all four;
- per-item oracle gain: floor of `(best single ratio - oracle) * 10000 /
  best single ratio`;
- bounded-segment gain: floor of `(whole fallback - safe segment route) *
  10000 / whole fallback`; and
- sample ceiling gap: floor of `(best practical sample - ZPAQ sample) * 10000
  / best practical sample`.

Complete per-category output must include source bytes, each codec’s bytes,
compression/decompression MB/s, peak RSS, determinism, exactness, commercial
tier, per-item winner, oracle bytes, container overhead, raw and clamped
segment deltas, ceiling sample bytes, every unavailable marker, and runner
comparability.

## Advancement and rejection

- Advance an item-selector hypothesis only at 1% net per-category gain with at
  least two different winning codecs.
- Advance a segment-selector hypothesis only at 2% net after AXE1G overhead,
  positive gains on at least two items, and no item more than 0.5% above its
  equally framed whole fallback.
- Advance representation research when the feasible sample ceiling beats the
  best practical sample by 3% in two categories or 5% in one.
- Reject selector-only work for a category below 0.5% item-oracle and 1%
  segment-oracle headroom. When the optional segment screen does not trigger,
  its gate contribution is exactly zero basis points.
- A “saturated” label is diagnostic only and additionally requires a ceiling
  gap below 1%; it is not a theoretical or global frontier claim.

The product gate remains unchanged: at least 5% smaller on frozen unseen data,
with speed, memory, integrity, corruption, streaming, portability, selector,
holdout, and independent-reproduction evidence.

## Required result and publication

A result must use the exact closed key sets listed in the config. Every path is
relative, normalized, unique, non-symlink, inside the immutable result
directory, and bound by byte length and SHA-256; missing and extra files fail.
The verifier reconstructs every summary and gate from bound raw receipts,
retains every attempt, and requires validation and holdout to remain
unaccessed. Speed summaries join exactly one successful compress and
decompress receipt for every declared category item and repetition, map each
phase's `wall_ns` into the frozen aggregation, and reject missing or extra
items or phases. The
publication must chart all four codecs, both oracle bounds, sample ceiling,
speed/RSS tiers, overhead, decisions, runner scope, and unavailable rows.

Offline publication verification validates recorded evidence and hashes. It
does not rerun codecs, rehash sealed corpus bytes, or remeasure RSS.
