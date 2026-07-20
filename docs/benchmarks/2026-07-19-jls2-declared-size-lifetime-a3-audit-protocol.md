# JLS2 A3 declared-size batching and lifetime audit protocol

## Status and purpose

This protocol is frozen before any A3 product edit or A3 measurement. A3 is a
development-only audit of whether declared-size-aware segment batching plus
shorter encoded-segment lifetime can remove enough peak resident memory to
justify a compound decoder candidate.

The retained product remains the pre-A1 commit
`7b081f6f11c2561c36289cfc57f7d3715ab8c594`. A1 context reuse and A2 inline
single-worker dispatch did not replace it. Neither experimental change replaces
the pre-A1 product. For isolated A3 attribution, the
paired baseline is the exact clean A2 commit
`0f3377dff647e8a6d99b65d8f8a269687faa8ec6`; therefore any passing A3
treatment is explicitly the compound A1+A2+A3 candidate, not an A3-only
product claim.

The consumed public-validation ranges can never be acquired, reconstructed,
decoded, tuned on, or rerun. The private holdout remains sealed. No corpus,
validation, or holdout byte is eligible for the audit implementation or its
synthetic tests. A strong development pass could authorize only a separately
frozen gate on a fresh, unconsumed validation set.

## Prior facts and kill threshold

The clean A2 run `29676674924`, job `88165232780`, compared exact A1 with the
compound A1+A2 candidate. All 64 decodes were exact and both binaries received
the same complete frames. Both variants peaked at **657,682,432 bytes**. A2
therefore produced zero measured stress-RSS reduction and failed the 448 MiB
A2 ceiling.

The A3 audit binds that fact exactly. The baseline RSS is not a CLI parameter
and **657,682,432** is the only accepted value. The retained evidence binds:

- baseline commit `131547f35747cc0ff9dedbdef66d8a9516a7464f` and binary
  `31db3a25eb0d935f43dc2411ada64e811ddd53b967a87c6d4aab113f3424a7e9`;
- candidate commit `0f3377dff647e8a6d99b65d8f8a269687faa8ec6` and binary
  `c67e9c9b1902414c2b2e67991631d4cd065041242e6dd39392d673da2ca752fd`;
- run attempt 1, artifact ID `8439147016`, artifact digest
  `sha256:b6930b7b9739a2e8768733096ba534406e1b87afa49a40b950e79bb6d72ec83d`,
  runner SHA-256
  `e5c538910b48afad74d930ce557fa6269f68e8e390c9bd6d02502c0f227ab6b4`,
  and workflow SHA-256
  `aa9c1cb696750a6fd546da7c5767f97fc1726d721b42eedefb298f3f83884f27`;
- Ubuntu 22.04 platform string
  `Linux-6.8.0-1062-azure-x86_64-with-glibc2.35`, four logical CPUs,
  Python 3.12.13,
  `rustc 1.97.0 (2d8144b78 2026-07-07)`, and
  `cargo 1.97.0 (c980f4866 2026-06-30)`;
- Cargo.lock SHA-256
  `a905547d069da6d55bf6739307ffe9c75202cc15e87a6ae399e10b8890544783`,
  `zstd` 0.13.3, `zstd-safe` 7.2.4, `zstd-sys`
  2.0.16+zstd.1.5.7, and bundled libzstd 1.5.7; and
- glibc 2.35 ptmalloc. A2 did not record allocator phase counters, so no
  allocator attribution may be inferred from A2's peak alone.

A3 freezes a development ceiling of **460 MiB** (482,344,960 bytes), leaving
52 MiB of headroom below the 512 MiB product boundary. The observed overage is
175,337,472 bytes. Before candidate work, the audit must attribute at least 60%
of that overage—**105,202,484 bytes**, rounded upward—to buffers whose live
occupancy the exact A3 treatment can eliminate. If it cannot, A3 is killed.

The A2 trial metadata records complete encoded inputs of 50,070 to 1,589,812
bytes. Even eliminating the largest encoded input allocation would explain
less than 1% of the 460 MiB overage. Encoded lifetime is report-only: it gets
**zero authorization credit**, cannot contribute to the 105,202,484-byte
threshold, and a lifetime-only release can never authorize candidate work or
an A/B.

## Exact A2 topology boundary and required hosted preflight

The retained A2 JSON and provenance bind the runner to four logical CPUs and
bind the fixture-level topology available without reopening bytes:

