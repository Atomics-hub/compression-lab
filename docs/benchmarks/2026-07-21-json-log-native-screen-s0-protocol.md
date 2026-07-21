# S0 native JSON/log model screen

Status: refrozen after adversarial review and before any measurement. Evidence
class: development-only model projection.

E1 measured a 2,132 basis-point complete-byte gap between Kanzi-max and the
feasible ZPAQ level-5 ceiling on the three licensed CLUE development items.
E2-A asks whether that generic context-model advantage survives a 460 MiB
memory target. S0 asks a different question: can JSON-aware online mechanisms
plausibly clear the ratio bar with bounded state and at most 96 modeled binary
events per record in the primary arm before Axiom spends time implementing a
complete codec? Literal bytes are permitted as a speed-bounded direct lane, but
each is charged at eight bits and therefore cannot become a free side channel.

## Boundary and authorization

S0 may use only the three development items and identities in
`config/json-log-native-screen-s0-v1.json`. Earlier validation data remains
consumed, no fresh validation corpus is frozen, and the private holdout remains
sealed with identities absent. The screen may not run until E2-A completes with
a transported E1 anchor and byte-identical confirmation. An E2-A anchor or
confirmation failure pauses S0; the other ratio and memory outcomes do not
change S0's frozen matrix or gates.

The exact per-item Kanzi and ZPAQ references were extracted from the pinned E1
GitHub artifacts while they remained available. Their result hashes already
appear in the frozen E2-A config. Before this freeze, both parent result members
were re-downloaded, their SHA-256 values were verified, and their first
repetitions were used to verify all six artifact byte counts and hashes. The
per-item references prevent an aggregate gain from concealing a regression on
the early, middle, or late slice.

## Exact information accounting

Every source byte must be reconstructible from the projected self-contained
streams and the fixed empty initial state. The ledger charges modeled-event
log loss and eight bits for each direct literal byte. It also charges parse and
fallback choices, escapes, lengths, record delimiters, exact JSON spelling and
syntax choices, dictionaries, cache decisions, stream metadata, blocks, coder
allowance, and framing. A decoder pass must regenerate every item and match its
frozen byte count and SHA-256. There is no uncharged reconstruction channel.

A record is the exact byte string through and including LF; a final nonempty
unterminated suffix is one record. Parsing is strict and byte-preserving.
Malformed JSON and records exceeding any bound use direct-literal fallback;
the fallback flag, length, bytes, and delimiter state are charged, and the
record does not update structure-specific state.

All state resets to the fixed empty state at each item boundary, so the
per-item comparison receives no cross-item training. A segment closes at the
first record boundary at or after 16 MiB, but model state persists across
segments. Items run in the config's declared order.

## Matrix

The ten arms isolate five mechanism groups: structural template/field demux
(M1), exact ID and time delta lanes with escapes (M2), a bounded session
reference cache (M3), a bounded online token dictionary (M4), and small
integer-only predictor mixing plus one SSE stage (M5). The full arm and three
leave-one-out arms measure attribution. M4 is quarantined because CLUE's
pseudonymized vocabulary may make token gains less transferable; the full
model without M4 must independently retain at least 700 basis points.

All state is online and input-derived. No trained, static, or shipped dictionary
bytes are free. Record, nesting, field, segment, cache, dictionary, table-byte,
total-state, and event limits are fixed in the config. Cache and dictionary
eviction uses the exact deterministic CLOCK rule there. The full arm must
satisfy `total modeled binary events <= 96 * record count` separately for every
item and for their aggregate; exceeding it kills S0. Direct literal bytes do
not consume this event budget but remain fully charged at eight bits. The raw
and intermediate diagnostic arms may exceed 96 because they cannot trigger
advance.

The primary decision arm is `full`. The other arms exist only for attribution,
apart from the independent `full-minus-m4` quarantine gate. That arm must be at
least 700 basis points smaller than Kanzi; otherwise S0 is labeled
vocabulary-carried and cannot authorize an exact build. M1 and M2 receive
their frozen ordered-chain deltas; M3, M4, and M5 receive their frozen
leave-one-out deltas. Negative attribution floors at zero, interactions follow
the config's fixed policy, and no post-hoc formula is allowed.

Each arm receives one ordered measurement and one deterministic confirmation.
The confirmation is a separate clean-checkout process and must reproduce the
per-item Q24 losses, literal counts, event counts, projected sizes, and decoded
hashes exactly. Before the first measurement, the engine commit and source,
base and refined constants manifests, runner, verifier, and this protocol are
SHA-256 pinned. Both constants manifests enumerate every model parameter and
stream grammar rule; they differ only at the two predeclared refinement table
maxima. A refined run uses its own pinned manifest and clean-checkout
confirmation while engine, runner, and verifier remain byte-identical.

## Projection and gates

The screen reports integer Q24 prequential loss plus direct-literal bytes and
converts their combined charged loss to bytes using the exact formula in the
config. It then charges a 0.5% coder allowance, 32 bytes per started source MiB
after each item reset, 24 bytes per item, and a conservative 4,096-byte framing
allowance. The block allowance is therefore 196 blocks (60 + 67 + 69) rather
than 195 for a concatenated stream. These are projections, not compressed
artifacts or codec results. The Kanzi aggregate exceeds its three raw artifact
payloads by 398 bytes because AXE1O charges shared complete-container framing.

- Advance to an exact native build only at 1,455,326 projected complete bytes
  or smaller, at least 1,500 basis points better than Kanzi-max.
- Permit one predeclared screen refinement from 1,455,327 through 1,540,934
  bytes. No second refinement is allowed.
- Kill the native screen lane at 1,540,935 bytes or larger.
- Report a mechanism at 8,561 attributed bytes; implement it in the exact codec
  only at 17,122 attributed bytes or more.
- For each item, charge its payload, separately rounded 0.5% coder allowance,
  32 bytes per started source MiB, 24 metadata bytes, and 4,096 framing bytes.
  No resulting full-arm item projection may exceed its single-item Kanzi AXE1O
  reference. This is intentionally stricter than aggregate parity: each item
  absorbs the full 4,096-byte projected framing charge, so an aggregate pass
  may still be conservatively killed by one item.

If and only if the first full-arm score lands in the refinement band while all
other gates pass, exactly one capacity refinement is allowed: the context-table
ceiling increases from 192 to 240 MiB and the SSE-table ceiling from 16 to 24
MiB. Those two maxima are the only changes; the 384 MiB total-state cap and
1,500-basis-point advance line remain unchanged. The refined run uses its own
manifest hash frozen before the first base measurement and receives a separate
clean-checkout confirmation. Failure to cross the same advance line kills S0;
there is no second refinement.

The 1,500 basis-point screen threshold is deliberately stricter than the later
1,000 basis-point exact-codec gate because an entropy projection is optimistic:
it does not yet prove a decoder, complete format, real speed, or real memory.

## Claim ceiling

S0 can authorize or kill implementation work. It cannot establish an Axiom
candidate score, unseen-data win, practical speed or memory result, category
state of the art, or product readiness. A later exact codec must independently
pass complete-byte, deterministic round-trip, corruption, memory, speed,
streaming, portability, and newly frozen lineage-distinct unseen-data gates.
