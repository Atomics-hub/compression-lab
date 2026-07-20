# GDB1 pre-G0 codec and baseline checkpoint

This checkpoint advances GDB1 without opening the CPython corpus and without
authorizing a compression measurement. It freezes a corpus-disabled AXPG1
reference decoder, the A0/A1/A2 bitstream mechanics, a derived-corpus manifest
contract with every content-derived slot still null, and one exact Linux
x86-64 baseline distribution.

The reference codec is intentionally synthetic-only. A0 preserves token kinds,
exact spellings, and exact trivia with the shared adaptive range coder. A1
moves identifier spellings into a first-occurrence lexicon and uses one global
MTF occurrence list. A2 changes only that occurrence representation to scoped
NEW, FREE, and MTF events. A2 currently accepts explicit synthetic scope plans;
the production LibCST ScopeProvider encoder remains pending and the command-line
entry point refuses arbitrary inputs.

## Exact cmix lock and platform correction

The official cmix v21 commit was acquired independently. Its pinned
`dictionary/english.dic` matches the preregistered 411,996-byte SHA-256. The
upstream source unconditionally uses x86 intrinsics and does not compile for
macOS arm64, so the honest G0 target is Linux x86-64 with AVX2. The binary was
cross-built twice with Zig 0.16.0 for `x86_64-linux-gnu.2.28`; both builds were
byte-identical.

| cmix decoder component | Bytes |
| --- | ---: |
| cmix binary | 9,890,616 |
| english.dic | 411,996 |
| GPL COPYING | 35,147 |
| version manifest | 344 |
| **Complete decoder distribution** | **10,338,103** |

The binary SHA-256 is
`59a16200f2b00ecd72c7c91217e5a5f7df467dc5952a8fdcaafbcf1457b0a644`.
It depends only on the declared Linux loader, libc, libdl, libm, and libpthread
host boundary. The source archive, Zig archive, build command, license, binary,
dictionary, and version manifest are all exact-hash bound.

The audited E1 macOS Kanzi, XZ, and zstd identities were independently
reverified, but they cannot be substituted into a Linux G0 comparison. Exact
Linux distributions for those three baselines remain pending. The zstd
dictionary also remains null until it is trained only from the future frozen
`dictionary_fit` split.

Therefore `measurement_authorized` remains false. G0 still requires the three
Linux distribution locks, production LibCST scope extraction, execution of the
frozen derived-manifest builder, freezing the trained zstd dictionary, and a
complete component-accounting verifier for every candidate arm and baseline.
