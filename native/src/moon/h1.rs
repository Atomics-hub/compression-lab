//! H1 floor arm: shared hashed high-order context mixing with confirm-byte
//! collision eviction.
//!
//! Development-only prescreen arm for the moonshot cycle 1 (Lane 2). It is a
//! byte-level model that ignores JSON grammar entirely: every source byte is
//! coded as eight modeled bits. Each bit draws predictions from hashed
//! contexts of byte orders {1,2,3,4,6,8} plus one sparse and one
//! word-boundary context, all sharing the single open-addressed
//! [`ContextTable`]. The eight per-context predictions are combined by the
//! moon-local [`MoonMixer`] — an N-input integer logistic mixer that sums
//! predictions in the log-odds domain, so agreeing evidence compounds and an
//! aliased confidently-wrong cell can be learned down. Its output feeds the
//! frozen s0 [`M5Mixer`] (adaptive mix + one SSE stage) as a base for
//! recalibration. Every modeled bit is charged through the frozen s0
//! [`Ledger`] and written to the frozen s0 tape, so the projection is exact,
//! integer-only, and directly comparable to the s0 arms. Encode immediately
//! re-decodes and checks ledger equality; decode is fail-closed on
//! corruption, exhaustion, and identity mismatch.

use crate::s0::{Ledger, LossTable, M5Mixer, Probability, Tape, TapeError, TapeReader, TapeWriter};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::mixer::{MoonMixer, MOON_MIXER_WEIGHT_BYTES};
use super::table::{ContextTable, H1_CONTEXT_TABLE_BYTES};

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

/// Declared model-state bytes for an H1 model at the given SSE capacity: the
/// 96 MiB context table plus the moon logistic mixer weight table plus the
/// frozen s0 mixer and SSE tables. Scratch registers (continuation model,
/// rolling word hash) and derived constant lookups (stretch table) are
/// excluded, mirroring the s0 `modeled_state_bytes` convention.
#[must_use]
pub fn h1_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    let (mixer_bytes, sse_bytes) =
        M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits).declared_state_bytes();
    H1_CONTEXT_TABLE_BYTES + MOON_MIXER_WEIGHT_BYTES + mixer_bytes + sse_bytes
}

/// The mutable H1 model state. Reused unchanged by the encoder and decoder so
/// both evolve byte-for-byte identically. Also reused as the shared floor
/// coder of the H6 hybrid arm, which drives its byte and flag primitives.
pub struct H1Model {
    contexts: ContextTable,
    moon: MoonMixer,
    mixer: Box<M5Mixer>,
    continuation: Probability,
    word: u64,
    last_byte: u8,
}

