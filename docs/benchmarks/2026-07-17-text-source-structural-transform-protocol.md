# Text/source structural transform development protocol

## Purpose

Test whether reversible structural separation adds compression information that
Kanzi 2.5.3 level 9 does not already capture. This is a representation probe on
the seven verified development items. It does not alter the practical baseline
census, open validation, or support a product or state-of-the-art claim.

The implementation is `src/compresslab/text_source_transform.py`. This protocol
was written before running any transformed item through a compression backend.

## Baseline dependency

The probe must not run until the complete 630-trial practical census has:

- completed every required item/codec pair;
- restored every measured source exactly;
- produced byte-identical artifacts across five measured repetitions; and
- named the per-track and per-item ratio leaders.

The current warmup signal suggests Kanzi level 9 may lead both tracks, but that
is not final evidence. Because TS-H1/H2 specifically test residual information
left by Kanzi's transform and context-mixing stack, the executable probe must
bind the completed baseline `results.json` SHA-256 and verify Kanzi is the
actual smallest eligible backend on both tracks. It must refuse to run if the
warmup order does not survive; a changed leader requires a new, predeclared
backend adapter and protocol revision.

## Predeclared hypotheses

### TS-H1: framing demultiplex

Generic codecs receive binary counts, paths or IDs, titles, and text
interleaved. Move structural metadata ahead of the content, encode nonnegative
integers as bounded varints, delta-code Wikimedia IDs, and front-code sorted
source paths and adjacent titles. Preserve record order and the original
trailing manifest digest.

Expected mechanism: longer uninterrupted text contexts and less binary framing
noise. The uncompressed framing audit bounds this as a diagnostic hypothesis,
not the likely final 5% solution: source framing is 0.18--0.80% of input and
Wikimedia framing is 0.99--2.38%.

### TS-H2: deterministic source extension lanes

In addition to TS-H1, concatenate file contents into lexicographically ordered
extension lanes while retaining original record order, path, lane ID, and
content size in the reversible metadata. The development corpus has strong
homogeneous lanes: TypeScript is entirely `.ts`, Rust is overwhelmingly `.rs`,
LLVM is dominated by `.cpp` and `.h`, and CPython is dominated by `.c`, `.py`,
and `.h`.

Expected mechanism: prevent unrelated language grammars and comment/identifier
statistics from evicting one another in the backend model. A single-lane
project remains an honest negative control for the metadata-only effect.

### Explicitly deferred

Grammar tokenization, identifier/literal/comment channelization, wiki-markup
tokenization, learned dictionaries, and a new entropy coder are not part of
this probe. They may be admitted only after TS-H1/H2 show which residual is
worth attacking. This keeps a failed structural idea cheap and attributable.

## Candidate artifact and accounting

For each applicable item and hypothesis:

1. transform the complete source item deterministically;
2. compress the complete transformed bytes with the exact winning practical
   backend and setting from the frozen census;
3. wrap the backend payload in an Axiom research envelope containing format
   magic/version, transform kind, original size, original SHA-256, backend ID,
   payload length, and payload SHA-256;
4. count every envelope and backend byte;
5. decompress, invert the transform, and require the exact original size and
   SHA-256; and
6. require two measured candidate artifacts to have the same complete SHA-256.

Envelope construction and extraction run as measured subprocesses. Their wall
time and peak RSS are included in the candidate encode/decode totals, so the
resource and speed screen covers the complete artifact path rather than only
the transform and backend payload. AXTP2 extraction hashes the complete backend
payload before decoding, deletes a rejected extraction, and fails closed on any
payload mutation. The measured unwrap worker also compares the declared source
size and SHA-256 with the frozen item identity and deletes the extracted payload
before rejecting any mismatch, so no rejected bytes reach the backend.
Extraction streams fixed-size chunks and never allocates from declared header
sizes. It deletes any stale destination before starting and deletes partial
output on every exception. The corruption preflight covers all 87 truncated
header lengths plus one-byte payload truncation and append cases.
The transform decoder validates a nonnegative integer output limit before
reconstruction, accepts the exact source-size boundary, rejects a one-byte
smaller boundary and a forged uint64 maximum declaration, and caps record count
before iterating metadata.
The encoder applies the same record and path/title limits while parsing source
items and rejects more than 4,096 extension lanes before constructing lane
payloads. It therefore cannot emit a structurally valid artifact that its own
decoder rejects solely because the encoder exceeded a frozen format bound.
For TS-H2, the decoder independently derives the sorted extension roster from
reconstructed paths and requires exact equality with the serialized lane
roster. Duplicate, reordered, missing, renamed, or unused zero-length lanes are
noncanonical and rejected.
Both source paths and Wikimedia titles must use the maximal common prefix with
their preceding value. A shorter prefix plus a longer suffix that reconstructs
the same bytes is an alternate encoding and is rejected as noncanonical.

Every successful receipt must contain exactly three compression commands
(transform worker, pinned Kanzi level 9, AXTP2 wrap) and exactly three inverse
commands (AXTP2 unwrap, pinned Kanzi decode, bounded transform decode), in that
order and with the frozen arguments. Failed receipts may contain only the exact
executed prefix of the same chain. Resume, raw publication, and offline public
evidence verification all reject a changed command or reordered phase.

No external dictionary, tokenizer, weights, model, or preprocessing state is
allowed. The backend binary is pinned toolchain code exactly as in the baseline
census; no backend data is trained or changed for this probe.

