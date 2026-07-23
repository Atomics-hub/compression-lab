//! H9 weird arm: offline bounded-grammar (Re-Pair) compression.
//!
//! Development-only prescreen arm for the moonshot cycle 1 (Lane 2). A
//! fundamentally different attack from S0 (adaptive bit models) and ZPAQ
//! (context mixing): build an offline, memory-bounded straight-line grammar
//! over the byte stream, then entropy-code the rule table and residual symbol
//! sequence with a small adaptive model. Two passes over the item (offline is
//! allowed for a prescreen arm; the runner's 600 s wall budget still applies).
//!
//! Pass 1 (Re-Pair): repeatedly replace the most frequent adjacent symbol pair
//! with a new nonterminal. Deterministic tie-breaking (lowest pair value wins),
//! a hard rule budget of 32,768 rules, and a bounded digram index (16 MiB
//! cap). It stops when no pair occurs at least twice or the budget is reached.
//!
//! Wall-time honesty (audit finding): this naive form rebuilds the digram
//! index and rescans the sequence once per created rule, so the worst case is
//! O(rule_budget x sequence_length), and the sequence need not shrink much
//! per rule. On real log data the 2026-07-23 prescreen recorded
//! `killed_by_budget` timeouts at 24, 12, and 4 MiB slice sizes under the
//! 600 s wall (runs in `runs/moon-prescreen-cycle1-h9-v1/`): the offline
//! naive form is computationally infeasible at prescreen scale on realistic
//! inputs, independent of its ratio. An incremental Re-Pair (priority queue
//! plus occurrence lists) would be near-linear; building it is a cycle-2
//! decision, not a patch to this arm.
//!
//! Pass 2 (charge): the rule table and final sequence are coded as fixed-width
//! MSB-first symbol ids through an order-1 adaptive model, reusing the frozen
//! s0 event kernel read-only ([`EventEncoder`]/[`EventDecoder`]/[`ContextStore`]).
//! The order-1 context is the previous symbol bucketed into a small fixed set
//! of trees. The decoder reconstructs the grammar from the charged rule table
//! and expands it; fail-closed on cycles, overflow, and bad rule references,
//! with the same ledger equality and immediate re-decode as the other arms.

use crate::s0::{ContextStore, EventDecoder, EventEncoder, EventError, Ledger, LossTable, Tape};
use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

/// Tape arm identity for the H9 grammar arm. Disjoint from the other moon arms.
pub const H9_ARM_ID: u8 = 102;

/// Number of terminal symbols (the byte alphabet).
pub const H9_TERMINALS: u32 = 256;
/// Hard rule budget: at most this many nonterminals are created.
pub const H9_RULE_BUDGET: usize = 32_768;
/// Full symbol alphabet: terminals plus every possible nonterminal.
pub const H9_SYMBOL_ALPHABET: u32 = H9_TERMINALS + H9_RULE_BUDGET as u32;
/// Order-1 model buckets: one adaptive symbol tree per bucket of the previous
/// symbol. A coarse order-1 that stays memory-bounded.
pub const H9_ORDER1_BUCKETS: usize = 64;

/// Two binary continuation contexts: "another rule follows" and "another
/// sequence symbol follows".
const H9_RULE_MORE_CONTEXT: usize = 0;
const H9_SEQUENCE_MORE_CONTEXT: usize = 1;
const H9_BINARY_CONTEXTS: usize = 2;

/// Declared bytes for the bounded pass-1 digram index (a hard cap).
pub const H9_DIGRAM_INDEX_CAP_BYTES: usize = 16 * 1024 * 1024;
/// Conservative per-entry footprint used to bound the digram index count.
const H9_DIGRAM_ENTRY_BYTES: usize = 16;
/// Maximum distinct digrams tracked at once (the bounded index).
pub const H9_MAX_DIGRAMS: usize = H9_DIGRAM_INDEX_CAP_BYTES / H9_DIGRAM_ENTRY_BYTES;
/// Declared bytes for the rule table: two u16 symbols per rule slot.
pub const H9_RULE_TABLE_BYTES: usize = H9_RULE_BUDGET * 4;