| item | source bytes | encoded bytes | encoded SHA-256 | segments |
|---|---:|---:|---|---:|
| clue-early-development | 62,267,473 | 1,589,812 | `46d38bedd6c2b2d9c0187b25bfb4417890ac49265703376f124b43088ec75043` | 4 |
| clue-middle-development | 69,847,327 | 840,515 | `9a5c53d076dfcd8310451752e11563978ae9b76dbca59fddd943a2a9dcc63417` | 5 |
| clue-late-development | 71,463,332 | 1,545,500 | `9a42acbbe659f5507e007d2b46326ac6a510b5247715f874082a6dbc8bf065ec` | 5 |
| jls2-context-stress-256 | 50,270,800 | 50,070 | `2fd97c117fab3e9410c5f266ef15e42790d06d1971f0849e0b4a295fd000319f` | 3 |

Exact per-segment decoded sizes, modes, raw-channel totals, and actual
concurrent decoded occupancy were not retained. Local synthetic topology must
not be substituted. Until the following preflight completes, the audit status
is exactly `hosted_attribution_required`, `passed` is false, and product A/B
authorization is false.

The preflight is development-only and must run on `ubuntu-22.04` at the exact
A2 candidate commit and toolchain above. It must regenerate each authorized A2
development fixture twice, require the exact whole-frame byte count and
SHA-256 in the table, and parse metadata without publishing corpus or decoded
bytes. Its signed JSON artifact must bind run ID, job ID, attempt, commit,
workflow and runner SHA-256, binary SHA-256, Cargo.lock SHA-256, platform,
four logical CPUs, Rust/Cargo/Zstandard versions, glibc version, and allocator
family. For every fixture and repetition it must report each segment's index,
mode, encoded bytes, declared output bytes, declared skeleton/channel raw
bytes, A2 batch index, and summed A2 peak concurrent declared decoded bytes.
The two topology reports must be identical.

In a diagnostic child using exact A2 scheduling, the same artifact must report
RSS from `/proc/self/smaps_rollup` and `mallinfo2` in-use, free-arena, and mmap
values at every frozen phase below. A declared bound is never observed
allocation. The preflight clears attribution only when phase-correlated RSS
reduction and phase-correlated decoded/Zstandard/allocator occupancy removed
are each at least **105,202,484 bytes**; credited bytes are their smaller
value. Encoded input/frame lifetime is listed separately and excluded from
both operands. Any missing field, identity mismatch, topology mismatch,
allocator API absence, repeated-generation mismatch, or smaller reduction is
a hard no-authorization result.

## Frozen audit instrumentation

The first A3 change is diagnostic only. It must not alter default decode
behavior, scheduling, format handling, output bytes, or errors. On generated
synthetic fixtures, record the following for every segment and batch:

1. complete encoded input length and capacity;
2. encoded segment frame length and whether it is borrowed or owned;
3. declared segment output bytes;
4. for columnar frames, exact declared skeleton plus channel raw bytes;
5. declared live working bytes, defined as column raw bytes plus segment output
   bytes (or direct output bytes for direct frames);
6. current A2 batch membership and summed declared live working bytes;
7. proposed declared-size-aware batch membership and the same sum;
8. Linux RSS and, when available on glibc, allocator in-use, free-arena, and
   mmap bytes at: input loaded, before batch, maximum live batch, after decoded
   buffers drop, after output buffers drop, and audit-only `malloc_trim(0)`;
   and
9. output size/SHA-256 and every existing corruption result.

RSS comes from `/proc/self/smaps_rollup` (falling back to `/proc/self/status`).
Allocator counters come from `mallinfo2` where available. Audit-only trimming
is performed after the untimed decode and only in a diagnostic child; it is
never part of candidate timing or normal product behavior.

The attribution report must separate:

- live encoded bytes;
- live declared decoded/reassembly buffers;
- allocator in-use bytes not represented by those declared buffers;
- free allocator arenas or mappings retained after buffers drop; and
- unclassified resident memory (libraries, stacks, page cache, and accounting
  differences).

The report may not label an upper bound as observed allocation. Credited A3
attribution is limited to the smaller of (a) the RSS reduction observed at the
corresponding phase and (b) declared decoded occupancy removed plus
phase-correlated Zstandard or allocator bytes released by that decoded
concurrency change. Encoded input and encoded-frame lifetime remain visible in
the report but are excluded from authorization credit. Unclassified memory,
lifetime-only releases, and allocator changes without phase correlation are
not credited.

## Frozen audit inputs

The audit implementation and unit tests use only deterministic generated
fixtures:

