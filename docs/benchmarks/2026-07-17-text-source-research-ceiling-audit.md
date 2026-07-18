# Text/source research-ceiling baseline audit

## Decision

Keep two distinct frontiers:

1. the complete same-host **practical frontier** now being measured; and
2. a separately labeled **research-ratio ceiling** whose resource limits and
   eligibility are explicit.

Do not call the practical leader the strongest text compressor. Do not call a
resource-reduced PAQ run the absolute PAQ ceiling. A future Axiom candidate may
earn a practical-category win before it earns an unrestricted-ratio win, but
the repository must show both statuses.

## Why Kanzi materially raises the practical bar

The pinned Kanzi 2.5.3 source at commit
`6eea1658897019ab3107df2806d5e534ef0798df` defines level 9 as the transform
chain `EXE+RLT+TEXT+UTF+DNA` followed by the `TPAQX` context-mixing entropy
coder. Our frozen command replaces Kanzi's default 32 MiB level-9 block with a
1 GiB maximum block and one job. Therefore, beating `kanzi-max` will require
more than wrapping a mainstream LZ codec or applying a generic BWT. The most
credible Axiom directions are specialized reversible source/text
representations followed by prediction or context mixing that adds information
not already captured by Kanzi's TEXT/UTF transforms.

The project source is Apache-2.0 and its documentation describes Kanzi as a
runtime-composable transform/entropy framework with content-aware transforms:
<https://github.com/flanglet/kanzi-cpp>.

## Admitted research-ceiling candidates

| Candidate | Exact upstream identity | Strong setting to reproduce | Resource reality | Eligibility state |
| --- | --- | --- | --- | --- |
| ZPAQ | Official `zpaq715.zip`, 1,000,646 bytes, SHA-256 `e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418` | Highest numeric method 5, one thread, largest block proven safe under the local cap; start with `-m510` (1 GiB block, documented maximum memory up to 16 GiB) | Locally feasible after the practical census; complete `.zpaq` bytes and deterministic metadata must be proven | exact source archive identity frozen; local build and preflight pending |
| paq8px | v216, tag commit `bf7b658fdcfc045a892920d01e830e6c6a790c21`, released 2026-06-24, GPL-2.0-or-later | Absolute upstream setting `-12L`, with no external pretraining files; local resource screen `-11L` may be measured but cannot stand in for `-12L` | Upstream lists about 29,358 MB for level 12 before file-type and OS overhead and warns that `-12L` needs 32 GB+ RAM; this host has exactly 32 GiB | `-11L` may be labeled local resource-bounded evidence; `-12L` requires a larger isolated host |
| cmix | v21, tag commit `c443679c0773b8ae5b05423827804063d82ae7a8`, released 2024-09-16, GPL-3.0 | v21's strongest documented text mode; command and dictionary/model dependencies must be source-audited before freezing | Upstream recommends at least 32 GB RAM; this host has no safe headroom | requires a larger isolated host; any external dictionary/model dependency must be counted or declared ineligible |
| NNCP | Official v3.3 `nncp-2024-06-05.tar.gz`, 1,180,969 bytes, SHA-256 `7b4be2a5871186b82cd5f1c6137a8f6fed0d0c6b2bb281793db1f0be65831119`; MIT source with redistributed LibNC binary | Strongest shipped 20-layer transformer (`enwik9` parameter profile), fixed seed 123; upstream `16384,512` self-contained preprocessor on Wikimedia and raw input on source bundles | Upstream requires Linux for compilation and says a GPU is required for acceptable large-model speed; its published enwik9 run took 2.8 days on an RTX 4090 | exact source/runtime identity frozen; separately authorized Linux/CUDA build and execution pending |