/// Decompression-bomb guard: a decoded grammar may not expand beyond this.
const H9_MAX_EXPANSION: usize = 64 * 1024 * 1024;

const _: () = assert!(H9_SYMBOL_ALPHABET <= 65_536);
const _: () = assert!(H9_ORDER1_BUCKETS.is_power_of_two());

fn symbol_bucket(previous: u32) -> usize {
    (previous as usize) & (H9_ORDER1_BUCKETS - 1)
}

fn h9_contexts() -> Result<ContextStore, EventError> {
    ContextStore::new(H9_BINARY_CONTEXTS, &[H9_SYMBOL_ALPHABET; H9_ORDER1_BUCKETS])
}

/// Declared model-state bytes: the rule table, the bounded digram index cap,
/// and the order-1 model tables (the event-kernel context store). The digram
/// index is pass-1 working memory; it is charged into the declared total as
/// instructed because it is real peak state during encoding.
#[must_use]
pub fn h9_declared_state_bytes(_table: &LossTable, _sse_bucket_bits: u32) -> usize {
    let order1_bytes = h9_contexts()
        .expect("h9 context store is valid")
        .modeled_state_bytes();
    H9_RULE_TABLE_BYTES + H9_DIGRAM_INDEX_CAP_BYTES + order1_bytes
}

/// The offline Re-Pair grammar of `source` under a rule budget: the ordered
/// rule table (rule `r` defines nonterminal `256 + r`) and the residual symbol
/// sequence. Deterministic: most-frequent digram wins, lowest pair value
/// breaks ties, the digram index is bounded, and it stops when no pair repeats
/// or the budget is reached.
pub(super) fn repair(source: &[u8], rule_budget: usize) -> (Vec<(u32, u32)>, Vec<u32>) {
    let mut sequence: Vec<u32> = source.iter().map(|&byte| u32::from(byte)).collect();
    let mut rules: Vec<(u32, u32)> = Vec::new();

    while rules.len() < rule_budget {
        let mut counts: HashMap<u64, u32> = HashMap::new();
        let mut index = 0;
        while index + 1 < sequence.len() {
            let key = (u64::from(sequence[index]) << 32) | u64::from(sequence[index + 1]);
            // Bounded digram index: once full, only already-tracked digrams are
            // counted further; new digrams are ignored (deterministic scan).
            if counts.len() < H9_MAX_DIGRAMS || counts.contains_key(&key) {
                *counts.entry(key).or_insert(0) += 1;
            }
            index += 1;
        }

        let mut best: Option<(u32, u64)> = None;
        for (&key, &count) in &counts {
            if count < 2 {
                continue;
            }
            match best {
                None => best = Some((count, key)),
                Some((best_count, best_key)) => {
                    if count > best_count || (count == best_count && key < best_key) {
                        best = Some((count, key));
                    }
                }
            }
        }
        let Some((_, key)) = best else {
            break;
        };
        let left = (key >> 32) as u32;
        let right = (key & 0xffff_ffff) as u32;
        let new_symbol = H9_TERMINALS + rules.len() as u32;
        rules.push((left, right));

        // Replace non-overlapping occurrences left-to-right.
        let mut replaced = Vec::with_capacity(sequence.len());
        let mut index = 0;
        while index < sequence.len() {
            if index + 1 < sequence.len() && sequence[index] == left && sequence[index + 1] == right
            {
                replaced.push(new_symbol);
                index += 2;
            } else {
                replaced.push(sequence[index]);
                index += 1;
            }
        }
        sequence = replaced;
    }

    (rules, sequence)
}

