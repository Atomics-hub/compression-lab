# S0 JSON/log native screen — frozen development result: KILL

- Evidence stage: `development_only_prequential_screen`
- Claim ceiling: Predeclared development-only model screen. It is not an exact
  codec result, candidate score, unseen validation, private holdout, product
  benchmark, independent reproduction, or state-of-the-art evidence.
- Protocol: `docs/benchmarks/2026-07-21-json-log-native-screen-s0-protocol.md`
  (SHA-256 `dbc2fa3cf8906f972273a6bad59e6ca9a68aa2e11000987ae1ee756bef970dc2`)
- Config: `config/json-log-native-screen-s0-v1.json`
- Freeze record: `config/json-log-native-screen-s0-freeze-v1.json`
  (engine commit `d194942007f1641c23c0e8a8b0023185f401b1be`; measurement ran at
  `b4c354958eed92ca0ba3916afc987f9fca22eb64`, the freeze-record merge commit)
- Capacity profile: base (`sse_bucket_bits` 17); the refined profile was never
  authorized because the full arm did not land in the refinement band.
- Run evidence: `runs/json-log-native-screen-s0-v1/`

## Decision

**KILL.** The full arm projected 26,871,011 complete bytes against the frozen
kill threshold of 1,540,935 (E1 Kanzi reference 1,712,149; gain −14,694 basis
points). Independently, the full arm breached the frozen 96-events-per-record
budget on every item and on the aggregate (145.8 / 146.1 / 200.4 events per
record; an over-limit full arm kills S0 regardless of projected size), and every
full-arm per-item projection exceeded its single-item Kanzi AXE1O reference.
The full-minus-m4 quarantine gate also failed (−50,426 basis points against the
+700 minimum), so the result is additionally labeled vocabulary-carried. No
exact native candidate is authorized from S0.

## Aggregate chart (all ten frozen arms, three development items, 203,578,132 source bytes, 750,000 records)

| Arm | Complete projected bytes | Gain vs Kanzi (bp) | Modeled events | Raw literal bytes | Peak RSS (MiB) |
|---|---:|---:|---:|---:|---:|
| raw-o3 | 13,342,263 | −67,927 | 1,832,203,191 | 0 | 581.8 |
| m1-chassis | 25,975,436 | −141,713 | 1,278,219,320 | 4,507 | 373.8 |
| m1-m2 | 22,993,364 | −124,296 | 1,102,448,741 | 4,507 | 353.6 |
| m1-m2-m3 | 12,401,393 | −62,432 | 425,212,390 | 4,507 | 268.3 |
| m1-m2-m4 | 81,140,089 | −463,908 | 209,774,775 | 70,782,579 | 320.1 |
| m1-m2-m5 | 16,297,668 | −85,189 | 1,102,448,741 | 4,507 | 372.8 |
| **full** | **26,871,011** | **−146,944** | **123,096,235** | **22,453,405** | 268.7 |
| full-minus-m3 | 80,535,949 | −460,380 | 209,774,775 | 70,782,579 | 338.3 |
| full-minus-m4 | 10,345,756 | −50,426 | 425,212,390 | 4,507 | 286.7 |
| full-minus-m5 | 27,149,939 | −148,573 | 123,096,235 | 22,453,405 | 250.6 |

References: E1 Kanzi-max 1,712,149 complete bytes; E1 ZPAQ ceiling 1,347,064
(21.32% headroom). Advance ≤ 1,455,326; refine 1,455,327–1,540,934; kill
≥ 1,540,935. Raw-o3 has no record grammar (records = 0 in its ledger; it is an
attribution-only arm exempt from the event budget, as are all non-full arms).
Peak RSS is the runner-measured process peak (source and tape buffers
included), not the declared model state; declared model-state components are
enumerated in the constants manifests and all lie inside the frozen
201,326,592-byte context and 402,653,184-byte total ceilings.

## Per-item complete projections (full arm gates in bold)

