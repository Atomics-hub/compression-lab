# TBL1 column-transpose selector probe

## Decision

**Representation retained; Python implementation rejected for product speed.**

On four bounded development slices, TBL1 plus zstd-19 and an exact direct
fallback produced 2,705,273 bytes versus 3,560,478 for direct zstd-19, a
24.02% aggregate reduction. It won three structurally different families and
routed the losing wide-float family to direct Zstandard with only the 47-byte
candidate header.

## Development comparison chart

| Family | Source bytes | Direct zstd-19 | TBL1 selector | Size result | Compress MB/s | Decompress MB/s | Backend | Exact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| AutoUniv mixed | 8,388,079 | 1,871,810 | 1,376,373 | ✅ 26.47% smaller | 0.65 | 6.64 | Column | ✅ |
| Covertype integer/binary | 8,388,596 | 960,055 | 661,453 | ✅ 31.10% smaller | 1.10 | 4.54 | Column | ✅ |
| Facebook dense numeric | 8,388,328 | 279,182 | 217,969 | ✅ 21.93% smaller | 2.69 | 10.00 | Column | ✅ |
| Gas-sensor wide float | 8,346,577 | 449,431 | 449,478 | ⚠️ 47-byte frame cost | 1.08 | 745.08 | Direct fallback | ✅ |
| **Aggregate** | **33,511,580** | **3,560,478** | **2,705,273** | **✅ 24.02% smaller** | — | — | 3 column / 1 direct | ✅ |

The speed cells are single local wall-clock observations and include both
candidate construction and exact decode. They are diagnostic only. The Python
reference misses the frozen 50/250 MB/s dense targets by a wide margin and is
not a product candidate.

## What TBL1 preserves

- every field byte and its original spelling;
- delimiter positions and variable row arity;
- empty fields, quotes, carriage returns, arbitrary binary bytes, LF state, and
  a final unterminated record;
- deterministic output, declared-size bounds, SHA-256 integrity, and rejection
  of truncated, corrupt, trailing, oversized, or unsupported frames;
- an equally framed direct-Zstandard fallback whenever column transposition is
  not smaller.

The transform treats the delimiter as a byte boundary even inside quoted text.
That is safe because the decoder restores the same delimiter bytes at the same
positions; it makes no semantic CSV claim.

## Evidence boundary

- Stage: dirty-tree bounded development probe
- Base commit: `323979c3e0174b2467e3bdc9ff05a61f54a83220`
- Corpus: first record-aligned 8 MiB of each frozen development family
- Corpus manifest SHA-256:
  `bac7f9bb94bac38dc621d927ff8cca70a8c2fde92c3689525a1de2d87d098f61`
- Each source slice SHA-256 is recorded in the machine-readable probe artifact.
- Public validation: unopened
- Private holdout: sealed

This is not a full-corpus, product, public-validation, private-holdout,
independent, market-leading, or state-of-the-art result.

## Next decision

Retain the representation and exact fallback. Replace both transform directions
with bounded native code, then run a clean full-development candidate decision
against Brotli-11, zstd-19, zstd-9, zstd-3, and LZ4-1. The native candidate must
preserve the size result while moving toward the frozen dense and balanced
speed gates.
