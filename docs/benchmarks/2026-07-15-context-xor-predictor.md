# Dual-context XOR predictor decision

## Purpose

STX2 showed that reorganizing the existing token transform could not fund its
decode cost. This experiment moves into the planned predictor seam with a
bounded, deterministic context model whose output can be measured separately
from selector and frame behavior.

The design is informed by Bloom's LZP observation that the most recent matching
context can predict following data, while deliberately avoiding another
literal/match parser because Zstandard already encodes literal and sequence
streams. Primary references:

- Charles Bloom, “LZP: A New Data Compression Algorithm,” DCC 1996,
  https://doi.org/10.1109/DCC.1996.488353
- RFC 8878, “Zstandard Compression and the `application/zstd` Media Type,”
  https://www.rfc-editor.org/rfc/rfc8878.html

This was a public-corpus prototype. The private holdout remained sealed.

## Candidate

The native prototype used two 65,536-entry hashed context memories:

- the previous four reconstructed bytes;
- the previous eight reconstructed bytes;
- an exact context tag, predicted next byte, and saturating confidence per
  entry;
- confidence preference for stable eight-byte context, then stable four-byte
  context, then the most recent matching prediction;
- deterministic table replacement on collision;
- a complete model reset every 1 MiB for bounded memory and block locality.

For each source byte, the transform emitted `actual XOR prediction`. The inverse
used already reconstructed bytes to reproduce the same prediction and recover
the source. The transformed stream was exactly source-sized and fed to
Zstandard level 3. This isolates whether the context predictor exposes entropy
that the existing backend can exploit.

The native implementation was deterministic and byte-exact across block
boundaries, arbitrary binary bytes, empty input, and incompressible input. Four
optimized Rust tests and two dedicated Python tests passed before the prototype
was removed after its decision gate.

## XOR residual result

| File | Direct zstd-3 | Predictor plus zstd-3 | Delta | Zero residuals |
| --- | ---: | ---: | ---: | ---: |
| SQLite ZIP | 2,946,008 | 2,946,008 | 0 | 0.45% |
| Chinook SQLite | 379,634 | 409,141 | +29,507 | 49.66% |
| NOAA PDF | 437,216 | 441,756 | +4,540 | 3.20% |
| sqlite3.h | 179,736 | 281,661 | +101,925 | 68.73% |
| sqlite3.c | 2,434,606 | 3,910,549 | +1,475,943 | 68.54% |
| sqlite3ext.h | 7,358 | 10,995 | +3,637 | 75.61% |
| shell.c | 306,310 | 484,660 | +178,350 | 67.90% |
| Chinook JSON | 175,491 | 216,527 | +41,036 | 86.76% |
| **Total** | **6,866,359** | **8,701,297** | **+1,834,938** | — |

The transform grew the aggregate payload by 26.72%. It also ran at only
16–36 MB/s on the public files, below the required product range. High zero
rates were not sufficient because incorrect XOR residuals destroyed literal
structure that Zstandard would otherwise model directly.

## Mask-and-miss ablation

To distinguish predictor quality from XOR representation, a second exact
encoding bit-packed prediction successes and retained actual bytes only for
misses. The mask and miss streams were compressed independently with Zstandard
level 3, including 16 bytes of stream-size metadata.

| File | Direct zstd-3 | Mask plus misses | Delta |
| --- | ---: | ---: | ---: |
| SQLite ZIP | 2,946,008 | 2,959,213 | +13,205 |
| Chinook SQLite | 379,634 | 468,361 | +88,727 |
| NOAA PDF | 437,216 | 443,867 | +6,651 |
| sqlite3.h | 179,736 | 211,497 | +31,761 |
| sqlite3.c | 2,434,606 | 2,991,560 | +556,954 |
| sqlite3ext.h | 7,358 | 8,830 | +1,472 |
| shell.c | 306,310 | 379,351 | +73,041 |
| Chinook JSON | 175,491 | 185,015 | +9,524 |
| **Total** | **6,866,359** | **7,647,694** | **+781,335** |

Separating prediction decisions and unchanged miss bytes cut the loss by more
than half, but the candidate remained 11.38% larger than direct Zstandard. The
negative result therefore belongs to the top-one prediction representation,
not only to XOR coding.

## Decision

Reject the dual-context predictor as a front-end transform. Remove its native
ABI and tests rather than retaining dead experimental surface. Do not integrate
it into adaptive-v3, open the private holdout, or claim that high prediction
accuracy implies compression value.

The useful result is architectural: a predictor must provide calibrated symbol
probabilities directly to its entropy coder. Converting only the top prediction
into XOR residuals or a success mask discards too much distributional
information and duplicates work that a mature LZ backend already performs.
The next predictor candidate should therefore pair bounded multi-order context
probabilities with arithmetic coding or ANS, and must expose model-only
cross-entropy before native format integration.
