# Dense-matrix representation development protocol

## Decision

Freeze a bounded representation search before inspecting transform output.
The fresh census identified one narrow blocker: unchanged TBS1 is the smallest
codec on record tables but is 59.88% larger than bzip2-9 on dense feature
matrices. This protocol protects the record-table path while testing three
materially distinct exact-byte matrix representations.

## Evidence boundary

Only the three already acquired development matrices may be used:

| Family | Source bytes | TBS1 bytes | bzip2-9 bytes |
| --- | ---: | ---: | ---: |
| Multiple Features pixels | 1,442,000 | 130,296 | 77,935 |
| Optical Digits | 563,639 | 117,259 | 89,361 |
| Semeion digits | 2,889,702 | 72,709 | 33,015 |
| **Aggregate** | **4,895,341** | **320,264** | **200,311** |

The public-validation matrices, Gisette and Madelon, remain unopened. Track
labels, source IDs, filenames, DOIs, declared delimiters, and family identities
are evaluation metadata, never production-selector inputs. No consumed TBL1
family contributes bytes, statistics, feature counts, header spellings, codec
deltas, or thresholds.

## Frozen hypotheses

### DMT1: separator-aware token alphabets

Split the source into alternating field lexemes and exact separator runs.
Dictionary-code both alphabets, bit-pack their indices, and entropy-code the
complete framed representation. Reconstruction must restore repeated spaces,
commas, tabs, CRLF/LF spelling, trailing separators, and every field byte.

### DMI1: typed integer and binary planes

Only when bounded parsing proves a rectangular integer or binary matrix,
retain exact lexeme and separator reconstruction metadata while coding values
column-major, as deltas, or as bit planes. Parsing failure is normal and must
route to an equally framed direct fallback.

### DMB1: fixed-row byte planes

Only when bounded bytes prove stable row widths, transpose byte positions or
small byte groups without semantic parsing. Preserve exact row terminators and
the final unterminated row state.

No hypothesis may special-case a dataset, filename, row count, column count,
header string, or known digest.

## Promotion gates

The strongest fresh-development baseline is bzip2-9 at 200,311 aggregate
bytes. A representation advances only if all of these pass:

1. complete framed output is at most 190,295 bytes, at least 5% below bzip2-9;
2. at least two of three families beat their strongest exact standard by 5%;
3. no family regresses more than 2% against its equally framed direct fallback;
4. the existing record-table aggregate regresses by at most 0.25%;
5. compression is at least 50 MB/s and decompression at least 250 MB/s;
6. peak RSS is at most 512 MiB with bounded streaming memory;
7. output is deterministic, exact, completely accounted, corruption-rejecting,
   and decodable by a portable reference implementation;
8. a selector trained with each development family left out uses no more than
   1 MiB of current-file bytes and no evaluation metadata; and
9. when both candidates are materialized, routing compares their complete
   framed sizes and never expands over the equally framed direct fallback.

Failed hypotheses remain documented. Passing a development gate authorizes a
candidate lock, not a performance claim or public-validation acquisition.

## Sequence

1. Implement exact reference transforms and exhaustive malformed-input tests.
2. Probe DMT1, DMI1, and DMB1 independently with complete frame overhead.
3. Reject dominated representations before native optimization.
4. Implement only the surviving representation in the Rust core.
5. Train and test the bounded selector with leave-one-family-out evaluation.
6. Re-run all eleven standards and publish the next full comparison chart.
7. Freeze candidate, format, runner, evaluator, operational gates, and receipt.
8. Only then authorize the first public-validation acquisition.

## Claim ceiling

This protocol fixes a development experiment. It is not compression evidence
and supports no public-validation, category-best, market-leading, or
state-of-the-art claim.
