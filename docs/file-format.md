# Compression Lab frame format

## Compatibility contract

The current encoder writes version 3. The decoder accepts versions 1, 2, and 3.
Existing meanings are immutable; an incompatible change requires a new version
number. All integers are unsigned and big-endian.

The `.clab` suffix is conventional. Detection uses the frame header, not the
filename. The format is lossless and deterministic for a fixed package and
dependency version. It provides corruption detection, not encryption or
authentication.

## Common header

Every frame begins with this 46-byte header:

| Offset | Bytes | Meaning |
| ---: | ---: | --- |
| 0 | 4 | ASCII magic `CLAB` |
| 4 | 1 | format version |
| 5 | 1 | backend identifier |
| 6 | 8 | original byte length |
| 14 | 32 | SHA-256 of the original bytes |

Versions 1 and 2 store one backend payload after this header. They remain
decoder compatibility formats and are not emitted by the public encoder.

## Version 3 segmented backend

Version 3 requires backend identifier 6. The common header is followed by a
four-byte segment count and then that many segment records. Empty input has a
zero segment count; non-empty input must have at least one segment.

Each segment has a 13-byte header:

| Bytes | Meaning |
| ---: | --- |
| 1 | recipe identifier |
| 4 | decoded segment length |
| 4 | payload length |
| 4 | CRC32 of decoded segment bytes |

The payload immediately follows. Segment decoded lengths must add exactly to
the common header's original length, the final payload must end exactly at the
frame boundary, every CRC32 must match, and the completed output SHA-256 must
match the common header.

| Recipe | Meaning |
| ---: | --- |
| 0 | stored bytes |
| 1 | Zstandard level-3 frame |
| 2 | delta-transposed bytes in a Zstandard level-3 frame |
| 3 | interleaved STX1 transform in a Zstandard level-3 frame |
| 4 | separately compressed STX1 skeleton and token-code channel |

Recipe 2 applies little-endian 32-bit delta coding followed by byte-plane
transpose. A final one-to-three-byte tail is copied unchanged.

## STX1 structured-text transform

STX1 begins with ASCII `STX1` and a two-byte dictionary count, followed by
`count` entries of a one-byte token length and the token bytes. There are at
most 254 distinct ASCII identifier tokens, each 3 to 64 bytes. Body byte
`0xff` introduces either a dictionary code from 0 through `count - 1` or
`0xfe`, which represents a literal `0xff`.

Recipe 3 prefixes the compressed STX1 frame with the eight-byte transformed
length. Recipe 4 begins with the eight-byte transformed length, four-byte
skeleton length, and four-byte compressed-skeleton length, followed by a
Zstandard skeleton frame and a Zstandard token-code frame.

## Decoder safety requirements

A decoder must reject unknown versions, backends, and recipes; truncated
headers and payloads; zero-length non-empty segments; segment totals beyond the
declared output; trailing bytes; invalid STX1 dictionaries or codes; checksum
failures; and declared output beyond the caller's configured allocation limit.
The reference public API enforces these rules before returning data.
