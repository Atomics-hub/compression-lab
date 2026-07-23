//! H1 floor arm: shared hashed high-order context mixing with confirm-byte
//! collision eviction.
//!
//! Development-only prescreen arm for the moonshot cycle 1 (Lane 2). It is a
//! byte-level model that ignores JSON grammar entirely: every source byte is
//! coded as eight modeled bits. Each bit draws predictions from hashed
//! contexts of byte orders {1,2,3,4,6,8} plus one sparse and one
//! word-boundary context, all sharing the single open-addressed
//! [`ContextTable`]. The per-context predictions are combined by
//! confidence-weighted averaging and then refined through the frozen s0
//! [`M5Mixer`] (adaptive logistic mix + one SSE stage). Every modeled bit is
//! charged through the frozen s0 [`Ledger`] and written to the frozen s0 tape,
//! so the projection is exact, integer-only, and directly comparable to the s0
//! arms. Encode immediately re-decodes and checks ledger equality; decode is
//! fail-closed on corruption, exhaustion, and identity mismatch.

use crate::s0::{
    Ledger, LossTable, M5Mixer, Probability, Tape, TapeError, TapeReader, TapeWriter,
    MAX_PROBABILITY, MIN_PROBABILITY,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::table::{ContextTable, H1_CONTEXT_TABLE_BYTES, H1_COUNTER_CEILING};

/// Tape arm identity for the H1 floor arm. Disjoint from the s0 arm ids so a
/// tape can never be decoded under the wrong kernel.
pub const H1_ARM_ID: u8 = 100;
/// Number of hashed contexts combined per modeled bit.
pub const H1_CONTEXT_COUNT: usize = 8;
/// Byte orders (context lengths in bytes) of the six direct contexts.
pub const H1_BYTE_ORDERS: [usize; 6] = [1, 2, 3, 4, 6, 8];
/// Probability update rate shift for the continuation model (matches the s0
/// event layer's `RATE_SHIFT`).
const H1_RATE_SHIFT: u32 = 5;

// Disjoint FNV-1a namespaces per context kind, so two contexts that hash the
// same bytes still land on different cells.
const TAG_ORDER: u8 = 0x01;
const TAG_SPARSE: u8 = 0xa5;
const TAG_WORD: u8 = 0x5a;
const TAG_WORD_ACCUM: u8 = 0x33;

// Mixer event identity reserved for the per-byte continuation flag; disjoint
// from every byte-bit identity (which are < 2^16).
const CONTINUATION_EVENT_ID: u64 = u64::MAX;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

fn fnv1a64(seed: u64, bytes: &[u8]) -> u64 {
    bytes.iter().fold(seed, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    })
}

fn is_word_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn observed_probability(probability_of_one: u16, bit: bool) -> u32 {
    if bit {
        u32::from(probability_of_one)
    } else {
        65_536 - u32::from(probability_of_one)
    }
}

/// Declared model-state bytes for an H1 model at the given SSE capacity:
/// the 96 MiB context table plus the frozen mixer and SSE tables. Scratch
/// registers (continuation model, rolling word hash) are O(1) and excluded,
/// mirroring the s0 `modeled_state_bytes` convention.
#[must_use]
pub fn h1_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    let (mixer_bytes, sse_bytes) =
        M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits).declared_state_bytes();
    H1_CONTEXT_TABLE_BYTES + mixer_bytes + sse_bytes
}

/// The mutable H1 model state. Reused unchanged by the encoder and decoder so
/// both evolve byte-for-byte identically.
struct H1Model {
    contexts: ContextTable,
    mixer: Box<M5Mixer>,
    continuation: Probability,
    word: u64,
    last_byte: u8,
}

impl H1Model {
    fn new(table: &LossTable, sse_bucket_bits: u32) -> Self {
        Self {
            contexts: ContextTable::new(),
            mixer: Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
            continuation: Probability::default(),
            word: 0,
            last_byte: 0,
        }
    }

