# Benchmark manifest-binding gate

Status: **passed, 9/9 controls**.

This infrastructure gate reproduces the condition that invalidated the DMS2
aggregate comparison: `manifest.json` contains two items while a differently
named scoring manifest contains one. The hardened runner selects the exact
named manifest, records its identity, and ignores the disagreeing sibling.

| Control | Previous behavior | Hardened behavior | Result |
| --- | --- | --- | --- |
| Manifest selection | Inferred `CORPUS/manifest.json` | Exact `--manifest` path | ✅ Pass |
| Manifest digest | Not present in shared results | Exact SHA-256 in `results.json` | ✅ Pass |
| Selected corpus identity | Corpus rows only | Count and ordered item IDs bound to manifest | ✅ Pass |
| Disagreeing sibling | Could be opened instead of projection | Ignored when explicit manifest is supplied | ✅ Pass |
| Invalid item digest | Rejected during load | Rejected before output directory or timing | ✅ Pass |
| Existing development commands | Used `manifest.json` | Same compatibility default retained | ✅ Pass |
| CLI | No exact-manifest option | `--manifest PATH` | ✅ Pass |
| Runner identity | Git state only | API version plus bound-runner, frozen-engine, and loader SHA-256 | ✅ Pass |
| Result semantics | Schema version 4 | Schema version 5 | ✅ Pass |

The machine-readable [receipt](receipt.json) contains every check and its
evidence. Reproduce it with:

```bash
PYTHONPATH=src python3 scripts/audit-benchmark-manifest-binding.py
```

Claim ceiling: this proves exact manifest selection, integrity, and result
provenance on a synthetic fixture only. It does **not** prove benchmark
representativeness, compression speed, compression ratio, or state-of-the-art
performance.