/// Expand a validated grammar to bytes. The rule table has already been
/// checked to reference only earlier symbols (a DAG), so this terminates;
/// [`H9_MAX_EXPANSION`] guards against a decompression bomb from a hostile
/// tape.
fn expand(rules: &[(u32, u32)], sequence: &[u32]) -> Result<Vec<u8>, H9Error> {
    let mut output = Vec::new();
    let mut stack: Vec<u32> = Vec::with_capacity(sequence.len());
    for &symbol in sequence.iter().rev() {
        stack.push(symbol);
    }
    while let Some(symbol) = stack.pop() {
        if symbol < H9_TERMINALS {
            if output.len() >= H9_MAX_EXPANSION {
                return Err(H9Error::ExpansionOverflow);
            }
            output.push(symbol as u8);
        } else {
            let rule_index = (symbol - H9_TERMINALS) as usize;
            let (left, right) = *rules.get(rule_index).ok_or(H9Error::BadRuleReference)?;
            if stack.len() + 2 > H9_MAX_EXPANSION {
                return Err(H9Error::ExpansionOverflow);
            }
            stack.push(right);
            stack.push(left);
        }
    }
    Ok(output)
}

/// Encode one item under the H9 arm at the base rule budget.
pub fn encode_h9_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), H9Error> {
    encode_h9_item_with_budget(source, table, item_index, H9_RULE_BUDGET)
}

/// Encode one item under the H9 arm at an explicit SSE capacity. H9 has no
/// mixer, so the capacity is accepted for a uniform kernel signature and
/// ignored.
pub fn encode_h9_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    _sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), H9Error> {
    encode_h9_item_with_budget(source, table, item_index, H9_RULE_BUDGET)
}

/// Encode with an explicit rule budget (tests use a small budget to exercise
/// budget-limited grammars quickly).
pub(super) fn encode_h9_item_with_budget(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    rule_budget: usize,
) -> Result<(Tape, Ledger), H9Error> {
    let (rules, sequence) = repair(source, rule_budget);
    let mut encoder = EventEncoder::new(table, h9_contexts()?, H9_ARM_ID, item_index);
    let mut previous = 0_u32;
    for &(left, right) in &rules {
        encoder.bit(H9_RULE_MORE_CONTEXT, true)?;
        encoder.symbol(symbol_bucket(previous), left)?;
        previous = left;
        encoder.symbol(symbol_bucket(previous), right)?;
        previous = right;
    }
    encoder.bit(H9_RULE_MORE_CONTEXT, false)?;
    for &symbol in &sequence {
        encoder.bit(H9_SEQUENCE_MORE_CONTEXT, true)?;
        encoder.symbol(symbol_bucket(previous), symbol)?;
        previous = symbol;
    }
    encoder.bit(H9_SEQUENCE_MORE_CONTEXT, false)?;
    let (tape, ledger) = encoder.finish();
    Ok((tape, ledger))
}

/// Decode one item under the H9 arm.
pub fn decode_h9_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, H9Error> {
    decode_h9_item_with_bits(tape, expected_ledger, table, expected_item_index, 0)
}

/// Decode one item under the H9 arm, checking arm and item identity and
/// independent ledger equality. The SSE capacity is accepted for a uniform
/// kernel signature and ignored.
pub fn decode_h9_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
    _sse_bucket_bits: u32,
) -> Result<Vec<u8>, H9Error> {
    if tape.arm_id() != H9_ARM_ID || tape.item_index() != expected_item_index {
        return Err(H9Error::TapeIdentityMismatch);
    }
    let mut decoder = EventDecoder::new(table, h9_contexts()?, tape);
    let mut previous = 0_u32;

    let mut rules: Vec<(u32, u32)> = Vec::new();
    while decoder.bit(H9_RULE_MORE_CONTEXT)? {
        if rules.len() >= H9_RULE_BUDGET {
            return Err(H9Error::RuleBudgetExceeded);
        }
        let left = decoder.symbol(symbol_bucket(previous))?;
        previous = left;
        let right = decoder.symbol(symbol_bucket(previous))?;
        previous = right;
        // A straight-line grammar only references earlier symbols: terminals
        // or nonterminals already defined. This rejects forward references and
        // therefore every cycle.
        let defined = H9_TERMINALS + rules.len() as u32;
        if left >= defined || right >= defined {
            return Err(H9Error::BadRuleReference);
        }
        rules.push((left, right));
    }

    let defined = H9_TERMINALS + rules.len() as u32;
    let mut sequence: Vec<u32> = Vec::new();
    while decoder.bit(H9_SEQUENCE_MORE_CONTEXT)? {
        let symbol = decoder.symbol(symbol_bucket(previous))?;
        previous = symbol;
        if symbol >= defined {
            return Err(H9Error::BadRuleReference);
        }
        sequence.push(symbol);
    }

    // Independent ledger equality and no-trailing-data check, reused from the
    // event kernel, before the grammar is expanded.
    decoder.finish(expected_ledger)?;
    expand(&rules, &sequence)
}

