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
and CMake/Make toolchain.

The zstd 1.5.7 and XZ Utils 5.8.3 source releases are independently retained,
hashed, licensed, and paired with exact upstream reference build commands.
The frozen E1 executables, however, are the already-measured macOS arm64
distribution builds and their hashes must not be silently replaced by a new
source build. A reference rebuild is admissible only if it reproduces the
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
- 17 AXE1S stratified-ceiling templates for ZPAQ method 510; and
- 68 conditional segment templates, retained as unexecuted until the frozen
  trigger is decidable from whole-item results.

Every template binds item ID, category, source declaration, source byte count
and digest, exact codec commands, executable path, process policy, and an
unexecuted status. AXE1S ranges are calculated only from the already-frozen
declared sizes. No item filesystem path is accepted by either preparation
stage.

The future measurement runner is constrained to one new process session per
operation, one codec job, a 24-hour operation timeout, process-group
termination followed by `SIGKILL`, POSIX `wait4` direct-child peak RSS with
explicit Darwin/Linux unit conversion, bounded captured output, and null
stdin. The runner itself is intentionally not invoked by this phase.

## Verification and claim ceiling

The verifier reconstructs every task object and command vector, rather than
checking task IDs alone. Mutated ranges, commands, states, process rules,
receipt bindings, extra files, or forbidden-result flags fail closed. The
tool-root and execution-plan exercise completed with 68 whole-item tasks, 17
sample tasks, 68 conditional segment templates, zero corpus access, and zero
measurements.

This is tool acquisition and an offline execution matrix only. It is not a
compression result, Axiom win, validation result, holdout result, commercial
speed result, or state-of-the-art claim.