- direct JLS2 streams with one and multiple declared segment sizes;
- columnar frames with controlled skeleton/channel raw-size tables;
- the existing generated `jls2-context-stress-256` contract (21,800 records,
  ordered keys `k000` through `k255`, one-digit values); and
- malformed declarations that exercise overflow, truncation, channel-count,
  raw-size, and output-size guards.

No CLUE source is fetched during the local audit phase. Synthetic evidence
cannot clear the gate. The strict hosted preflight may access only the same
three licensed development ranges and generated stress fixture used by A2,
solely to establish the bound topology and phase attribution above. Only if
that preflight clears the 60% decoded-concurrency threshold may a separately
frozen later A/B use those same frames. The complete Linux-generated frames
must be generated twice for determinism and supplied byte-identically to exact
A2 and A3.

## Conditional A3 candidate

Candidate implementation is prohibited until the strict hosted attribution
preflight clears the kill gate. A synthetic upper bound, an encoded-lifetime
reduction, or a local-host measurement cannot clear it.
If it clears, the candidate is frozen as follows:

- parent: exact A2 commit
  `0f3377dff647e8a6d99b65d8f8a269687faa8ec6`;
- product files: only `native/src/jls2.rs` and, if required to avoid retaining a
  monolithic input allocation, `native/src/bin/clab-jls2.rs`;
- retain A1 reusable Zstandard contexts and A2 inline execution when
  `workers == 1` explicitly as part of the compound candidate;
- parse and validate every declared size, frame boundary, and digest with the
  existing bounds before trusting it for scheduling;
- preserve segment order and form consecutive batches whose summed declared
  live working bytes do not exceed a frozen **32 MiB** budget; an individual
  segment above the budget runs alone;
- release decoded raw streams, reassembly buffers, completed segment outputs,
  and no-longer-needed encoded segment storage at the earliest verified phase;
- retain the current outer encoded SHA-256, nested payload SHA-256, restored
  SHA-256, maximum-output guard, atomic output publication, corruption
  behavior, and error specificity; and
- do not change the JLS2/JLF2/JLC1 bytes, version, encoder, selector, compression
  parameters, channel assignment, Zstandard worker count, or decoder CLI.

If shortening encoded lifetime would require weakening validation-before-use,
copying more encoded data, changing the file format, or publishing output
before all integrity checks pass, that subchange is killed and recorded as
unsupported. Declared-size batching must then pass on its own; no benefit is
credited to encoded lifetime.

## Conditional paired A/B schedule

Only after the audit gate passes:

- exact A2 is the baseline and the frozen compound A1+A2+A3 commit is candidate;
- `ubuntu-22.04`, cold standalone child processes, Linux `wait4` RSS conversion;
- the exact A2 four-input fixture contract;
- one discarded warmup per input and binary;
- seven measured rounds with the A2 alternating order;
- fresh process and fresh atomic destination per decode;
- parent wall time includes startup, all file I/O, verification, and output
  publication; and
- 64/64 restored outputs must match complete size and SHA-256.

## Immutable A3 selection gates

The compound candidate passes development only if all are true:

1. the pre-candidate audit attributes at least 105,202,484 bytes to releasable
   A3-controlled buffers;
2. all 64 scheduled decodes are exact and both binaries receive identical
   complete frames;
3. every corruption, malformed-input, maximum-output, and atomic-publication
   test remains green;
4. candidate peak RSS is at most **460 MiB on every input**;
5. stress peak RSS is at least 20% below paired A2, or the candidate is below
   460 MiB with phase telemetry independently accounting for enough released
   bytes to credibly remain below the 512 MiB product boundary;
6. candidate median aggregate decode throughput is at least 95% of A2;
7. candidate peak RSS is no higher than A2 on any CLUE development family;
8. every candidate item median is at least 250 MB/s and every aggregate round
   is at least 225 MB/s;
9. candidate aggregate coefficient of variation is at most 20%; and
10. complete encoded bytes, compression ratio, format/version, encoder output,
    selector behavior, and integrity semantics are unchanged.

Failure of the attribution, exactness, 460 MiB, or integrity gate is final for
this candidate. A failure retains the pre-A1 product baseline; exact A2 remains
an attribution baseline only. No result can rewrite the consumed
public-validation no-pass.

## Claim ceiling

This protocol can produce only **development-only decoder-memory attribution**.
It cannot support public-validation, private-holdout, independent-reproduction,
universal, market-leading, world-best, or state-of-the-art claims.