/// H9 encode/decode error. Every variant is terminal for the item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum H9Error {
    RuleBudgetExceeded,
    BadRuleReference,
    ExpansionOverflow,
    TapeIdentityMismatch,
    Event(EventError),
}

impl From<EventError> for H9Error {
    fn from(error: EventError) -> Self {
        Self::Event(error)
    }
}

impl Display for H9Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon H9 error: {self:?}")
    }
}

impl Error for H9Error {}

#[cfg(test)]
mod tests {
    use super::*;

    const PINNED_TAPE_SHA256: &str =
        "e9b822993062d5e9ef6ccdc809aaa96ea4292f8af48348e3390afb6253ee4608";

    fn regime_snippets() -> Vec<(&'static str, Vec<u8>)> {
        let mut snippets: Vec<(&'static str, Vec<u8>)> = Vec::new();

        // Heavy phrase-level repetition (grammar should compress well).
        let mut repetitive = Vec::new();
        for _ in 0..80 {
            repetitive.extend_from_slice(b"{\"event\":\"heartbeat\",\"ok\":true}\n");
        }
        snippets.push(("repetitive", repetitive));

        // Templated with small varying tails.
        let mut templated = Vec::new();
        for index in 0..60_u32 {
            templated.extend_from_slice(format!("GET /api/v1/item/{}\n", index % 8).as_bytes());
        }
        snippets.push(("templated", templated));

        // No repeats at all: the grammar degenerates to raw symbols.
        let unique: Vec<u8> = (0..200_u32).map(|index| (index % 251 + 1) as u8).collect();
        snippets.push(("no-repeats", unique));

        // Single repeated byte: deep balanced grammar.
        snippets.push(("single-byte-run", vec![b'a'; 500]));

        // Full binary alphabet cycled.
        snippets.push(("binary", (0..=255_u8).cycle().take(400).collect()));

        // Edge and adversarial cases.
        snippets.push(("tiny", b"ab\n".to_vec()));
        snippets.push(("no-newline", b"{\"tail\":true}".to_vec()));
        snippets.push(("one-byte", b"x".to_vec()));
        snippets.push(("empty", Vec::new()));

        snippets
    }

    #[test]
    fn round_trips_exactly_across_every_regime() {
        let table = LossTable::generate();
        for (name, source) in regime_snippets() {
            let (tape, ledger) = encode_h9_item(&source, &table, 1).unwrap();
            let decoded = decode_h9_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape_a, ledger_a) = encode_h9_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_h9_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn repair_is_deterministic_and_reduces_repetitive_input() {
        let source = regime_snippets().remove(0).1;
        let (rules_a, sequence_a) = repair(&source, H9_RULE_BUDGET);
        let (rules_b, sequence_b) = repair(&source, H9_RULE_BUDGET);
        assert_eq!(rules_a, rules_b);
        assert_eq!(sequence_a, sequence_b);
        // Phrase repetition shrinks the symbol sequence well below the bytes.
        assert!(sequence_a.len() < source.len() / 2);
    }

    #[test]
    fn rule_budget_is_never_exceeded_and_grammars_stop_early() {
        // A tiny budget forces the grammar to stop before full convergence,
        // yet it still round-trips exactly through the standard decoder.
        let table = LossTable::generate();
        let source = vec![b'z'; 1000];
        for budget in [0_usize, 1, 4, 16] {
            let (rules, _) = repair(&source, budget);
            assert!(rules.len() <= budget);
            let (tape, ledger) = encode_h9_item_with_budget(&source, &table, 0, budget).unwrap();
            assert_eq!(decode_h9_item(&tape, ledger, &table, 0).unwrap(), source);
        }
    }

    #[test]
    fn no_repeat_input_degenerates_to_raw_symbols() {
        let source = regime_snippets().remove(2).1; // no-repeats
        let (rules, sequence) = repair(&source, H9_RULE_BUDGET);
        assert!(
            rules.is_empty(),
            "expected no rules for non-repeating input"
        );
        assert_eq!(sequence.len(), source.len());
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, ledger) = encode_h9_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_h9_item(&tape, wrong, &table, 0),
            Err(H9Error::Event(EventError::LedgerDivergence { .. }))
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"grammar\n".to_vec();
        let (tape, ledger) = encode_h9_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_h9_item(&tape, ledger, &table, 4),
            Err(H9Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_h9_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert!(Tape::from_bytes(&bytes).is_err());
    }

    #[test]
    fn a_truncated_tape_is_rejected() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_h9_item(&source, &table, 0).unwrap();
        let bytes = tape.to_bytes();
        // Drop the last payload byte (and its digest): the header no longer
        // matches the truncated content.
        assert!(Tape::from_bytes(&bytes[..bytes.len() - 1]).is_err());
    }

    #[test]
    fn a_rule_referencing_an_undefined_nonterminal_fails_closed() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        // Encode a single rule (a,a) over "aaaa" so the stream begins with a
        // rule-more=true bit then the two symbols of rule 0.
        let source = b"aaaa".to_vec();
        let (tape, ledger) =
            encode_h9_item_with_budget(&source, &table, 0, H9_RULE_BUDGET).unwrap();
        // Re-encode the same grammar but with rule 0's left symbol forced to
        // nonterminal 256 (itself, which is undefined while rule 0 is being
        // read). This crafts a hostile tape via the encoder primitives.
        let mut encoder = EventEncoder::new(&table, h9_contexts().unwrap(), H9_ARM_ID, 0);
        encoder.bit(H9_RULE_MORE_CONTEXT, true).unwrap();
        encoder.symbol(symbol_bucket(0), 256).unwrap(); // undefined nonterminal
        encoder.symbol(symbol_bucket(256), b'a' as u32).unwrap();
        encoder.bit(H9_RULE_MORE_CONTEXT, false).unwrap();
        encoder.bit(H9_SEQUENCE_MORE_CONTEXT, false).unwrap();
        let (hostile_tape, hostile_ledger) = encoder.finish();
        assert_eq!(
            decode_h9_item(&hostile_tape, hostile_ledger, &table, 0),
            Err(H9Error::BadRuleReference)
        );
        // Sanity: the honest tape still decodes.
        let _ = Sha256::digest(tape.to_bytes());
        assert_eq!(decode_h9_item(&tape, ledger, &table, 0).unwrap(), source);
    }

    #[test]
    fn declared_state_accounts_for_rules_index_and_order1_tables() {
        let table = LossTable::generate();
        let order1 = h9_contexts().unwrap().modeled_state_bytes();
        let total = h9_declared_state_bytes(&table, 0);
        assert_eq!(
            total,
            H9_RULE_TABLE_BYTES + H9_DIGRAM_INDEX_CAP_BYTES + order1
        );
        // Regression pin of the exact figure the receipts report.
        assert_eq!(total, 25_297_254);
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"the cat sat on the mat, the cat sat on the mat.\n".to_vec();
        let (tape, _) = encode_h9_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned tape SHA-256 changed");
    }
}
