# Public-checkout verification gate

Status: **passed, 16/16 controls**.

This infrastructure gate checks that editable tests which bind historical git
objects degrade to explicit skips, rather than errors, when those objects are
unavailable in shallow clones or source archives. Full-history checkouts remain
strict: when an object is present, the original binding assertions still run.

| Control group | Evidence | Result |
| --- | --- | --- |
| Guard wiring | Five editable history-bound modules guard every affected method | ✅ Pass |
| Guard semantics | A hermetic git fixture accepts present commits, refuses bad pins on full history, and permits skips only without history | ✅ Pass |
| Shallow-checkout behavior | The guarded methods complete or skip without errors | ✅ Pass |
| Optional dependency | The numeric prototype skips only when `zstandard` is unavailable | ✅ Pass |
| Public instructions | README documents installation, CI-parity warnings, and history requirements | ✅ Pass |
| Frozen boundary | Both lock-frozen readiness modules remain byte-identical | ✅ Pass |
| Existing doctrine | The original DMS2 object-presence precedent remains present | ✅ Pass |

The machine-readable [receipt](receipt.json) contains all 16 checks and their
source bindings. Reproduce it without corpus or candidate execution:

```bash
PYTHONPATH=src python3 scripts/audit-public-checkout-verification.py
```

Claim ceiling: this proves that the advertised verification suite's editable,
git-history-bound checks degrade to explicit skips instead of errors when their
referenced commit objects are absent, while a synthetic git fixture confirms
the guard distinguishes present and absent objects. It does **not** prove test
suite completeness, packaging correctness, release readiness, benchmark
representativeness, compression speed, compression ratio, or the historical
bindings themselves on a checkout lacking those objects. Two lock-frozen
readiness modules intentionally retain their full-history requirement.