After execution, `scripts/publish-text-source-structural-transform.py` must
revalidate all 33 structural receipts, revalidate all 630 practical-baseline
receipts, reconstruct the decision from those receipts, and atomically publish
an exact five-file bundle: Markdown, comparison JSON, SVG, privacy-safe public
evidence JSON, and a publication receipt. Structural `evidence.json` retains
all decision-bearing fields from all 33 receipts, replaces only process streams
with byte-counted SHA-256 commitments, and binds the separately checked-in
630-trial baseline public evidence by SHA-256. Local repository and work paths
must be sanitized when receipts are created, and any remaining local absolute
path makes publication fail. The standalone
`scripts/verify-text-source-structural-publication.py` must reconstruct the
structural summary and decisions from the checked-in five-file bundle plus the
separately verified practical-baseline five-file bundle, without the ignored
corpus, raw baseline directory, or raw structural directory. The chart
must retain all 15 practical standards beside every applicable Axiom variant
and show complete bytes, ratio, compression/decompression speed, peak RSS,
exactness, determinism, an explicit yes/no for whether an admitted Axiom
candidate beat each standard, portability status, runner comparability, the
hypothesis decision, and this evidence boundary. Size is directly comparable
because every row counts a complete artifact over identical source bytes.
Candidate speed and memory are same-host context, not a paired timing claim,
because the later subprocess-chain run and frozen baseline census execute
separately.
A structurally valid process or exactness failure must remain publishable as
negative evidence with its failed fields visible; missing receipts, altered
identities, inconsistent phase accounting, or unreconstructable summaries must
still make publication fail closed.

## Execution order

Use one warmup and two measured repetitions per item/hypothesis, shuffled with
seed `20260718`, one backend thread, and a 12-hour limit per compression or
decompression operation. Run only from a fully clean commit, including no
untracked files. Preserve one atomic receipt per repetition so the run is
resumable, but accept an existing attempt or receipt only when its complete
identity, outcome, phase count, wall-time sum, peak-RSS maximum, artifact
accounting, and evidence bindings still match the frozen protocol. Do not run
concurrently with the baseline census or any other CPU/memory-intensive
benchmark.

## Frozen gates

TS-H1 and TS-H2 are evaluated independently and separately for source-code and
Wikimedia tracks.

| Gate | Requirement |
| --- | --- |
| completeness | every applicable development item has two measured trials |
| exactness | every restored byte count and SHA-256 equals the source |
| determinism | both complete candidate artifact SHA-256 values match |
| accounting | envelope plus all backend bytes are counted |
| corruption preflight | a one-bit backend-payload mutation and every possible one-bit mutation of the fixed AXTP2 header are rejected before backend decoding, with no extracted payload retained |
| bounded malformed-size handling | all truncated-header lengths and truncated/appended payloads are rejected without allocating from declared sizes or retaining stale/partial output |
| H1 diagnostic ratio | aggregate candidate is at least 0.50% smaller than the same backend on the same items |
| H1 item guard | no item is more than 0.25% larger than its raw-backend artifact |
| H2 source ratio | aggregate candidate is at least 2.00% smaller than the same backend on all four source projects |
| H2 item guard | no source project is more than 0.50% larger than its raw-backend artifact |
| final-specialist admission | at least one hypothesis is 3.00% smaller on its development track with no item regression above 0.50% |
| resource screen | complete encode/decode peak RSS is no more than 2 GiB above the raw backend and no operation times out |

A hypothesis that misses its gate is rejected and retained as negative evidence.
Meeting the 3% admission gate does not establish the requested 5% category win;
it only justifies a more capable successor transform on development data.

## Frozen successor routing

The next material hypothesis is also selected without reading the future
structural result. The ordered rules in
`config/text-source-successor-routing-v1.json` were frozen before TS-H1/H2
execution, and `scripts/route-text-source-structural-successor.py` will accept
only the offline-verified five-file structural publication. It writes an
immutable decision bound to the routing config, comparison, publication
receipt, structural result, and practical baseline. The companion
`scripts/verify-text-source-structural-successor-decision.py` independently
reconstructs both track decisions and rejects edited routes or injected wins.

For source bundles, an admitted or diagnostic TS-H2 signal routes to TS-S1:
bounded reversible lexical-role channels for whitespace, comments,
identifiers, literals, punctuation, and raw escape bytes inside deterministic
extension lanes. If only TS-H1 signals, TS-S1 keeps demultiplexing but drops the
unsupported extension-lane premise. If both structural hypotheses fail, AXTS1
is rejected as the successor base and TS-P1 instead tests a bounded mixed
byte/token predictor plus a completely counted development-trained static
dictionary over canonical source bundles.

For Wikimedia, an admitted or diagnostic TS-H1 signal routes to WK-S1:
bounded reversible plain-text, template/tag, link/entity, title, and metadata
channels. If TS-H1 fails, WK-P1 drops the AXTS1 envelope and tests markup-aware
prediction plus a completely counted development-trained static token
dictionary. Dictionary training and evaluation splits must be frozen before
fitting, and unsupported syntax always has a raw reversible escape path.

Every route remains development-only and starts with zero Axiom wins. Its next
candidate must be at least 5.00% smaller than the strongest eligible complete
practical or admitted research baseline, regress no item by more than 0.50%,
restore exactly, produce two byte-identical measured artifacts, and count all
decoder state. Unavailable or incomplete research baselines stay visible and
cannot be converted into wins. Public validation and private holdout remain
sealed regardless of which rule matches.

## Evidence boundary

- Stage: development representation probe.
- Inputs: the same seven licensed development items already acquired.
- Famous enwik8/enwik9: diagnostic context only and not used for selection.
- Public validation: sealed and unaccessed.
- Private holdout: sealed and unaccessed.
- Research-ceiling codecs: separately audited and not replaced by this probe.
- Claim ceiling: no category, product, market-leading, world-best, or
  state-of-the-art claim.