    /// The eight context hashes for one bit: six direct byte orders, one
    /// sparse context (positions p-1 and p-3), and the rolling word context.
    fn context_hashes(&self, history: &[u8], node: u8) -> [u64; H1_CONTEXT_COUNT] {
        let mut hashes = [0_u64; H1_CONTEXT_COUNT];
        let position = history.len();
        for (slot, &order) in H1_BYTE_ORDERS.iter().enumerate() {
            let start = position.saturating_sub(order);
            let mut hash = fnv1a64(FNV_OFFSET, &[TAG_ORDER, order as u8]);
            hash = fnv1a64(hash, &history[start..position]);
            hashes[slot] = fnv1a64(hash, &[node]);
        }
        // Sparse: skip the immediately preceding byte to capture longer-range
        // regularity a dense order-2 misses.
        let mut sparse = fnv1a64(FNV_OFFSET, &[TAG_SPARSE]);
        let near = position
            .checked_sub(1)
            .map(|index| history[index])
            .unwrap_or(0);
        let far = position
            .checked_sub(3)
            .map(|index| history[index])
            .unwrap_or(0);
        sparse = fnv1a64(sparse, &[near, far, node]);
        hashes[6] = sparse;
        // Word: hash of the run of word bytes since the last boundary.
        let word = fnv1a64(FNV_OFFSET, &[TAG_WORD]);
        let word = fnv1a64(word, &self.word.to_le_bytes());
        hashes[7] = fnv1a64(word, &[node]);
        hashes
    }

    /// Resolve the eight contexts and combine their predictions into one base
    /// probability, returning the cell indices to update after the bit.
    fn combine(&mut self, history: &[u8], node: u8) -> ([usize; H1_CONTEXT_COUNT], u16) {
        let hashes = self.context_hashes(history, node);
        let mut indices = [0_usize; H1_CONTEXT_COUNT];
        let mut numerator = 0_u64;
        let mut denominator = 0_u64;
        for (slot, &hash) in hashes.iter().enumerate() {
            let index = self.contexts.resolve(hash);
            let cell = self.contexts.cell(index);
            let weight = 1 + u64::from(cell.confidence().min(u32::from(H1_COUNTER_CEILING)));
            numerator += weight * u64::from(cell.probability_of_one());
            denominator += weight;
            indices[slot] = index;
        }
        let base = (numerator / denominator)
            .clamp(u64::from(MIN_PROBABILITY), u64::from(MAX_PROBABILITY))
            as u16;
        (indices, base)
    }

    fn event_id(&self, node: u8) -> u64 {
        (u64::from(self.last_byte) << 8) | u64::from(node)
    }

    fn observe(&mut self, indices: &[usize; H1_CONTEXT_COUNT], bit: bool) {
        for &index in indices {
            self.contexts.observe(index, bit);
        }
    }

    fn advance_byte(&mut self, byte: u8) {
        self.last_byte = byte;
        if is_word_byte(byte) {
            self.word = fnv1a64(
                self.word.max(FNV_OFFSET) ^ u64::from(TAG_WORD_ACCUM),
                &[byte],
            );
        } else {
            self.word = 0;
        }
    }
}

