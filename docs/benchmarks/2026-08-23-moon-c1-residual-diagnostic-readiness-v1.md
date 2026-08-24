# Moon C1 residual diagnostic — prospective readiness v1

Status: **READY TO AUTHORIZE, execution false.** This document and
`config/moon-c1-residual-diagnostic-readiness-v1.json` prepare two
mechanism-local diagnostic observations. They do not authorize either read.

## Scientific and authority ceiling

This is a non-scoring diagnostic of the already-retained C1 arm. It attributes
the arm's own charged Q24 loss and exposes match lifecycle plus an explicitly
non-causal 1/2/4-candidate diversity oracle. It does not create or evaluate a
candidate, decide survival, score compression ratio, advance a corpus phase,
advance a scientific ledger, or support a SOTA,
championship, product, input-class, funding, or realizable-gain claim.
It does consume exactly two shared Moon development-budget entries, from
`52` to `54`, one durably charged before each subprocess dispatch.

All execution and read flags in the readiness config are false. Authorization
requires this exact literal, with the placeholder replaced by the full 40-hex
commit that contains the final reviewed readiness package:

```text
Authorize Moon C1 residual diagnostic at readiness commit {FINAL_READINESS_COMMIT}
```

Any other spelling or any mismatch in commit, tree, source hashes, build
inputs, snapshot identities, item indices, SSE width, command, report schema,
or output roster refuses. The literal authorizes exactly the two retained reads,
the durable local attempt ref, two shared-budget charges from 52 to 54, and only
the two reports, `sweep-summary.json`, and `SHA256SUMS` listed below. It does not authorize a rerun, scoring, candidate
execution, external publication, push, merge, or any other data access.

## Frozen implementation identity

- Parent before the implementation: `d14f3d310ac5c2471d64cda2fe86be3e1aa2948d`
- Audited implementation commit: `e514b230cce457a2a603837b286fe8e80d55e770`
- Audited implementation tree: `ef131cba9a4597cdf0e8150dda1195b601154e24`
- CLI: `clab-moon-kernel diagnose-c1`
- Report schema: `clab-moon-c1-residual-diagnostic-v2`
- SSE bucket bits: `17`

The readiness config pins every changed native source, `native/Cargo.toml`, and
`native/Cargo.lock` by SHA-256. The final readiness commit may add only this
prospective docs/config/test package; its native and build-input bytes must
still equal the implementation commit.

The complete synthetic golden is also pinned: source
`aaaaaa-aaaaaaXaaaaaa\n`, item 7, charged-event digest
`5b78a73f3d8eeac809ba5867a2c6f0f0d1d9f4fe67c5319d5b69fc347501833a`,
and complete deterministic report digest
`a6f3e8388f6aa37c647846bc5cb8adb8469e724ab0ad3e20ee6daced52404492`.

## Retained snapshot identities

The package binds existing repository metadata; readiness verification does
not open either retained snapshot.

| snapshot | item | bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `gharchive-2026-05-15-14-s24` | 0 | 25,165,377 | `a6873fdebc69a79c1cad8e7b4b52c8d207c5e7f5fa5ed1df3ec4117d920802b4` |
| `gharchive-2026-06-15-14-s24` | 1 | 25,165,414 | `05220440b98e0adfc933ce0b6f838a6bed37d35118e4bb4f02075d7e34e50f79` |

Those identities must agree in both pinned metadata sources:

- `config/moon-cycle2-c1c2c8-public-prescreen-v1.json`, SHA-256
  `433d7eb641d49d82cb83b1e03fd7042725c906bc0c6f914db7a991924d44f872`
- `runs/moon-prescreen-cycle1-h1-v1/local-references-s24.json`, SHA-256
  `5fb1a001b44e5652c5be19f9eead6167f29ce53084c791c3ab982a1fc750e07f`

## Exact output roster

No repository evidence file outside this roster may be produced. The separately
supplied shared Moon budget and its transient concurrency lock are lifecycle
state, not evidence outputs:

