# Dense-matrix representation development decision

## Decision

**The ratio representation passes. The product candidate does not yet pass.**

On three fresh development matrices, a complete-frame selector between DMA1
adaptive arithmetic contexts and DMP1 numeric bit planes produced 177,434
bytes. That is 11.42% smaller than bzip2-9 and passes the frozen 190,295-byte
aggregate target. It beats the strongest standard by at least 5% on two of
three families. The Python reference is far below the 50/250 MB/s operational
gate, so the representation advances only to native Rust implementation.

## Current chart

| Family | Source bytes | Selected route | Selected bytes | bzip2-9 bytes | Result | Encode / decode MB/s |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| Multiple Features pixels | 1,442,000 | DMA1 | **74,133** | 77,935 | **4.88% smaller** | 1.25 / 1.33 |
| Optical Digits | 563,639 | DMA1 | **72,762** | 89,361 | **18.58% smaller** | 0.85 / 0.84 |
| Semeion digits | 2,889,702 | DMP1 | **30,539** | 33,015 | **7.50% smaller** | 3.12 / 7.84 |
| **Aggregate** | **4,895,341** | **DMS1 selector** | **177,434** | **200,311** | **11.42% smaller** | **reference only** |

All complete frames restored the exact original bytes. Multiple Features is
0.12 percentage points short of its individual 5% target, but the predeclared
gate requires two families and both Optical Digits and Semeion pass.

## Hypothesis ledger

| Representation | Complete bytes | Result vs bzip2-9 | Family wins at 5% | Decision |
| --- | ---: | ---: | ---: | --- |
| DMT1 row-major token dictionary | 230,158 | 14.90% larger | 1 | Reject universal path |
| DMI1 column-major token IDs | 255,964 | 27.78% larger | 0 | Reject |
| DMP1 row-major numeric bit planes | 244,655 | 22.14% larger | 1 | Retain binary component |
| DMC1 static arithmetic contexts | 199,232 | 0.54% smaller | 1 | Reject stored model |
| DMA1 adaptive arithmetic contexts | 179,168 | 10.56% smaller | 1 | Retain numeric component |
| **DMS1 complete-frame selector** | **177,434** | **11.42% smaller** | **2** | **Advance to native only** |

The useful context is `(column position, previous symbol)`, derived entirely
from the current rectangular byte stream. No filename, source identity, track
label, known shape, DOI, or dataset-specific threshold participates.

## Why it works

The rejected column-major paths assumed that the same feature across different
samples was the strongest dependency. It was not. The surviving arithmetic
model preserves row order and predicts each value from its column position and
the immediately preceding value. It removes the static-model table by updating
the same deterministic model in encoder and decoder. DMP1 remains useful for
binary-like streams where simple bit planes are smaller.

## Gate status

| Gate | Status |
| --- | --- |
| At most 190,295 bytes aggregate | ✅ 177,434 |
| At least two 5% family wins | ✅ 2 of 3 |
| Exact deterministic reference frames | ✅ |
| 50 MB/s compression | ❌ 0.85–3.12 MB/s Python reference |
| 250 MB/s decompression | ❌ 0.84–7.84 MB/s Python reference |
| Record-table regression protection | Pending native selector |
| Bounded streaming memory, corruption, portable decoder | Pending native candidate |
| Public validation remains unopened | ✅ |

## Next action

Implement DMA1 and DMP1 in the Rust core, keep the complete-frame smaller-of
selector, and fall back to unchanged TBS1 for inputs that fail bounded numeric
rectangular parsing. Only a native candidate that preserves the record-table
win and passes all operational gates may be locked for public validation.

## Claim ceiling

This is fresh development representation evidence, not a product or validation
result. It supports no category-best, market-leading, or state-of-the-art
claim.