The build surface is frozen before execution. ZPAQ uses the upstream `zpaq`
Makefile target with `CXXFLAGS=-O3`, overriding only its host-specific
`-march=native` default. paq8px uses upstream CMake in `Release` mode with
`NATIVECPU=OFF`, bundled zlib, the declared C/C++ compilers, and one build job.
cmix uses its upstream `cmix` target with the README's compatibility-safe
`-std=c++14 -Wall -O3` flags rather than `-Ofast -march=native`. NNCP uses the
shipped Linux `nncp` target and the pinned LibNC files in the same archive.
These exact argv arrays live in `config/text-source-gates-v1.json`; a receipt
with any different build command is invalid.

Primary upstream references:

- ZPAQ v7.15's official page links `zpaq715.zip`, names its source members,
  release date, public-domain license, five methods, and memory behavior:
  <https://mattmahoney.net/dc/zpaq.html>.
- paq8px v216 documents the `-12L` maximum, its approximate memory ladder,
  exact CLI, and research-only positioning:
  <https://github.com/hxim/paq8px>.
- cmix v21 documents its 32 GB recommendation, single-file behavior, build
  modes, and compatibility warning for `-Ofast -march=native`:
  <https://github.com/byronknoll/cmix>.
- NNCP v3.3 documents its transformer/LSTM models, optional text preprocessor,
  commands, hardware, runtime, and MIT license:
  <https://bellard.org/nncp/> and <https://bellard.org/nncp/readme.txt>.
- ZPAQ's official manual documents method 5, block-size encoding, one-thread
  control, complete archive behavior, and memory up to 16 times block size:
  <https://mattmahoney.net/dc/zpaqdoc.html>.
- The Large Text Compression Benchmark provides useful historical ceiling
  context, but its enwik datasets are famous, repeatedly optimized benchmarks
  and are not unseen Axiom evidence: <https://www.mattmahoney.net/dc/text.html>.

## ZPAQ deterministic artifact plan

ZPAQ's normal journaling archive stores a transaction date, input filename,
file modification date, and optional attributes. The ceiling runner must stage
each byte stream under the fixed basename `input.bin`, set its modification
time to `2000-01-01T00:00:00Z`, omit attributes, and freeze the transaction
date. The exact compression arguments are:

```text
add $ARTIFACT input.bin -method 510 -threads 1 -noattributes -until 20000101000000
```

The official manual defines `510` as numeric method 5 with block-size digit 10,
or `2^10 MiB = 1 GiB`, and documents memory up to 16 times the block size for
method 5. The same manual states that `add -until DATE` timestamps the appended
update with that date. With one selected internal file, `extract ... input.bin
-to $RESTORED` renames that file to the exact external destination; omitting
the selected file would instead prefix a directory and is therefore forbidden
by this protocol. Extraction forces that fresh temporary destination, uses one
thread, and ignores attributes. Every journaling header, filename, hash, and
payload byte remains counted. This recipe is only a predeclared reproducibility
plan until the pinned source is built and two measured complete archive hashes
match.

## cmix v21 dependency and portability decision

The exact v21 tree contains two data assets. Forced text mode uses
`dictionary/english.dic` as both a reversible text dictionary and predictor
pretraining stream. The decoder refuses a dictionary-coded payload unless the
same dictionary is supplied. The pinned file is **411,996 bytes**, SHA-256
`4c8568cca9343b9a6212477880f56f8efd162f8784224a25edd043097d36215a`.
The primary self-contained ceiling row must add those bytes once to the cmix
payload. A payload-only, installed-codec row may be shown separately but is not
eligible for a self-contained Axiom size claim.

`dictionary/new_article_order` is used only by cmix's separately documented
enwik9 preprocessor. It is prohibited on the frozen source and Wikimedia
tracks; enwik9 remains diagnostic-only. The optional external `precomp-cpp`
path is also excluded unless a later protocol pins, reverses, and counts it in
full before execution.

The compatible build uses `-O3`. Upstream explicitly warns that
`-Ofast -march=native` can create cross-machine incompatibility because cmix's
model depends on floating-point behavior. The frozen strongest applicable
commands are `cmix -t english.dic input payload` and
`cmix -d english.dic payload restored`, on a larger isolated host with safe
headroom beyond the upstream 32 GiB recommendation.

