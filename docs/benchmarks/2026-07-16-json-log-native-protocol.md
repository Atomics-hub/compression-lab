# JSON-log LWX2 native discovery protocol

## Hypothesis

LWX1 established a large synthetic ratio opportunity but failed its frozen
Python speed gate. LWX2 asks whether the opportunity survives a simpler
single-reference policy that can execute in one bounded native pass.

The representation and gates below are frozen before measuring LWX2 sizes or
throughput.

## Representation

LWX2:

- splits only at byte `0x0a` and preserves all input bytes;
- uses the most recent record of the same length as the sole reference;
- stores history in 1,024 deterministic length-hash slots;
- references records no larger than 32 KiB, bounding retained history to
  approximately 32 MiB plus allocator overhead;
- replaces a slot on length collision, identically in encoder and decoder;
- emits a raw record when zero/literal run coding is not locally smaller;
- uses no source-specific rule, JSON parser, learned model, or validation
  identity;
- feeds the complete transformed stream to zstd-3 and zstd-9 and retains an
  exact direct-backend fallback.

The C ABI must validate null pointers, capacities, varints, record counts,
reference availability, output bounds, complete input consumption, and exact
output length.

## Discovery data

Use the same three already-exposed deterministic JSONL families from LWX1.
They are discovery data only and may be reused to compare the changed
representation. No fresh public validation family may be opened.

## Frozen gates

Advance to fresh public corpus design only if all gates pass:

1. Native and Python reference encoders produce byte-identical LWX2 streams.
2. Native and Python decoders restore every discovery and adversarial fixture
   exactly.
3. LWX2+zstd-9 remains at least 20% smaller than direct zstd-9 on all three
   discovery families.
4. LWX2+zstd-9 is smaller than Brotli-11 on at least two of three discovery
   families.
5. At least 75% of records use a reference.
6. Complete compression throughput, including transform and zstd-9, reaches at
   least 100 MB/s on the local 4 MiB discovery inputs.
7. Native transform-only throughput reaches at least 250 MB/s.
8. Native decode plus zstd decode reaches at least 250 MB/s.
9. Complete direct fallback prevents expansion on random, already-compressed,
   non-line-oriented, and long-record inputs.
10. Rust debug/release tests, Python equivalence tests, malformed-input tests,
    and the existing full suite pass.

No world-class claim follows from this protocol. A pass authorizes only the
fresh 100 MiB public train/validation corpus and log-specific baseline phase
defined by the LWX1 promotion requirements.
