# JLF2 and JLS2 encoded-integrity protocol

## Rejected integrity model

JLF1 and JLS1 stored SHA-256 of the original bytes. That proves decoded
content, but does not necessarily reject every encoded-bit mutation: a bit in
unused backend padding could change the frame while leaving decoded bytes
unchanged.

The corruption gate requires detection of frame corruption, not only output
corruption. JLF1/JLS1 are therefore rejected before validation.

## JLF2

JLF2 retains the exact concurrent direct-versus-JLC2 selector and adds
SHA-256 of the selected payload. Decode verifies payload SHA before invoking
either backend, then verifies original SHA after decode.

## JLS2

JLS2 retains 16 MiB record-aligned segmentation and adds:

- explicit zero flags and reserved fields;
- SHA-256 of every byte after the stream header, including segment headers and
  complete JLF2 frames.

The bytes API verifies encoded payload SHA before segment decode. The file API
hashes segment headers and frames while reading, writes restored bytes only to
a temporary destination, and publishes the destination only after both
encoded and original hashes match.

## Frozen gates

1. Every single-bit mutation of the deterministic small fuzz frame is
   rejected.
2. All truncations and appended bytes are rejected.
3. Random JLF/JLS/JCT bytes fail within the declared output bound.
4. Exact fallback and segmentation ratios remain above their frozen gates.
5. File and bytes APIs emit identical bytes.
6. Memory and quiet-host speed gates remain unchanged.

Blind validation remains unopened.
