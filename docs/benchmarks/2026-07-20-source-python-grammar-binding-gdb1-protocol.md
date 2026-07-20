# Python grammar/binding GDB1 frozen development protocol

## Decision and evidence boundary

This preregistration tests one narrow question: after competent Python lexical
modeling and identifier-spelling deduplication, does lexical scope and binding
identity expose enough additional redundancy to justify a source specialist?
It uses Python only so a positive A2-minus-A1 difference cannot be explained by
language classification or a second parser. No GDB1 corpus, dependency, or
measurement was accessed while this protocol and
`config/source-python-grammar-binding-gdb1-v1.json` were written.

The only admitted corpus project is CPython 3.14.6. TypeScript, Rust, LLVM,
public validation, and private holdout remain sealed. The result is development
evidence even if every gate passes. It cannot establish an Axiom win, product
win, source-category win, world-best result, or state of the art.

## Frozen split and one-shot rule

Only regular `.py` files participate. Canonical UTF-8 relative path bytes are
hashed, the first unsigned 64-bit big-endian digest word is reduced modulo ten,
and buckets are fixed as follows:

- 0--1: dictionary fitting only;
- 2--7: cheap training screen G0; and
- 8--9: one-shot development holdout G1.

Files are solid-packed in lexicographic path-byte order. Paths, modes, lengths,
filter/exclusion counts, framing, and original hashes are counted. A canonical
derived manifest and dependency lock must be committed before any file bytes
are opened by the experiment. G1 may be opened exactly once and only after a
verified, immutable G0 pass. A failed G0 kills GDB1 without inspecting G1. No
parameter, split, parser, coder, fallback, or gate may change after G0.
Each stage repeats the pinned source-corpus manifest, prior baseline evidence,
and Kanzi binary digests. G1 must use the exact G0 dependency lock and derived
Python manifest digests; a changed digest is a hard attribution failure.

## Pinned lossless syntax strategy

The parser is LibCST 1.8.6 with `MetadataWrapper` and `ScopeProvider`, under a
CPython 3.12 patch release frozen in the dependency lock. The lock must name and
hash every wheel/source archive and every file in the executable decoder
distribution. It is intentionally absent from this scaffold: dependency
acquisition is a separate, pre-measurement operation, and execution fails closed
until the lock exists. This avoids silently blessing whatever package happens
to be installed.

LibCST output must reproduce the original bytes exactly and is cross-checked
against Python token spans. Encoding, BOM, newline style, comments, whitespace,
inter-token gaps, and trailing bytes are data. Parser error, unsupported or
ambiguous binding metadata, a non-identical CST round trip, or any frozen limit
breach selects a counted whole-file raw fallback. There is no best-effort
semantic rewrite.

Each A1/A2 header stores and counts the parser name/version, dependency-lock
digest, grammar flags, and fallback policy. The primary complete bundle also
counts the exact parser/runtime distribution and decoder. This is stricter than
ordinary installed-codec accounting, so the exact same distribution rule is
applied to all competitors.

## Attributable arms

All arms share exactly one `axiom-int-range-v1` integer coder: 32-bit integer
range arithmetic, deterministic renormalization, order-0 counts initialized to
one, and a rescale at total 16,384 by `ceil(count / 2)`. Byte streams use the
same model over symbols 0--255. Stream counts, not an implicit EOF, terminate
decoding. No arm may select a different backend or tune a coder parameter.

- **A0 token+trivia:** token kinds, exact spellings, and exact trivia/gaps. It
  must be a competent strong control rather than a weak ideal-bit estimator.
- **A1 flat identifiers:** A0 plus a first-occurrence spelling lexicon and one
  global identifier MTF occurrence stream. It has no scope information.
- **A2 scope/bindings:** byte-for-byte A1 framing, lexicon, nonidentifier
  streams, and coder. Only the occurrence stream changes to lexical-scope
  `NEW`, `FREE`, and current-scope `MTF(rank)` events. `FREE` records ancestor
  distance and target-table rank; unresolved module names use an explicit
  module-free table. Each event's table mutation is frozen in config.

