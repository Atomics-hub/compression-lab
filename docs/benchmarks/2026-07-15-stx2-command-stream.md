# STX2 command-stream size gate

## Purpose

Whole-frame profiling showed that the STX1 structured-text path spends about
half of its fused core time expanding 318,206 dictionary references on the
9.5 MB SQLite source. STX2 tests a representation intended to make that decode
loop simpler: one-byte token commands plus length-delimited literal runs.

This was a benchmark-only prototype. Its explicit gate required complete-frame
size to beat STX1 before native implementation or adaptive-v3 integration.
The private holdout remained sealed.

## Candidate format

The reversible prototype used:

- `STX2` magic and the existing length-prefixed ranked dictionary;
- token commands `0..dictionary_count-1`, reducing each selected-token
  reference from STX1's two bytes to one;
- compact literal commands `dictionary_count..254`, where the command itself
  encodes short literal length;
- command `255` followed by an unsigned LEB128 length and raw literal bytes for
  larger runs;
- the same deterministic 1 MiB first/middle/tail dictionary ranking as STX1;
- Zstandard level 3 over the complete transformed stream;
- the same four-byte transformed-size field used by the adaptive-v3 recipe.

Arbitrary bytes, including `0xff`, are legal inside length-delimited literals
and require no escaping. A prototype decoder validated exact output length,
dictionary commands, LEB128 termination, literal bounds, and complete input
consumption.

## Dictionary-size sweep

The sweep tested 16, 32, 64, 96, 128, 160, 192, 224, and 254 ranked tokens on
all five structured public files. Aggregate complete recipe payload was:

| Dictionary tokens | STX2 bytes | Delta versus STX1 |
| ---: | ---: | ---: |
| 16 | 3,298,283 | +306,526 |
| 32 | 3,315,061 | +323,304 |
| 64 | 3,347,097 | +355,340 |
| 96 | 3,363,406 | +371,649 |
| 128 | 3,389,173 | +397,416 |
| 160 | 3,395,266 | +403,509 |
| 192 | 3,400,815 | +409,058 |
| 224 | 3,405,544 | +413,787 |
| 254 | 3,416,850 | +425,093 |

Sixteen tokens was the best single policy. Allowing a separate optimum for each
file changed only `sqlite3ext.h`, which preferred 32 tokens, and reduced the
STX2 total by just 74 bytes.

## Complete size result

| File | Direct zstd-3 | STX1 | Best STX2 | STX2 minus STX1 |
| --- | ---: | ---: | ---: | ---: |
| Chinook JSON | 175,491 | 170,943 | 183,695 | +12,752 |
| sqlite3.h | 179,736 | 169,199 | 193,170 | +23,971 |
| sqlite3.c | 2,434,606 | 2,349,087 | 2,588,025 | +238,938 |
| sqlite3ext.h | 7,358 | 7,811 | 8,092 | +281 |
| shell.c | 306,310 | 294,717 | 325,227 | +30,510 |
| **Total** | **3,103,501** | **2,991,757** | **3,298,209** | **+306,452** |

Best-per-file STX2 was 10.24% larger than STX1 and 194,708 bytes larger than
direct Zstandard level 3. It failed on every individual file, not merely in the
aggregate.

## Correctness

The reversible encoder and decoder round-tripped all five files after the STX2
stream itself was compressed and decompressed with Zstandard. The exact
best-policy exception, 32 tokens on `sqlite3ext.h`, was also independently
round-tripped and produced an 8,092-byte complete recipe payload.

This confirms that the size loss is a property of the representation rather
than a malformed or non-reversible prototype. The likely cause is that literal
framing disrupts source context and adds a command per token-adjacent literal
run; one-byte token references do not repay that entropy cost after Zstandard.

## Decision

Reject STX2 without adding production code, native ABI, recipe identifiers, or
decoder complexity. Its intended speed advantage does not earn measurement
because it fails the prerequisite ratio gate decisively.

STX1 remains the structured-text representation. The next research direction
should preserve its interleaved literal context while reducing reference
dispatch cost, or find a different transform family whose size gain is large
enough to fund decode overhead. Any successor must first beat STX1 and direct
zstd-3 on complete bytes using public validation data.
