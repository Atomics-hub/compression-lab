# JSON-log length-window discovery protocol

## Decision question

Compression Lab 0.1 improves structured text relative to Zstandard level 3 but
does not beat ratio-oriented baselines. This discovery asks whether
line-oriented JSON logs are a stronger product wedge: can nearby records with
the same byte length be represented as bounded references plus compact
byte-exact residuals, then compressed more effectively than the original
stream?

The first implementation is a research transform named LWX1. It is informed by
the published LogLite observation that nearby same-length log records often
have aligned invariant regions. Compression Lab's implementation is independent
and uses only the paper's public description; the LogLite repository has no
visible software license and its source code must not be copied.

Primary research reference:

- Benzhao Tang et al., “LogLite: Lightweight Plug-and-Play Streaming Log
  Compression,” PVLDB 18(11), 2025, arXiv:2507.10337.

## Candidate

LWX1:

- splits only on byte `0x0a` and retains line terminators exactly;
- maintains a bounded most-recent-first window for each exact record length;
- compares up to eight same-length references;
- XORs the record with the best reference;
- encodes aligned zero runs and literal residual runs in byte-aligned commands;
- emits the raw record when the residual representation is not locally smaller;
- is deterministic, byte-exact, and independent of JSON parsing or schema
  knowledge.

The transform is evaluated both with Zstandard level 3 and level 9. Complete
candidate selection must retain a direct-backend fallback; transformed output
may never make the production frame larger.

## Discovery boundary

Discovery may use only:

- deterministic synthetic JSONL families generated in the repository;
- public JSON families already exposed by the version-0.1 research history.

No new family designated for blind validation may be downloaded or measured
until the representation, window policy, frame metadata, and validation gates
are frozen in a follow-up protocol. The private holdout remains sealed.

## Discovery gates

Advance LWX1 to native implementation and fresh public train/validation design
only if all of these pass:

1. Exact round trips pass for empty input, LF, CRLF, a final unterminated
   record, arbitrary bytes, and malformed/truncated streams.
2. LWX1 plus Zstandard level 9 is at least 5% smaller than direct Zstandard
   level 9 on at least two structurally distinct JSONL discovery families.
3. The transformed candidate beats direct Zstandard level 3 on every promoted
   discovery family.
4. At least 75% of records use references on each promoted family.
5. The pure-Python prototype sustains at least 10 MB/s on 4 MiB discovery
   inputs; a native promotion target is at least 250 MB/s.
6. Complete candidate selection prevents expansion on non-log or adversarial
   inputs.

## Promotion and claim gates

Passing discovery is not evidence of a world-class compressor. Before any
product integration:

- freeze at least six licensed training families and six repository-separated
  blind validation families totaling at least 100 MiB;
- compare direct zstd-3/9/19, Brotli-6/11, LZMA-9, 7-Zip-9, gzip-9, LogLite,
  and reproducible log-specific baselines such as CLP or PBC where licensing
  and platform support permit;
- require at least 5% aggregate size improvement over zstd-9 on blind JSON logs;
- require a Pareto position against the strongest reproducible log-specific
  baseline, not merely a win over a fast general-purpose level;
- report compression and decompression speed, peak memory, stream latency,
  corruption behavior, exact byte restoration, and performance by family;
- rerun the frozen candidate on an isolated hosted machine and seek an
  independent reproduction before using “best” or “state of the art.”