Therefore A2 minus A1 isolates scope/binding identity. Comprehensions,
decorators, imports, `global`, `nonlocal`, pattern bindings, class/function
boundaries, and shadowing must either receive deterministic ScopeProvider
resolution or force the whole file through the same raw fallback in A1 and A2.

## Complete accounting and comparison

The primary number at every gate is `complete_bundle_bytes`, the sum of:

1. solid compressed payload;
2. header, flags, file manifest, fallback map, paths, modes, and lengths;
3. every table, permutation, stream directory, and raw escape;
4. every trained dictionary or external decoder asset;
5. exact decoder source/binary and parser/runtime distribution; and
6. license/version manifest.

Every component has a byte count and SHA-256 and the verifier recomputes the
sum. Payload-only or installed-codec numbers may be plotted as secondary
context but can never be a gate denominator.

The primary comparison is one solid archive for the complete split. The runner
also produces independently framed per-file diagnostics for every arm and
baseline, but these are not added or substituted for the solid denominator.
They expose regressions and fallback behavior. Candidate and baseline complete
distribution accounting must be symmetric.

The strongest baseline is the smallest eligible, exact, deterministic complete
bundle among all four required runs:

- Kanzi 2.5.3 maximum (`TEXT+UTF+BWT+RANK+ZRLT`/TPAQX through level 9);
- XZ Utils 5.8.3 LZMA2 `-9e`, one thread;
- Zstandard 1.5.7 `--ultra -22 -T1` with a dictionary trained only on buckets
  0--1 and counted once; and
- cmix v21 text mode at commit
  `c443679c0773b8ae5b05423827804063d82ae7a8`, including its pinned 411,996-byte
  English dictionary once in the complete bundle.

Missing, timed-out, nondeterministic, inexact, unaccounted, or over-memory
required baseline results make the stage incomplete; they do not disappear
from the competition.

## Gates and kill rules

Every operation is single-process/single-job, has a six-hour timeout and an
8-GiB peak-RSS ceiling, and runs twice with no warmup. Both complete archive
hashes must match and every restored byte and file identity must match.
Malformed/truncated headers, noncanonical integers, forged lengths/counts,
payload mutations, appended bytes, and dependency-lock mismatch must fail
before unbounded allocation or restored output acceptance.

### G0: cheap training signal

On buckets 2--7:

- A0 must be no more than 5.00% larger than the strongest complete baseline;
- A2 must be at least 1.00% smaller than A1; and
- all completeness, exactness, determinism, accounting, time, memory, and
  fallback checks must pass.

Failure kills the hypothesis without opening buckets 8--9.

### G1: strong development headroom

On the one-shot buckets 8--9:

- A2 must be at least 8.00% smaller than the strongest complete baseline;
- A2 must remain at least 1.00% smaller than A1;
- no independently framed A2 file may be more than 0.50% larger than its
  smallest eligible baseline diagnostic; and
- all common operational and integrity gates must pass.

Only a G1 pass admits a separately frozen validation experiment. Missing 8%
headroom is a rejection, not an invitation to tune on the consumed holdout.

The later product bar remains at least 5.00% smaller than the strongest complete
baseline on separately frozen unseen data, plus practical speed, bounded
memory, streaming/large-file behavior, corruption resistance, portability, and
independent reproduction. GDB1 does not lower that bar.

## Required publication

Each completed stage retains canonical receipts, the complete component
manifest, both repetitions, per-file diagnostics, exactness/corruption results,
host/tool/dependency identities, time/RSS, the derived corpus-manifest digest,
and a decision reconstructed by an offline verifier. Charts must show all four
baselines and A0/A1/A2, distinguish solid complete bundles from per-file
diagnostics, and state which gates passed. Sealed data must never be read by a
publisher or verifier.

The scaffold verifier checks canonical receipt consistency, exact identity
bindings, component arithmetic, stage continuity, and gate decisions. It does
not possess artifacts and therefore cannot prove that a self-declared byte
count or digest came from real bytes. The eventual runner and publisher must
recompute component sizes and hashes from ordinary artifact files and immutable
receipts; independent reproduction remains required. A scaffold-verifier pass
alone is never measurement evidence.