1. `runs/moon-c1-residual-diagnostic-v1/gharchive-2026-05-15-14-s24__c1-residual-diagnostic.report.json`
2. `runs/moon-c1-residual-diagnostic-v1/gharchive-2026-06-15-14-s24__c1-residual-diagnostic.report.json`
3. `runs/moon-c1-residual-diagnostic-v1/sweep-summary.json`
4. `runs/moon-c1-residual-diagnostic-v1/SHA256SUMS`

The diagnostic's no-force atomic publication path is mandatory. Existing
destinations refuse; `--force` is forbidden.

Before the first snapshot byte is opened, the runner atomically creates
`refs/moon/c1-residual-diagnostic-v1/attempt`. Its continued presence blocks a
rerun even if evidence outputs are lost. Deliberate deletion of that local ref
by an administrator is destructive administrative compromise and is not
claimed to be resisted.

## Memory semantics

Each report must close its checked component ledger and must report
`accounted_concurrent_logical_bytes <= 536870912`. This is a logical-payload
ceiling only. It is not an RSS measurement, an RSS ceiling, or proof about
allocator/stack overhead. No memory figure may be promoted beyond that wording.

## Accepted P2 limitations

These four limitations remain part of the authorized interpretation:

1. **Acc size wording tension.** `aggregation_struct_bytes` uses Rust
   `size_of::<Acc>()` as a logical accounting component while the report also
   excludes stack, allocator overhead, and `Vec` capacity. It is a conservative
   bookkeeping proxy, not a direct allocation or RSS measurement.
2. **Post-link cleanup ambiguity.** Held-directory no-force publication
   hard-links a validated, synced private pending inode containing the retained
   in-memory bytes to the destination. If later pending-link cleanup fails, the
   destination may already be validly published while the command reports
   failure and leaves the pending hard link.
3. **Shadow collision-test evidence limitation.** Tests pin low-width slot
   rotation, deterministic fifth-candidate eviction, and depth monotonicity via
   factored helpers; they do not construct a full production-width end-to-end
   hash-collision corpus.
4. **Shadow evidence prohibition.** Shadow rows are non-causal per-position
   candidate-diversity upper bounds and may change candidate every byte. They
   are prohibited as direct funding evidence and as realizable-gain evidence.

## Authorized manual procedure

The narrow runner validates authority, source/build/package hashes and metadata,
verifies the absolute Cargo, rustc, and clang executable digests and versions,
and verifies the absolute Git executable digest and version for every authority,
archive, and durable-attempt operation. It materializes the exact implementation
tree and builds it offline/locked in an
exclusive fixed production build root with a fixed environment before opening
retained bytes. Git receives a minimal non-inherited environment, so ambient
repository/config/object-directory overrides are absent. The release binary
must match its frozen SHA-256; dispatch uses a private read-only copy whose
digest is checked immediately before each invocation. Snapshot validation is the first
retained read: one streaming pass measures bytes, SHA-256, and newline records.
Every inbound JSON object—including readiness config, references, budget, and
staged reports—is parsed by one recursive loader that rejects duplicate keys and
the non-standard `NaN`/infinity constants.
The runner rejects preexisting or dangling-symlink output paths and durably
replaces and fsyncs the shared Moon budget **before** each dispatch.
A dispatched failure remains charged. No other Moon budget writer may run
concurrently. It invokes only `diagnose-c1`, never scores or decides, validates
report closure, retains the validated report bytes in memory, and publishes
exactly those bytes plus a deterministic sweep summary through a held output
directory descriptor with no-clobber writes.
The real kernel likewise receives only the frozen `LC_ALL`, `PATH`, and private
`TMPDIR` runtime environment; ambient credentials, `DYLD_*`, Python, and home
configuration do not reach the child.

Lifecycle tests use temporary synthetic snapshots and a fake kernel to prove
authorization/preflight/charge/failure/publication behavior; that layer does
not claim producer parity. A separate Python integration test makes two
independent clean build invocations through that same exact fixed production
root, requires the frozen release SHA-256 byte-for-byte both times, runs the real
producer on the pinned synthetic source, matches the complete report/event/tape
goldens, and passes those actual bytes through the Python validator. After—and only after—the
exact owner literal is received, set the paths below and run these commands
without alteration.

