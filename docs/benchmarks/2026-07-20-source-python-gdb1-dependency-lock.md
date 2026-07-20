# GDB1 exact-hash PyPI dependency lock

## Outcome

The package dependency closure required by the frozen Python grammar/binding
GDB1 protocol is now locked before any GDB1 corpus access. Official PyPI
metadata for LibCST 1.8.6 declares one active dependency under Python 3.12:
`pyyaml>=5.2`. The lock selects PyYAML 6.0.3. It has no `Requires-Dist`
entries, so the closure ends there. No extras, source distributions, optional
typing backports, Python 3.13 `pyyaml-ft`, or Python 3.14 marker branch is
admitted.

The canonical lock is
`config/source-python-gdb1-dependency-lock-v1.json`, SHA-256
`d31eda5ed923263a7a76f5a3d85cbf35a9e26b78bd3f8cdd7f627863e9f65108`.
It binds the frozen GDB1 config at SHA-256
`59f635f56738d6c908828735646dd463bffbdf44f1801064cf6317ca8a4b3954`.

This is public dependency identity only. No CPython corpus file, derived split,
development holdout, public validation, private holdout, or compression
measurement was opened to create or verify it.

## Frozen targets

- CPython 3.12.12 / CPython ABI `cp312` / macOS 11+ arm64, for local
  development and exactness work.
- CPython 3.12.12 / CPython ABI `cp312` / manylinux 2.28 x86-64, for hosted
  development measurement.

The package lock does not pretend that CPython itself is a PyPI dependency.
Under the already-frozen complete-bundle rule, the eventual decoder
distribution must separately inventory, count, and hash every required
interpreter and standard-library file. Until that inventory exists, this lock
does not authorize corpus access or measurement.

## Exact official artifacts

| Package | Target | Filename | Bytes | SHA-256 | License |
| --- | --- | --- | ---: | --- | --- |
| LibCST 1.8.6 | macOS arm64 | `libcst-1.8.6-cp312-cp312-macosx_11_0_arm64.whl` | 2,083,726 | `f1472eeafd67cdb22544e59cf3bfc25d23dc94058a68cf41f6654ff4fcb92e09` | MIT AND PSF-2.0 AND Apache-2.0 |
| LibCST 1.8.6 | manylinux x86-64 | `libcst-1.8.6-cp312-cp312-manylinux_2_28_x86_64.whl` | 2,301,473 | `c9d7aeafb1b07d25a964b148c0dda9451efb47bbbf67756e16eeae65004b0eb5` | MIT AND PSF-2.0 AND Apache-2.0 |
| PyYAML 6.0.3 | macOS arm64 | `pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl` | 173,973 | `fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0` | MIT |
| PyYAML 6.0.3 | manylinux x86-64 | `pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | 807,870 | `ba1cc08a7ccde2d2ec775841541641e4548226580ab850948cbfda66a1befcdc` | MIT |

Every row records its exact `files.pythonhosted.org` URL and upload timestamp.
Each wheel also binds the embedded `METADATA`, `WHEEL`, `RECORD`, and license
member by path, byte size, and SHA-256.

## Acquisition and offline verification

Acquire into an empty cache:

```sh
python scripts/acquire-source-python-gdb1-dependencies.py /path/to/cache
```

The acquirer reads only exact-version JSON from `pypi.org`, requires every
artifact field to match the lock, permits downloads only from
`files.pythonhosted.org`, enforces redirect hosts and byte bounds, writes an
exclusive temporary file, verifies SHA-256, and atomically installs it. An
existing file is accepted only when its exact bytes match. Unexpected files,
symlinks, substitutions, sdists, and partials fail closed.

Verify a populated cache without network access:

```sh
python scripts/verify-source-python-gdb1-dependency-lock.py \
  --artifact-dir /path/to/cache
```

The verifier requires canonical ordinary lock/config files and an exact cache
roster. It verifies each complete wheel, rejects unsafe or duplicate ZIP
members and symlinks, checks the embedded package name/version/requirements,
wheel tags and license roster, and independently verifies every wheel `RECORD`
hash and byte count. Passing this verifier establishes dependency identity; it
does not establish a codec result or authorize a compression claim.