/// Charge one modeled byte-bit on the encoder side. Prediction is independent
/// of the bit value, so the decoder reproduces the identical charged loss.
#[allow(clippy::too_many_arguments)]
fn encode_bit(
    model: &mut H1Model,
    indices: &[usize; H1_CONTEXT_COUNT],
    base: u16,
    event_id: u64,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), H1Error> {
    let charged = model.mixer.predict(event_id, base);
    let loss = table
        .get(observed_probability(charged, bit))
        .ok_or(H1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(H1Error::LedgerOverflow)?;
    writer.push_bit(bit)?;
    model.mixer.update(bit);
    model.observe(indices, bit);
    Ok(())
}

fn decode_bit(
    model: &mut H1Model,
    indices: &[usize; H1_CONTEXT_COUNT],
    base: u16,
    event_id: u64,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<bool, H1Error> {
    let bit = reader.read_bit()?;
    let charged = model.mixer.predict(event_id, base);
    let loss = table
        .get(observed_probability(charged, bit))
        .ok_or(H1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(H1Error::LedgerOverflow)?;
    model.mixer.update(bit);
    model.observe(indices, bit);
    Ok(bit)
}

fn encode_continuation(
    model: &mut H1Model,
    more: bool,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), H1Error> {
    let base = model.continuation.probability_of_one();
    let charged = model.mixer.predict(CONTINUATION_EVENT_ID, base);
    let loss = table
        .get(observed_probability(charged, more))
        .ok_or(H1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(H1Error::LedgerOverflow)?;
    writer.push_bit(more)?;
    model.mixer.update(more);
    model.continuation.update(more, H1_RATE_SHIFT);
    Ok(())
}

fn decode_continuation(
    model: &mut H1Model,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<bool, H1Error> {
    let more = reader.read_bit()?;
    let base = model.continuation.probability_of_one();
    let charged = model.mixer.predict(CONTINUATION_EVENT_ID, base);
    let loss = table
        .get(observed_probability(charged, more))
        .ok_or(H1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(H1Error::LedgerOverflow)?;
    model.mixer.update(more);
    model.continuation.update(more, H1_RATE_SHIFT);
    Ok(more)
}

/// Encode one item under the H1 arm at the base SSE capacity.
pub fn encode_h1_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), H1Error> {
    encode_h1_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

/// Encode one item under the H1 arm at an explicit SSE capacity.
pub fn encode_h1_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), H1Error> {
    let mut model = H1Model::new(table, sse_bucket_bits);
    let mut writer = TapeWriter::new(H1_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    for (position, &byte) in source.iter().enumerate() {
        encode_continuation(&mut model, true, table, &mut ledger, &mut writer)?;
        let history = &source[..position];
        let mut node: u32 = 1;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, base) = model.combine(history, node as u8);
            let event_id = model.event_id(node as u8);
            encode_bit(
                &mut model,
                &indices,
                base,
                event_id,
                bit,
                table,
                &mut ledger,
                &mut writer,
            )?;
            node = (node << 1) | u32::from(bit);
        }
        model.advance_byte(byte);
        if byte == b'\n' {
            ledger.add_record().ok_or(H1Error::LedgerOverflow)?;
        }
    }
    encode_continuation(&mut model, false, table, &mut ledger, &mut writer)?;
    Ok((writer.finish(), ledger))
}

/// Decode one item under the H1 arm at the base SSE capacity.
pub fn decode_h1_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, H1Error> {
    decode_h1_item_with_bits(
        tape,
        expected_ledger,
        table,
        expected_item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

/// Decode one item under the H1 arm at an explicit SSE capacity, checking arm
/// and item identity and independent ledger equality.
pub fn decode_h1_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, H1Error> {
    if tape.arm_id() != H1_ARM_ID || tape.item_index() != expected_item_index {
        return Err(H1Error::TapeIdentityMismatch);
    }
    let mut model = H1Model::new(table, sse_bucket_bits);
    let mut ledger = Ledger::default();
    let mut reader = tape.reader();
    let mut output: Vec<u8> = Vec::new();
    loop {
        if !decode_continuation(&mut model, table, &mut ledger, &mut reader)? {
            break;
        }
        let mut node: u32 = 1;
        for _ in 0..8 {
            let (indices, base) = model.combine(&output, node as u8);
            let event_id = model.event_id(node as u8);
            let bit = decode_bit(
                &mut model,
                &indices,
                base,
                event_id,
                table,
                &mut ledger,
                &mut reader,
            )?;
            node = (node << 1) | u32::from(bit);
        }
        let byte = (node & 0xff) as u8;
        output.push(byte);
        model.advance_byte(byte);
        if byte == b'\n' {
            ledger.add_record().ok_or(H1Error::LedgerOverflow)?;
        }
    }
    if !reader.is_finished() {
        return Err(H1Error::TrailingChargedData);
    }
    if ledger != expected_ledger {
        return Err(H1Error::LedgerDivergence {
            encoder: expected_ledger,
            decoder: ledger,
        });
    }
    Ok(output)
}

/// H1 encode/decode error. Every variant is terminal for the item; the caller
/// discards partially charged state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum H1Error {
    InvalidProbability,
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Tape(TapeError),
}

impl From<TapeError> for H1Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for H1Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon H1 error: {self:?}")
    }
}

impl Error for H1Error {}

#[cfg(test)]
mod tests {
    use super::*;

    fn regime_snippets() -> Vec<(&'static str, Vec<u8>)> {
        let mut snippets: Vec<(&'static str, Vec<u8>)> = Vec::new();

        // High whole-value duplication: the same record repeated.
        let mut duplicated = Vec::new();
        for _ in 0..40 {
            duplicated.extend_from_slice(b"{\"level\":\"info\",\"msg\":\"ready\"}\n");
        }
        snippets.push(("high-duplication", duplicated));

        // High key/value cardinality: every record distinct.
        let mut varied = Vec::new();
        for index in 0..60_u32 {
            let mix = index.wrapping_mul(2_654_435_761);
            varied.extend_from_slice(
                format!(
                    "{{\"id\":{},\"session\":\"s{}\",\"tag\":\"{:08x}\",\"path\":\"/a/{}/{}\"}}\n",
                    100_000 + index,
                    index % 997,
                    mix,
                    index % 521,
                    index % 733
                )
                .as_bytes(),
            );
        }
        snippets.push(("high-cardinality", varied));

        // Line-oriented (non-JSON) log text.
        let mut logs = Vec::new();
        for index in 0..50_u32 {
            logs.extend_from_slice(
                format!(
                    "2026-07-22 10:{:02}:{:02} WARN worker[{}] retrying\n",
                    index % 60,
                    (index * 7) % 60,
                    index % 8
                )
                .as_bytes(),
            );
        }
        snippets.push(("line-log", logs));

        // Adversarial and edge bytes: empty-ish, binary, no trailing newline.
        snippets.push(("tiny", b"{}\n".to_vec()));
        snippets.push(("binary", (0..=255_u8).cycle().take(300).collect()));
        snippets.push(("no-newline", b"{\"tail\":true}".to_vec()));
        snippets.push(("empty", Vec::new()));

        snippets
    }

    #[test]
    fn round_trips_exactly_across_every_regime() {
        let table = LossTable::generate();
        for (name, source) in regime_snippets() {
            let (tape, ledger) = encode_h1_item(&source, &table, 1).unwrap();
            let decoded = decode_h1_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
            assert_eq!(ledger.raw_literal_bytes, 0, "H1 charges no literals");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(1).1;
        let (tape_a, ledger_a) = encode_h1_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_h1_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n{\"a\":1}\n".to_vec();
        let (tape, ledger) = encode_h1_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_h1_item(&tape, wrong, &table, 0),
            Err(H1Error::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"hello world\n".to_vec();
        let (tape, ledger) = encode_h1_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_h1_item(&tape, ledger, &table, 4),
            Err(H1Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn refined_sse_bits_hold_the_tape_and_event_stream() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1;
        let (base_tape, base_ledger) = encode_h1_item_with_bits(&source, &table, 0, 17).unwrap();
        let (refined_tape, refined_ledger) =
            encode_h1_item_with_bits(&source, &table, 0, 18).unwrap();
        // The SSE capacity refines only the charged probability: it never
        // changes the tape bits, the event structure, or the literals.
        assert_eq!(base_tape.to_bytes(), refined_tape.to_bytes());
        assert_eq!(
            base_ledger.modeled_binary_events,
            refined_ledger.modeled_binary_events
        );
        assert_eq!(base_ledger.records, refined_ledger.records);
        assert_eq!(
            base_ledger.raw_literal_bytes,
            refined_ledger.raw_literal_bytes
        );
        // The refined tape decodes exactly under its own capacity.
        assert_eq!(
            decode_h1_item_with_bits(&refined_tape, refined_ledger, &table, 0, 18).unwrap(),
            source
        );
    }

    #[test]
    fn declared_state_bytes_account_for_table_mixer_and_sse() {
        let table = LossTable::generate();
        let model = H1Model::new(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        // The 96 MiB context table dominates the declared state.
        assert_eq!(
            model.contexts.declared_state_bytes(),
            H1_CONTEXT_TABLE_BYTES
        );
        let (mixer_bytes, sse_bytes) = model.mixer.declared_state_bytes();
        let composed = model.contexts.declared_state_bytes() + mixer_bytes + sse_bytes;
        let standalone = h1_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(composed, standalone);
        // Regression pin of the exact figure the receipts report.
        assert_eq!(standalone, 119_799_808);
        // The refined SSE capacity only grows the SSE table.
        let refined = h1_declared_state_bytes(&table, crate::s0::SSE_REFINED_BUCKET_BITS);
        assert!(refined > standalone);
    }

    #[test]
    fn projection_is_exact_and_scores_through_the_frozen_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (_, ledger) = encode_h1_item(&source, &table, 0).unwrap();
        let projection = ledger.project_item(source.len() as u64).unwrap();
        // Highly duplicated input compresses well below its source size.
        assert!(projection.payload_bytes < source.len() as u64);
    }
}