impl H1Model {
    pub fn new(table: &LossTable, sse_bucket_bits: u32) -> Self {
        Self {
            contexts: ContextTable::new(),
            moon: MoonMixer::new(table),
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

    /// Resolve the eight contexts, returning the cell indices to update after
    /// the bit and each cell's current probability of a one. The predictions
    /// are combined by the logistic mixer, not here.
    fn resolve(&mut self, history: &[u8], node: u8) -> ([usize; H1_CONTEXT_COUNT], [u16; 8]) {
        let hashes = self.context_hashes(history, node);
        let mut indices = [0_usize; H1_CONTEXT_COUNT];
        let mut probabilities = [0_u16; 8];
        for (slot, &hash) in hashes.iter().enumerate() {
            let index = self.contexts.resolve(hash);
            indices[slot] = index;
            probabilities[slot] = self.contexts.cell(index).probability_of_one();
        }
        (indices, probabilities)
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
            // Accumulate a rolling hash of the current word run. `word == 0` is
            // the reserved boundary state (set below on any non-word byte), so
            // the first byte of a fresh word must seed from the FNV offset
            // rather than 0; subsequent bytes fold into the running hash.
            let seed = if self.word == 0 {
                fnv1a64(FNV_OFFSET, &[TAG_WORD_ACCUM])
            } else {
                self.word
            };
            let hashed = fnv1a64(seed, &[byte]);
            // Keep the accumulator nonzero so it never collides with the
            // boundary state mid-word.
            self.word = if hashed == 0 { FNV_OFFSET } else { hashed };
        } else {
            self.word = 0;
        }
    }

    /// Encode one byte as eight modeled bits through the H1 mixing floor,
    /// given the preceding byte history. Advances the model. Reused verbatim
    /// by the H6 hybrid arm for miss-line bytes so their per-byte grammar is
    /// identical to H1's.
    pub fn encode_byte(
        &mut self,
        byte: u8,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), H1Error> {
        let mut node: u32 = 1;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities) = self.resolve(history, node as u8);
            let event_id = self.event_id(node as u8);
            encode_bit(
                self,
                &indices,
                &probabilities,
                node as u8,
                event_id,
                bit,
                table,
                ledger,
                writer,
            )?;
            node = (node << 1) | u32::from(bit);
        }
        self.advance_byte(byte);
        Ok(())
    }

    /// Decode one byte, mirror of [`encode_byte`]. Advances the model.
    ///
    /// [`encode_byte`]: H1Model::encode_byte
    pub fn decode_byte(
        &mut self,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<u8, H1Error> {
        let mut node: u32 = 1;
        for _ in 0..8 {
            let (indices, probabilities) = self.resolve(history, node as u8);
            let event_id = self.event_id(node as u8);
            let bit = decode_bit(
                self,
                &indices,
                &probabilities,
                node as u8,
                event_id,
                table,
                ledger,
                reader,
            )?;
            node = (node << 1) | u32::from(bit);
        }
        let byte = (node & 0xff) as u8;
        self.advance_byte(byte);
        Ok(byte)
    }

    /// Charge one continuation bit through the H1 floor estimator (the shared
    /// s0 mixer keyed by the continuation identity, against the continuation
    /// probability cell). The H6 hybrid arm reuses this verbatim for its
    /// per-byte framing so that, on the miss substream, its continuation
    /// events are charged bit-for-bit identically to pure H1.
    pub fn encode_continuation_bit(
        &mut self,
        more: bool,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), H1Error> {
        let base = self.continuation.probability_of_one();
        let charged = self.mixer.predict(CONTINUATION_EVENT_ID, base);
        let loss = table
            .get(observed_probability(charged, more))
            .ok_or(H1Error::InvalidProbability)?;
        ledger
            .add_modeled_event(loss)
            .ok_or(H1Error::LedgerOverflow)?;
        writer.push_bit(more)?;
        self.mixer.update(more);
        self.continuation.update(more, H1_RATE_SHIFT);
        Ok(())
    }

    /// Decode one continuation bit, mirror of [`encode_continuation_bit`].
    ///
    /// [`encode_continuation_bit`]: H1Model::encode_continuation_bit
    pub fn decode_continuation_bit(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<bool, H1Error> {
        let more = reader.read_bit()?;
        let base = self.continuation.probability_of_one();
        let charged = self.mixer.predict(CONTINUATION_EVENT_ID, base);
        let loss = table
            .get(observed_probability(charged, more))
            .ok_or(H1Error::InvalidProbability)?;
        ledger
            .add_modeled_event(loss)
            .ok_or(H1Error::LedgerOverflow)?;
        self.mixer.update(more);
        self.continuation.update(more, H1_RATE_SHIFT);
        Ok(more)
    }
}

/// The shared prediction step for one modeled byte-bit. The moon logistic
/// mixer combines the eight context probabilities into a base, which the s0
/// mixer recalibrates. Prediction is independent of the bit value, so the
/// decoder reproduces the identical charged probability.
fn predict_byte_bit(
    model: &mut H1Model,
    probabilities: &[u16; H1_CONTEXT_COUNT],
    node: u8,
    event_id: u64,
) -> u16 {
    let last_byte = model.last_byte;
    let base = model.moon.predict(node, last_byte, probabilities);
    model.mixer.predict(event_id, base)
}

/// Apply the paired updates for one modeled byte-bit, preserving
/// charge-before-update: both mixers and the cells learn only after the bit.
fn update_byte_bit(model: &mut H1Model, indices: &[usize; H1_CONTEXT_COUNT], bit: bool) {
    model.mixer.update(bit);
    model.moon.update(bit);
    model.observe(indices, bit);
}

/// Charge one modeled byte-bit on the encoder side.
#[allow(clippy::too_many_arguments)]
fn encode_bit(
    model: &mut H1Model,
    indices: &[usize; H1_CONTEXT_COUNT],
    probabilities: &[u16; H1_CONTEXT_COUNT],
    node: u8,
    event_id: u64,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), H1Error> {
    let charged = predict_byte_bit(model, probabilities, node, event_id);
    let loss = table
        .get(observed_probability(charged, bit))
        .ok_or(H1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(H1Error::LedgerOverflow)?;
    writer.push_bit(bit)?;
    update_byte_bit(model, indices, bit);
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn decode_bit(
    model: &mut H1Model,
    indices: &[usize; H1_CONTEXT_COUNT],
    probabilities: &[u16; H1_CONTEXT_COUNT],
    node: u8,
    event_id: u64,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<bool, H1Error> {
    let bit = reader.read_bit()?;
    let charged = predict_byte_bit(model, probabilities, node, event_id);
    let loss = table
        .get(observed_probability(charged, bit))
        .ok_or(H1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(H1Error::LedgerOverflow)?;
    update_byte_bit(model, indices, bit);
    Ok(bit)
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
        model.encode_continuation_bit(true, table, &mut ledger, &mut writer)?;
        model.encode_byte(byte, &source[..position], table, &mut ledger, &mut writer)?;
        if byte == b'\n' {
            ledger.add_record().ok_or(H1Error::LedgerOverflow)?;
        }
    }
    model.encode_continuation_bit(false, table, &mut ledger, &mut writer)?;
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
        if !model.decode_continuation_bit(table, &mut ledger, &mut reader)? {
            break;
        }
        let byte = model.decode_byte(&output, table, &mut ledger, &mut reader)?;
        output.push(byte);
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

    // Pinned once from the deterministic encoder; the tape is a pure function
    // of the source bytes and arm/item identity.
    const PINNED_TAPE_SHA256: &str =
        "c18a1027239a395224286a06fa5a93d7b4ccdb3d825d7b79a754196f5deb2776";

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
    fn declared_state_bytes_account_for_table_moon_mixer_and_sse() {
        let table = LossTable::generate();
        let model = H1Model::new(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        // The 96 MiB context table dominates the declared state.
        assert_eq!(
            model.contexts.declared_state_bytes(),
            H1_CONTEXT_TABLE_BYTES
        );
        let (mixer_bytes, sse_bytes) = model.mixer.declared_state_bytes();
        let composed = model.contexts.declared_state_bytes()
            + model.moon.declared_state_bytes()
            + mixer_bytes
            + sse_bytes;
        let standalone = h1_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(composed, standalone);
        // The moon logistic mixer weight table is charged as mutable state.
        assert_eq!(model.moon.declared_state_bytes(), MOON_MIXER_WEIGHT_BYTES);
        // Regression pin of the exact figure the receipts report.
        assert_eq!(standalone, 119_947_264);
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

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_h1_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        // Flip a bit in the middle of the payload (before the trailing digest).
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert_eq!(Tape::from_bytes(&bytes), Err(TapeError::DigestMismatch));
    }

    #[test]
    fn one_extra_charged_bit_past_end_of_stream_fails_closed() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n".to_vec();
        let (tape, ledger) = encode_h1_item(&source, &table, 0).unwrap();
        let bytes = tape.to_bytes();

        // Rebuild the serialized tape with one extra trailing zero bit charged
        // past the decoder's end-of-stream flag, recomputing the digest so the
        // tape parses but leaves the reader with an unconsumed bit.
        const HEADER: usize = 14; // MAGIC(4) + arm(1) + item(1) + bit_count(8)
        const DIGEST: usize = 32;
        let bit_count = u64::from_le_bytes(bytes[6..14].try_into().unwrap());
        let bit_bytes_len = bit_count.div_ceil(8) as usize;
        let new_bit_count = bit_count + 1;
        let new_bit_bytes_len = new_bit_count.div_ceil(8) as usize;
        let payload_end = bytes.len() - DIGEST;

        let mut rebuilt = Vec::new();
        rebuilt.extend_from_slice(&bytes[..6]);
        rebuilt.extend_from_slice(&new_bit_count.to_le_bytes());
        let bit_end = HEADER + bit_bytes_len;
        rebuilt.extend_from_slice(&bytes[HEADER..bit_end]);
        if new_bit_bytes_len > bit_bytes_len {
            rebuilt.push(0);
        }
        rebuilt.extend_from_slice(&bytes[bit_end..payload_end]);
        let digest = Sha256::digest(&rebuilt);
        rebuilt.extend_from_slice(&digest);

        let tampered = Tape::from_bytes(&rebuilt).unwrap();
        assert_eq!(
            decode_h1_item(&tampered, ledger, &table, 0),
            Err(H1Error::TrailingChargedData)
        );
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        // A fixed input; the tape is a pure function of the source bytes and
        // identity (H1 writes the literal bit stream), so this SHA is stable
        // across mixer changes.
        let source = b"{\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":2}\n"
            .to_vec();
        let (tape, _) = encode_h1_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned tape SHA-256 changed");
    }
}