| Arm | clue-early | clue-middle | clue-late |
|---|---:|---:|---:|
| raw-o3 | 4,778,402 | 3,797,095 | 4,774,960 |
| m1-chassis | 7,959,949 | 8,480,540 | 9,543,140 |
| m1-m2 | 7,030,299 | 7,468,635 | 8,502,625 |
| m1-m2-m3 | 3,260,097 | 2,894,702 | 6,254,787 |
| m1-m2-m4 | 26,167,981 | 28,081,351 | 26,898,952 |
| m1-m2-m5 | 5,572,022 | 4,589,230 | 6,144,610 |
| **full** | **6,029,851** | **7,064,218** | **13,785,137** |
| full-minus-m3 | 26,094,823 | 27,809,721 | 26,639,599 |
| full-minus-m4 | 3,030,807 | 2,247,998 | 5,075,143 |
| full-minus-m5 | 6,079,662 | 7,141,365 | 13,937,107 |

Full-arm per-item Kanzi AXE1O references: 630,525 / 438,522 / 643,208 — every
item exceeded its reference (kill on the per-item rule as well). Full-arm
events per record: 145.8 / 146.1 / 200.4 against the 96 budget.

## Mechanism attribution (frozen formulas; report ≥ 8,561 bytes, exact-build ≥ 17,122 bytes)

| Mechanism | Attribution bytes | Reportable | Exact-build |
|---|---:|:--:|:--:|
| M1 (raw-o3 − m1-chassis) | 0 | no | no |
| M2 (m1-chassis − m1-m2) | 2,982,072 | yes | yes |
| M3 (full-minus-m3 − full) | 53,664,938 | yes | yes |
| M4 (full-minus-m4 − full) | 0 | no | no |
| M5 (full-minus-m5 − full) | 278,928 | yes | yes |

The attribution thresholds authorize nothing here because only the full arm can
advance and it was killed; the numbers are retained as diagnostic evidence.

## What the screen measured

1. **The bounded S0 accounting kernel is nowhere near the E1 frontier on real
   log data.** Even the best arm (full-minus-m4, 10.35 MB) projects 6.0× the
   Kanzi reference; the raw order-3 baseline (13.3 MB) is 7.8×. The 21.32%
   headroom between Kanzi and ZPAQ lives far below what these bounded
   single-pass adaptive models reach.
2. **The template chassis models real records worse than a raw byte stream**
   (m1-chassis 26.0 MB vs raw-o3 13.3 MB). Splitting values into per-lane
   hashed order-1/2 contexts fragments statistics that a single order-3 stream
   already captures.
3. **M3's bounded session-reference cache is the only large positive
   mechanism** (+53.7 MB attribution in the full chain; m1-m2 22.99 MB →
   m1-m2-m3 12.40 MB standalone). Whole-value repetition dominates these logs.
4. **M4's bounded online token dictionary is strongly negative on real data**
   (m1-m2-m4 81.1 MB with 70.8 MB of raw literal escape bytes). Its
   charged miss-prefix literals overwhelm any token reuse it finds.
5. **The 96-events-per-record budget is unreachable for this grammar** on
   ~271-byte average records: even with M2/M3/M4 consuming values, the full arm
   needs 145.8–200.4 events per record on average.

## Exactness, determinism, confirmation

- Exactness: every arm×item tape re-decoded to the exact source bytes
  (`decode_matches_source` in all 30 receipts; independent verifier re-decoded
  all 30 tapes and matched the frozen item SHA-256s).
- Determinism: receipts are content-derived only; the clean-checkout
  confirmation re-cloned the repo at the freeze commit, verified every
  engine-source SHA-256 against the freeze record, rebuilt the kernel, re-ran
  all 30 encodes, and byte-compared every receipt (see
  `runs/json-log-native-screen-s0-v1/confirmation.log`).
- Verification: `runs/json-log-native-screen-s0-v1/verification.json` — the
  integrity checks (roster, bindings, SHA256SUMS, receipts, redecode,
  projections, gates, segments) all pass; the event-limit check reports the
  frozen gate breach that (with the byte and per-item gates) produces the kill.
- Segment ledger: diagnostic 16 MiB snapshots recorded in every receipt; no
  decision uses them.

## Disposition

S0 is killed by its own preregistered gates. Per the frozen decision framework,
only structure-aware mechanisms could have rescued the JSON/log native lane
after E2-A killed context-memory scaling; they did not. No exact product
candidate, no refinement run, and no further S0 measurement are authorized.
Successor work, if any, requires a new preregistered protocol that accounts for
what this screen measured (M3-style value reuse is real; per-lane context
fragmentation and charged dictionary misses are net losses; the event budget
was mis-sized for this grammar).
