# GDB1 standalone runtime distribution contract

## Decision

GDB1 is frozen as a **standalone research codec** for every primary ratio gate.
This follows the existing preregistration, which puts parser/runtime distribution
bytes in `complete_bundle_bytes`. The primary G0, G1, validation, product, and
strongest-ratio views must count one complete runtime distribution per solid
benchmark bundle. Runtime, parser, model, dictionary, decoder, and manifest
costs may not be treated as free or silently amortized.

An installed Python-library view may be reported as secondary operational
context: payload bytes plus a separately disclosed one-time install footprint.
It cannot pass a ratio gate, select a winner, or support a strongest-compressor
claim. Changing the primary to installed-library accounting would require a new
protocol before any corpus access; it cannot be done after seeing a result.

This decision is strict and expensive. Before decoder code and manifests, the
frozen base distribution costs are:

| Target | Stripped CPython archive | LibCST + PyYAML wheels | Base distribution |
| --- | ---: | ---: | ---: |
| macOS arm64 | 16,722,813 | 2,257,699 | **18,980,512** |
| manylinux x86-64 | 33,321,975 | 3,109,343 | **36,431,318** |

Those bytes may make GDB1 fail. That is an honest consequence of the declared
self-contained comparison, not a reason to remove them after measurement.

## Interpreter identity

Both targets use CPython 3.12.12 from the
`astral-sh/python-build-standalone` 20251028 release, using the exact stripped
`install_only` archives. The builder is MPL-2.0. The upstream CPython source is
also bound independently:

- `https://www.python.org/ftp/python/3.12.12/Python-3.12.12.tar.xz`
- 20,798,712 bytes
- SHA-256 `fb85a13414b028c49ba18bbd523c2d055a30b56b18b92ce454ea2c51edc656c4`
- embedded PSF-2.0 license SHA-256
  `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`

The macOS runtime archive is 16,722,813 bytes with SHA-256
`194997bc8cc08f1ed19a7e6a72544d8ce6688ef5e8969d61de2848aeb68fbf6c`.
The manylinux archive is 33,321,975 bytes with SHA-256
`d136b7168603620bf82fd2ec0fcaed2a5853551aae66f8023b3ae32b435683f2`.
Exact release URLs and timestamps are frozen in
`config/source-python-gdb1-runtime-distribution-v1.json`.

The builder's MPL-2.0 license is provenance for tooling that is not shipped in
the decoder bundle, so its bytes are referenced but not added to bundle size.
Licenses actually present in the runtime and wheels are already counted inside
those exact archives; their paths and hashes are included in the inventories.

## Extraction-free inventories

`scripts/inventory-source-python-gdb1-runtime.py` reads each gzip tar without
extracting it. It rejects absolute/traversing paths, duplicate members,
escaping links, devices, FIFOs, and unknown member types. Every regular file is
hashed. The canonical digest covers path, type, mode, size, content hash, and
link target. Separate digests bind the complete standard-library roster,
license roster, and native-object roster.

The checked-in inventories are:

- `config/source-python-gdb1-runtime-macos-arm64-v1.json`, SHA-256
  `fd574cdc52294303bdc3028aa8532e923109d0aebeab29656dc69c84b88d7843`;
- `config/source-python-gdb1-runtime-linux-x86_64-v1.json`, SHA-256
  `69487bbbdc4f2c865de8b132e982ffe5e87ad25ebb0a2118163e6d5ef592ed84`.

The runtime archives are deliberately counted whole. They contain more than a
minimal decoder closure, including bundled tooling. No pruning is allowed under
this contract. A smaller standalone runtime would be a new, frozen packaging
hypothesis requiring its own exact inventory before corpus access.

## Native and operating-system dependencies

The inventory code parses 64-bit little-endian Mach-O load commands and ELF
dynamic tables directly. It records every packaged native object and its
`LC_LOAD_*` or `DT_NEEDED` dependencies. It applies the same audit to the
LibCST and PyYAML native extensions inside their exact wheels.

Packaged runtime libraries count through the runtime archive. Package native
extensions count through their wheels. OS-provided frameworks, loader, libc,
libm, libpthread, libgcc, and comparable system libraries are declared in the
target contract rather than copied into the bundle. Therefore portability is
limited to the frozen macOS 11+ arm64 and manylinux 2.28 x86-64 ABI contracts;
there is no broader portability claim without exact second-host decoding.

## Offline verification and remaining authorization

Run the complete artifact verification with the three runtime/source artifacts
and the four dependency wheels:

```sh
python scripts/verify-source-python-gdb1-runtime-distribution.py \
  --artifact-dir /path/to/runtime-artifacts \
  --dependency-artifact-dir /path/to/wheels
```

The verifier binds the frozen GDB1 protocol and dependency lock, checks the
standalone accounting formula, validates source and builder identities,
recomputes both complete tar inventories, re-verifies every wheel, recomputes
wheel-native dependencies, and rejects symlinks, substitutions, unexpected
files, changed manifests, and arithmetic drift.

`measurement_authorized` remains false. This phase contains no corpus access or
compression measurement. G0 also requires frozen decoder code/format manifests,
the derived Python corpus manifest, and symmetric complete-distribution locks
for Kanzi, XZ, trained-dictionary Zstandard, and cmix. Until those exist, neither
this verifier nor the package lock authorizes a benchmark or claim.
