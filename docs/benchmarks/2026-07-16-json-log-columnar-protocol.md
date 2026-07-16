# Flat-JSON log columnar development protocol

## Motivation

Two source-agnostic record deltas were tested on the five opened LogTrie
development families:

- LWX2 exact-length XOR won strongly on four families but fell back to direct
  Zstandard on Mac.
- LWS1 prefix/suffix splice referenced essentially every record but still
  produced output 10.97% larger than zstd-9 on HealthApp and 11.06% larger on
  Mac.

This rejects record alignment as the complete answer. The next hypothesis is
that mixing JSON fields with different distributions prevents the backend
from exploiting low-entropy columns.

The representation and gates below are frozen before measuring JLC1. The
Hadoop, OpenSSH, and OpenStack validation files remain unopened.

## Frozen category

JLC1 targets newline-delimited flat JSON objects. Each record may contain
string, number, boolean, null, object, or array values, but only top-level
object fields are separated into channels. Non-object or malformed records
remain byte-exact skeleton literals.

This is a deliberately bounded product wedge, not a universal JSON claim.

## Frozen representation

For every record:

1. Scan the top-level JSON object without normalizing or reserializing it.
2. Preserve all original bytes outside value tokens in a skeleton stream,
   including whitespace, key spelling and escaping, key order, punctuation,
   CRLF/LF endings, and the final unterminated record.
3. Assign each distinct raw top-level key token a deterministic channel ID in
   first-seen order, up to 256 channels.
4. Replace each extracted value span in the skeleton with an escaped marker
   and channel ID.
5. Append the exact raw value token to that channel as a length-prefixed byte
   string.
6. If a record cannot be scanned exactly or the channel limit is reached,
   preserve the complete record as a skeleton literal.

Compress the skeleton and every nonempty channel independently with
Zstandard level 3. JLC1 stores:

- magic and version;
- original byte size and SHA-256;
- skeleton raw and compressed sizes;
- channel count;
- every channel raw and compressed size;
- concatenated compressed streams.

The decoder must validate every size, marker, varint, channel reference,
channel exhaustion condition, complete payload consumption, output bound, and
SHA-256 before returning bytes.

No source identity, known schema, field-specific codec, semantic
normalization, learned dictionary, event template, validation identity, or
family exception is allowed.

## Development evidence

Use only the checksum-pinned Apache, HealthApp, HPC, Mac, and ZooKeeper files
in `logtrie-json-log-train-v1`. Reuse the already-recorded zstd-9 and
Brotli-11 sizes from the resumable core benchmark.

## Predeclared gates

Advance JLC1 to a native implementation and selector protocol only if:

1. every file and adversarial fixture round-trips byte-for-byte;
2. every development family is at least 5% smaller than direct zstd-9;
3. aggregate bytes are at least 20% smaller than direct zstd-9;
4. JLC1 beats Brotli-11 on at least four of five families;
5. aggregate bytes are at least 5% smaller than Brotli-11;
6. at least 95% of records are extracted as flat JSON on every LogTrie family;
7. malformed JSON, nested values, escaped strings, CRLF, binary bytes,
   missing fields, reordered fields, and final unterminated records remain
   byte-exact;
8. corruption, truncation, trailing data, impossible sizes, invalid markers,
   channel underflow, and channel leftovers are rejected;
9. the existing Python and Rust suites remain green.

Pure-Python speed is diagnostic only. A ratio pass authorizes a separate
native protocol requiring at least 250 MB/s extraction, 100 MB/s complete
compression, 250 MB/s complete decompression, bounded memory, streaming
chunks, and an exact direct fallback before validation.

If any ratio gate fails, retain JLC1 as rejected development evidence. Do not
download or inspect the blind validation files.
