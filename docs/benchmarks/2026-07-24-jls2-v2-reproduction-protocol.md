# JLS2 v2 independent dedicated-machine reproduction protocol

This protocol describes how a genuinely independent operator reproduces the
frozen Atompress (JLS2) CLUE-LDS v2 public-validation result on a dedicated
machine. It is the reproduction step listed as pending and owner-gated in
`docs/benchmarks/2026-07-24-clue-jls2-public-validation-v2-results.md` and in
`docs/RESEARCH_LANES.md` Lane 1.

The entry point is `scripts/reproduce-jls2-v2.py`. It reuses the frozen v2
scripts (`fetch-clue-json-corpus-v2.py`, `benchmark-clue-jls2-public-validation-v2.py`,
`benchmark-pbc-competitor.py`, `evaluate-clue-jls2-public-validation-v2.py`)
without forking their logic, and reuses the clean-child instrument
`scripts/measure-clean-rss.py`. Its own added value is: pinned-commit and
clean-tree preflight, printing and verifying every frozen source hash, driving
the frozen scripts in the frozen order, comparing the reproduced byte counts and
gate decisions against the immutable hosted decision under
`runs/clue-jls2-public-validation-v2/decision.json`, and writing a self-bound
reproduction receipt.

## Claim ceiling

Independent reproduction reproduces the **same** frozen, category-scoped v2
result on the two named previously unopened CLUE-LDS temporal ranges. It is not a
new score. It does not change the immutable v1 `not_passed`, does not prove the
sealed private holdout, does not cover general files, and supports no universal,
market-leading, world-best, or state-of-the-art language. Unavailable specialists
remain unavailable, never beaten.

## What counts as independent

Reproduction is credible only when all of the following hold:

- **A genuinely separate dedicated machine.** Not the primary development
  machine that produced the frozen candidate, and not a shared or noisy host.
- **An operator-independent run.** Driven by someone other than the author of
  the frozen result, from a clean checkout, following only this document.
- **A re-derivation, not a replay.** A GitHub re-run of
  `.github/workflows/clue-jls2-public-validation-v2.yml` is **not** independent
  reproduction: it is the same runner class executing the same workflow. A run on
  the primary development Mac is **not** independent either.

The reproduction reproduces byte counts exactly. Compression and decode wall
time and clean-child peak RSS are machine-dependent: they are reported as
measured and the frozen gates are applied to them by the evaluator, but they are
not required to equal the hosted numbers.

## Requirements

The full pipeline reproduces the frozen `ubuntu-22.04`, 4-vCPU environment class
and therefore requires **Linux** (the script refuses to run the full pipeline on
any other platform). The frozen PBC specialist build, the pinned 7-Zip Linux
x64 asset, and the standard-codec builds are Linux-targeted. On any platform the
`--smoke` mode runs without these.

Toolchain (matching the frozen workflow):

- Ubuntu 22.04 class, 4 vCPU, x86-64.
- Python 3.12 with the package installed: `python -m pip install -e ".[dev]"`,
  then pin the linter `python -m pip install 'ruff==0.15.22'`.
- Rust (stable; the workflow uses the default hosted toolchain) with `cargo`.
- Build dependencies:
  `build-essential clang cmake curl libboost-all-dev lld llvm-dev ninja-build xz-utils`.
- Network access to GitHub, `archives.boost.io`, `codeload.github.com`, and the
  CLUE-LDS record at Zenodo (`10.5281/zenodo.7119953`).

The pinned commits and asset digests for zstd, lz4, brotli, 7-Zip, and PBC are
read by the script directly from the frozen
`config/clue-jls2-public-validation-v2-gates.json`, so this bundle cannot drift
from the sealed contract. The standard-codec and PBC build commands mirror
`.github/workflows/clue-jls2-public-validation-v2.yml`, which remains the
authoritative build recipe.

## Exact invocation (dedicated Linux machine)

```bash
# 1. Clean checkout at the pinned reproduction commit (the merge commit that
#    contains both the frozen v2 apparatus and this reproduction bundle).
git clone https://github.com/Atomics-hub/compression-lab
cd compression-lab
git checkout <PINNED_REPRODUCTION_COMMIT>
git status --porcelain --untracked-files=no   # must be empty

# 2. Prerequisites (once).
sudo apt-get update
sudo apt-get install -y build-essential clang cmake curl \
  libboost-all-dev lld llvm-dev ninja-build xz-utils
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install 'ruff==0.15.22'

# 3. Reproduce. --pinned-commit asserts HEAD; the receipt lands outside runs/.
python scripts/reproduce-jls2-v2.py \
  --pinned-commit <PINNED_REPRODUCTION_COMMIT> \
  --receipt-out "$HOME/jls2-v2-reproduction-receipt.json"
```

The run rebuilds the pinned codecs and the native `clab-jls2`, builds the pinned
PBC specialist, re-acquires only the two authorized public ranges
(`clue-validation-v2-c` 28,000,001..28,250,000 and `clue-validation-v2-d`
40,000,001..40,250,000, verifying their source SHA-256), runs the frozen
benchmark, PBC, and evaluator, verifies exact output byte-identity, measures
clean wall time and clean-child peak RSS, and prints one of:

- `REPRODUCED: byte counts and gate decisions match the frozen hosted result`
  (exit 0), or
- `NOT REPRODUCED: ...` (exit 2).

Re-acquiring the two public ranges for reproduction is permitted: it consumes
public data only to reproduce the **same** frozen result and never mints a new
score. It does not open the sealed private holdout, which stays sealed.

## Smoke mode (any platform, including this Darwin development host)

```bash
python scripts/reproduce-jls2-v2.py --smoke \
  --receipt-out "$HOME/jls2-v2-smoke-receipt.json"
```

`--smoke` builds the native decoder, synthesizes a tiny NDJSON input, compresses
it with the frozen candidate driver (measured through the clean-child
instrument), decodes it with the standalone native `clab-jls2` (also measured),
and asserts deterministic output and exact byte-identity. It does **not** consume
CLUE-LDS, does not build the Linux-only baselines or PBC, and does not reproduce
the frozen byte counts. Shim-floor eligibility is not asserted on a tiny
synthetic target (it is below the instrument's few-MiB floor by design and is
meaningful only on the full corpus).

## Reproduction receipt

The receipt is JSON, written to `--receipt-out`. It records machine identity
(OS, release, arch, CPU model, CPU count, RAM, Python version), the git state,
every measured number, every verified frozen hash, the reproduced aggregate,
family, and per-gate results, and the comparison verdict against the hosted
decision. It is bound with a SHA-256 over its own canonicalized content
(`receipt_sha256`), so any later edit is detectable.

**Where the receipt goes.** When a genuine dedicated machine executes this
protocol, the receipt is produced outside the repository (e.g. the operator's
home directory) and delivered to the project owner. Sealing it into a
`runs/clue-jls2-public-validation-v2-reproduction/` entry is a separate,
owner-dispatched publication step; **this PR intentionally creates no `runs/`
entry**, because the frozen run evidence is immutable and only the owner
dispatches a reproduction publication.

## What was tested before this PR

On the primary development Mac (Darwin arm64 — explicitly **not** an independent
reproduction), `--smoke` was run end to end: native build, frozen compress
driver, standalone native decode, clean-child instrument, frozen-hash
verification, deterministic output, exact byte-identity, and self-bound receipt
generation all passed. The full Linux pipeline (standard-codec and PBC builds,
CLUE-LDS acquisition, frozen benchmark/PBC/evaluator, byte-count comparison) was
not run here; it is validated by the dedicated-machine execution above, which
remains required.
