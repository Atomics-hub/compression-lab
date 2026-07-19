# WK-C1 recursive template/schema columnarization screen

Status: frozen training-only protocol. No WK-C1 corpus measurement or result
existed when `config/text-source-wk-c1-screen-v1.json` was written.

## Decision being purchased

The immutable TS-H1 framing probe was neutral on Wikimedia, and the four BWT
diagnostics were 13.42% to 17.41% larger than Kanzi-max on the two-item wiki
screen. Neither result tests the remaining markup-specific hypothesis: repeated
template invocations may expose longer homogeneous value contexts when values
are grouped by a schema learned only from the current bytes.

WK-C1 therefore tests one exact representation against an attribution
ablation. It is not an ideal-bits estimate and does not use an external
template database, learned dictionary, weights, or side state.

## Frozen information boundary

Only English Wikibooks and Wikinews from the already-consumed training split
may be opened. Rust, LLVM, and Wikiversity remain reserved and inaccessible;
CPython and TypeScript are out of scope and are not opened. Public validation
and private holdout remain sealed. The runner must obtain the roster from the
manifest but may stat, hash, and open only the two screen paths. Reserved and
out-of-scope paths need not exist.

The practical census, manifest, pinned Kanzi binary, structural result and
public evidence, successor-routing decision, and completed BWT rejection and
publication are SHA-256-bound in the config. The BWT result remains an exact
negative diagnostic with `axiom_wins = 0`.

## Frozen scanner and reversible grammar

The scanner operates on bytes, never Unicode-normalized text. It recognizes
balanced `{{...}}` invocations recursively to depth 64. A top-level pipe within
an invocation separates fields; a top-level equals sign within a parameter
separates its exact serialized name and value. Pipes and equals signs inside a
nested template or balanced `[[...]]` link do not split the surrounding field.
Exact lowercase `<!--...-->` comments and `<nowiki>...</nowiki>` regions are
protected raw bytes. Triple-brace parameters, unclosed constructs, excessive
depth/count/field limits, nested constructs in a template name or named-key,
and any unsupported region take the raw exact escape path.

The encoder is bounded before allocation by the limits in the config: at most
2 GiB input, 64 levels, 1,000,000 accepted templates, 8,000,000 total fields,
1,024 fields per template, 4,096-byte template and key names, and 128 MiB per
field. The decoder enforces the same counts, canonical varints and section
lengths, exact source-size limit, and full input consumption.

Both variants serialize recursive structure and raw escapes. The full variant
serializes every accepted value as a recursively encoded subdocument, groups
those byte strings into columns keyed by the exact serialized
`(template-name,param-key)` pair, and orders the table lexicographically by the
serialized key. Positional keys contain their zero-based parameter ordinal.
Counted preorder metadata retains exact invocation order, exact parameter
order, named-versus-positional status, column identity, and row identity. The
structure-only ablation uses the identical recursive parser and metadata but
keeps value subdocuments in invocation order instead of schema columns. Exact
template names, named keys, delimiters, raw bytes, column tables, row
permutations, metadata, and value streams are all inside the transform frame.

Decoder reconstruction must reproduce the original byte length and SHA-256.
Malformed, unsupported, or noncanonical input cannot disappear: it is either
an exact counted raw escape or a closed failure.

## Complete candidate and backend

Each transform frame is compressed with the pinned Kanzi 2.5.3 level-9 path:

```text
kanzi --compress --level=9 --block=1g --jobs=1 --verbose=0 --force \
  --input=TRANSFORM --output=PAYLOAD
kanzi --decompress --jobs=1 --verbose=0 --force \
  --input=PAYLOAD --output=TRANSFORM
```

The final AXWK2 artifact contains magic/version, variant, original size and
SHA-256, backend identity, backend payload size and SHA-256, and the complete
payload. The compressed WKC1 frame already contains every schema table,
permutation, metadata stream, value stream, and raw escape. The filesystem size
of AXWK2 is the candidate byte count; there is no uncounted dictionary or side
file. Encode and decode measurements cover transform, Kanzi, wrapping,
unwrapping, and inverse transform. Two measured repetitions after zero warmups
must produce identical complete AXWK2 SHA-256 values. Every decode must restore
the manifest-bound size and SHA-256. Complete encode and decode peak RSS must
not exceed 4 GiB.

The Kanzi-max control is reused from immutable census evidence and is not
rerun. Its complete bytes are 12,622,786 for Wikibooks, 11,534,002 for
Wikinews, and 24,156,788 in aggregate. The matching two-item TS-H1 control is
12,630,261 plus 11,524,881 = 24,155,142 complete bytes.

## Frozen integer gates

Percentages are explanatory; byte comparisons decide:

| Gate | Exact requirement |
| --- | ---: |
| 1% signal vs Kanzi-max | full candidate <= 23,915,220 bytes |
| 2% strong signal vs Kanzi-max | full candidate <= 23,673,652 bytes |
| 1% better than two-item TS-H1 | full candidate <= 23,913,590 bytes |
| Wikibooks +0.5% item guard | <= 12,685,899 bytes |
| Wikinews +0.5% item guard | <= 11,591,672 bytes |
| Columnarization attribution | `full * 10000 <= structure-only * 9950` |
| Resource cap | every complete encode/decode peak RSS <= 4,294,967,296 bytes |

The full variant signals only if it is complete, exact, deterministic, within
both item and resource guards, at least 1% smaller than Kanzi-max, at least 1%
smaller than TS-H1, and at least 0.50% smaller than structure-only. A signal
below 2% is retained as diagnostic evidence and admits no codec. Only a strong
signal under every other gate admits a separately frozen codec prototype.
No-signal rejects WK-C1 on this training split. The structure-only result is
always reported but cannot independently admit a codec.

Even a strong screen is not a product or category win. A later complete Axiom
artifact must remain at least 5% smaller than Kanzi-max (no more than 22,948,948
bytes here), count decoder code and every state byte, restore exactly, remain
deterministic, and pass corruption, streaming, speed, portability, packaging,
and independent-reproduction gates.

## Claim ceiling

This is a training-only recursive wikitext representation screen. Exact
complete candidates are development artifacts, not Axiom wins, validation
results, holdout results, independent reproduction, product codecs,
novel-algorithm results, or state-of-the-art evidence. `axiom_wins` remains zero
regardless of the screen decision.