```sh
export AUTHORIZED_READINESS_COMMIT='<full commit from the owner literal>'
export OWNER_LITERAL="Authorize Moon C1 residual diagnostic at readiness commit $AUTHORIZED_READINESS_COMMIT"
export SNAPSHOT_A='<retained path for gharchive-2026-05-15-14-s24>'
export SNAPSHOT_B='<retained path for gharchive-2026-06-15-14-s24>'
export MOON_BUDGET='/Users/guts/Documents/axiom-moonshot-corpora/run-budget.json'

test "$(git rev-parse HEAD)" = "$AUTHORIZED_READINESS_COMMIT"
test -z "$(git status --porcelain)"
test "$(git rev-parse e514b230cce457a2a603837b286fe8e80d55e770^{tree})" = 'ef131cba9a4597cdf0e8150dda1195b601154e24'
git diff --exit-code e514b230cce457a2a603837b286fe8e80d55e770 -- native/src/bin/clab-moon-kernel.rs native/src/moon/c1.rs native/src/moon/c1_diagnose.rs native/src/moon/diagnose.rs native/src/moon/mod.rs native/Cargo.toml native/Cargo.lock
test "$(shasum -a 256 native/src/bin/clab-moon-kernel.rs | cut -d ' ' -f 1)" = 'abed0cae2f2de5b24bedb42c6b63b6282af8f4902bcaa636b23904bda6d0dd77'
test "$(shasum -a 256 native/src/moon/c1.rs | cut -d ' ' -f 1)" = '0d0c6d818b4b317bfb4bf67cd3ca4a7e470bdac9501b46a890051253a6d8b6d9'
test "$(shasum -a 256 native/src/moon/c1_diagnose.rs | cut -d ' ' -f 1)" = '335c1cffff2a427f1b016510c641ff0a7ee8df324978d93b467fcf3be66e718f'
test "$(shasum -a 256 native/src/moon/diagnose.rs | cut -d ' ' -f 1)" = '6075732cc70763bbf9432d302334c3c225173b008c34f8ecbb8e3343c2280017'
test "$(shasum -a 256 native/src/moon/mod.rs | cut -d ' ' -f 1)" = 'ccf7ba4357a34361e657c24c6cc2e1bd64ca99dd29b7885c46bcc1709347b9bb'
test "$(shasum -a 256 native/Cargo.toml | cut -d ' ' -f 1)" = '984a69ab00314eaef3659fbc7642c0ea738f7d19d3895cf6530738278691c707'
test "$(shasum -a 256 native/Cargo.lock | cut -d ' ' -f 1)" = 'a905547d069da6d55bf6739307ffe9c75202cc15e87a6ae399e10b8890544783'
test "$(shasum -a 256 config/moon-cycle2-c1c2c8-public-prescreen-v1.json | cut -d ' ' -f 1)" = '433d7eb641d49d82cb83b1e03fd7042725c906bc0c6f914db7a991924d44f872'
test "$(shasum -a 256 runs/moon-prescreen-cycle1-h1-v1/local-references-s24.json | cut -d ' ' -f 1)" = '5fb1a001b44e5652c5be19f9eead6167f29ce53084c791c3ab982a1fc750e07f'

python3 scripts/moon-c1-residual-diagnostic-run.py config/moon-c1-residual-diagnostic-readiness-v1.json --authorized-readiness-commit "$AUTHORIZED_READINESS_COMMIT" --owner-literal "$OWNER_LITERAL" --budget-state "$MOON_BUDGET" --snapshot-a "$SNAPSHOT_A" --snapshot-b "$SNAPSHOT_B"
```

Before accepting the observation, both reports must have the pinned schema,
snapshot source SHA, item index and SSE width; their identity guards must all be
true; their ledger/partition closures must hold; and their logical accounting
must be within the ceiling. Failure is an incomplete diagnostic observation,
not a C1 score or scientific KILL, and it creates no permission to rerun.