## paq8px v216 self-contained ceiling decision

The fair absolute command is `paq8px -12L -forcetext input payload`. Upstream
labels plain `-12L` as its maximum fully self-contained comparison and states
that single-file mode stores only contents—no path, filename, timestamp,
attribute, permission, or other metadata. The decoder is simply
`paq8px -d payload restored`; every payload byte is counted.

The flags `T`, `E`, and `R`, explicit saved/loaded LSTM snapshots, and bundled
`english.dic`, `english.emb`, and `english.exp` assets are prohibited. Upstream
documents those paths as external predictor pretraining state that is not
stored in the archive and must be supplied again for decoding. Forced-text is
not pretraining: it only disables block detection and selects the text model
set for the whole already-declared text/source item.

The same command at `-11L` is admitted under the local 18 GiB screen but is
labeled resource-bounded. It cannot replace the `-12L` row, which remains
external-host-only. Both settings must report the selected SIMD/build identity,
round-trip exactly, and produce two byte-identical measured payload hashes.

## NNCP v3.3 self-contained and portability decision

The official archive is **1,180,969 bytes**, SHA-256
`7b4be2a5871186b82cd5f1c6137a8f6fed0d0c6b2bb281793db1f0be65831119`.
It bundles `libnc.so` (565,336 bytes, SHA-256
`1836cdfde987885e542cb88847cc58c9abefb0ef59a511ea9540dcbe46ac6d3e`)
and `libnc_cuda.so` (3,979,504 bytes, SHA-256
`ea9ee53d217a673e8547dddbfe8253b9c9ea4ec18ad86c7bd939ac2572f7999e`).
The executable and selected LibNC library are disclosed installed-codec
dependencies, using the same framing as every other baseline executable. They
are not per-file archive bytes, but their exact identities remain evidence.

NNCP does not ship pretrained model weights. Its file header records the model
class, full parameters, seed, and other decoding state. Encoder and decoder
initialize identical weights from seed 123 and train online from the symbols.
When `--preprocess` is enabled, the encoder derives a vocabulary from that same
input and zlib-compresses the vocabulary into the NNCP output. The complete
output is therefore the counted self-contained artifact; no side dictionary or
weight file is admitted.

The `enwik9` profile name is a shipped parameter configuration, not permission
to reuse a published enwik score or external enwik bytes. It is the strongest
shipped 20-layer transformer and is frozen before execution. For the Wikimedia
track, use upstream's documented tokenizer recipe:

```text
nncp --cuda -T 1 --profile enwik9 --seed 123 --preprocess 16384,512 c input payload
nncp --cuda -T 1 d payload restored
```

For source bundles, use the same transformer without a tokenizer rather than
inventing an unvalidated source-specific vocabulary setting:

```text
nncp --cuda -T 1 --profile enwik9 --seed 123 c input payload
nncp --cuda -T 1 d payload restored
```

`--dict`, `--load_coefs`, `--encode_only`, and `--max_size` are prohibited.
They respectively introduce externally prepared state, name external
coefficients, create output documented as undecodable, or truncate the input.
Every run must restore the exact declared bytes. Two complete artifact hashes
must match on the pinned CUDA host, and a second declared compatible host must
decode the artifact exactly before NNCP receives any portability label. If
floating-point or GPU differences prevent cross-host decoding, the result stays
same-host research context with that limitation visible.

## Frozen admission rules

After the practical census is complete, verified, and published,
`scripts/prepare-text-source-research-ceiling-execution.py` converts this audit
and the bound practical result into one immutable 35-task execution plan. It
contains 28 formal tasks (four ceiling candidates across seven items) plus
seven separately labeled paq8px `-11L` local resource screens. Every task keeps
its exact input identity, command, host class, side-asset accounting, pending
status, and `Axiom outcome: untested`. The plan refuses differing replacement.
It is a pre-execution lock, not a benchmark result: only later exact,
deterministic receipts on the declared local, larger-memory, or Linux/CUDA host
can change a row from pending.

