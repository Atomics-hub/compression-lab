# E1 tool acquisition and execution-lock protocol

Status: implemented and exercised without corpus access or compression
measurement. This layer preserves the frozen E1 census declaration byte for
byte; it does not revise codecs, commands, items, gates, or claim scope.

## Purchased guarantee

No E1 corpus byte is eligible to be opened until a closed tool root proves all
of the following at once:

- the audited E1 config, protocol, and verifier still have their frozen hashes;
- all four upstream source archives came through HTTPS from the declared
  official project host or GitHub's official release-asset CDN and match exact
  byte counts and SHA-256 values;
- licenses, source identities, build commands, compiler/build-tool binaries,
  E1 executables, versions, runtime libraries, and the complete directory
  roster match the declaration; and
- the canonical immutable receipt says `corpus_accessed=false` and
  `measurements_exist=false`.

Any missing, extra, symlinked, special, renamed, substituted, or mutated entry
fails before execution-plan promotion. Downloads use bounded temporary files
and atomic promotion. Redirects are rechecked against the official-host
allowlist. Archives remain opaque acquisition evidence; a later builder must
perform the separately declared safe-extraction checks before compiling.

## Source and binary provenance

Kanzi 2.5.3 is commit-bound to the official `flanglet/kanzi-cpp` archive and
ZPAQ 7.15 to Matt Mahoney's official archive. Their locked builds reproduced
the executable SHA-256 values already present in E1 on the locked Apple clang
and CMake/Make toolchain. ZPAQ embeds `__DATE__`; the build therefore freezes
that macro to `Jul 18 2026`, the date in the already-frozen binary, rather than
pretending an ordinary date-dependent rebuild is reproducible.

The zstd 1.5.7 and XZ Utils 5.8.3 source releases are independently retained,
hashed, licensed, and paired with exact upstream reference build commands.
The frozen E1 executables are the macOS arm64 hosted builds reproduced with
identical byte counts and SHA-256 values in preflight runs `29773961392` and
`29774099968`. A reference rebuild is admissible only if it reproduces the
frozen executable SHA-256; otherwise changing to it requires a separately
audited successor census. This distinction avoids a false source-to-binary
reproducibility claim.

Because those two distribution executables are dynamically linked, E1 also
binds the exact non-system `libzstd`, `liblzma`, and `liblz4` bytes under the
loader names they request. The sealed root sets its library search path to
those copies for version probes and future execution. System libraries remain
part of the declared Darwin arm64 host boundary.

## Offline execution matrix

Only after the tool receipt verifies does the planner read the already-tracked
E1 JSON declaration—not corpus paths—to emit:

- 68 whole-item templates: 17 training declarations by four frozen codecs;
- 68 AXE1S stratified-sample templates: all four codecs over all 17 frames,
  allowing the declared practical-versus-ZPAQ ceiling gap to be computed; and
- 68 conditional segment templates, retained as unexecuted until the frozen
  trigger is decidable from whole-item results.

Every template binds item ID, category, source declaration, source byte count
and digest, exact codec commands, executable path, process policy, and an
unexecuted status. AXE1S ranges are calculated only from the already-frozen
declared sizes. No item filesystem path is accepted by either preparation
stage.

The checked-in measurement runner is constrained to one new process session
per operation, one codec job, a 24-hour operation timeout, process-group
termination followed by `SIGKILL`, POSIX `wait4` direct-child peak RSS with
explicit Darwin/Linux unit conversion, bounded captured output, and null
stdin. Every hosted shard independently reverifies the exact tool root and
offline schedule before it reads the training manifest. Measured repetitions
retain every compressed artifact and prove exact decompression; the verifier
rejects undeclared files and reconstructs complete AXE1O and AXE1G bytes.

## Hosted training dispatch

The manual-only `frontier-headroom-e1-training.yml` workflow is the strict E1
executor. It has no push or scheduled trigger and requires the literal
confirmation `RUN_E1_TRAINING_ONLY`. All GitHub actions are pinned by commit.
It freezes tools and the complete schedule before a separate job may fetch the
four licensed development corpora, then assembles exactly the declared 17-item
training roster. Public-validation and private-holdout access are absent.

Measurement is split into 20 whole/sample jobs (five categories by practical
or ZPAQ lane), followed by five conditional segment jobs. The final job
requires all 25 shard results, verifies exact schemas, provenance, process
telemetry, artifacts, logs, directory closure, deterministic repetitions, and
round trips, then emits complete-byte controls and oracle summaries with
SHA-256 accounting. Segment results include an actual one-segment AXE1G
fallback under identical framing; payload-only wins are inadmissible.

The workflow has completed hosted identity preflights but no corpus-bearing
measurement. It remains dispatch-ready for the training-only census.
Successful training measurements remain development evidence only and cannot
raise the frozen E1 claim ceiling to validation, holdout, Axiom-win, or
state-of-the-art evidence.

## Verification and claim ceiling

The verifier reconstructs every task object and command vector, rather than
checking task IDs alone. Mutated ranges, commands, states, process rules,
receipt bindings, extra files, or forbidden-result flags fail closed. The
tool-root and execution-plan exercise completed with 68 whole-item tasks, 68
sample tasks, 68 conditional segment templates, zero corpus access, and zero
measurements.

This is tool acquisition and an offline execution matrix only. It is not a
compression result, Axiom win, validation result, holdout result, commercial
speed result, or state-of-the-art claim.
