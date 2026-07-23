# S0 JSON/log native screen — immutable run evidence (decision: KILL)

Frozen development-only prequential screen of the ten-arm bounded
structure-aware S0 model matrix on the three licensed CLUE development items.
The standardized chart, per-item tables, attribution, and disposition are in
[docs/benchmarks/2026-07-22-json-log-native-screen-s0-results.md](../../docs/benchmarks/2026-07-22-json-log-native-screen-s0-results.md).

- Evidence stage: `development_only_prequential_screen`. This is not an exact
  codec result, candidate score, unseen validation, private holdout, product
  benchmark, independent reproduction, or state-of-the-art evidence.
- Decision: **KILL** — full arm 26,871,011 projected complete bytes
  (kill ≥ 1,540,935; Kanzi reference 1,712,149), event budget breached on every
  item (145.8/146.1/200.4 events per record vs 96), every per-item projection
  above its Kanzi AXE1O reference, and the full-minus-m4 quarantine failed.
- Freeze: `config/json-log-native-screen-s0-freeze-v1.json`
  (engine commit `d194942…b1be`; measurement at freeze-record merge
  `b4c354958eed92ca0ba3916afc987f9fca22eb64`; base profile, `sse_bucket_bits` 17).

## Contents

- `result.json` — deterministic measurement result: per-arm per-item ledgers,
  projections, gates, attribution. Content-derived only.
- `receipts/<arm>/<item>.json` — all 30 kernel encode receipts (ledger,
  per-item projection, segment ledger, source/tape/decoded SHA-256s).
- `verification.json` — independent verifier output (`--redecode all`):
  roster, bindings, SHA256SUMS, receipts, redecode, projections, gates, and
  segments checks all pass; the event-limit check records the frozen gate
  breach that produces the kill.
- `environment.json` — host-specific diagnostics (toolchain, kernel binary
  SHA-256, per-cell peak RSS and CPU/wall time); excluded from byte
  comparisons by design.
- `SHA256SUMS` — hashes of result.json, every receipt, and every tape. The 30
  tapes (~1.4 GB of exact event/literal streams) are not committed; they are
  deterministically reproducible from the freeze commit, which the
  clean-checkout confirmation proves.
- `runner.log`, `verifier.log`, `confirmation.log` — process logs. The
  confirmation log ends with `{"confirmed": true, "receipts": 30}`: a fresh
  clone at the freeze commit, engine-source SHA verification against the
  freeze record, a rebuild, and a full re-encode reproduced all 30 receipts
  byte-for-byte.

## Reproduction

```sh
python scripts/benchmark-json-log-native-screen-s0.py --profile base --output-dir <fresh-dir>
python scripts/verify-json-log-native-screen-s0-run.py --run-dir <fresh-dir> --profile base --redecode all
python scripts/confirm-json-log-native-screen-s0-clean-checkout.py \
  --commit b4c354958eed92ca0ba3916afc987f9fca22eb64 --run-dir <fresh-dir> \
  --scratch-dir <fresh-scratch> --freeze-record config/json-log-native-screen-s0-freeze-v1.json \
  --profile base --corpus-dir corpora/clue-json-log-development-v1
```

Requires the three licensed CLUE development items at their frozen SHA-256
identities in `corpora/clue-json-log-development-v1/`.