`scripts/verify-text-source-research-ceiling-plan.py` independently verifies
the checked-in practical publication, reloads the checked-in gate config,
recomputes all 35 tasks byte-for-byte, and requires exactly 28 formal plus seven
context-only tasks. It deliberately reuses the repository commit stored in the
plan binding, so later verification proves the original lock rather than
silently rebinding it to the verifier's current checkout.

Before a task may execute, each declared host class must supply a canonical
host-scoped toolchain receipt accepted by
`scripts/validate-text-source-research-ceiling-toolchain.py`. Available rows
bind the source archive or tag, compiler and complete build command, executable
bytes and SHA-256, host CPU/RAM identity, and any required runtime assets. cmix
must byte-verify its counted `english.dic`; NNCP must byte-verify both pinned
LibNC libraries and name the GPU and CUDA runtime. Unavailable rows instead
carry a nonempty reason and `Axiom outcome: untested`; tool availability alone
always reports zero Axiom wins. A receipt covers exactly the profiles assigned
to its host class and cannot import or omit another class's work.

For the measured Mac,
`scripts/prepare-local-text-source-research-toolchain.py` downloads only when
explicitly enabled, verifies the pinned ZPAQ archive and paq8px commit, rejects
unsafe ZIP members or a dirty source checkout, builds in fresh temporary
directories, installs byte-stable executables atomically, and emits the exact
two-profile local receipt. A differing existing binary or receipt is refused;
build failure is reported as unavailable and never as an Axiom result.

`scripts/prepare-external-text-source-research-toolchain.py` is the equivalent
larger-host handoff. It builds exactly one profile per root: paq8px `-12L`,
cmix v21 with its byte-verified counted dictionary, or NNCP 3.3 with both
pinned LibNC runtimes. Git checkouts and NNCP TAR extraction are transactional;
links, traversal, special files, dirty commits, runtime drift, and a host below
the declared memory class are refused. NNCP additionally requires explicit
Linux, GPU, and CUDA identities. An unavailable receipt again requires an
explicit opt-in and reports zero Axiom wins. Every external invocation also
requires a user-chosen pseudonymous host ID, so two physically distinct but
identically specced machines do not collapse to the same identity hash.

`scripts/benchmark-text-source-research-ceiling.py` executes only that verified
host slice. It stages the exact manifest-bound bytes, resolves the generic
planned command to the byte-verified executable, records one warmup plus two
measured trials as atomic canonical receipts, counts required side assets,
requires an exact bounded restoration, and rejects differing resumed receipts.
The local class receives an 18 GiB address-space and measured peak-RSS gate.
The 12-hour limit is cumulative for each profile and track family—not a fresh
12 hours for every operation. Exhaustion, timeout, over-cap execution, inexact
output, and nondeterministic measured artifacts remain visible with `Axiom
outcome: untested` and can never be converted into wins.

One successful measured payload per item is retained outside the timed region.
The host result binds their exact count and a path/size/SHA-256 manifest, while
the raw verifier checks every retained byte against the measured receipt. This
is required evidence, not an uncounted model or dictionary. In particular, an
NNCP same-host result remains `pending_second_host_decode` and is not formally
admitted until a different declared compatible host decodes those exact
retained payloads to the task-bound source SHA-256 values.

`scripts/verify-text-source-research-second-host-decode.py` performs and then
reconstructs that portability gate. It refuses the primary host ID, stages each
manifest-bound NNCP payload, applies the same cumulative per-track wall budget,
requires exact bounded restoration of all seven source digests, and writes one
canonical receipt per item. Only seven exact receipts can set
`formal_nncp_ceiling_admitted`; altered summaries, missing or extra receipts,
and any injected Axiom win fail verification.

`scripts/verify-text-source-research-ceiling-run.py` is the fail-closed raw-run
verifier. It reloads the plan and byte-verified toolchain, reconstructs every
task summary from the atomic trial receipts, rechecks exact commands and
resource accounting, reapplies the cumulative family budget, and requires the
immutable file and directory roster. Edited summaries, injected wins, missing
or extra receipts, symlinks, and noncanonical JSON are rejected.

