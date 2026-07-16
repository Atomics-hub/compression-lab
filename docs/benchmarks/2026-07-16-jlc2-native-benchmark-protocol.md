# JLC2 native benchmark protocol

## Scope

This protocol measures the byte-identical native JCT1 extractor and
reassembler plus the complete JLC2 level-6 frame on the five opened LogTrie
development families. It is frozen before a quiet-host decision run.

No validation file may be downloaded or scored from this protocol.

## Implementation under test

- Rust scans LF-delimited records and emits deterministic JCT1 bytes.
- The Python reference and Rust implementation must emit byte-identical JCT1.
- The skeleton is compressed first at zstd level 6.
- Independent channels are compressed concurrently at zstd level 6.
- Channel output order is fixed, so parallel execution cannot change bytes.
- Decode inflates the skeleton, inflates channels concurrently, rebuilds JCT1,
  reassembles in Rust, and verifies the outer SHA-256.

## Host preflight

Before the decision run, execute:

```text
scripts/wait-for-quiet-host.py \
  --gates config/jlc2-native-gates.json \
  --consecutive 3 \
  --interval 10 \
  --timeout 600
```

The run is eligible only when one-minute load divided by logical CPU count is
at most 1.0 for three consecutive samples. Record load and logical CPU count
at run start, every family checkpoint, and run end.

## Timing

For each family:

1. Verify SHA-256 against the corpus manifest.
2. Produce Python-reference and native JCT1 once and require byte identity.
3. Warm each measured operation once.
4. Run five repetitions and use the median:
   - native JCT1 transform;
   - native JCT1 reassembly;
   - complete JLC2 compression;
   - complete JLC2 decompression.
5. Require identical complete frame bytes across all compression repetitions.
6. Require exact source bytes from every decode repetition.
7. Atomically checkpoint JSON after each family.

Rates use decimal MB/s and original source bytes.

## Frozen speed gates

Use `config/jlc2-native-gates.json`:

- native transform: at least 250 MB/s on every family;
- complete compression: at least 75 MB/s on every family;
- aggregate complete compression: at least 100 MB/s;
- complete decompression: at least 250 MB/s on every family;
- at least five repetitions;
- no more than 256 channels.

The ratio result must remain byte-identical to the accepted JLC2 development
artifact.

A speed pass advances only to memory, selector/fallback, streaming, fuzzing,
and competitive-baseline work. It does not authorize blind validation or a
public performance claim.