`scripts/aggregate-text-source-research-ceiling.py` is the only admission path
from the four host-scoped runs into one research-ceiling result. It requires
all four declared host classes and all 35 planned tasks, reruns each raw-run
verifier, computes measured timing and peak RSS from repetitions 1 and 2, and
keeps speed and RSS explicitly host-scoped while allowing complete artifact
bytes to be compared across hosts. The seven NNCP tasks remain pending unless
the distinct-host decoder result also verifies. Only the 28 formal tasks can
set `all_formal_ceiling_tasks_admitted`; the paq8px `-11L` screen stays context
only, and the aggregate hard-codes zero Axiom wins. The companion
`scripts/verify-text-source-research-ceiling-aggregate.py` reconstructs the
immutable aggregate from the plan, toolchains, raw receipts, retained-artifact
bindings, and optional second-host evidence before any chart may consume it.

`scripts/publish-text-source-research-ceiling.py` requires that raw aggregate
verification again at its CLI boundary, then emits an immutable five-file
public bundle and standardized chart containing all 15 practical rows, all five
research profiles, and an explicit untested Axiom row for each track. The chart
reports complete bytes, ratio, compression and decompression speed, peak RSS,
exactness, determinism, host scope, admission state, and `Axiom beats?` without
turning missing measurements into victories. The companion
`scripts/verify-text-source-research-ceiling-publication.py` reconstructs the
JSON, Markdown, and SVG byte-for-byte from the embedded public evidence; the
raw-run aggregate verifier remains the authority for private host receipts and
retained artifacts.

The plan's formal completion rule explicitly prevents the local paq8px `-11L`
screen from substituting for `-12L`, requires all 28 formal item rows, and keeps
unavailable, unsafe, timed-out, or failed tasks from being interpreted as Axiom
wins.

Before any ceiling result is counted:

1. bind the upstream source/archive URL, version or commit, byte count,
   SHA-256, license, build command, compiler, resulting binary bytes, and binary
   SHA-256;
2. use the same seven already verified development items without opening public
   validation or private holdout;
3. give each candidate one complete item at a time and count every output byte;
4. use one codec thread unless the candidate is intrinsically GPU based, in
   which case device and parallelism are reported rather than compared as
   same-host speed;
5. require exact restoration, bounded output, and at least two byte-identical
   measured artifacts before calling the result deterministic;
6. include any dictionary, tokenizer, weights, or model state required by the
   decoder unless it is immutable code/data shipped as part of the pinned
   decoder distribution; disclose that distinction explicitly;
7. report timeouts, unsafe memory requirements, unsupported platforms, and
   unavailable hardware as unavailable—not as Axiom wins;
8. never mix same-host speed rows with externally hosted speed rows without a
   clear comparability marker;
9. keep enwik8/enwik9 results as external diagnostic context only; they cannot
   promote or validate an Axiom hypothesis; and
10. retain the exact practical and research-ceiling rosters in every later
    Axiom comparison chart.

## Resource gate

The measurement Mac has 34,359,738,368 bytes (32 GiB) of installed memory.
Launching a process whose advertised working set is about 29.4--32 GB would
leave no defensible headroom for macOS, the benchmark harness, decompression,
or transient preprocessing. The local gate therefore caps a single candidate
at 18 GiB peak RSS and aborts on sustained swap pressure. This cap admits ZPAQ
`-m510` and a paq8px `-11L` resource-bounded screen, but it does not convert
either into an absolute maximum claim.

No paid or separately provisioned compute is assumed by this audit. The full
paq8px, cmix, and NNCP rows remain required before any unrestricted-ratio or
world-best claim; acquiring such a host is an explicit later launch decision.

## Claim ceiling

This document is a source and resource audit only. It establishes neither a
codec score nor an Axiom win. All current text/source bytes are development
data, and public validation and private holdout remain sealed.
